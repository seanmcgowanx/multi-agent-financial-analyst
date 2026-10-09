"""Coordinator: plans, routes steps to specialists, writes/revises the report."""

# class Coordinator(Agent):
#     plan(ticker, past_runs) -> list[{"specialist", "task"}]
#
#     route(step, ticker) -> str   -- SPECIALISTS[step["specialist"]].analyze(...)
#                                     unknown label -> fallback specialist + log it
#
#     synthesize(ticker, findings) -> str            -- draft report
#     revise(report, feedback, findings) -> str      -- optimizer half of eval loop
