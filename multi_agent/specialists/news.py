"""News specialist: runs the NewsChain for the coordinator's task."""

# process(task)  -- overrides Agent.process: NewsChain().run(ticker, task) -> news brief text.
#                   A fixed prompt chain with no tools, so the plan assigns it at most one step.

import re

from multi_agent.base import Agent
from multi_agent.workflows import NewsChain


class NewsAnalyst(Agent):
    """Answer coordinator news tasks with the NewsChain."""

    def __init__(self):
        super().__init__(name="News Analyst", role="financial news research specialist")
        self.last_chain = None

    def process(self, task):
        """Return the chain's news brief for the task as text."""
        # Coordinator.route appends "(ticker: SYMBOL)" to every task.
        match = re.search(r"\(ticker:\s*([^)]+)\)\s*$", task)
        if match is None:
            raise ValueError("news task must end with '(ticker: SYMBOL)'")
        self.last_chain = NewsChain().run(match.group(1).strip(), task)
        summary = self.last_chain["summary"]
        self.memory.append({"task": task, "result": summary})
        return summary
