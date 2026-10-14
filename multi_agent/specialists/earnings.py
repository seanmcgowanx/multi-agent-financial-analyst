"""Earnings specialist: reported income statements, margins, filing metadata."""

from multi_agent.base import Agent
from multi_agent.prompts import EARNINGS_ROLE


class EarningsAnalyst(Agent):
    """Answer earnings research tasks through the shared tool loop."""

    def __init__(self):
        super().__init__(
            name="Earnings Analyst",
            role=EARNINGS_ROLE,
            tools=["get_financials", "get_recent_filings"],
        )

    def process(self, task):
        """Return concise earnings findings as text for the coordinator."""
        return self.use_tools(task)
