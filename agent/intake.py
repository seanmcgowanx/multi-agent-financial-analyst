"""Resolve one research request before specialist delegation."""

import re
from typing import Literal

import yfinance as yf
from pydantic import Field

from agent.historical import dated_earnings, requested_period
from agent.prompts import INTAKE_PROMPT
from agent.runtime import Phase2Failure, RunContext
from agent.schemas import Record, ResearchRequest


class Interpretation(Record):
    """Keep the model proposal separate from verified identity."""

    ticker: str = Field(max_length=20)
    company: str = Field(max_length=150)
    question: str = Field(min_length=1, max_length=1000)
    clarification: str = Field(max_length=500)


class IntakeResult(Record):
    """Return a request or a question without starting specialists."""

    status: Literal["ready", "needs_clarification"]
    message: str = ""
    request: ResearchRequest | None = None
    model_calls: int = 0


def lookup_company(query):
    """Read a small identity result without requesting news."""
    try:
        rows = yf.Search(
            query,
            max_results=5,
            news_count=0,
            lists_count=0,
            timeout=10,
            raise_errors=True,
        ).quotes
        return [
            {
                "ticker": row["symbol"],
                "company": row.get("longname") or row.get("shortname", ""),
            }
            for row in rows
            if row.get("symbol") and row.get("quoteType") == "EQUITY"
        ]
    except Exception:
        raise Phase2Failure(
            "identity_unavailable",
            "Company lookup is unavailable. Try again later.",
        ) from None


class IntakeSession:
    """Keep clarification history separate from saved research lessons."""

    def __init__(
        self,
        supervisor,
        *,
        ticker=None,
        company=None,
        period_basis="auto",
        response_format="auto",
        lookup=None,
    ):
        self.context = RunContext(supervisor.model, supervisor.settings, 4)
        self.overrides = {
            "ticker": ticker,
            "company": company,
            "period_basis": period_basis,
            "response_format": response_format,
        }
        self.messages = []
        self.previous = None
        self.lookup = lookup or lookup_company

    def reply(self, message):
        """Interpret the full exchange and validate before delegation."""
        if not message.strip() or len(message) > 1000:
            raise ValueError("Provide a question of at most 1000 characters.")
        self.messages.append({"role": "user", "text": message})
        user_text = " ".join(
            item["text"] for item in self.messages if item["role"] == "user"
        )
        if len(user_text) > 1000:
            raise ValueError("The conversation request is too long.")
        # Keep explicit details even when the model repeats a stale question.
        if self.previous is None:
            self.previous = self.context.ask(
                "supervisor:understand",
                Interpretation,
                INTAKE_PROMPT,
                {"messages": self.messages, "overrides": self.overrides},
            )
        proposal = self.previous
        question = user_text
        period = requested_period(question, self.overrides["period_basis"])

        def clarify(text):
            previous_questions = [
                item["text"]
                for item in self.messages
                if item["role"] == "assistant"
            ]
            if text in previous_questions:
                raise Phase2Failure(
                    "clarification_stalled",
                    "The clarification could not be resolved. No research "
                    "was started. Restate the complete question with company, "
                    "metric, quarter, year, and fiscal or calendar basis.",
                )
            self.messages.append({"role": "assistant", "text": text})
            return IntakeResult(
                status="needs_clarification",
                message=text,
                model_calls=self.context.model_calls,
            )

        ticker = self.overrides["ticker"] or proposal.ticker
        company = self.overrides["company"] or proposal.company
        # A possessive name is an explicit user identity, not a model guess.
        named = re.search(
            r"(?:what (?:were|was|are|is) |show |give me )"
            r"([A-Za-z][A-Za-z0-9 .&-]{0,100})['’]s\s",
            self.messages[0]["text"],
            re.I,
        )
        if not company and named:
            company = named[1].strip()
        if (
            self.overrides["ticker"]
            and proposal.ticker
            and proposal.ticker.upper() != ticker.upper()
        ):
            return clarify(
                "The ticker and question conflict. Please confirm the company."
            )
        if not company and not ticker:
            if len(self.messages) > 1 and re.fullmatch(
                r"[A-Za-z][A-Za-z .&-]{0,100}", message.strip(" .")
            ):
                company = message.strip(" .")
            else:
                return clarify("Which company or ticker do you mean?")
        if (
            re.search(
                r"multiple companies|which company|conflict",
                proposal.clarification,
                re.I,
            )
            and not named
            and not self.overrides["ticker"]
        ):
            return clarify(proposal.clarification)
        if not dated_earnings(question) and proposal.clarification:
            return clarify(proposal.clarification)
        if dated_earnings(question):
            missing = []
            if period is None or period.basis == "unspecified":
                missing.append(
                    "Which quarter, year, and fiscal or calendar basis?"
                )
            if not re.search(r"\bEPS\b|earnings per share", question, re.I):
                missing.append("Do you want EPS or net income?")
            if re.search(r"net income|revenue", question, re.I):
                return clarify(
                    "Historical net income and revenue are not supported yet. "
                    "Enter quit to stop, or start a separate EPS request."
                )
            if missing:
                return clarify(" ".join(missing))
        # Remember identity separately from clarification wording.
        self.previous = proposal.model_copy(
            update={"ticker": ticker, "company": company}
        )
        rows = self.lookup(company or ticker)
        matches = [
            row
            for row in rows
            if not ticker or row["ticker"].upper() == ticker.upper()
        ]
        if len(matches) != 1:
            return clarify(
                "The company lookup did not confirm one matching ticker. "
                "Please confirm the company and ticker."
            )
        request = ResearchRequest(
            ticker=matches[0]["ticker"],
            company_name=matches[0]["company"],
            question=question,
            period_basis=self.overrides["period_basis"],
            response_format=self.overrides["response_format"],
        )
        return IntakeResult(
            status="ready",
            request=request,
            model_calls=self.context.model_calls,
        )


def prepare_request(
    supervisor,
    question,
    *,
    ticker=None,
    company=None,
    period_basis="auto",
    response_format="auto",
    clarify=False,
    callback=None,
    audit=None,
):
    """Share request preparation between the CLI and future notebook."""
    if ticker and company and not clarify:
        return ResearchRequest(
            ticker=ticker,
            company_name=company,
            question=question,
            period_basis=period_basis,
            response_format=response_format,
        ), 0
    session = supervisor.conversation(
        ticker=ticker,
        company=company,
        period_basis=period_basis,
        response_format=response_format,
    )
    result = session.reply(question)
    while result.status == "needs_clarification" and callback:
        answer = callback(result.message)
        if not answer or answer.strip().lower() in {"quit", "exit"}:
            break
        result = session.reply(answer)
    if audit is not None:
        audit.update(
            messages=session.messages, resolved=result.model_dump(mode="json")
        )
    return (
        result.request if result.status == "ready" else result,
        result.model_calls,
    )
