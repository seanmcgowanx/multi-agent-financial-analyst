"""Define the data exchanged by tools, agents, and evaluation."""

import re
from datetime import date, datetime, timezone
from typing import Any, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

T = TypeVar("T")
ErrorCode = Literal[
    "missing_key",
    "invalid_input",
    "timeout",
    "network_error",
    "rate_limit",
    "authentication",
    "provider_error",
    "invalid_response",
    "dependency_missing",
]


class Record(BaseModel):
    """Reject non-finite numbers in provider data."""

    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


class ToolError(Record):
    """Describe a failure without provider messages or secret values."""

    code: ErrorCode
    message: str
    retryable: bool = False


class ToolResult(Record, Generic[T]):
    """Keep status, source, time, data, and errors together."""

    status: Literal["ok", "empty", "error"]
    source: str
    retrieved_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    data: T | None = None
    error: ToolError | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_status(self) -> "ToolResult[T]":
        """Prevent success and failure fields from conflicting."""
        if self.status == "error":
            if self.error is None or self.data is not None:
                raise ValueError("An error needs details and no data.")
        elif self.error is not None or self.data is None:
            raise ValueError("A data result needs data and no error.")
        return self


class PriceBar(Record):
    """Store one unadjusted daily price bar."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int = Field(ge=0)


class PriceHistory(Record):
    """Store daily prices in the exchange timezone."""

    ticker: str
    currency: str | None = None
    exchange_timezone: str | None = None
    adjusted: bool = False
    bars: list[PriceBar]


class Observation(Record):
    """Keep missing FRED values as null."""

    date: date
    value: float | None


class MacroSeries(Record):
    """Store observations in the native units of the FRED series."""

    series_id: str
    observations: list[Observation]


class Article(Record):
    """Keep news text and source links for the later prompt chain."""

    title: str = Field(min_length=1)
    url: str = Field(pattern=r"^https?://")
    published_at: datetime
    source: str | None = None
    author: str | None = None
    description: str | None = None
    content: str | None = None


class NewsData(Record):
    """Store one bounded page of news results."""

    query: str
    total_results: int = Field(ge=0)
    articles: list[Article]


class Filing(Record):
    """Store EDGAR filing metadata returned by sec-api.io."""

    accession_number: str = Field(min_length=1)
    form_type: str
    filed_at: datetime
    period_of_report: date | None = None
    cik: str
    company_name: str
    url: str = Field(pattern=r"^https?://")


class FilingData(Record):
    """Store a bounded filing search result."""

    ticker: str
    filings: list[Filing]


class StatementPeriod(Record):
    """Store financial statement values for one reporting period."""

    period_end: date
    values: dict[str, float | None]


class FinancialStatements(Record):
    """Store statements without guessing the reporting currency."""

    ticker: str
    frequency: Literal["annual", "quarterly"]
    currency: str | None = None
    income_statement: list[StatementPeriod]
    balance_sheet: list[StatementPeriod]
    cash_flow: list[StatementPeriod]


class EarningsRecord(Record):
    """Store reported and estimated earnings per share."""

    period: date
    eps_estimate: float | None = None
    eps_actual: float | None = None
    surprise_ratio: float | None = None


class EarningsHistory(Record):
    """Store historical earnings observations."""

    ticker: str
    earnings: list[EarningsRecord]


Role = Literal["market", "earnings", "news"]


def ticker_symbol(value: str) -> str:
    """Allow common stock symbols and Yahoo index symbols."""
    if not isinstance(value, str):
        raise ValueError("The ticker must be text.")
    value = value.strip().upper()
    if not re.fullmatch(r"\^?[A-Z0-9][A-Z0-9.=-]{0,14}", value):
        raise ValueError("The ticker has an invalid format.")
    return value


class Lesson(Record):
    """Store a research practice, not a claim about current prices."""

    id: str
    run_id: str
    ticker: str
    text: str = Field(min_length=1, max_length=600)
    outcome: Literal["accepted", "needs_review"]
    created_at: datetime


class MemoryDocument(Record):
    """Validate the version and contents before any update."""

    version: Literal[1] = 1
    lessons: list[Lesson] = Field(default_factory=list, max_length=100)


class ResearchRequest(Record):
    """Keep the research task separate from provider content."""

    ticker: str
    question: str = Field(min_length=1, max_length=1000)
    company_name: str = Field(default="", max_length=150)
    period_basis: Literal["auto", "fiscal", "calendar"] = "auto"
    response_format: Literal["auto", "answer", "report"] = "auto"

    @field_validator("ticker")
    @classmethod
    def valid_ticker(cls, value: str) -> str:
        """Normalize a supported ticker."""
        return ticker_symbol(value)

    @field_validator("question")
    @classmethod
    def valid_question(cls, value: str) -> str:
        """Reject blank questions."""
        if not value.strip():
            raise ValueError("The research question is empty.")
        return value.strip()


class ToolPlan(Record):
    """Let a specialist choose only its own allowed tool names."""

    tools: list[str]
    rationale: str


class Finding(Record):
    """Link one generated finding to known evidence identifiers."""

    claim: str
    evidence_ids: list[str]


class AnalysisDraft(Record):
    """Return findings and explicit limits in a fixed format."""

    summary: str
    findings: list[Finding]
    limitations: list[str]


class Evidence(Record):
    """Keep bounded data, provider status, and retrieval time."""

    id: str
    tool: str
    source: str
    retrieved_at: datetime
    status: Literal["ok", "empty", "error"]
    data: dict[str, Any] | None
    warnings: list[str]
    error_code: str | None


class StageEvent(Record):
    """Record visible execution without keys or raw error text."""

    stage: str
    status: Literal["started", "ok", "empty", "error", "partial"]


class RunError(Record):
    """Describe a safe failure at the agent boundary."""

    code: str
    message: str


class CleanArticle(Record):
    """Keep bounded cleaned text with its original source link."""

    id: str
    title: str
    text: str
    url: str
    published_at: datetime


class ArticleLabel(Record):
    """Classify an article for the current company and research task."""

    article_id: str
    relevant: bool
    category: Literal["earnings", "market", "company", "other"]


class Classification(Record):
    """Return exactly one label per cleaned article."""

    labels: list[ArticleLabel]


class NewsFact(Record):
    """Link an extracted statement to an exact source text excerpt."""

    id: str
    article_id: str
    claim: str
    quote_id: str
    quote: str


class SelectedFact(Record):
    """Select a known source excerpt instead of recreating its text."""

    id: str
    article_id: str
    claim: str
    quote_id: str


class Extraction(Record):
    """Return only facts from relevant input articles."""

    facts: list[SelectedFact]


class NewsCandidateDecision(Record):
    """Explain selection without claiming certain language detection."""

    title: str
    url: str
    score: int = 0
    language_hint: str = "uncertain"
    outcome: str


class NewsDiagnostics(Record):
    """Count each selection stage and explain empty outcomes."""

    query: str = ""
    from_date: str | None = None
    total_results: int = 0
    received_count: int = 0
    duplicate_count: int = 0
    unusable_count: int = 0
    selected_count: int = 0
    relevant_count: int = 0
    fact_count: int = 0
    rejected_fact_count: int = 0
    empty_reason: str | None = None
    candidates: list[NewsCandidateDecision] = Field(default_factory=list)


class NewsChainData(Record):
    """Keep the output of every completed news stage."""

    diagnostics: NewsDiagnostics = Field(default_factory=NewsDiagnostics)
    articles: list[CleanArticle] = Field(default_factory=list)
    labels: list[ArticleLabel] = Field(default_factory=list)
    facts: list[NewsFact] = Field(default_factory=list)


class AgentResult(Record):
    """Return a specialist result ready for later delegation."""

    role: Role
    ticker: str
    status: Literal["ok", "partial", "empty", "error"]
    analysis: AnalysisDraft | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    events: list[StageEvent] = Field(default_factory=list)
    model_calls: int = 0
    error: RunError | None = None
    news_chain: NewsChainData | None = None

    @model_validator(mode="after")
    def consistent_status(self) -> "AgentResult":
        """Require findings for success and details for failure."""
        if self.status in ("ok", "partial") and self.analysis is None:
            raise ValueError("A successful analysis needs a draft.")
        if self.status == "error" and self.error is None:
            raise ValueError("An error needs details.")
        if self.status != "error" and self.error is not None:
            raise ValueError("Only an error result can contain an error.")
        return self


class EvaluationDraft(Record):
    """Ask the model for scores, specific feedback, and reusable lessons."""

    accuracy: int = Field(ge=0, le=5, strict=True)
    coverage: int = Field(ge=0, le=5, strict=True)
    clarity: int = Field(ge=0, le=5, strict=True)
    revision_required: bool
    critique: list[str] = Field(max_length=4)
    lessons: list[str] = Field(min_length=1, max_length=3)


class Evaluation(Record):
    """Separate model judgement from deterministic acceptance checks."""

    version: int
    assessment: EvaluationDraft
    accepted: bool
    citation_issues: list[str] = Field(default_factory=list)
    evidence_issues: list[str] = Field(default_factory=list)


class Delegation(Record):
    """Send a bounded research question to one specialist."""

    role: Role
    question: str


class ResearchPlan(Record):
    """Select the needed specialists and explain the research steps."""

    rationale: str
    response_format: Literal["answer", "report"] = "answer"
    steps: list[Delegation] = Field(min_length=1, max_length=3)


class ReportDraft(AnalysisDraft):
    """Constrain the combined report before the model generates it."""

    findings: list[Finding] = Field(min_length=1, max_length=6)
    limitations: list[str] = Field(max_length=12)


class SupervisorResult(Record):
    """Retain drafts, evaluations, handoffs, and memory evidence."""

    run_id: str
    response_format: Literal["answer", "report"] = "report"
    status: Literal["completed", "partial", "needs_review", "error"]
    request: ResearchRequest | None = None
    plan: ResearchPlan | None = None
    report: AnalysisDraft | None = None
    model_report_versions: list[AnalysisDraft] = Field(default_factory=list)
    report_versions: list[AnalysisDraft] = Field(default_factory=list)
    specialists: list[AgentResult] = Field(default_factory=list)
    references: dict = Field(default_factory=dict)
    evaluations: list[Evaluation] = Field(default_factory=list)
    lessons_loaded: list[Lesson] = Field(default_factory=list)
    lessons_saved: list[Lesson] = Field(default_factory=list)
    memory_warnings: list[str] = Field(default_factory=list)
    events: list[StageEvent] = Field(default_factory=list)
    model_calls: int = 0
    error: RunError | None = None

    @model_validator(mode="after")
    def check_outcome(self) -> "SupervisorResult":
        """Do not label an unevaluated report as complete."""
        if self.status in ("completed", "partial"):
            if not self.report or not self.evaluations:
                raise ValueError("A completed report needs an evaluation.")
            if not self.evaluations[-1].accepted:
                raise ValueError("A completed report needs accepted scores.")
        if self.status == "needs_review":
            if not self.evaluations or self.evaluations[-1].accepted:
                raise ValueError(
                    "A review result needs a rejected evaluation."
                )
        if (self.status == "error") != (self.error is not None):
            raise ValueError("Error status and error details must agree.")
        return self
