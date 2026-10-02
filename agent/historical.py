"""Find and validate quarterly EPS in SEC source records."""

import calendar
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlsplit

import requests
from pydantic import Field

from agent.config import Settings
from agent.prompts import EARNINGS_EXTRACT_PROMPT
from agent.providers import (
    ToolFailure,
    bad_response,
    failure,
    request_json,
    require_key,
    ticker_symbol,
)
from agent.schemas import Record, ToolResult
from agent.tools import get_sec_filings


class EarningsPeriod(Record):
    """Keep the requested quarter separate from filing dates."""

    year: int = Field(ge=1993, le=2100)
    quarter: int = Field(ge=1, le=4)
    basis: Literal["fiscal", "calendar", "unspecified"]

    def calendar_dates(self):
        """Return exact calendar dates only for a calendar request."""
        month = self.quarter * 3
        return (
            date(self.year, month - 2, 1),
            date(self.year, month, calendar.monthrange(self.year, month)[1]),
        )


def dated_earnings(question: str) -> bool:
    """Recognize dated financial requests that need a period check."""
    return bool(
        re.search(r"\b(?:EPS|earnings|net income|revenue)\b", question, re.I)
        and re.search(r"(?<!\d)(?:19|20)\d{2}\b", question)
    )


def requested_period(question: str, basis: str = "auto"):
    """Parse one year and quarter, leaving ambiguous requests unresolved."""
    years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}\b", question))
    quarters = set(re.findall(r"\bQ([1-4])\b", question, re.I))
    words = {"first": "1", "second": "2", "third": "3", "fourth": "4"}
    for word, number in words.items():
        if re.search(rf"\b{word} quarter\b", question, re.I):
            quarters.add(number)
    if len(years) != 1 or len(quarters) != 1:
        return None
    fiscal = bool(re.search(r"\bfiscal\b|\bFY\s*\d", question, re.I))
    cal = bool(re.search(r"\bcalendar\b", question, re.I))
    if fiscal and cal:
        return None
    inferred = "fiscal" if fiscal else "calendar" if cal else "unspecified"
    if basis != "auto":
        if inferred not in ("unspecified", basis):
            return None
        inferred = basis
    year = int(next(iter(years)))
    if not 1993 <= year <= 2100:
        return None
    return EarningsPeriod(
        year=year,
        quarter=int(next(iter(quarters))),
        basis=inferred,
    )


class HistoricalEPSFact(Record):
    """Keep exact source dates, units, and filing provenance."""

    metric: str
    value: float
    unit: str
    start: date | None
    end: date
    accession: str
    url: str
    source_kind: str = "xbrl"
    value_quote: str = ""
    period_quote: str = ""
    fiscal_year: int | None = None
    fiscal_period: str | None = None


class HistoricalEPS(Record):
    """Return only facts for the requested quarter."""

    ticker: str
    requested: EarningsPeriod
    facts: list[HistoricalEPSFact]
    retrieval_attempts: list[dict] = Field(default_factory=list)


def scalar(value):
    """Read simple cover fields without choosing among segments."""
    if isinstance(value, dict):
        return value.get("value")
    return value if isinstance(value, (str, int)) else None


def extract_eps(raw, filing, target):
    """Reject annual totals, wrong periods, segments, and unknown units."""
    cover = raw.get("CoverPage") or {}
    cik = str(scalar(cover.get("EntityCentralIndexKey")) or "").lstrip("0")
    if not cik or cik != filing.cik.lstrip("0"):
        return []
    year = scalar(cover.get("DocumentFiscalYearFocus"))
    focus = scalar(cover.get("DocumentFiscalPeriodFocus"))
    report_end = scalar(cover.get("DocumentPeriodEndDate"))
    wanted = "FY" if target.quarter == 4 else f"Q{target.quarter}"
    if target.basis == "fiscal" and (
        str(year) != str(target.year) or focus != wanted
    ):
        return []
    income = raw.get("StatementsOfIncome") or {}
    facts = []
    for metric in ("EarningsPerShareBasic", "EarningsPerShareDiluted"):
        rows = income.get(metric, [])
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or row.get("segment"):
                continue
            try:
                start = date.fromisoformat(row["period"]["startDate"])
                end = date.fromisoformat(row["period"]["endDate"])
                value = Decimal(str(row["value"]))
            except (KeyError, TypeError, ValueError, InvalidOperation):
                continue
            if not value.is_finite() or not 70 <= (end - start).days <= 105:
                continue
            unit = str(row.get("unitRef", "")).lower()
            if unit not in ("usd", "usd/shares", "usdshares"):
                continue
            if target.basis == "calendar":
                if (start, end) != target.calendar_dates():
                    continue
            elif target.basis == "fiscal":
                if abs(end.year - target.year) > 1:
                    continue
                if end.isoformat() != report_end:
                    continue
                if filing.period_of_report != end:
                    continue
            else:
                continue
            facts.append(
                HistoricalEPSFact(
                    metric=metric,
                    value=float(value),
                    unit="USD per share",
                    start=start,
                    end=end,
                    accession=filing.accession_number,
                    url=filing.url,
                    fiscal_year=int(year) if str(year).isdigit() else None,
                    fiscal_period=str(focus) if focus else None,
                )
            )
    return facts


