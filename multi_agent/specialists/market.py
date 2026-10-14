"""Market specialist: price action, valuation context, macro backdrop."""

from multi_agent.base import Agent
from multi_agent.prompts import MARKET_ROLE


class MarketAnalyst(Agent):
    """Use the shared tool loop to answer market research tasks."""

    def __init__(self):
        super().__init__(
            name="Market Analyst",
            role=MARKET_ROLE,
            tools=["get_price_history", "get_fred_series"],
        )

    def process(self, task):
        """Return market findings as text for the coordinator."""
        return self.use_tools(task)
