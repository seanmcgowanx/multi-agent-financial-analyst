"""Coordinator: plans, routes steps to specialists, writes/revises the report."""

# class Coordinator(Agent):
#     REQUIREMENT: Plans its research steps
#     plan(ticker, past_runs) -> list[{"specialist", "task"}]
#
#     REQUIREMENT: Routing
#     route(step, ticker) -> str   -- SPECIALISTS[step["specialist"]].analyze(...)
#                                     unknown label -> fallback specialist + log it
#
#     synthesize(ticker, findings) -> str            -- draft report
#     revise(report, feedback, findings) -> str      -- optimizer half of eval loop
