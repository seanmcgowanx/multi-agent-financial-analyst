"""Deterministic workflows: news prompt chain and report evaluator."""

# REQUIREMENT: Prompt Chaining - fixed sequence of LLM steps below.
# ingest -> preprocess -> classify -> extract -> summarize
# news_pipeline(ticker) - @tool for the news subagent

# REQUIREMENT: Self-reflection - the evaluator critiques the draft.
# REQUIREMENT: Evaluator-Optimizer - this is the "evaluator" half.
# Evaluation(score: int, feedback: str, passed: bool)
# evaluate_report(report) - model.with_structured_output(Evaluation)
