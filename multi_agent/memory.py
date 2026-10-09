"""Learning across runs: an append-only run log at memory/run_log.jsonl."""

# append_run(ticker, score, rounds, lesson)  -- one JSON line per run.
# recent_runs(n, ticker=None)                -- last n entries, optionally by ticker,
#                                               formatted for the coordinator's plan prompt.
