"""Learning across runs: an append-only lesson log at memory/lessons.jsonl."""

# append_lesson(lesson) -- one JSON line per lesson; written only when a run taught something.
# get_lessons(n=100)    -- newest n lessons, formatted for the coordinator's plan prompt.

import json

from multi_agent.config import LESSONS_PATH


def append_lesson(lesson):
    LESSONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LESSONS_PATH, "a", encoding="utf-8") as memory:
        memory.write(json.dumps({"lesson": lesson}) + "\n")


def get_lessons(n=100):
    if not LESSONS_PATH.exists():
        return "No lessons yet"

    entries = [
        json.loads(line)["lesson"]
        for line in LESSONS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return "\n".join(f"- {lesson}" for lesson in entries[-n:]) or "No lessons yet"