def get_historical_eps(ticker, target, *, settings=None):
    """Use one filing query and at most four XBRL conversions."""
    source = "SEC XBRL via sec-api.io"
    config = settings or Settings.load()
    try:
        target = EarningsPeriod.model_validate(target)
        if target.basis == "unspecified":
            raise ValueError("Choose fiscal or calendar quarters.")
    except (ValueError, TypeError):
        from agent.providers import invalid

        return invalid(source)
    if target.basis == "calendar":
        start, end = target.calendar_dates()
        forms = ("10-Q", "10-K")
    else:
        start = date(target.year - 1, 1, 1)
        end = date(target.year + 1, 12, 31)
        forms = ("10-K",) if target.quarter == 4 else ("10-Q",)
    filings = get_sec_filings(
        ticker,
        forms,
        limit=12,
        settings=config,
        period_start=start,
        period_end=end,
    )
    if filings.status == "error":
        return ToolResult(status="error", source=source, error=filings.error)
    warnings = [
        "Only matching GAAP EPS facts are used. Non-GAAP EPS is not supplied.",
        "Values retain the selected filing basis. No stock split adjustment "
        "or subtraction of annual and year-to-date EPS is performed.",
        "Search is bounded to 12 filing records and four XBRL conversions.",
    ]
    candidates = sorted(
        filings.data.filings,
        key=lambda f: (
            abs((f.period_of_report or start).year - target.year),
            f.filed_at,
        ),
    )[:4]
    facts = []
    try:
        for filing in candidates:
            raw = request_json(
                "GET",
                "https://api.sec-api.io/xbrl-to-json",
                config,
                headers={
                    "Authorization": config.sec_api_key.get_secret_value()
                },
                params={"accession-no": filing.accession_number},
            )
            facts = extract_eps(raw, filing, target)
            if facts:
                break
        # Conflicting contexts are not resolved by choosing a convenient value.
        unique = {}
        for fact in facts:
            key = (fact.metric, fact.start, fact.end)
            if key in unique and unique[key].value != fact.value:
                facts = []
                warnings.append("Conflicting EPS contexts need human review.")
                break
            unique[key] = fact
        else:
            facts = list(unique.values())
        if not facts:
            warnings.append(
                "No matching quarterly EPS fact was verified. "
                "This does not prove that historical data does not exist."
            )
        return ToolResult(
            status="ok" if facts else "empty",
            source=source,
            data=HistoricalEPS(
                ticker=filings.data.ticker, requested=target, facts=facts
            ),
            warnings=warnings,
        )
    except ToolFailure as exc:
        return failure(source, exc)
    except (KeyError, TypeError, ValueError, AttributeError):
        return bad_response(source)


QUARTERS = ("first", "second", "third", "fourth")


class Release(Record):
    """Keep an issuer-matched excerpt and its discovered source URL."""

    url: str
    accession: str
    cik: str
    text: str


