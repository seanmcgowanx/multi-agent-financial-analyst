"""Base Agent class, mirroring the course lab (final-project-demo.ipynb).

Same shape as the lab: name, role, model, in-session memory list,
call_llm / process / send_to. Each agent's creator picks its model.
Plain prompt in, text out; no function-calling API.
"""

# class Agent:
#     __init__(name, role, model=DEFAULT_MODEL, tools=None)
#     call_llm(prompt, system=None) -> str      -- config.client.chat.completions.create
#     process(task) -> str                      -- call_llm + append to self.memory
#     send_to(other_agent, message) -> str      -- lab-style handoff
#
#     use_tools(task) -> str
#         REQUIREMENT: Uses tools dynamically
#         Loop up to MAX_TOOL_STEPS:
#           prompt = role + TOOL_PROTOCOL + tool descriptions + task + observations
#           parse JSON reply; if "tool": run TOOLS[name]["fn"](**args), append
#           observation; if "final": return it. Bad JSON -> retry with error note.
