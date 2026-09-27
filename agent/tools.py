"""Layer 1: raw API tools (@tool)."""

# REQUIREMENT: Dynamic tool use - these are the tools agents choose from.
# Docstrings are what the agent reads to pick a tool; keep them specific.

# get_price_history(ticker, period) - yfinance
# get_financials(ticker) - yfinance
# get_earnings_history(ticker) - yfinance
# get_company_news(ticker, days) - NewsAPI
# get_fred_series(series_id, start_date) - FRED
#   (FEDFUNDS, DGS10, CPIAUCSL, UNRATE, GDP, VIXCLS)
# get_recent_filings(ticker, form_type) - SEC EDGAR
