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

# Coordinator.synthesize: turn the specialists' findings into the draft report.
COORDINATOR_SYNTHESIZE = """Write an investment research report on {ticker} from
these specialist findings:

{findings}

Use only facts and numbers from the findings; do not invent data. If a finding
is an error or missing, say what could not be covered.

Sections: Summary, Financials, News & Sentiment, Market, Risks, Outlook."""

# Coordinator.revise: rewrite the report to address the evaluator's feedback.
COORDINATOR_REVISE = """Revise this investment research report to address the
reviewer's feedback.

Report:
{report}

Feedback:
{feedback}

Specialist findings:
{findings}

Use only facts and numbers from the findings; do not invent data. Keep the
same sections. Return only the full revised report."""

# team.run: one reusable lesson after a first draft fails evaluation.
LESSON = """A stock research report's first draft failed review.

Plan used:
{plan}

Reviewer feedback:
{feedback}

Lessons already learned:
{lessons}

Write one short, reusable lesson on how to plan or write these reports better
next time. It must apply to any company, so include no company facts or numbers.
If the lesson is already covered above, reply only NONE."""

# EARNINGS_ROLE: specialist role description

# NEWS_ROLE: specialist role description

# MARKET_ROLE: specialist role description

# NEWS_CHAIN_*: one prompt per chain step (preprocess, classify, extract, summarize).

# EVALUATOR: score 0-10 on a rubric, return JSON {"score", "feedback"}.