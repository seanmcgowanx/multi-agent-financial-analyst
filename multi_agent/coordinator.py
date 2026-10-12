"""Coordinator: plans, routes steps to specialists, writes/revises the report."""

# class Coordinator(Agent):
#     plan(ticker, lessons) -> list[{"specialist", "task"}]
#
#     route(step, ticker) -> str   -- self.specialists[step["specialist"]].analyze(...)
#                                     unknown label -> returns an error string
#
#     synthesize(ticker, findings) -> str            -- draft report
#     revise(report, feedback, findings) -> str      -- optimizer half of eval loop

import json

from multi_agent.base import Agent
from multi_agent.prompts import COORDINATOR_PLAN


class Coordinator(Agent):
    def __init__(self, specialists):
        super().__init__(
            name="Coordinator",
            role="financial research coordinator",
        )
        self.specialists = specialists  # {label: specialist instance}, built by team

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

    def route(self, step, ticker):
        label = step["specialist"]
        if label not in self.specialists:
            return f"Unknown specialist {label!r}; valid: {', '.join(self.specialists)}"

        print(f"{self.name} -> {label}: {step['task'][:40]}...")
        return self.specialists[label].analyze(step["task"], ticker)
