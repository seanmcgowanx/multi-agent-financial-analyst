"""InvestmentResearchTeam: wires agents together and exposes run(). Mirrors the lab's MultiAgentTeam."""

# run(ticker)         -- the full pipeline; returns every intermediate for the notebook.
# show_team_status()  -- like the lab: tasks completed per agent.

import json

from multi_agent.config import EVAL_THRESHOLD, MAX_ROUNDS
from multi_agent.coordinator import Coordinator
from multi_agent.memory import append_lesson, get_lessons
from multi_agent.prompts import LESSON
from multi_agent.specialists import SPECIALISTS
from multi_agent.tools import get_price_history
from multi_agent.workflows import Evaluator


class ResearchTeam:
    def __init__(self):
        self.specialists = {label: cls() for label, cls in SPECIALISTS.items()}
        self.coordinator = Coordinator(self.specialists)
        self.evaluator = Evaluator()

    def run(self, ticker):
        """Returns a dict: plan, findings, drafts, evaluations, report."""
        ticker = ticker.strip().upper()
        # Raises ValueError on typos and fake tickers, before any LLM call
        get_price_history(ticker)

        lessons = get_lessons()
        plan = self.coordinator.plan(ticker, lessons)
        findings = [self.coordinator.route(step, ticker) for step in plan]

        # Evaluator-optimizer loop: every draft is evaluated, at most MAX_ROUNDS drafts
        drafts = [self.coordinator.synthesize(ticker, findings)]
        evaluations = [self.evaluator.evaluate(drafts[-1], ticker)]
        while evaluations[-1]["score"] < EVAL_THRESHOLD and len(drafts) < MAX_ROUNDS:
            feedback = evaluations[-1]["feedback"]
            drafts.append(self.coordinator.revise(drafts[-1], feedback, findings))
            evaluations.append(self.evaluator.evaluate(drafts[-1], ticker))

        # Write lesson if first eval does not pass and if a similar lesson does not exist
        if evaluations[0]["score"] < EVAL_THRESHOLD:
            prompt = LESSON.format(
                plan=json.dumps(plan, indent=2),
                feedback=evaluations[0]["feedback"],
                lessons=lessons,
            )
            lesson = self.coordinator.call_llm(prompt).strip()
            if lesson != "NONE":
                append_lesson(lesson)

        return {
            "plan": plan,
            "findings": findings,
            "drafts": drafts,
            "evaluations": evaluations,
            "report": drafts[-1],
        }

    def show_team_status(self):
        print("\nTEAM STATUS")
        agents = [self.coordinator, *self.specialists.values(), self.evaluator]
        for agent in agents:
            print(f"  {agent.name} ({agent.role}): {len(agent.memory)} tasks completed")
