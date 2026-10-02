"""Run the news prompt chain and report evaluation workflow."""

import re
from datetime import datetime, timedelta, timezone

from agent.config import Settings
from agent.evidence import RULES, grounding_issues, period_issues
from agent.news import (
    clean_text,
    complete_excerpts,
    news_query,
    select_news,
    unsupported_numbers,
)
from agent.prompts import (
    EVALUATOR_PROMPT,
    NEWS_CLASSIFY_PROMPT,
    NEWS_EXTRACT_PROMPT,
    NEWS_SUMMARY_PROMPT,
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
    validate_request,
    verify_ticker,
)
from agent.schemas import (
    AgentResult,
    AnalysisDraft,
    Classification,
    CleanArticle,
    Evaluation,
    EvaluationDraft,
    Extraction,
    NewsChainData,
    NewsData,
    NewsFact,
    ResearchRequest,
)
from agent.tools import get_company_news


def preprocess(data: NewsData, settings: Settings) -> list[CleanArticle]:
    """Keep unique source links and bounded visible text."""
    articles = []
    seen = set()
    for article in data.articles:
        if article.url in seen:
            continue
        seen.add(article.url)
        title = clean_text(article.title)[:200]
        text = clean_text(
            " ".join(
                filter(
                    None,
                    (
                        article.title,
                        article.description,
                        article.content,
                    ),
                )
            )
        )[: settings.news_text_chars]
        if not title or not text:
            continue
        articles.append(
            CleanArticle(
                id=f"a{len(articles) + 1}",
                title=title,
                text=text,
                url=article.url,
                published_at=article.published_at,
            )
        )
        if len(articles) >= settings.news_article_limit:
            break
    return articles


class NewsChain:
    """Keep every completed stage visible in the returned result."""

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

    def run(self, request: ResearchRequest | dict) -> AgentResult:
        """Use bounded model calls only when news evidence is available."""
        context = RunContext(self.model, self.settings, 4, self.event_sink)
        chain = NewsChainData()
        ticker = ""

        def empty(reason, *stages):
            """Keep empty-stage evidence consistent across early returns."""
            chain.diagnostics.empty_reason = reason
            for stage in stages:
                context.event(stage, "empty")
            return context.result("news", ticker, "empty", news_chain=chain)

        try:
            request = validate_request(request)
            ticker = request.ticker
            if isinstance(self.model, OpenAIModel):
                if not self.settings.openai_api_key.get_secret_value():
                    raise Phase2Failure(
                        "missing_key", "Set OPENAI_API_KEY locally."
                    )
            verify_ticker(ticker, context, self.ticker_verifier)
            # REQUIREMENT: Ingest, preprocess, classify, extract, summarize.
            context.event("ingest", "started")
            search_from = (
                datetime.now(timezone.utc).date()
                - timedelta(days=self.settings.news_lookback_days)
            ).isoformat()
            chain.diagnostics.query = news_query(request)
            chain.diagnostics.from_date = search_from
            raw = safe_tool(
                lambda: get_company_news(
                    chain.diagnostics.query,
                    limit=self.settings.news_candidate_limit,
                    sort_by="relevancy",
                    from_date=search_from,
                    settings=self.settings,
                )
            )
            context.event("ingest", raw.status)
            if raw.status == "error":
                chain.diagnostics.empty_reason = "provider_error"
                context.evidence.append(evidence_record("news", raw, 1))
                raise Phase2Failure(
                    raw.error.code, "News ingestion could not complete."
                )
            context.event("preprocess", "started")
            chain.articles, chain.diagnostics = select_news(
                raw.data, request, self.settings
            )
            chain.diagnostics.from_date = search_from
            context.evidence.append(
                evidence_record(
                    "news",
                    raw,
                    1,
                    {
                        "query": raw.data.query,
                        "articles": [
                            a.model_dump(mode="json") for a in chain.articles
                        ],
                    },
                )
            )
            context.event("preprocess", "ok" if chain.articles else "empty")
            if not chain.articles:
                reason = (
                    "provider_empty"
                    if not raw.data.articles
                    else "no_usable_candidates"
                )
                return empty(reason, "classify", "extract", "summarize")
            classification = context.ask(
                "classify",
                Classification,
                NEWS_CLASSIFY_PROMPT,
                {
                    "request": request.model_dump(),
                    "articles": [
                        a.model_dump(mode="json") for a in chain.articles
                    ],
                },
            )
            ids = [label.article_id for label in classification.labels]
            if len(ids) != len(set(ids)) or set(ids) != {
                article.id for article in chain.articles
            }:
                raise Phase2Failure(
                    "invalid_model_output",
                    "Article classification IDs differ.",
                )
            chain.labels = classification.labels
            context.event("classify", "ok")
            relevant = {
                label.article_id for label in chain.labels if label.relevant
            }
            chain.diagnostics.relevant_count = len(relevant)
            if not relevant:
                return empty("no_relevant_articles", "extract", "summarize")
            articles = [a for a in chain.articles if a.id in relevant]
            excerpts = {
                f"{article.id}:q{index}": {
                    "article_id": article.id,
                    "text": text,
                }
                for article in articles
                for index, text in enumerate(
                    complete_excerpts(article.text), start=1
                )
                if text.strip()
            }
            if not excerpts:
                return empty("no_supported_facts", "extract", "summarize")
            extraction = context.ask(
                "extract",
                Extraction,
                NEWS_EXTRACT_PROMPT,
                {
                    "request": request.model_dump(),
                    "labels": [label.model_dump() for label in chain.labels],
                    "excerpts": excerpts,
                },
            )
            fact_ids = [fact.id for fact in extraction.facts]
            if len(fact_ids) > 6 or len(fact_ids) != len(set(fact_ids)):
                raise Phase2Failure(
                    "invalid_model_output", "Extracted fact IDs are invalid."
                )
            grounded = []
            for fact in extraction.facts:
                excerpt = excerpts.get(fact.quote_id)
                if (
                    not re.fullmatch(r"f[1-9][0-9]?", fact.id)
                    or excerpt is None
                    or excerpt["article_id"] != fact.article_id
                ):
                    raise Phase2Failure(
                        "invalid_model_output",
                        "A fact has no matching source quote.",
                    )
                check_prose(fact.claim)
                if unsupported_numbers(fact.claim, excerpt["text"]):
                    chain.diagnostics.rejected_fact_count += 1
                    continue
                grounded.append(
                    NewsFact(**fact.model_dump(), quote=excerpt["text"])
                )
            chain.facts = grounded
            fact_ids = [fact.id for fact in grounded]
            context.event("extract", "ok" if chain.facts else "empty")
            chain.diagnostics.fact_count = len(chain.facts)
            if not chain.facts:
                return empty("no_supported_facts", "summarize")
            draft = ask_analysis(
                context,
                "summarize",
                NEWS_SUMMARY_PROMPT,
                {
                    "request": request.model_dump(),
                    "facts": [fact.model_dump() for fact in chain.facts],
                    "sources": [
                        {
                            "article_id": a.id,
                            "url": a.url,
                            "published_at": a.published_at.isoformat(),
                        }
                        for a in articles
                    ],
                },
                set(fact_ids),
            )
            if chain.diagnostics.rejected_fact_count:
                draft.limitations.append(
                    "Some extracted claims were omitted because their numbers "
                    "were not supported by the cited excerpt."
                )
            draft.limitations.extend(raw.warnings)
            draft.limitations.append(
                "This is a bounded news sample. Source claims need "
                "human review."
            )
            draft.limitations = list(dict.fromkeys(draft.limitations))
            context.event("summarize", "ok")
            return context.result(
                "news", ticker, "ok", analysis=draft, news_chain=chain
            )
        except Phase2Failure as exc:
            return context.failed("news", ticker, exc, news_chain=chain)


