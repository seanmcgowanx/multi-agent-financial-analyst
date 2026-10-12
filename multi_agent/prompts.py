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

# Coordinator.plan: break the analysis into steps, each tagged with a specialist.
COORDINATOR_PLAN = """Plan a stock analysis of {ticker}.

Specialists you can assign:
- earnings: reported financials, SEC filings, earnings trends
- news: recent news coverage and sentiment
- market: price action, valuation, macro conditions

Lessons from past runs (follow them):
{lessons}

Break the analysis into 3-6 steps. Each step goes to one specialist and names
a specific, answerable task.

Reply with JSON only:
{{"steps": [{{"specialist": "earnings|news|market", "task": "<task>"}}]}}"""

# COORDINATOR_SYNTHESIZE / COORDINATOR_REVISE: write report; revise with feedback.
# EARNINGS_ROLE, NEWS_ROLE, MARKET_ROLE: specialist role descriptions.
# NEWS_CHAIN_*: one prompt per chain step (preprocess, classify, extract, summarize).
# EVALUATOR: score 0-10 on a rubric, return JSON {"score", "feedback"}.
# LESSON: one reusable lesson on how to plan/write (no company facts), or "NONE".
#   Include memory.get_lessons(); reply NONE if the lesson is already covered there.
