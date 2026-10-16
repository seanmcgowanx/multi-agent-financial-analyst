"""Environment, shared OpenAI client, default LLM, paths, evaluator and tool settings."""

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
EVAL_THRESHOLD = 9  # passing score (1-10); first drafts at 8 still had real gaps
MAX_ROUNDS = 3  # most drafts per run: the first plus up to 2 revisions

# Tools
MAX_TOOL_STEPS = 6

# Memory
LESSONS_PATH = Path(__file__).resolve().parent.parent / "memory" / "lessons.jsonl"