class VisibleText(HTMLParser):
    """Keep paragraph boundaries and omit scripts and hidden content."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "ix:hidden"):
            self.skip += 1
        if tag in ("p", "div", "tr", "br", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "ix:hidden") and self.skip:
            self.skip -= 1
        if tag in ("p", "div", "tr", "h1", "h2", "h3"):
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_data(self, text):
        if not self.skip:
            self.parts.append(text)


def release_text(html):
    """Normalize spaces while retaining source paragraph boundaries."""
    parser = VisibleText()
    parser.feed(html)
    return "\n".join(
        " ".join(line.split())
        for line in "".join(parser.parts).splitlines()
        if line.strip()
    )


def archive_path(url, cik):
    """Accept only issuer-matched SEC document paths returned by search."""
    parts = urlsplit(url)
    match = re.fullmatch(
        r"/Archives/edgar/data/(\d+)/(\d{18})/([A-Za-z0-9_.-]+)", parts.path
    )
    if (
        parts.scheme != "https"
        or parts.hostname not in ("www.sec.gov", "sec.gov")
        or parts.query
        or parts.fragment
        or parts.username
        or parts.port
        or not match
        or match[1].lstrip("0") != str(cik).lstrip("0")
    ):
        raise ToolFailure("invalid_response", "The filing URL is invalid.")
    return "/" + "/".join(match.groups())


def download_release(url, cik, settings):
    """Download one bounded exhibit using a fixed provider host."""
    path = archive_path(url, cik)
    try:
        with requests.get(
            "https://archive.sec-api.io" + path,
            headers={"Authorization": settings.sec_api_key.get_secret_value()},
            timeout=(settings.request_timeout, settings.request_timeout),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 200:
                code = (
                    "authentication"
                    if response.status_code in (401, 403)
                    else "provider_error"
                )
                raise ToolFailure(
                    code, "The filing download was not available."
                )
            chunks = []
            size = 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 2_000_000:
                    raise ToolFailure(
                        "invalid_response", "The filing is too large."
                    )
                chunks.append(chunk)
            return release_text(
                b"".join(chunks).decode("utf-8", errors="replace")
            )
    except requests.Timeout:
        raise ToolFailure(
            "timeout", "The filing download timed out."
        ) from None
    except requests.RequestException:
        raise ToolFailure(
            "network_error", "The filing download failed."
        ) from None


def heading_matches(text, target):
    """Require a joined quarter and fiscal-year label near the heading."""
    lines = [
        line
        for line in text[:1600].splitlines()
        if "|" not in line and ".htm" not in line.lower()
    ]
    head = " ".join(" ".join(lines[:10]).lower().split())
    quarter = rf"(?:{QUARTERS[target.quarter - 1]} quarter|q{target.quarter})"
    year = r"(?:fiscal\s*(?:year\s*)?|fy\s*)(\d{4}|\d{2})\b"
    match = re.search(rf"{quarter}.{{0,35}}?{year}", head)
    if not match:
        match = re.search(rf"{year}.{{0,35}}?{quarter}", head)
    if not match:
        return False
    value = int(match[1])
    if value < 100:
        value += 2000
    return value == target.year


def discover_releases(ticker, target, *, settings=None):
    """Resolve issuer, search one page, and inspect at most four exhibits."""
    settings = settings or Settings.load()
    ticker = ticker_symbol(ticker)
    require_key(settings.sec_api_key.get_secret_value())
    identity = get_sec_filings(ticker, limit=1, settings=settings)
    if identity.status == "error":
        raise ToolFailure(identity.error.code, identity.error.message)
    if not identity.data.filings:
        return []
    cik = identity.data.filings[0].cik
    raw = request_json(
        "POST",
        "https://api.sec-api.io/full-text-search",
        settings,
        headers={"Authorization": settings.sec_api_key.get_secret_value()},
        body={
            "query": (
                f'"{QUARTERS[target.quarter - 1]} quarter" "{target.year}"'
            ),
            "ciks": [cik],
            "formTypes": ["8-K", "6-K"],
            "startDate": date(target.year - 1, 1, 1).isoformat(),
            "endDate": date(target.year + 1, 12, 31).isoformat(),
            "page": "1",
        },
    )
    hits = raw.get("filings")
    if not isinstance(hits, list):
        raise ToolFailure("invalid_response", "The filing search is invalid.")
    releases = []
    seen = set()
    downloads = 0

    def rank(hit):
        if not isinstance(hit, dict):
            return (2, 2)
        description = str(hit.get("description", "")).lower()
        return (
            0 if "press release" in description else 1,
            0 if hit.get("type") == "EX-99.1" else 1,
        )

    for hit in sorted(hits[:100], key=rank):
        if not isinstance(hit, dict):
            continue
        if str(hit.get("cik", "")).lstrip("0") != str(cik).lstrip("0"):
            continue
        form = str(hit.get("type", ""))
        if not form.startswith("EX-99"):
            continue
        url = hit.get("filingUrl", "")
        if url in seen:
            continue
        seen.add(url)
        archive_path(url, cik)
        text = download_release(url, cik, settings)
        downloads += 1
        if heading_matches(text, target) and re.search(
            r"quarter\b.{0,30}\bended", text[:3000], re.I
        ):
            releases.append(
                Release(
                    url=url,
                    accession=hit["accessionNo"],
                    cik=cik,
                    text=text[:7500],
                )
            )
        if len(releases) == 2 or downloads == 4:
            break
    return releases


class ReleaseEPSSelection(Record):
    """Require exact supporting text for each selected EPS value."""

    document: int = Field(
        ge=0, le=1, description="The zero-based document index in the input."
    )
    value: float
    accounting: Literal["GAAP", "non-GAAP", "reported"]
    shares: Literal["basic", "diluted"]
    end: date
    period_quote: str = Field(
        description="Exact source sentence with quarter ended and its date."
    )
    value_quote: str


class ReleaseEPSSelections(Record):
    """Keep the model extraction small and reviewable."""

    facts: list[ReleaseEPSSelection] = Field(max_length=4)


def supported_selection(item, release, target):
    """Check quote membership, period, metric, and the reported value."""
    if not heading_matches(release.text, target):
        return False
    if not all(
        quote and quote in release.text
        for quote in (item.period_quote, item.value_quote)
    ):
        return False
    if item.period_quote not in release.text[:3000]:
        return False
    dates = (
        item.end.isoformat(),
        f"{item.end:%B} {item.end.day}, {item.end.year}",
    )
    if not any(value in item.period_quote for value in dates):
        return False
    if not re.search(r"quarter\b.{0,30}\bended", item.period_quote, re.I):
        return False
    if abs(item.end.year - target.year) > 1:
        return False
    quote = item.value_quote
    if not re.search(r"earnings|\beps\b", quote, re.I):
        return False
    if not re.search(rf"\b{item.shares}\b", quote, re.I):
        return False
    if not re.search(r"\bquarter\b|quarterly", quote, re.I):
        # A short value sentence may follow the quoted quarterly period.
        before = release.text.find(item.period_quote)
        after = release.text.find(quote)
        if not 0 <= after - before <= 1200:
            return False
    non_gaap = bool(re.search(r"non[- ]gaap|adjusted", quote, re.I))
    if (item.accounting == "non-GAAP") != non_gaap:
        return False
    if item.accounting == "GAAP" and not re.search(r"\bGAAP\b", quote):
        return False
    # Do not take a comparison-period value later in the same sentence.
    amount = re.search(r"\$\s*([-+]?\d+(?:\.\d+)?)", quote)
    if not amount or Decimal(amount[1]) != Decimal(str(item.value)):
        return False
    if re.search(r"full.year|for fiscal|annual", quote, re.I):
        return False
    return True


def repair_selection(item, release, target):
    """Resolve exact source sentences only when one pair passes all checks."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", release.text[:3000])
    periods = [
        text
        for text in sentences
        if re.search(r"quarter\b.{0,30}\bended", text, re.I)
    ]
    values = [
        text
        for text in sentences
        if re.search(r"earnings|\beps\b", text, re.I)
    ]
    matches = []
    for period in periods:
        for value in values:
            candidate = item.model_copy(
                update={"period_quote": period, "value_quote": value}
            )
            if supported_selection(candidate, release, target):
                matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


