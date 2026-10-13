"""Plain Python functions that call data APIs, plus a registry agents choose from.

Each tool takes simple kwargs and returns a short string (LLM-readable). Agents see
TOOLS descriptions in their prompt and pick tools by name via the JSON protocol in
prompts.TOOL_PROTOCOL.
"""

# get_price_history(ticker, period)      -- yfinance
# get_financials(ticker)                 -- yfinance income/balance summary
# get_company_news(ticker, days)         -- NewsAPI (fallback: yfinance news)
# get_recent_filings(ticker, form_type)  -- SEC EDGAR
# get_fred_series(series_id)             -- FRED (e.g. FEDFUNDS, CPIAUCSL)

import yfinance as yf


def get_price_history(ticker, period="6mo"):
    """Returns a string: start/end close, % change, high/low close, average
    volume, and about 20 evenly spaced closes over the period. Raises ValueError
    if there is no data (invalid or delisted ticker)."""
    history_df = yf.Ticker(ticker).history(period=period)

    if history_df.empty:
        raise ValueError(
            f"No price data for {ticker!r}, it might be invalid or delisted"
        )

    close = history_df["Close"]
    change = (close.iloc[-1] / close.iloc[0] - 1) * 100
    # Sample ~20 closes so the output size doesn't grow with the period.
    step = max(1, len(close) // 20)
    points = ", ".join(f"{d:%Y-%m-%d} {c:.2f}" for d, c in close.iloc[::step].items())

    price_summary = (
        f"{ticker} {period}: {close.iloc[0]:.2f} -> {close.iloc[-1]:.2f} ({change:+.1f}%), "
        f"high {close.max():.2f}, low {close.min():.2f}, "
        f"avg volume {history_df['Volume'].mean():,.0f}\n"
        f"Closes: {points}"
    )
    return price_summary


# Registry
TOOLS = {
    "get_price_history": {
        "fn": get_price_history,
        "description": (
            "get_price_history(ticker, period='6mo'): Returns a price summary "
            "(start/end close, % change, high/low, avg volume, ~20 sampled closes). "
            "period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max."
        ),
    },
}
