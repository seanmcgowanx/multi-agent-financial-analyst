"""Plain Python functions that call data APIs, plus a registry agents choose from.

Each tool takes simple kwargs and returns a short string (LLM-readable). Agents see
TOOLS descriptions in their prompt and pick tools by name via the JSON protocol in
prompts.TOOL_PROTOCOL.
"""

# get_price_history(ticker, period)      -- yfinance
# get_financials(ticker)                 -- yfinance income/balance summary
# get_company_news(ticker, days)         -- NewsAPI (fallback: yfinance news); NewsChain step, not in TOOLS
# get_recent_filings(ticker, form_type)  -- SEC EDGAR
# get_fred_series(series_id)             -- FRED (e.g. FEDFUNDS, CPIAUCSL)

import math
from datetime import datetime, timedelta, timezone

import requests
import yfinance as yf

from multi_agent.config import FRED_API_KEY, NEWSAPI_KEY, SEC_USER_AGENT


def get_price_history(ticker, period="6mo"):
    """Returns a string: start/end dates and closes, % change, high/low close,
    average volume, price currency, price and return basis, count of missing
    closes dropped, and about 20 evenly spaced closes over the period.

    Closes are not dividend-adjusted (auto_adjust=False), so % change is a
    price change, not a total return. Raises ValueError if there is no data
    (invalid or delisted ticker) or no valid closing prices.
    """
    stock = yf.Ticker(ticker)
    history_df = stock.history(period=period, auto_adjust=False)

    if history_df.empty:
        raise ValueError(
            f"No price data for {ticker!r}, it might be invalid or delisted"
        )

    close = history_df["Close"].dropna()
    missing_count = len(history_df) - len(close)

    if close.empty:
        raise ValueError(f"No valid closing prices available for {ticker!r}")

    metadata = stock.get_history_metadata() or {}
    currency = metadata.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        currency = "unspecified by source"

    change = (close.iloc[-1] / close.iloc[0] - 1) * 100
    # Sample ~20 closes so the output size doesn't grow with the period.
    step = max(1, len(close) // 20)
    points = ", ".join(f"{d:%Y-%m-%d} {c:.2f}" for d, c in close.iloc[::step].items())

    price_summary = (
        f"{ticker} {period}: "
        f"{close.index[0]:%Y-%m-%d} close {close.iloc[0]:.2f} -> "
        f"{close.index[-1]:%Y-%m-%d} close {close.iloc[-1]:.2f} "
        f"({change:+.1f}%), "
        f"high {close.max():.2f}, low {close.min():.2f}, "
        f"avg volume {history_df['Volume'].mean():,.0f}\n"
        f"Price currency/unit reported by Yahoo Finance: {currency}\n"
        "Price basis: Yahoo Close with auto_adjust=False.\n"
        "Return basis: percentage change in closing prices; "
        "dividend income is not included. This is not a total return.\n"
        f"Missing closing prices omitted: {missing_count}\n"
        f"Closes: {points}\n"
        f"Source: https://finance.yahoo.com/quote/{ticker}/history"
    )
    return price_summary


def get_financials(ticker):
    """Summarize up to four quarterly income statements in reported currency.

    Amounts are unscaled currency units; diluted EPS is currency per share.
    Missing figures remain unavailable, and request failures propagate to the
    shared tool loop. This is not a balance-sheet or cash-flow analysis.
    """
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError("ticker must be a non-empty string")
    ticker = ticker.strip().upper()
    stock = yf.Ticker(ticker)
    statement = stock.get_income_stmt(freq="quarterly")
    if statement.empty:
        raise ValueError(f"No quarterly income statements available for {ticker!r}")
    statement = statement.sort_index(axis=1, ascending=False).iloc[:, :4]
    info = stock.get_info() or {}
    currency = info.get("financialCurrency")
    if not isinstance(currency, str) or not currency.strip():
        currency = "unspecified by source"

    def number(column, field):
        value = column.get(field)
        if value is None:
            return None
        value = float(value)
        return value if math.isfinite(value) else None

    def amount(value):
        return "unavailable" if value is None else f"{value:,.2f}"

    def margin(value, revenue):
        if value is None or revenue is None or revenue <= 0:
            return "unavailable"
        return f"{value / revenue * 100:.2f}%"

    lines = [
        (
            f"{ticker}: {len(statement.columns)} latest available quarterly "
            "income statements (newest first)."
        ),
        (
            f"Financial-reporting currency: {currency}. Amounts are in currency "
            "units, not millions; diluted EPS is currency per share."
        ),
    ]
    available = False
    for date, column in statement.items():
        revenue = number(column, "TotalRevenue")
        gross_profit = number(column, "GrossProfit")
        operating_income = number(column, "OperatingIncome")
        net_income = number(column, "NetIncome")
        eps = number(column, "DilutedEPS")
        available |= any(
            value is not None
            for value in (revenue, gross_profit, operating_income, net_income, eps)
        )
        lines.append(
            f"Quarter ended {date:%Y-%m-%d}: revenue {amount(revenue)}; "
            f"gross margin {margin(gross_profit, revenue)}; "
            f"operating margin {margin(operating_income, revenue)}; "
            f"net income {amount(net_income)}; diluted EPS {amount(eps)}"
        )
    if not available:
        raise ValueError(f"No usable quarterly income figures for {ticker!r}")
    lines.append(
        "Margins calculated from same-quarter profit divided by revenue. "
        "Unavailable figures are not zero. Balance sheet and cash flow are "
        "not included. Source: Yahoo Finance quarterly income statements, "
        f"https://finance.yahoo.com/quote/{ticker}/financials"
    )
    return "\n".join(lines)


def get_company_news(ticker, days=7):
    """Return up to five recent ticker-related news articles.

    NewsAPI is used when configured; Yahoo Finance news is the fallback.
    Articles with known publication dates older than ``days`` are omitted.
    """
    ticker = ticker.strip().upper()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    articles = []
    provider = "NewsAPI"
    newsapi_error = None

    if NEWSAPI_KEY:
        try:
            response = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": ticker,
                    "from": cutoff.date().isoformat(),
                    "sortBy": "publishedAt",
                    "pageSize": 5,
                    "language": "en",
                },
                headers={"X-Api-Key": NEWSAPI_KEY},
                timeout=20,
            )
            payload = response.json()
            if payload.get("status") == "ok":
                articles = payload.get("articles", [])
            else:
                newsapi_error = payload.get("message") or f"HTTP {response.status_code}"
        except (requests.RequestException, ValueError, TypeError) as e:
            newsapi_error = str(e)

    if not articles:
        provider = "Yahoo Finance"
        # Name the NewsAPI failure so an empty result isn't mistaken for no news.
        if newsapi_error:
            provider += f" (NewsAPI failed: {newsapi_error})"
        articles = yf.Ticker(ticker).news or []

    formatted = []
    for article in articles:
        content = article.get("content") or article
        published = article.get("publishedAt") or content.get("pubDate")
        timestamp = article.get("providerPublishTime")
        published_at = None
        if isinstance(published, str):
            try:
                published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=timezone.utc)
                published_at = published_at.astimezone(timezone.utc)
            except ValueError:
                published_at = None
        elif isinstance(timestamp, (int, float)):
            published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)

        if published_at is not None and published_at < cutoff:
            continue

        source = article.get("source") or content.get("provider") or {}
        source_name = (
            (
                source.get("name") or source.get("displayName")
                if isinstance(source, dict)
                else source
            )
            or article.get("publisher")
            or "Unknown source"
        )
        url = article.get("url") or content.get("canonicalUrl") or article.get("link")
        if isinstance(url, dict):
            url = url.get("url")
        title = article.get("title") or content.get("title") or "Untitled"
        summary = article.get("description") or content.get("summary")
        date_label = (
            published_at.strftime("%Y-%m-%d %H:%M UTC")
            if published_at
            else "date unavailable"
        )
        formatted.append(
            (
                published_at or datetime.min.replace(tzinfo=timezone.utc),
                f"{date_label} | {source_name}: {title}"
                + (f"\n{summary}" if summary else "")
                + (f"\n{url}" if url else ""),
            )
        )

    formatted.sort(key=lambda item: item[0], reverse=True)
    if not formatted:
        return (
            f"No recent news found for {ticker} in the past {days} days. "
            f"Source checked: {provider}."
        )

    return (
        f"{ticker}: latest news from the past {days} days (source: {provider})\n"
        + "\n\n".join(item[1] for item in formatted[:5])
    )


