# Multi-agent financial analyst

AAI-520 final team project, University of San Diego.

Team repository: https://github.com/seanmcgowanx/multi-agent-financial-analyst

The Supervisor plans research and routes work to Earnings, News, and Market
specialists. Specialists select tools and return cited findings. An evaluator
scores the answer and provides feedback for revision. Brief lessons are saved
and reused across runs. LangChain provides structured model calls. LangSmith
tracing is optional.

## Python file guide

The project has 17 Python source files. Every project Python file is listed
in the two tables below, with its function. Installed dependency files in
.venv are not part of this list.

Start with app.py, supervisor.py, subagents.py, tools.py, and workflows.py
to follow a research request. Supporting files handle shared data and source
checks.

### Main Python files (9)

| File | Function |
| --- | --- |
| [app.py](app.py) | Reads command-line options, accepts clarification replies, starts research or the offline demo, and saves JSON, TXT, or HTML output. It also formats the terminal answer. |
| [agent/__init__.py](agent/__init__.py) | Marks agent as a Python package so the application and future notebook can import its modules. |
| [agent/config.py](agent/config.py) | Defines Settings. Loads .env and environment variables, holds API keys without displaying them, and sets model, timeout, news, revision, and memory limits. |
| [agent/prompts.py](agent/prompts.py) | Holds shared static instructions for request understanding, planning, synthesis, revision, news processing, and EPS extraction. |
| [agent/supervisor.py](agent/supervisor.py) | Defines Supervisor and the public run() function. Loads lessons, plans research, selects specialists, combines evidence, evaluates and revises the answer, and saves lessons. |
| [agent/subagents.py](agent/subagents.py) | Defines MarketAgent, EarningsAgent, and NewsAgent. Shares bounded tool execution for Market and Earnings. NewsAgent uses the news prompt chain. These are the three specialist roles. |
| [agent/tools.py](agent/tools.py) | Provides get_price_history(), get_financial_statements(), get_earnings_history(), get_fred_series(), get_company_news(), and get_sec_filings(). Each tool returns structured data or a safe error. SEC filing search here returns metadata and links. |
| [agent/workflows.py](agent/workflows.py) | Runs the five news stages: ingest, preprocess, classify, extract, and summarize. Also contains evaluate_report() and required_corrections() for the evaluator-optimizer loop. |
| [agent/memory.py](agent/memory.py) | Defines PersistentMemory. Loads recent lessons for a ticker and saves new lessons with duplicate removal, file locking, and atomic file updates. |

### Supporting Python files (8)

| File | Function |
| --- | --- |
| [agent/intake.py](agent/intake.py) | Defines IntakeSession and prepare_request(). Uses model-proposed identity and explicit user details, asks for missing information, validates the company through a lookup, and prepares a ResearchRequest. The CLI and notebook entry point share this code. |
| [agent/runtime.py](agent/runtime.py) | Provides LangChain model calls, LangSmith tracing, model-call limits, safe tool execution, ticker availability checks, evidence records, and one bounded citation-repair attempt. RunContext keeps the state of an invocation. |
| [agent/schemas.py](agent/schemas.py) | Defines the shared Pydantic records for prices, news, filings, requests, findings, plans, evaluations, lessons, and final results. Validates data shape, ticker syntax, and result status. |
| [agent/providers.py](agent/providers.py) | Handles HTTP timeouts, optional retries, missing keys, and safe provider errors. Runs Yahoo requests in a child process with a time limit and converts provider tables into structured records. Its main() function is the child-process entry point. |
| [agent/historical.py](agent/historical.py) | Parses requested quarters and years. Retrieves historical SEC XBRL EPS facts, discovers earnings-release exhibits when needed, extracts EPS, and checks source quotes, values, accounting labels, and dates. No company-specific source URL is hardcoded. |
| [agent/evidence.py](agent/evidence.py) | Checks known source interpretation risks. Keeps values and dates together, preserves topic coverage, checks historical periods, formats supported findings, and adds factual source limitations. It does not perform universal fact verification. |
| [agent/news.py](agent/news.py) | Cleans HTML and news text, builds the company query, removes duplicate URLs, ranks candidate articles, selects complete excerpts, and rejects extracted numbers absent from the cited text. |
| [agent/demo.py](agent/demo.py) | Supplies synthetic prices and scripted model responses for --demo. It makes no API calls and does not load the archived test files. |

## Other project files

These files support the Python code but are not Python source files.

### Configuration, documentation, and stored data

| File | Function |
| --- | --- |
| [README.md](README.md) | Explains installation, commands, file responsibilities, assignment criteria, and current limits. |
| [requirements.txt](requirements.txt) | Lists pinned direct dependencies for the application. Use this file for the normal installation. |
| [requirements-lock.txt](requirements-lock.txt) | Records pinned packages from the captured local environment, including indirect dependencies. It is an environment snapshot, not an automatically maintained lock manager. |
| [requirements-dev.txt](requirements-dev.txt) | Includes the application requirements and Ruff for local style and formatting checks. It does not restore the archived tests. |
| [pyproject.toml](pyproject.toml) | Configures Ruff: 79-character lines, the Python target, and checks for errors, unused code, whitespace, and import order. |
| [.env.example](.env.example) | Provides empty API-key fields and example settings. Copy it to .env when setting up a new installation. |
| memory/notes.json | Stores persistent research lessons. It is local data, ignored by Git, and is read and updated by PersistentMemory. MEMORY_PATH can select a different file. |

### Generated files and local folders

These files are created when needed. They are not additional application code.
The default report folder can be changed with --output-dir.

