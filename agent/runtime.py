"""Share model calls, tracing, and bounded execution."""

import json
import re
import warnings
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from typing import Any, Protocol, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langsmith import Client, trace, tracing_context
from langsmith.run_helpers import get_tracing_context
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from agent.config import Settings
from agent.prompts import STYLE
from agent.providers import ToolFailure, failure
from agent.schemas import (
    AgentResult,
    AnalysisDraft,
    Evidence,
    PriceHistory,
    ResearchRequest,
    RunError,
    StageEvent,
    ToolResult,
)
from agent.tools import get_price_history


@contextmanager
def model_tracing(settings: Settings):
    """Use explicit settings instead of ambient tracing variables."""
    key = settings.langsmith_api_key.get_secret_value()
    enabled = settings.langsmith_tracing and bool(key)
    current = get_tracing_context()
    client = current.get("client") if enabled else None
    owned = enabled and client is None
    if settings.langsmith_tracing and not key:
        warnings.warn(
            "LangSmith tracing needs LANGSMITH_API_KEY.", stacklevel=2
        )
    if owned:
        try:
            client = Client(
                api_key=key,
                api_url="https://api.smith.langchain.com",
                timeout_ms=5000,
            )
        except Exception:
            enabled = False
            owned = False
            warnings.warn("LangSmith tracing could not start.", stacklevel=2)
    try:
        with tracing_context(
            enabled=enabled,
            client=client,
            project_name=settings.langsmith_project,
        ):
            yield
    finally:
        if owned:
            try:
                client.flush(timeout=10)
            except Exception:
                warnings.warn(
                    "LangSmith trace upload could not finish.", stacklevel=2
                )


def traced_research(function):
    """Group delegation and model stages under a named research run."""

    @wraps(function)
    def wrapped(self, request):
        with model_tracing(self.settings):
            # Only the request is recorded. The agent holds secret settings.
            inputs = (
                request.model_dump(mode="json")
                if hasattr(request, "model_dump")
                else {}
            )
            with trace(type(self).__name__, inputs=inputs) as run:
                result = function(self, request)
                if run is not None:
                    run.end(
                        outputs={
                            "status": result.status,
                            "model_calls": result.model_calls,
                            "run_id": getattr(result, "run_id", None),
                        }
                    )
                return result

    return wrapped


T = TypeVar("T", bound=BaseModel)


class Phase2Failure(Exception):
    """Carry an error message that is safe to show."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class StructuredModel(Protocol):
    """Allow deterministic tests without a real model or API key."""

    def generate(self, schema: type[T], instruction: str, payload: dict) -> T:
        """Produce one validated response."""
        ...


class OpenAIModel:
    """Call the configured small model through LangChain."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(self, schema: type[T], instruction: str, payload: dict) -> T:
        """Make one bounded call without automatic paid retries."""
        key = self.settings.openai_api_key.get_secret_value()
        if not key:
            raise Phase2Failure("missing_key", "Set OPENAI_API_KEY locally.")
        encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False)
        if len(encoded) > self.settings.llm_input_chars:
            raise Phase2Failure(
                "input_limit", "The model input exceeds the configured limit."
            )
        try:
            model = ChatOpenAI(
                model=self.settings.openai_model,
                api_key=key,
                base_url="https://api.openai.com/v1",
                temperature=0,
                max_tokens=self.settings.llm_max_tokens,
                timeout=self.settings.llm_timeout,
                max_retries=0,
            )
            runnable = model.with_structured_output(
                schema, method="json_schema", strict=True
            )
            # Honor the explicit local tracing settings.
            with model_tracing(self.settings):
                result = runnable.invoke(
                    [
                        SystemMessage(content=STYLE + " " + instruction),
                        HumanMessage(content=encoded),
                    ]
                )
            return schema.model_validate(result)
        except APITimeoutError:
            raise Phase2Failure(
                "timeout", "The model call timed out."
            ) from None
        except AuthenticationError:
            raise Phase2Failure(
                "authentication", "OpenAI rejected the API key."
            ) from None
        except RateLimitError:
            raise Phase2Failure(
                "rate_limit", "The model request limit was reached."
            ) from None
        except APIConnectionError:
            raise Phase2Failure(
                "network_error", "The model network request failed."
            ) from None
        except APIStatusError:
            raise Phase2Failure(
                "model_error", "The model provider rejected the request."
            ) from None
        except (ValidationError, ValueError, TypeError):
            raise Phase2Failure(
                "invalid_model_output", "The model response was invalid."
            ) from None
        except Exception:
            # Parsing errors can come from either the SDK or LangChain.
            raise Phase2Failure(
                "model_error", "The model response could not be processed."
            ) from None


