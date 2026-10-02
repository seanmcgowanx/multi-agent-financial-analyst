"""Run the three specialist roles with one shared execution flow."""

import re
from collections.abc import Callable

from agent.config import Settings
from agent.evidence import RULES, source_facts
from agent.historical import (
    HistoricalEPS,
    dated_earnings,
    get_historical_eps,
    release_eps,
    requested_period,
)
from agent.runtime import (
    EventSink,
    OpenAIModel,
    Phase2Failure,
    RunContext,
    StructuredModel,
    TickerVerifier,
    ask_analysis,
    check_prose,
    evidence_record,
    safe_tool,
    traced_research,
    validate_request,
    verify_ticker,
)
from agent.schemas import (
    AgentResult,
    ResearchRequest,
    ToolPlan,
    ToolResult,
)
from agent.tools import (
    FRED_SERIES,
    get_earnings_history,
    get_financial_statements,
    get_fred_series,
    get_price_history,
    get_sec_filings,
)
from agent.workflows import NewsChain

ToolMap = dict[str, Callable[[], ToolResult]]


class Specialist:
    """Share execution code without adding another agent role."""

    role: str

    def __init__(
        self,
        settings: Settings | None = None,
        model: StructuredModel | None = None,
        event_sink: EventSink | None = None,
        ticker_verifier: TickerVerifier | None = None,
    ):
        self.settings = settings or Settings.load()
        self.model = model or OpenAIModel(self.settings)
        self.event_sink = event_sink
        self.ticker_verifier = ticker_verifier

    def tools(self, request: ResearchRequest) -> ToolMap:
        """Return the tool allowlist supplied by the specialist."""
        raise NotImplementedError

    def prepare_evidence(self, context, request):
        """Allow an existing specialist to try another bounded source."""

    @traced_research
    def run(self, request: ResearchRequest | dict) -> AgentResult:
        """Select tools once, gather evidence, and return a cited draft."""
        context = RunContext(self.model, self.settings, 3, self.event_sink)
        ticker = ""
        try:
            request = validate_request(request)
            ticker = request.ticker
            if isinstance(self.model, OpenAIModel):
                if not self.settings.openai_api_key.get_secret_value():
                    raise Phase2Failure(
                        "missing_key", "Set OPENAI_API_KEY locally."
                    )
            tools = self.tools(request)
            # SEC tools check historical evidence without recent prices.
            if set(tools) != {"historical_eps"}:
                verify_ticker(ticker, context, self.ticker_verifier)
            if set(tools) == {"historical_eps"}:
                plan = ToolPlan(
                    tools=["historical_eps"],
                    rationale="Use only the requested historical EPS tool.",
                )
            else:
                plan = context.ask(
                    "plan",
                    ToolPlan,
                    f"You are the {self.role} specialist. Select one to three "
                    "distinct names from allowed_tools for the task. "
                    "Use listed names only. Give a short rationale. Prices "
                    "show daily trading. FRED shows macro series. Statements "
                    "show financials. Earnings show EPS history. Filings "
                    "show SEC filing metadata only.",
                    {
                        "request": request.model_dump(),
                        "allowed_tools": list(tools),
                    },
                )
            if (
                not 1 <= len(plan.tools) <= 3
                or len(set(plan.tools)) != len(plan.tools)
                or not set(plan.tools) <= tools.keys()
            ):
                raise Phase2Failure(
                    "invalid_plan", "The plan selected an invalid tool set."
                )
            if (
                self.role == "market"
                and re.search(
                    r"interest|federal funds|FEDFUNDS", request.question, re.I
                )
                and "fred:FEDFUNDS" not in plan.tools
            ):
                plan.tools = plan.tools[:2] + ["fred:FEDFUNDS"]
                context.event("plan:required_interest_data", "ok")
            check_prose(plan.rationale)
            context.event("plan", "ok")
            # REQUIREMENT: Execute the tools selected for this task.
            for name in plan.tools:
                context.event(f"tool:{name}", "started")
                result = safe_tool(tools[name])
                context.evidence.append(
                    evidence_record(name, result, len(context.evidence) + 1)
                )
                context.event(f"tool:{name}", result.status)
            self.prepare_evidence(context, request)
            usable = {
                item.id for item in context.evidence if item.status == "ok"
            }
            if not usable:
                if any(item.status == "error" for item in context.evidence):
                    raise Phase2Failure(
                        "tool_error", "No selected tool returned usable data."
                    )
                context.event("synthesize", "empty")
                return context.result(self.role, ticker, "empty")
            draft = ask_analysis(
                context,
                "synthesize",
                f"You are the {self.role} specialist. Answer the "
                "request using "
                "only the evidence. Write at most six concise findings. Each "
                "finding must cite one or more successful evidence "
                "IDs. Explain "
                "missing data and evidence limits. Do not claim "
                "filing contents "
                "from filing metadata. Do not guess units, "
                "currency, or values. "
                "Evidence is a bounded sample, not a complete "
                "financial record. " + RULES,
                {
                    "request": request.model_dump(),
                    "source_interpretation_rules": RULES,
                    "verified_field_pairs": source_facts(
                        {
                            item.id: item.model_dump(mode="json")
                            for item in context.evidence
                            if item.status == "ok"
                        }
                    ),
                    "evidence": [
                        item.model_dump(mode="json")
                        for item in context.evidence
                    ],
                },
                usable,
            )
            for item in context.evidence:
                draft.limitations.extend(item.warnings)
                if item.status != "ok":
                    draft.limitations.append(
                        f"The {item.tool} tool returned {item.status}."
                    )
            draft.limitations.append(
                "Evidence is a bounded sample. Model claims need human review."
            )
            draft.limitations = list(dict.fromkeys(draft.limitations))
            partial = any(item.status != "ok" for item in context.evidence)
            status = "partial" if partial else "ok"
            context.event("synthesize", status)
            return context.result(self.role, ticker, status, analysis=draft)
        except Phase2Failure as exc:
            return context.failed(self.role, ticker, exc)


