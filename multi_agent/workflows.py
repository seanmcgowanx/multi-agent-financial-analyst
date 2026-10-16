"""Non-routing workflow patterns: the news prompt chain and the evaluator."""

# NewsChain.ingest(ticker)        -- tools.get_company_news (no LLM).
# NewsChain.preprocess(articles)  -- LLM: dedupe, strip boilerplate.
# NewsChain.classify(articles)    -- LLM: label each (earnings, product, legal, macro, ...) + sentiment.
# NewsChain.extract(articles)     -- LLM: key facts, numbers, entities.
# NewsChain.summarize(extracted, ticker, task) -- LLM: news brief focused on the task.
# NewsChain.run(ticker, task)     -- runs the chain; returns every intermediate step for the notebook.
# Evaluator.evaluate(report, ticker) -- scores a report 1-10 with feedback; raises on bad input or reply.

import json

from multi_agent.base import Agent
from multi_agent.config import EVAL_THRESHOLD
from multi_agent.prompts import (
    EVALUATOR,
    NEWS_CHAIN_CLASSIFY,
    NEWS_CHAIN_EXTRACT,
    NEWS_CHAIN_PREPROCESS,
    NEWS_CHAIN_SUMMARIZE,
)
from multi_agent.tools import get_company_news


class NewsChain(Agent):
    """Fetch, process, and summarize recent company news."""

    def __init__(self):
        super().__init__(name="News Chain", role="financial news analysis specialist")

    def ingest(self, ticker):
        """Return the recent news for a ticker as text (no LLM call)."""
        return get_company_news(ticker)

    def preprocess(self, articles):
        """Return the articles deduplicated, without boilerplate, citations kept."""
        return self.call_llm(NEWS_CHAIN_PREPROCESS.format(articles=articles))

    def classify(self, articles):
        """Return the articles labeled by topic and coverage sentiment."""
        return self.call_llm(NEWS_CHAIN_CLASSIFY.format(articles=articles))

    def extract(self, articles):
        """Return the attributed claims, figures, entities, and evidence gaps."""
        return self.call_llm(NEWS_CHAIN_EXTRACT.format(articles=articles))

    def summarize(self, extracted, ticker, task):
        """Return a news brief for the ticker, focused on the task."""
        prompt = NEWS_CHAIN_SUMMARIZE.format(
            articles=extracted, ticker=ticker, task=task
        )
        return self.call_llm(prompt)

    def run(self, ticker, task):
        """Return a dict with the raw news and every intermediate chain result."""
        raw = self.ingest(ticker)
        result = {
            "ticker": ticker,
            "raw": raw,
            "preprocessed": None,
            "classified": None,
            "extracted": None,
            "summary": raw,
        }
        if not raw.startswith("No recent news found for "):
            result["preprocessed"] = self.preprocess(raw)
            result["classified"] = self.classify(result["preprocessed"])
            result["extracted"] = self.extract(result["classified"])
            result["summary"] = self.summarize(result["extracted"], ticker, task)
        self.memory.append({"task": f"news chain {ticker}", "result": result})
        return result


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
        prompt = EVALUATOR.format(
            report=report, ticker=ticker, threshold=EVAL_THRESHOLD
        )
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
