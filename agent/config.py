"""Environment, shared OpenAI client, paths, and evaluator settings."""

# Load .env with python-dotenv.
# client = openai.OpenAI(api_key=OPENAI_API_KEY)  -- one client, like the lab.
# DEFAULT_MODEL: used when an agent's creator doesn't pick one.
# API keys: NEWSAPI_KEY, FRED_API_KEY, SEC_USER_AGENT.
# Paths: RUN_LOG_PATH = memory/run_log.jsonl.
# Evaluator: EVAL_THRESHOLD (pass score), MAX_ROUNDS (refinement limit).
# MAX_TOOL_STEPS: cap on the tool loop in Agent.use_tools.
