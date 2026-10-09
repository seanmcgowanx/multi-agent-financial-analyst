"""Plain Python functions that call data APIs, plus a registry agents choose from.

No framework decorators. Each tool takes simple kwargs and returns a short
string (LLM-readable). Agents see TOOLS descriptions in their prompt and pick
tools by name via the JSON protocol in prompts.TOOL_PROTOCOL.
"""

# get_price_history(ticker, period)      -- yfinance
# get_financials(ticker)                 -- yfinance income/balance summary
# get_company_news(ticker, days)         -- NewsAPI (fallback: yfinance news)
# get_recent_filings(ticker, form_type)  -- SEC EDGAR
# get_fred_series(series_id)             -- FRED (e.g. FEDFUNDS, CPIAUCSL)
# Add more freely (Alpha Vantage, Kaggle datasets, ...).

# Registry: {"get_price_history": {"fn": get_price_history,
#   "description": "get_price_history(ticker, period='6mo'): ..."}}
# The description is all the model sees, so include the call signature.
TOOLS = {}
# Specialists receive a subset of TOOLS.
