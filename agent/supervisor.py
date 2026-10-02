"""Plan, delegate, evaluate, refine, and retain research lessons."""

import re
from collections.abc import Mapping
from typing import Protocol
from uuid import uuid4

from agent.config import Settings
from agent.evidence import (
    RULES,
    period_issues,
    prepare_report,
    source_facts,
)
from agent.historical import dated_earnings, requested_period
from agent.memory import MemoryFailure, PersistentMemory
from agent.prompts import REVISION_PROMPT, SUPERVISOR_PROMPT, SYNTHESIS_PROMPT
from agent.runtime import (
    EventSink,
    OpenAIModel,
    Phase2Failure,
    RunContext,
    StructuredModel,
    TickerVerifier,
    check_prose,
    traced_research,
    validate_request,
    verify_ticker,
)
from agent.schemas import (
    AgentResult,
    AnalysisDraft,
    Delegation,
    Evaluation,
    EvaluationDraft,
    ReportDraft,
    ResearchPlan,
    ResearchRequest,
    RunError,
    SupervisorResult,
)
from agent.subagents import EarningsAgent, MarketAgent, NewsAgent
from agent.workflows import evaluate_report, required_corrections


class SpecialistClient(Protocol):
    """Allow the Supervisor to use real specialists or test doubles."""

    def run(self, request: ResearchRequest) -> AgentResult:
        """Return specialist findings and source evidence."""
        ...


def source_references(results: list[AgentResult]) -> dict:
    """Give evidence unique IDs across all specialist results."""
    references = {}
    for result in results:
        if result.status not in ("ok", "partial"):
            continue
        if result.role == "news":
            if not result.news_chain:
                continue
            articles = {a.id: a for a in result.news_chain.articles}
            for fact in result.news_chain.facts:
                article = articles.get(fact.article_id)
                if (
                    article is None
                    or not fact.quote.strip()
                    or fact.quote not in article.text
                ):
                    continue
                references[f"news:{fact.id}"] = {
                    "source": "NewsAPI article",
                    "claim": fact.claim,
                    "quote": fact.quote,
                    "url": article.url,
                    "published_at": article.published_at.isoformat(),
                }
        else:
            for item in result.evidence:
                if item.status == "ok":
                    references[f"{result.role}:{item.id}"] = {
                        "source": item.source,
                        "tool": item.tool,
                        "retrieved_at": item.retrieved_at.isoformat(),
                        "data": item.data,
                        "warnings": item.warnings,
                    }
    return references


def specialist_summaries(results: list[AgentResult]) -> list[dict]:
    """Keep coverage and findings while namespacing their citations."""
    summaries = []
    for result in results:
        analysis = result.analysis.model_dump() if result.analysis else None
        if analysis:
            for finding in analysis["findings"]:
                finding["evidence_ids"] = [
                    f"{result.role}:{identifier}"
                    for identifier in finding["evidence_ids"]
                ]
        summaries.append(
            {
                "role": result.role,
                "status": result.status,
                "analysis": analysis,
                "error_code": result.error.code if result.error else None,
            }
        )
    return summaries


def validate_report(report: AnalysisDraft) -> None:
    """Check report size and writing style before evaluation."""
    check_prose(report.summary)
    if not 1 <= len(report.findings) <= 6 or len(report.limitations) > 12:
        raise Phase2Failure("invalid_report", "The report size is invalid.")
    for text in [
        finding.claim for finding in report.findings
    ] + report.limitations:
        check_prose(text)


def normalize_plan(plan: ResearchPlan) -> ResearchPlan:
    """Combine repeated roles without losing their task questions."""
    check_prose(plan.rationale)
    if not 1 <= len(plan.steps) <= 3:
        raise Phase2Failure("invalid_plan", "The role plan is invalid.")
    questions = {}
    for step in plan.steps:
        check_prose(step.question)
        question = step.question.strip()
        if len(question) > 1000:
            raise Phase2Failure("invalid_plan", "A task question is too long.")
        selected = questions.setdefault(step.role, [])
        if question not in selected:
            selected.append(question)
    steps = []
    for role, tasks in questions.items():
        question = " ".join(tasks)
        if len(question) > 1000:
            raise Phase2Failure(
                "invalid_plan", "The combined specialist task is too long."
            )
        steps.append(Delegation(role=role, question=question))
    return ResearchPlan(
        rationale=plan.rationale,
        steps=steps,
        response_format=plan.response_format,
    )


