"""Investment research agent: tools -> subagents -> supervisor.

Import order is one-way: config -> prompts -> tools -> memory ->
workflows -> subagents -> supervisor.

"# REQUIREMENT: <name>" comments mark where each course rubric item is
implemented. Find them all with: grep -rn "REQUIREMENT:" agent/
"""
