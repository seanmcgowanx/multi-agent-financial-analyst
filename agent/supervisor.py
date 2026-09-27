"""Layer 3: supervisor agent and run() entry point."""

# REQUIREMENT: Routing - supervisor picks which subagent to call.

# REQUIREMENT: Planning - supervisor writes a plan before calling tools.
# supervisor_agent: tools=[analyze_earnings, analyze_news, analyze_market],
#   SUPERVISOR_PROMPT, checkpointer=InMemorySaver()

# REQUIREMENT: Evaluator-Optimizer - run() loops draft -> score -> fix.

# REQUIREMENT: Self-reflection - run() revises using evaluator feedback.

# REQUIREMENT: Learning across runs - run() loads and saves notes.
# run(ticker): load notes -> invoke -> evaluate -> refine (max 3)
#   -> save lesson -> return report + score log
