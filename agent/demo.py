"""Supply synthetic data for the offline demonstration."""

from agent.schemas import PriceBar, PriceHistory, ToolResult


def draft(ids=None):
    """Build a short model response using known evidence IDs."""
    return {
        "summary": "The available evidence shows recent company activity.",
        "findings": [
            {
                "claim": "The supplied data reports company activity.",
                "evidence_ids": ids or ["e1"],
            }
        ],
        "limitations": ["The sample is small."],
    }


def prices(empty=False):
    """Return one price bar without opening a network connection."""
    return ToolResult(
        status="empty" if empty else "ok",
        source="yfinance",
        data=PriceHistory(
            ticker="AAPL",
            bars=[]
            if empty
            else [
                PriceBar(
                    date="2026-09-28",
                    open=10,
                    high=12,
                    low=9,
                    close=11,
                    volume=100,
                )
            ],
        ),
    )


class ScriptedModel:
    """Return test responses in order and retain inputs for inspection."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, schema, instruction, payload):
        self.calls.append((schema, instruction, payload))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return schema.model_validate(response)


def plan(*roles):
    """Build a valid test delegation plan."""
    return {
        "rationale": "Gather evidence for the requested topics.",
        "steps": [
            {"role": role, "question": "Review the available evidence."}
            for role in roles
        ],
    }


def report(revised=False, ids=None):
    """Return distinguishable initial and revised drafts."""
    return {
        "summary": "The report includes source limits."
        if revised
        else "The company has recent data.",
        "findings": [
            {
                "claim": "The supplied closing price is 11.",
                "evidence_ids": ids or ["market:e1"],
            }
        ],
        "limitations": ["The sample contains one daily price."]
        if revised
        else [],
    }


def evaluation(accepted=True):
    """Make evaluator feedback trigger a real revision when requested."""
    return {
        "accuracy": 5,
        "coverage": 4 if accepted else 2,
        "clarity": 5,
        "revision_required": not accepted,
        "critique": []
        if accepted
        else ["Explain that the price sample is only one day."],
        "lessons": ["State the date range and limits of every price sample."],
    }
