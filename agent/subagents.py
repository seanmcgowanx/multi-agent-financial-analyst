"""Layer 2: specialist subagents wrapped as @tool functions."""

# REQUIREMENT: Dynamic tool use - each subagent picks among its tools.
# Wrapper docstrings are what the supervisor routes on.

# earnings_agent -> analyze_earnings
#   get_financials, get_earnings_history, get_recent_filings

# news_agent -> analyze_news
#   news_pipeline, get_company_news

# market_agent -> analyze_market
#   get_price_history, get_fred_series
