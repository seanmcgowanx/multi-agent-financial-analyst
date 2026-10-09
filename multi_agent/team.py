"""InvestmentResearchTeam: wires agents together and exposes run(). Mirrors the lab's MultiAgentTeam."""

# class InvestmentResearchTeam:
#     __init__: Coordinator, specialists, Evaluator
#
#     run(ticker) -> dict
#         1. past = memory.recent_runs(...)
#         2. plan = coordinator.plan(ticker, past)
#         3. findings = [coordinator.route(step, ticker) for step in plan]
#         4. report = coordinator.synthesize(ticker, findings)
#         5. Evaluate -> revise loop:
#            loop up to MAX_ROUNDS: evaluate -> pass? break : revise
#         6. memory.append_run(ticker, score, rounds, lesson)
#         return {"plan", "findings", "drafts", "evaluations", "report"}
#            (every intermediate kept so the notebook can show and chart it)
#
#     show_team_status()  -- like the lab: tasks completed per agent