def get_recent_filings(ticker, form_type="10-Q"):
    """List up to five matching filings from SEC's recent submissions block.

    Returns metadata and document links, not a summary of filing contents.
    Older archive blocks are not searched. SEC_USER_AGENT must identify the
    requester with a name and contact email, as configured by the caller.
    """
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError("ticker must be a non-empty string")
    if not isinstance(form_type, str) or not form_type.strip():
        raise ValueError("form_type must be a non-empty string")
    if not SEC_USER_AGENT:
        raise ValueError("SEC_USER_AGENT is not configured (name and email)")
    ticker = ticker.strip().upper().replace(".", "-")
    form_type = form_type.strip().upper()
    headers = {"User-Agent": SEC_USER_AGENT}
    response = requests.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()
    companies = response.json()
    company = next(
        (item for item in companies.values() if item["ticker"] == ticker), None
    )
    if company is None:
        raise ValueError(f"Ticker {ticker!r} not found in SEC ticker mapping")
    cik = int(company["cik_str"])
    response = requests.get(
        f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()
    recent = response.json()["filings"]["recent"]
    matches = [i for i, form in enumerate(recent["form"]) if form == form_type]
    matches.sort(key=lambda i: recent["filingDate"][i], reverse=True)
    lines = [
        (
            f"SEC EDGAR: {company['title']} ({ticker}), CIK {cik:010d}; "
            f"up to five recent {form_type} filings (exact form match)."
        )
    ]
    for i in matches[:5]:
        accession = recent["accessionNumber"][i]
        document = recent["primaryDocument"][i]
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/"
            f"{accession.replace('-', '')}/{document}"
        )
        lines.append(
            f"{form_type}; filed {recent['filingDate'][i]}; "
            f"report period {recent['reportDate'][i] or 'unavailable'}; "
            f"accession {accession}; document {url}"
        )
    if not matches:
        lines.append("No matching filings in the recent submissions block.")
    lines.append(
        "Scope: recent submissions only; older archive blocks not searched. "
        "Metadata and links only; filing contents have not been read."
    )
    return "\n".join(lines)