class Supervisor:
    """Coordinate only the three frozen specialist roles."""

    def conversation(self, **overrides):
        """Start a conversation before research."""
        from agent.intake import IntakeSession

        return IntakeSession(self, **overrides)

    def __init__(
        self,
        settings: Settings | None = None,
        model: StructuredModel | None = None,
        memory: PersistentMemory | None = None,
        specialists: Mapping[str, SpecialistClient] | None = None,
        event_sink: EventSink | None = None,
    ):
        self.settings = settings or Settings.load()
        self.model = model or OpenAIModel(self.settings)
        self.memory = memory or PersistentMemory(self.settings.memory_path)
        self.specialists = dict(specialists or {})
        self.event_sink = event_sink
        if not self.specialists.keys() <= {"market", "earnings", "news"}:
            raise ValueError("The specialist mapping has an unknown role.")

    def _delegate(
        self,
        role: str,
        request: ResearchRequest,
        context: RunContext,
        verifier: TickerVerifier,
    ) -> AgentResult:
        """Show both sides of each handoff and contain specialist failures."""
        context.event(f"delegate:{role}", "started")
        try:
            client = self.specialists.get(role)
            if client is None:
                factory = {
                    "market": MarketAgent,
                    "earnings": EarningsAgent,
                    "news": NewsAgent,
                }[role]
                client = factory(
                    self.settings,
                    self.model,
                    ticker_verifier=verifier,
                    event_sink=lambda event: context.event(
                        f"{role}:{event.stage}", event.status
                    ),
                )
            result = AgentResult.model_validate(client.run(request))
            if result.role != role or result.ticker != request.ticker:
                raise ValueError("The specialist returned a different task.")
        except Exception:
            result = AgentResult(
                role=role,
                ticker=request.ticker,
                status="error",
                error=RunError(
                    code="specialist_error",
                    message="The specialist could not complete its task.",
                ),
            )
        context.event(f"return:{role}", result.status)
        return result

    @traced_research
    def run(self, request: ResearchRequest | dict) -> SupervisorResult:
        """Run a bounded research cycle and save reusable lessons."""
        context = RunContext(
            self.model,
            self.settings,
            3 + 2 * self.settings.max_revisions,
            self.event_sink,
        )
        state = {
            "run_id": str(uuid4()),
            "response_format": "answer",
            "request": None,
            "plan": None,
            "report": None,
            "report_versions": [],
            "model_report_versions": [],
            "specialists": [],
            "references": {},
            "evaluations": [],
            "lessons_loaded": [],
            "lessons_saved": [],
            "memory_warnings": [],
        }

        def finish(status: str, error: RunError | None = None):
            context.event(
                "result",
                "ok"
                if status == "completed"
                else ("error" if status == "error" else "partial"),
            )
            return SupervisorResult(
                **state,
                status=status,
                events=context.events,
                model_calls=context.model_calls
                + sum(item.model_calls for item in state["specialists"]),
                error=error,
            )

        def period_review(message):
            """Keep missing period evidence visible without model approval."""
            state["report"] = AnalysisDraft(
                summary=message, findings=[], limitations=[message]
            )
            state["report_versions"].append(state["report"])
            state["evaluations"].append(
                Evaluation(
                    version=0,
                    assessment=EvaluationDraft(
                        accuracy=0,
                        coverage=0,
                        clarity=5,
                        revision_required=True,
                        critique=[message],
                        lessons=[
                            "Verify the requested period before answering."
                        ],
                    ),
                    accepted=False,
                    evidence_issues=[message],
                )
            )
            context.event("period:check", "partial")
            return finish("needs_review")

        try:
            request = validate_request(request)
            state["request"] = request
            if request.response_format != "auto":
                state["response_format"] = request.response_format
            historical = dated_earnings(request.question)
            if historical:
                target = requested_period(
                    request.question, request.period_basis
                )
                if target is None:
                    return period_review(
                        "Please specify one quarter and year, and choose "
                        "fiscal or calendar using --period-basis. "
                        "No historical EPS answer has been verified."
                    )
                if not re.search(
                    r"\bEPS\b|earnings per share", request.question, re.I
                ):
                    return period_review(
                        "Historical lookup currently supports quarterly "
                        "EPS only. Specify EPS, or review the requested "
                        "historical metric manually."
                    )
                if re.search(
                    r"\bnews\b|\bprices?\b|interest rate|net income|revenue",
                    request.question,
                    re.I,
                ):
                    return period_review(
                        "Ask one historical quarterly EPS question. "
                        "Historical research across other topics is not "
                        "supported by this bounded lookup."
                    )
            if isinstance(self.model, OpenAIModel):
                if not self.settings.openai_api_key.get_secret_value():
                    raise Phase2Failure(
                        "missing_key", "Set OPENAI_API_KEY locally."
                    )
            verifier = TickerVerifier(self.settings)
            # Historical SEC research does not need recent Yahoo prices.
            if not historical:
                verify_ticker(request.ticker, context, verifier)
            context.event("memory:load", "started")
            try:
                state["lessons_loaded"] = self.memory.load_lessons(
                    request.ticker
                )
                context.event(
                    "memory:load", "ok" if state["lessons_loaded"] else "empty"
                )
            except MemoryFailure as exc:
                state["memory_warnings"].append(str(exc))
                context.event("memory:load", "error")
            lessons = [lesson.text for lesson in state["lessons_loaded"]]
            # REQUIREMENT: Plan research and route to selected specialists.
            plan = context.ask(
                "plan",
                ResearchPlan,
                SUPERVISOR_PROMPT,
                {"request": request.model_dump(), "past_lessons": lessons},
            )
            if historical:
                plan = ResearchPlan(
                    rationale="Use EPS evidence for the requested quarter.",
                    response_format=plan.response_format,
                    steps=[
                        Delegation(role="earnings", question=request.question)
                    ],
                )
            original_steps = len(plan.steps)
            plan = normalize_plan(plan)
            if len(plan.steps) < original_steps:
                context.event("plan:merge", "ok")
            state["plan"] = plan
            state["response_format"] = (
                plan.response_format
                if request.response_format == "auto"
                else request.response_format
            )
            context.event("plan", "ok")
            for step in plan.steps:
                if step.role == "market" and any(
                    term in request.question.lower()
                    for term in ("interest", "federal funds", "fedfunds")
                ):
                    step.question = (
                        step.question[:900]
                        + " Include FEDFUNDS interest rate observations."
                    )
                delegated = request.model_copy(
                    update={"question": step.question}
                )
                state["specialists"].append(
                    self._delegate(step.role, delegated, context, verifier)
                )
            references = source_references(state["specialists"])
            state["references"] = references
            if historical:
                issues = period_issues(request, references)
                if issues:
                    codes = sorted(
                        {
                            item.error_code
                            for specialist in state["specialists"]
                            for item in specialist.evidence
                            if item.error_code
                        }
                    )
                    if codes:
                        issues.append(
                            "Source retrieval issue: " + ", ".join(codes) + "."
                        )
                    return period_review(" ".join(issues))
            if not references:
                raise Phase2Failure(
                    "no_evidence", "No specialist returned usable evidence."
                )
            coverage = specialist_summaries(state["specialists"])
            base_payload = {
                "response_format": state["response_format"],
                "request": request.model_dump(),
                "verified_field_pairs": source_facts(references),
                "references": references,
                "specialists": coverage,
                "past_lessons": lessons,
                "source_interpretation_rules": RULES,
            }
            draft = context.ask(
                "synthesize:0",
                ReportDraft,
                SYNTHESIS_PROMPT + RULES,
                base_payload,
            )
            state["model_report_versions"].append(draft.model_copy(deep=True))
            # REQUIREMENT: Reflect on quality and revise using feedback.
            for version in range(self.settings.max_revisions + 1):
                validate_report(draft)
                draft = prepare_report(draft, references, coverage)
                state["report"] = draft
                state["report_versions"].append(draft)
                context.event(f"synthesize:{version}", "ok")
                evaluation = evaluate_report(
                    context,
                    request,
                    draft,
                    references,
                    coverage,
                    version,
                    self.settings.evaluation_threshold,
                )
                state["evaluations"].append(evaluation)
                if (
                    evaluation.accepted
                    or version == self.settings.max_revisions
                ):
                    break
                draft = context.ask(
                    f"revise:{version + 1}",
                    ReportDraft,
                    REVISION_PROMPT + RULES,
                    {
                        **base_payload,
                        "required_corrections": required_corrections(
                            evaluation, self.settings.evaluation_threshold
                        ),
                        "previous_report": draft.model_dump(),
                        "evaluation": evaluation.model_dump(),
                    },
                )
                state["model_report_versions"].append(
                    draft.model_copy(deep=True)
                )
                validate_report(draft)
                draft = prepare_report(draft, references, coverage)
                if draft == state["report"]:
                    # Keep the rejected result and stop repeated model calls.
                    context.event(f"revise:{version + 1}:unchanged", "partial")
                    break
                context.event(f"revise:{version + 1}", "ok")
            accepted = state["evaluations"][-1].accepted
            context.event("memory:save", "started")
            if state["memory_warnings"]:
                context.event("memory:save", "error")
            else:
                try:
                    state["lessons_saved"] = self.memory.save_lessons(
                        request.ticker,
                        state["evaluations"][-1].assessment.lessons,
                        "accepted" if accepted else "needs_review",
                        state["run_id"],
                    )
                    context.event("memory:save", "ok")
                except MemoryFailure as exc:
                    state["memory_warnings"].append(str(exc))
                    context.event("memory:save", "error")
            if not accepted:
                return finish("needs_review")
            degraded = bool(state["memory_warnings"]) or any(
                result.status != "ok" for result in state["specialists"]
            )
            return finish("partial" if degraded else "completed")
        except Phase2Failure as exc:
            return finish("error", RunError(code=exc.code, message=str(exc)))


def run(
    ticker: str | None = None,
    *,
    question: str = "Give me a company analysis.",
    company: str | None = None,
    period_basis: str = "auto",
    response_format: str = "auto",
    settings: Settings | None = None,
    clarification_callback=None,
):
    """Run research from Python, or return a needed clarification."""
    from agent.intake import prepare_request

    supervisor = Supervisor(settings)
    request, intake_calls = prepare_request(
        supervisor,
        question,
        ticker=ticker,
        company=company,
        period_basis=period_basis,
        response_format=response_format,
        callback=clarification_callback,
    )
    if not isinstance(request, ResearchRequest):
        return request
    result = supervisor.run(request)
    result.model_calls += intake_calls
    return result