T = TypeVar("T", bound=BaseModel)
EventSink = Callable[[StageEvent], None]


def check_prose(text: str) -> None:
    """Reject prohibited punctuation and common contractions in model prose."""
    normalized = text.replace(chr(0x2019), "'")
    pattern = r"\b\w+(?:n't|'re|'ve|'ll|'d|'m)\b|\b(?:it|that|there|what)'s\b"
    if (
        not text.strip()
        or chr(0x2014) in text
        or re.search(pattern, normalized, re.IGNORECASE)
    ):
        raise Phase2Failure(
            "invalid_model_output",
            "The model prose did not meet the text rules.",
        )


class RunContext:
    """Keep state local to one invocation, with no persistent memory."""

    def __init__(
        self,
        model: StructuredModel,
        settings: Settings,
        budget: int,
        event_sink: EventSink | None = None,
    ):
        self.model = model
        self.settings = settings
        self.budget = budget
        self.model_calls = 0
        self.events: list[StageEvent] = []
        self.evidence: list[Evidence] = []
        self.event_sink = event_sink

    def event(self, stage: str, status: str) -> None:
        """Record a safe event and notify an optional local display."""
        event = StageEvent(stage=stage, status=status)
        self.events.append(event)
        if self.event_sink:
            self.event_sink(event)

    def ask(
        self, stage: str, schema: type[T], instruction: str, payload: dict
    ) -> T:
        """Enforce limits before every model call, including test doubles."""
        if self.model_calls >= self.budget:
            raise Phase2Failure(
                "call_limit", "The model call limit was reached."
            )
        encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False)
        if len(encoded) > self.settings.llm_input_chars:
            raise Phase2Failure("input_limit", "The model input is too large.")
        self.event(stage, "started")
        self.model_calls += 1
        try:
            with (
                model_tracing(self.settings),
                trace(stage, inputs={"payload": payload}) as run,
            ):
                result = schema.model_validate(
                    self.model.generate(schema, instruction, payload)
                )
                if run is not None:
                    run.end(outputs=result.model_dump(mode="json"))
        except Phase2Failure:
            self.event(stage, "error")
            raise
        except Exception:
            self.event(stage, "error")
            raise Phase2Failure(
                "invalid_model_output", "The model response was invalid."
            ) from None
        return result

    def result(
        self, role: str, ticker: str, status: str, **kwargs: Any
    ) -> AgentResult:
        """Build the final result with the full local trace."""
        return AgentResult(
            role=role,
            ticker=ticker,
            status=status,
            evidence=self.evidence,
            events=self.events,
            model_calls=self.model_calls,
            **kwargs,
        )

    def failed(
        self, role: str, ticker: str, error: Phase2Failure, **kwargs: Any
    ) -> AgentResult:
        """Preserve completed evidence when a later stage fails."""
        self.event("result", "error")
        return self.result(
            role,
            ticker,
            "error",
            error=RunError(code=error.code, message=str(error)),
            **kwargs,
        )


def validate_request(value: ResearchRequest | dict) -> ResearchRequest:
    """Return a checked request without exposing validation input."""
    try:
        return ResearchRequest.model_validate(value)
    except (ValidationError, TypeError):
        raise Phase2Failure(
            "invalid_input", "Provide a valid ticker and research question."
        ) from None


def safe_tool(call: Callable[[], ToolResult]) -> ToolResult:
    """Contain unexpected adapter errors without printing exception text."""
    try:
        result = call()
        if not isinstance(result, ToolResult):
            raise TypeError("The tool result is invalid.")
        return result
    except Exception:
        return failure(
            "tool adapter",
            ToolFailure(
                "provider_error", "The selected tool could not complete."
            ),
        )


