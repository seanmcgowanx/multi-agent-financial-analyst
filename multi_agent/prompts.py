"""All system prompts and prompt templates."""

# Appended to a tool-using agent's prompt by Agent.use_tools.
TOOL_PROTOCOL = """You can call these tools:
{tool_descriptions}

Reply with exactly ONE JSON object and nothing else, in one of two forms:
  {{"thought": "<why>", "tool": "<tool name>", "args": {{<keyword args>}}}}
  {{"thought": "<why>", "final": "<your answer to the task>"}}

Call one tool per reply. You will see each tool's result before your next
reply. Give a final answer once you have enough information; do not repeat a
call you have already made."""

# COORDINATOR_PLAN: given ticker + past run log, return JSON steps, each
#   tagged with a specialist: [{"specialist": "earnings|news|market", "task": "..."}]
# COORDINATOR_SYNTHESIZE / COORDINATOR_REVISE: write report; revise with feedback.
# EARNINGS_ROLE, NEWS_ROLE, MARKET_ROLE: specialist role descriptions.
# NEWS_CHAIN_*: one prompt per chain step (preprocess, classify, extract, summarize).
# EVALUATOR: score 0-10 on a rubric, return JSON {"score", "feedback"}.
# LESSON: turn a finished run into a one-line lesson for the run log.