def release_eps(context, request, target):
    """Use one model extraction call after bounded document discovery."""
    source = "SEC earnings release via sec-api.io"
    try:
        releases = discover_releases(
            request.ticker, target, settings=context.settings
        )
    except ToolFailure as exc:
        return ToolResult(status="error", source=source, error=exc.error)
    facts = []
    resolved = target.model_copy(update={"basis": "fiscal"})
    if releases and target.basis != "calendar":
        selection = context.ask(
            "extract:earnings_release",
            ReleaseEPSSelections,
            EARNINGS_EXTRACT_PROMPT,
            {
                "requested": resolved.model_dump(mode="json"),
                "documents": [
                    {"document": index, **release.model_dump()}
                    for index, release in enumerate(releases)
                ],
            },
        )
        for item in selection.facts:
            if item.document >= len(releases):
                continue
            release = releases[item.document]
            if not supported_selection(item, release, resolved):
                item = repair_selection(item, release, resolved)
                if item is None:
                    continue
            facts.append(
                HistoricalEPSFact(
                    metric=f"{item.accounting} {item.shares} EPS",
                    value=item.value,
                    unit="dollars per share as reported",
                    start=None,
                    end=item.end,
                    accession=release.accession,
                    url=release.url,
                    fiscal_year=target.year,
                    fiscal_period="FY"
                    if target.quarter == 4
                    else f"Q{target.quarter}",
                    source_kind="release",
                    value_quote=item.value_quote,
                    period_quote=item.period_quote,
                )
            )
    # Conflicting current-period claims require review, not a chosen winner.
    values = {}
    for fact in facts:
        key = fact.metric
        signature = (fact.value, fact.end)
        if key in values and values[key] != signature:
            facts = []
            break
        values[key] = signature
    warnings = [
        "Quarterly EPS comes from a filed earnings release. "
        "Values retain the release basis; no stock split adjustment is made.",
        "Release search is bounded. A missing result does not prove "
        "that the data does not exist.",
    ]
    if target.basis == "unspecified":
        warnings.insert(
            0,
            f"Interpreted Q{target.quarter} {target.year} as the company "
            "fiscal quarter based on the release heading. This is not "
            "an exact calendar-quarter answer. Use --period-basis calendar "
            "if you meant calendar dates.",
        )
    return ToolResult(
        status="ok" if facts else "empty",
        source=source,
        data=HistoricalEPS(
            ticker=request.ticker, requested=resolved, facts=facts
        ),
        warnings=warnings,
    )
