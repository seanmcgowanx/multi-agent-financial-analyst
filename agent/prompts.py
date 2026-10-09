"""All system prompts and prompt templates."""

# TOOL_PROTOCOL: tells an agent to reply with ONE JSON object per turn:
#   {"tool": "<name>", "args": {...}}  to call a tool, or
#   {"final": "<answer>"}              when done.
# COORDINATOR_PLAN: given ticker + past run log, return JSON steps, each
#   tagged with a specialist: [{"specialist": "earnings|news|market", "task": "..."}]
# COORDINATOR_SYNTHESIZE / COORDINATOR_REVISE: write report; revise with feedback.
# EARNINGS_ROLE, NEWS_ROLE, MARKET_ROLE: specialist role descriptions.
# NEWS_CHAIN_*: one prompt per chain step (preprocess, classify, extract, summarize).
# EVALUATOR: score 0-10 on a rubric, return JSON {"score", "feedback"}.
# LESSON: turn a finished run into a one-line lesson for the run log.