def citation_issues(report: AnalysisDraft, references: dict) -> list[str]:
    """Identify empty or unknown citations without asking the model."""
    issues = []
    for index, finding in enumerate(report.findings, start=1):
        if not finding.evidence_ids:
            issues.append(f"Finding {index} has no evidence link.")
        elif not set(finding.evidence_ids) <= references.keys():
            issues.append(f"Finding {index} cites unknown evidence.")
    if not report.findings:
        issues.append("The report has no findings.")
    return issues


def required_corrections(evaluation: Evaluation, threshold: int) -> list[str]:
    """Make rejected scores visible even when the model requests no edit."""
    corrections = evaluation.evidence_issues + evaluation.citation_issues
    for dimension in ("accuracy", "coverage", "clarity"):
        score = getattr(evaluation.assessment, dimension)
        if score < threshold:
            corrections.append(
                f"The {dimension} score is {score}; the minimum is "
                f"{threshold}. Address the feedback with supported findings. "
                "Do not invent missing data."
            )
    return corrections + evaluation.assessment.critique


def evaluate_report(
    context: RunContext,
    request: ResearchRequest,
    report: AnalysisDraft,
    references: dict,
    coverage: list[dict],
    version: int,
    threshold: int,
) -> Evaluation:
    """Use one structured LLM call, then apply fixed quality checks."""
    issues = citation_issues(report, references)
    evidence_issues = grounding_issues(report, references, coverage)
    evidence_issues.extend(period_issues(request, references))
    assessment = context.ask(
        f"evaluate:{version}",
        EvaluationDraft,
        EVALUATOR_PROMPT + RULES,
        {
            "acceptance_threshold": threshold,
            "request": request.model_dump(),
            "report": report.model_dump(),
            "references": references,
            "specialist_coverage": coverage,
            "citation_issues": issues,
            "evidence_issues": evidence_issues,
        },
    )
    scores = (assessment.accuracy, assessment.coverage, assessment.clarity)
    if any(not 0 <= value <= 5 for value in scores):
        raise Phase2Failure(
            "invalid_evaluation", "A score is outside zero to five."
        )
    if len(assessment.critique) > 4 or not 1 <= len(assessment.lessons) <= 3:
        raise Phase2Failure(
            "invalid_evaluation", "The evaluator lists are invalid."
        )
    for text in assessment.critique + assessment.lessons:
        check_prose(text)
        if len(text) > 600:
            raise Phase2Failure(
                "invalid_evaluation", "Evaluator text is too long."
            )
    accepted = (
        min(scores) >= threshold
        and not assessment.revision_required
        and not issues
        and not evidence_issues
    )
    if not accepted and not assessment.critique:
        assessment.critique.append(
            "Correct unsupported claims and cover the requested topics."
        )
    result = Evaluation(
        version=version,
        assessment=assessment,
        accepted=accepted,
        citation_issues=issues,
        evidence_issues=evidence_issues,
    )
    context.event(f"evaluate:{version}", "ok" if accepted else "partial")
    return result
