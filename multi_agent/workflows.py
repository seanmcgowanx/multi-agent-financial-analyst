"""Non-routing workflow patterns: the news prompt chain and the evaluator."""

# class NewsChain:  Ingest -> Preprocess -> Classify -> Extract -> Summarize
#     ingest(ticker)       -- tools.get_company_news (no LLM)
#     preprocess(articles) -- LLM: dedupe, strip boilerplate
#     classify(articles)   -- LLM: label each (earnings, product, legal, macro, ...)
#                             + sentiment
#     extract(articles)    -- LLM: key facts, numbers, entities
#     summarize(extracted) -- LLM: concise news brief
#     run(ticker) -> dict of every intermediate step (for the notebook demo)

# class Evaluator(Agent):
#     evaluate(report, ticker) -> {"score": int, "feedback": str}

import json

from multi_agent.base import Agent
from multi_agent.prompts import EVALUATOR


class Evaluator(Agent):
    """Review report quality and return feedback for the coordinator."""

    def __init__(self):
        super().__init__(name="Evaluator", role="financial report reviewer")

    def evaluate(self, report, ticker):
        """Return a validated score (1-10) and actionable feedback.

        Invalid inputs or model output raise ValueError (TypeError if the reply
        is not a JSON object). API failures propagate from call_llm; they must
        not be mistaken for a report quality score.
        Only successful evaluations are recorded in session memory.
        """
        if not isinstance(report, str) or not report.strip():
            raise ValueError("report must be a non-empty string")
        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError("ticker must be a non-empty string")

        ticker = ticker.strip().upper()
        prompt = EVALUATOR.format(report=report, ticker=ticker)
        raw = self.call_llm(prompt, json_mode=True)
        try:
            result = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Evaluator response must be valid JSON") from exc

        if not isinstance(result, dict):
            raise TypeError("Evaluator response must be a JSON object")
        score = result.get("score")
        feedback = result.get("feedback")
        # bool is a subclass of int, but is not a valid report score.
        if type(score) is not int or not 1 <= score <= 10:
            raise ValueError("Evaluator score must be an integer from 1 to 10")
        if not isinstance(feedback, str) or not feedback.strip():
            raise ValueError("Evaluator feedback must be a non-empty string")

        evaluation = {"score": score, "feedback": feedback.strip()}
        self.memory.append({"task": f"evaluate {ticker}", "result": evaluation})
        return evaluation