| File or folder | Function |
| --- | --- |
| output/reports/<ticker>_<run_id>.json | Saves the request, plan, specialist evidence, report versions, evaluations, events, lessons, and final status. |
| output/reports/<ticker>_<run_id>.txt | Saves the readable answer when the response format is answer. |
| output/reports/<ticker>_<run_id>.html | Saves the readable report and execution details when the response format is report. This is an application report, not a notebook export. |
| output/reports/<ticker>_<run_id>_conversation.json | Saves a completed intake conversation and its resolved request. |
| memory/notes.json.lock | Temporary lock used while updating the default memory file. |
| memory/.lessons-*.tmp | Temporary file used to write updated lessons before replacing the memory file. |

There is no current notebook. Previous notebooks, test
files, phase documents, and reports are preserved in the backup. A new notebook
will import this package when notebook preparation resumes.

## How the files work together

1. app.py loads Settings from config.py and reads the question.
2. intake.py resolves missing request details when clarification is enabled.
3. supervisor.py loads memory and plans which specialists are needed.
4. subagents.py selects tools from tools.py. providers.py handles requests;
   historical.py handles the historical EPS path. News uses workflows.py and
   news.py for the required five-stage chain.
5. supervisor.py combines findings. evidence.py checks source usage, and
   workflows.py evaluates the draft. The Supervisor can revise using feedback.
6. memory.py saves lessons, and app.py saves the result files.

schemas.py defines the data exchanged at each step. runtime.py supplies model
calls, execution limits, and tracing. prompts.py provides shared instructions.
The future notebook can start from supervisor.run() instead of app.py.

## Setup

The existing .venv and .env remain usable. For a fresh installation, use
Python 3.10 or later:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Enter OPENAI_API_KEY, NEWS_API_KEY, FRED_API_KEY, SEC_API_KEY, and optionally
LANGSMITH_API_KEY in .env. SEC_API_KEY is for sec-api.io, which supplies SEC
EDGAR records. yfinance needs no key. Do not put keys in source or a notebook.
Set LANGSMITH_TRACING=true to enable tracing. Research questions and source
excerpts can appear in traces; settings and credentials are excluded.

## Run a question

```bash
.venv/bin/python app.py --live --env-file .env \
  --question "What were NVIDIA's earnings for Q4 2023?"
```

At the clarification prompt, enter:

```text
Fiscal 2023, GAAP and non-GAAP diluted EPS.
```

The verified pre-refactor live result was $0.57 GAAP diluted EPS and $0.88
non-GAAP diluted EPS for the quarter ended January 29, 2023, on the original
release basis. That saved answer was reproduced offline after refactoring.
This does not replace live validation of other companies or wording.

For an explicit request that skips clarification:

```bash
.venv/bin/python app.py --live --env-file .env \
  --ticker NVDA --company NVIDIA --period-basis fiscal \
  --question "What were NVDA GAAP and non-GAAP diluted EPS for Q4 fiscal 2023?"
```

For news only:

```bash
.venv/bin/python app.py --live --env-file .env \
  --ticker NVDA --company NVIDIA --question "Summarize recent NVIDIA news."
```

Add --clarify to explicit arguments to use intake. Enter quit to stop.
Clarification supports one research request. It is not general continuous
chat, and short replies such as both are not generally supported.

Use --format auto, answer, or report. Answers save JSON and TXT; reports save
JSON and HTML under output/reports. Use --output-dir to choose another folder.
A successful intake also saves the conversation. Only a completed result is
marked successful; needs_review remains an unverified answer. CLI exit codes
are 0 for completed, 1 for incomplete research or errors, and 2 for stopped
or noninteractive clarification. Model attempts do not count provider calls.
Every --live command can use API quota.

## Offline demonstration

```bash
.venv/bin/python app.py --demo
```

This uses synthetic data through the research pipeline without external calls.
The demo is explicitly labeled and does not import the archived tests.

## Future notebook entry point

A notebook in the project root can use the same request preparation as the CLI:

```python
from pathlib import Path
from agent.config import Settings
from agent.supervisor import run

result = run(
    question="What were NVIDIA's earnings for Q4 2023?",
    settings=Settings.load(Path(".env")),
    clarification_callback=input,
)
print(result.status)
if result.status == "completed":
    print(result.report.summary)
```

This example makes live calls. Without clarification_callback, an unclear
request returns needs_clarification with a message. Explicit ticker, company,
question, and period_basis arguments can be supplied to run(). Structured
results support model_dump() and model_dump_json().

## Assignment criteria

| Required capability | Implementation and evidence to show |
| --- | --- |
| Planning | Supervisor produces a structured research plan |
| Dynamic tool use | Selected specialists choose allowed API tools |
| Self-reflection | Evaluator critique and report revision history |
| Learning across runs | Lessons saved and loaded from memory/notes.json |
| Prompt chaining | Separate ingest, preprocess, classify, extract, summarize stages |
| Routing | Supervisor delegates only to selected specialist roles |
| Evaluator-optimizer | Draft, evaluation, feedback, and bounded revision |
| Readable code | PEP 8, simple comments, typed data, and explicit failures |
| Notebook evidence | Pending: workflows, capabilities, evaluation, and iteration |
| GitHub collaboration | Pending: team commits and repository alignment |

The assignment requires all four agent functions and three workflows to be
implemented and demonstrated. The final notebook must be readable as PDF or
HTML and contain the repository link and explanations. No replacement notebook
or HTML notebook export has been created during this refactor.

## Limits

Historical retrieval supports quarterly EPS, including a bounded release
fallback. Historical net income and revenue are not implemented. Missing
historical evidence cannot be replaced with current values. Historical EPS
research uses SEC evidence and does not require a recent Yahoo price check. NewsAPI text can
be truncated; market and macro data are bounded samples. Saved lessons do not
train the model. Source checks reduce known errors but are not universal fact
verification.
