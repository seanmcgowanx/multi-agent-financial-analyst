"""Non-routing workflow patterns: the news prompt chain and the evaluator."""

# REQUIREMENT: Prompt Chaining
# class NewsChain:  Ingest -> Preprocess -> Classify -> Extract -> Summarize
#     ingest(ticker)       -- tools.get_company_news (no LLM)
#     preprocess(articles) -- LLM: dedupe, strip boilerplate
#     classify(articles)   -- LLM: label each (earnings, product, legal, macro, ...)
#                             + sentiment
#     extract(articles)    -- LLM: key facts, numbers, entities
#     summarize(extracted) -- LLM: concise news brief
#     run(ticker) -> dict of every intermediate step (for the notebook demo)

# REQUIREMENT: Evaluator-Optimizer (evaluate half; the refine loop is in team.py)
# class Evaluator(Agent):
#     evaluate(report, ticker) -> {"score": int, "feedback": str}