def get_fred_series(series_id):
    """Return metadata and up to 13 recent observations in original units.

    Missing observations are omitted and counted. Failures raise so the base
    Agent tool loop can report them and retry. No transformations are applied.
    """
    if not isinstance(series_id, str) or not series_id.strip():
        raise ValueError("series_id must be a non-empty string")
    series_id = series_id.strip().upper()
    if not FRED_API_KEY:
        raise ValueError("FRED_API_KEY is not configured")

    params = {
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "series_id": series_id,
    }
    payloads = []
    for endpoint in ("series", "series/observations"):
        query = dict(params)
        if endpoint.endswith("observations"):
            query.update(sort_order="desc", limit=13, units="lin")
        try:
            response = requests.get(
                f"https://api.stlouisfed.org/fred/{endpoint}",
                params=query,
                timeout=20,
            )
            response.raise_for_status()
            payloads.append(response.json())
        except (requests.RequestException, ValueError):
            # Request exceptions can contain the API key in the URL. The base
            # Agent forwards error text to the model, so expose a safe message.
            raise RuntimeError(
                "FRED request failed; check the series ID, key, and connection"
            ) from None

    metadata = payloads[0].get("seriess", [])
    observations = payloads[1].get("observations", [])
    if not metadata:
        raise ValueError("FRED returned no series metadata")
    info = metadata[0]
    valid = [row for row in observations if row["value"] != "."]
    if not valid:
        raise ValueError("FRED returned no available recent observations")
    points = "; ".join(f"{row['date']}: {row['value']}" for row in reversed(valid))
    missing = len(observations) - len(valid)
    return (
        f"FRED {series_id}: {info['title']}\n"
        f"Units: {info['units']}; frequency: {info['frequency']}; "
        f"adjustment: {info['seasonal_adjustment']}\n"
        f"Recent observations (oldest to newest): {points}\n"
        f"Missing observations omitted: {missing}. "
        "Values are in original units, not a calculated growth rate.\n"
        f"Source: https://fred.stlouisfed.org/series/{series_id}"
    )


# Registry
TOOLS = {
    "get_recent_filings": {
        "fn": get_recent_filings,
        "description": (
            "get_recent_filings(ticker, form_type='10-Q'): Up to five recent "
            "SEC EDGAR filings, with filing dates, report periods, accession "
            "numbers and document links. Exact form match (10-Q, 10-K, 8-K, "
            "or amendments such as 10-Q/A). Metadata only, not filing text: "
            "do not claim to have read a filing, verified figures against it, "
            "or extracted risks or management commentary from it. SEC report "
            "periods may differ from Yahoo quarter labels; keep each source's "
            "dates."
        ),
    },
    "get_financials": {
        "fn": get_financials,
        "description": (
            "get_financials(ticker): Up to four recent quarterly income "
            "statements: revenue, gross and operating margins, net income, "
            "diluted EPS, period-end dates, and financial-reporting currency. "
            "Excludes balance sheet and cash flow. When citing, state period "
            "dates, currency, and source, and keep currency amounts, per-share "
            "EPS, and percentage margins distinct. Unavailable values are not "
            "zero. Label quarter-over-quarter comparisons as such; claim "
            "year-over-year growth only with both matching quarters. Four "
            "quarters alone do not establish a durable trend."
        ),
    },
    "get_fred_series": {
        "fn": get_fred_series,
        "description": (
            "get_fred_series(series_id): Get up to 13 recent FRED observations "
            "with dates, original units, frequency, and seasonal adjustment. "
            "Examples: FEDFUNDS (interest rate), UNRATE (unemployment rate), "
            "CPIAUCSL (consumer price index level, NOT an inflation rate). "
            "When citing, keep the reported units and adjustment, and treat "
            "macro links to a stock as plausible influences, not proven causes."
        ),
    },
    "get_price_history": {
        "fn": get_price_history,
        "description": (
            "get_price_history(ticker, period='6mo'): Returns a price summary "
            "(start/end close, % change, high/low, avg volume, ~20 sampled closes). "
            "period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max. "
            "% change is a price change excluding dividends, not a total return. "
            "Use the reported currency; if unspecified, say so. When comparing "
            "to a benchmark, state each series' actual start and end dates and "
            "whether they align. Do not compute moving averages from the "
            "sampled closes. Price history alone does not show whether a stock "
            "is cheap or expensive."
        ),
    },
}
