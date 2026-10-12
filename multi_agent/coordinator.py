"""Coordinator: plans, routes steps to specialists, writes/revises the report."""

# class Coordinator(Agent):
#     plan(ticker, lessons) -> list[{"specialist", "task"}]
#
#     route(step, ticker) -> str   -- SPECIALISTS[step["specialist"]].analyze(...)
#                                     unknown label -> fallback specialist + log it
#
#     synthesize(ticker, findings) -> str            -- draft report
#     revise(report, feedback, findings) -> str      -- optimizer half of eval loop

import json

from multi_agent.base import Agent
from multi_agent.prompts import COORDINATOR_PLAN


class Coordinator(Agent):
    def __init__(self):
        super().__init__(
            name="Coordinator",
            role="financial research coordinator",
        )

    def plan(self, ticker, lessons):
        """Returns the plan's steps. The model replies with:
        {
            "steps": [
                {"specialist": "earnings|news|market", "task": "<task>"}
            ]
        }
        """
        prompt = COORDINATOR_PLAN.format(ticker=ticker, lessons=lessons)
        return json.loads(self.call_llm(prompt, json_mode=True))["steps"]