def compact_data(tool: str, result: ToolResult) -> dict | None:
    """Keep useful evidence within a known size before model synthesis."""
    if result.data is None:
        return None
    data = result.data.model_dump(mode="json")
    if tool == "prices":
        data["bars"] = data["bars"][-10:]
    elif tool == "statements":
        wanted = {
            "TotalRevenue",
            "NetIncome",
            "OperatingIncome",
            "BasicEPS",
            "DilutedEPS",
            "TotalAssets",
            "TotalDebt",
            "StockholdersEquity",
            "OperatingCashFlow",
            "FreeCashFlow",
            "CapitalExpenditure",
            "CashAndCashEquivalents",
        }
        for name in ("income_statement", "balance_sheet", "cash_flow"):
            data[name] = data[name][:2]
            for period in data[name]:
                period["values"] = {
                    key: value
                    for key, value in period["values"].items()
                    if key in wanted
                }
    elif tool == "earnings":
        data["earnings"] = data["earnings"][-4:]
    elif tool == "filings":
        data["filings"] = data["filings"][:3]
    return data


def evidence_record(
    tool: str, result: ToolResult, index: int, data: dict | None = None
) -> Evidence:
    """Preserve status and provenance without any raw provider errors."""
    return Evidence(
        id=f"e{index}",
        tool=tool,
        source=result.source,
        retrieved_at=result.retrieved_at,
        status=result.status,
        data=compact_data(tool, result) if data is None else data,
        warnings=result.warnings,
        error_code=result.error.code if result.error else None,
    )


class CitationFailure(Phase2Failure):
    """Identify source links that need one correction attempt."""


def ask_analysis(
    context: RunContext,
    stage: str,
    instruction: str,
    payload: dict,
    allowed_ids: set[str],
) -> AnalysisDraft:
    """Allow one citation correction using the same collected evidence."""
    payload = {**payload, "allowed_evidence_ids": sorted(allowed_ids)}
    instruction += (
        " Use only IDs in allowed_evidence_ids for evidence_ids. "
        "Select IDs whose evidence supports the claim. Do not invent IDs."
    )
    for attempt in range(2):
        current_stage = stage if attempt == 0 else f"{stage}:citation_repair"
        draft = context.ask(current_stage, AnalysisDraft, instruction, payload)
        try:
            validate_analysis(draft, allowed_ids)
        except CitationFailure:
            context.event(current_stage, "error")
            if attempt:
                raise
            payload = {
                **payload,
                "correction": (
                    "The previous response had missing or unknown IDs. "
                    "Write a new analysis from the same evidence. "
                    "Every finding "
                    "must cite supported IDs from allowed_evidence_ids."
                ),
            }
        else:
            if attempt:
                context.event(current_stage, "ok")
            return draft
    raise AssertionError("The bounded correction loop did not return.")


def validate_analysis(draft: AnalysisDraft, allowed_ids: set[str]) -> None:
    """Reject unsupported evidence references and empty findings."""
    check_prose(draft.summary)
    if not 1 <= len(draft.findings) <= 6:
        raise Phase2Failure(
            "invalid_model_output", "The analysis needs one to six findings."
        )
    for finding in draft.findings:
        check_prose(finding.claim)
        if (
            not finding.evidence_ids
            or not set(finding.evidence_ids) <= allowed_ids
        ):
            raise CitationFailure(
                "invalid_model_output",
                "A finding has an unknown evidence link.",
            )
    for item in draft.limitations:
        check_prose(item)


class TickerVerifier:
    """Share a successful check only within one Supervisor run."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.verified: set[str] = set()

    def check(self, ticker: str) -> None:
        """Reject unverified symbols without guessing if they are delisted."""
        if ticker in self.verified:
            return
        result = safe_tool(
            lambda: get_price_history(ticker, "5d", settings=self.settings)
        )
        if (
            result.status != "ok"
            or not isinstance(result.data, PriceHistory)
            or result.data.ticker != ticker
            or not result.data.bars
        ):
            raise Phase2Failure(
                "ticker_unverified",
                "Recent market data could not verify this ticker. "
                "Check the symbol or retry when the provider is available.",
            )
        self.verified.add(ticker)


def verify_ticker(
    ticker: str, context: RunContext, verifier: TickerVerifier | None = None
) -> None:
    """Record the check without adding a model call."""
    checker = verifier or TickerVerifier(context.settings)
    context.event("ticker:verify", "started")
    try:
        checker.check(ticker)
    except Phase2Failure:
        context.event("ticker:verify", "error")
        raise
    context.event("ticker:verify", "ok")
