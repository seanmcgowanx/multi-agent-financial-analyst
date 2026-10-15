"""News specialist: runs the NewsChain and interprets the result."""

import re

from multi_agent.base import Agent
from multi_agent.workflows import NewsChain


class NewsAnalyst(Agent):
	"""Answer coordinator news tasks using the NewsChain findings."""

	def __init__(self):
		super().__init__(name="News Analyst", role="financial news research specialist")
		self.last_chain = None

	def process(self, task):
		"""Route a coordinator task through the chain and synthesize its findings."""
		if not isinstance(task, str) or not task.strip():
			raise ValueError("task must be a non-empty string")
		match = re.search(r"\(ticker:\s*([^)]+)\)\s*$", task, re.IGNORECASE)
		if match is None:
			raise ValueError("news task must end with '(ticker: SYMBOL)'")
		return self.analyze(task, match.group(1).strip())

	def analyze(self, task, ticker):
		"""Run the NewsChain and interpret its summary for a coordinator task."""
		if not isinstance(task, str) or not task.strip():
			raise ValueError("task must be a non-empty string")
		if not isinstance(ticker, str) or not ticker.strip():
			raise ValueError("ticker must be a non-empty string")
		ticker = ticker.strip().upper()
		request = task.strip()
		prefix = "Process this from Coordinator:"
		if request.startswith(prefix):
			request = request[len(prefix):].strip()
		request = re.sub(
			r"\s*\(ticker:\s*[^)]+\)\s*$", "", request, flags=re.IGNORECASE
		)

		self.last_chain = NewsChain().run(ticker)
		summary = self.last_chain["summary"]
		if self.last_chain["raw"].startswith("No recent news found for "):
			self.memory.append({"task": task, "result": summary})
			return summary

		analysis_task = (
			f"Research request: {request}\n\n"
			f"News-chain findings for {ticker}:\n{summary}\n\n"
			"Answer only from these findings. Attribute reported claims, distinguish "
			"coverage sentiment from expected stock performance, and identify gaps."
		)
		return super().process(analysis_task)
