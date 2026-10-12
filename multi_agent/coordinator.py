"""Coordinator: plans, routes steps to specialists, writes/revises the report."""

# class Coordinator(Agent):
#     plan(ticker, lessons) -> list[{"specialist", "task"}]
#
#     route(step, ticker) -> str   -- send_to(self.specialists[step["specialist"]], ...)
#                                     unknown label -> returns an error string
#
#     synthesize(ticker, findings) -> str            -- draft report
#     revise(report, feedback, findings) -> str      -- optimizer half of eval loop

import json

from multi_agent.base import Agent
from multi_agent.prompts import COORDINATOR_PLAN, COORDINATOR_SYNTHESIZE


class Coordinator(Agent):
    def __init__(self, specialists):
        super().__init__(
            name="Coordinator",
            role="financial research coordinator",
            model="gpt-6-sol",
        )
        self.specialists = specialists

    def plan(self, ticker, lessons):
        """Returns the plan's steps. The model replies with:
        {
            "steps": [
                {"specialist": "earnings|news|market", "task": "<task>"}
            ]
        }
        """
        prompt = COORDINATOR_PLAN.format(ticker=ticker, lessons=lessons)
        reply = self.call_llm(prompt, reasoning_effort="high", json_mode=True)
        return json.loads(reply)["steps"]

    def route(self, step, ticker):
        """Returns a string: the specialist's findings for this step, or an
        error message if the label is unknown.
        """
        label = step["specialist"]
        task = step["task"]
        if label not in self.specialists:
            return f"Unknown specialist {label!r}"

        return self.send_to(self.specialists[label], f"{task} (ticker: {ticker})")

    def synthesize(self, ticker, findings):
        """Returns a string: the draft report, with sections:
        Summary, Financials, News & Sentiment, Market, Risks, Outlook.
        """
        numbered = "\n\n".join(f"{i}. {f}" for i, f in enumerate(findings, 1))
        prompt = COORDINATOR_SYNTHESIZE.format(ticker=ticker, findings=numbered)
        return self.call_llm(prompt, reasoning_effort="high")
