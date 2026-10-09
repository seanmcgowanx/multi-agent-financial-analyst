"""Environment, shared OpenAI client, paths, and evaluator settings."""

# Load .env with python-dotenv.
# client = openai.OpenAI(api_key=OPENAI_API_KEY)  -- one client, like the lab.
# DEFAULT_MODEL: used when an agent's creator doesn't pick one.
# API keys: NEWSAPI_KEY, FRED_API_KEY, SEC_USER_AGENT.
# Paths: RUN_LOG_PATH = memory/run_log.jsonl.
# Evaluator: EVAL_THRESHOLD (pass score), MAX_ROUNDS (refinement limit).
# MAX_TOOL_STEPS: cap on the tool loop in Agent.use_tools.

import os
from pathlib import Path

import openai
from dotenv import load_dotenv

load_dotenv()

# Keys
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
FRED_API_KEY = os.getenv("FRED_API_KEY")
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT")

# LLM
client = openai.OpenAI(api_key=OPENAI_API_KEY) 
DEFAULT_MODEL = "gpt-6-luna"

# Evaluator
# EVAL_THRESHOLD = 
# MAX_ROUNDS = 

# Tools
MAX_TOOL_STEPS = 10

# Memory
RUN_LOG_PATH = Path(__file__).resolve().parent.parent / "memory" / "run_log.jsonl"