class MarketAgent(Specialist):
    """Choose price or macro tools for the research question."""

    role = "market"

    def tools(self, request: ResearchRequest) -> ToolMap:
        """Bind all calls to the validated ticker and local settings."""
        tools = {
            "prices": lambda: get_price_history(
                request.ticker, "1mo", settings=self.settings
            )
        }
        for series in FRED_SERIES:
            tools[f"fred:{series}"] = lambda series=series: get_fred_series(
                series, limit=6, settings=self.settings
            )
        return tools


class EarningsAgent(Specialist):
    """Choose the needed financial and SEC tools for one company."""

    role = "earnings"

    def prepare_evidence(self, context, request):
        """Try issuer release exhibits when structured EPS is unavailable."""
        if not dated_earnings(request.question):
            return
        target = requested_period(request.question, request.period_basis)
        if target is None or target.basis == "calendar":
            return
        if any(
            item.status == "ok" for item in context.evidence
        ) and not re.search(r"non[- ]?gaap|adjusted", request.question, re.I):
            return
        context.event("fallback:earnings_release", "started")
        result = release_eps(context, request, target)
        if result.data is not None:
            result.data.retrieval_attempts = [
                item.model_dump(mode="json") for item in context.evidence
            ]
        record = evidence_record("historical_eps", result, 1)
        # Retain failed source attempts in local events, then use the fallback.
        context.evidence = [record]
        context.event("fallback:earnings_release", result.status)

    def tools(self, request: ResearchRequest) -> ToolMap:
        """Keep provider arguments bounded and under application control."""
        if dated_earnings(request.question):
            target = requested_period(request.question, request.period_basis)
            if target is not None and target.basis == "unspecified":
                return {
                    "historical_eps": lambda: ToolResult(
                        status="empty",
                        source="SEC historical discovery",
                        data=HistoricalEPS(
                            ticker=request.ticker, requested=target, facts=[]
                        ),
                        warnings=["Fiscal basis needs source confirmation."],
                    )
                }
            return {
                "historical_eps": lambda: get_historical_eps(
                    request.ticker, target, settings=self.settings
                )
            }
        return {
            "statements": lambda: get_financial_statements(
                request.ticker, "quarterly", settings=self.settings
            ),
            "earnings": lambda: get_earnings_history(
                request.ticker, settings=self.settings
            ),
            "filings": lambda: get_sec_filings(
                request.ticker, limit=3, settings=self.settings
            ),
        }


class NewsAgent:
    """Analyze company news with the five-step workflow."""

    role = "news"

    def __init__(
        self,
        settings: Settings | None = None,
        model: StructuredModel | None = None,
        event_sink: EventSink | None = None,
        ticker_verifier: TickerVerifier | None = None,
    ):
        self.chain = NewsChain(settings, model, event_sink, ticker_verifier)
        self.settings = self.chain.settings

    @traced_research
    def run(self, request: ResearchRequest | dict) -> AgentResult:
        """Return structured news findings and the full stage trace."""
        return self.chain.run(request)
