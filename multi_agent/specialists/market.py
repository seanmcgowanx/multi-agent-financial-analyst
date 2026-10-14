"""Market specialist: price action, valuation context, macro backdrop."""

# process(task)  -- overrides Agent.process: use_tools(get_price_history, get_fred_series) -> findings text.

from multi_agent.base import Agent


class MarketAnalyst(Agent):
    """Use the shared tool loop to answer market research tasks."""

    def __init__(self):
        super().__init__(
            name="Market Analyst",
            role="market research specialist",
            tools=["get_price_history", "get_fred_series"],
        )

    def process(self, task):
        """Return market findings as text for the coordinator."""
        return self.use_tools(task)
