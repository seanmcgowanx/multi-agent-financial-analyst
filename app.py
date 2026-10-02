"""Run local financial research and save structured, readable reports."""

import argparse
import json
import sys
import tempfile
from html import escape
from pathlib import Path

from agent.config import Settings
from agent.intake import prepare_request
from agent.runtime import Phase2Failure
from agent.schemas import ResearchRequest, SupervisorResult
from agent.supervisor import Supervisor


def render_report(result: SupervisorResult) -> str:
    """Escape all research content before placing it in an HTML page."""
    data = result.model_dump(mode="json")
    report = result.report
    title = (
        f"{result.request.ticker} research" if result.request else "Research"
    )
    findings = ""
    if report:
        findings = "".join(
            f"<li>{escape(item.claim)}<br><small>Sources: "
            f"{escape(', '.join(item.evidence_ids))}</small></li>"
            for item in report.findings
        )
    summary = report.summary if report else "No report was produced."
    limits = "".join(
        f"<li>{escape(item)}</li>"
        for item in (report.limitations if report else [])
    )
    error = str(result.error.message) if result.error else "None"
    details = escape(json.dumps(data, indent=2, ensure_ascii=True))
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title>"
        "<style>body{font:16px/1.6 system-ui;max-width:960px;margin:40px auto;"
        "padding:0 20px;color:#172333}li{margin:12px 0}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f4f8;"
        "padding:16px}small{color:#40536b}</style><main>"
        f"<h1>{escape(title)}</h1><p>Status: <strong>"
        f"{escape(result.status)}</strong></p><p>{escape(summary)}</p>"
        f"<h2>Findings</h2><ol>{findings}</ol>"
        f"<h2>Limitations</h2><ul>{limits}</ul><p>Error: {escape(error)}</p>"
        "<h2>Sources, evaluations, and execution details</h2>"
        "<p>Raw model drafts in model_report_versions are audit material "
        "and may contain errors. "
        "The report above is the evaluated version.</p>"
        f"<pre>{details}</pre></main></html>"
    )


def render_answer(result: SupervisorResult) -> str:
    """Show checked findings and sources without another model call."""
    lines = [f"Status: {result.status}"]
    if result.status != "completed":
        lines.append("This result needs review. It is not a verified answer.")
    if result.report is None:
        lines.append(result.error.message if result.error else "No answer.")
        return "\n".join(lines)
    if not result.report.findings:
        lines.append(result.report.summary)
    for finding in result.report.findings:
        lines.append(f"- {finding.claim} [{', '.join(finding.evidence_ids)}]")
    used = {key for f in result.report.findings for key in f.evidence_ids}
    for key in sorted(used):
        ref = result.references.get(key, {})
        lines.append(f"Source {key}: {ref.get('source', 'See JSON evidence')}")
        if ref.get("url"):
            lines.append(ref["url"])
        for field in ("retrieved_at", "published_at"):
            if ref.get(field):
                lines.append(f"{field}: {ref[field]}")
    if result.report.limitations:
        lines.append("Limits:")
        lines.extend(f"- {text}" for text in result.report.limitations)
    return "\n".join(lines)


def demo_result() -> SupervisorResult:
    """Exercise the real workflow with synthetic data and no network calls."""
    from unittest.mock import patch

    from agent.demo import (
        ScriptedModel,
        draft,
        evaluation,
        plan,
        prices,
        report,
    )

    model = ScriptedModel(
        [
            plan("market"),
            {"tools": ["prices"], "rationale": "Read synthetic price data."},
            draft(),
            report(),
            evaluation(),
        ]
    )
    with tempfile.TemporaryDirectory(prefix="aai520-demo-") as folder:
        settings = Settings(memory_path=Path(folder) / "lessons.json")
        with patch(
            "agent.runtime.get_price_history",
            return_value=prices(),
        ):
            with patch(
                "agent.subagents.get_price_history", return_value=prices()
            ):
                return Supervisor(settings, model).run(
                    ResearchRequest(
                        ticker="AAPL",
                        company_name="Apple",
                        question="Demonstrate synthetic price research.",
                    )
                )


def clarification_reply(message):
    """Read one terminal reply, or stop without starting research."""
    print(f"Status: needs_clarification. {message}")
    if not sys.stdin.isatty():
        return None
    try:
        return input("Your reply (or quit): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None


def main(argv: list[str] | None = None) -> int:
    """Require an explicit live choice before using provider APIs."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--demo", action="store_true")
    parser.add_argument(
        "--clarify",
        action="store_true",
        help="Interpret the question and accept clarification replies.",
    )
    parser.add_argument("--ticker")
    parser.add_argument("--company")
    parser.add_argument("--question")
    parser.add_argument(
        "--format",
        choices=("auto", "answer", "report"),
        default="auto",
    )
    parser.add_argument(
        "--period-basis",
        choices=("auto", "fiscal", "calendar"),
        default="auto",
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--memory-file", type=Path)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("output/reports")
    )
    args = parser.parse_args(argv)
    if args.live and not args.question:
        parser.error("Live runs require a question.")
    try:
        conversation = {}
        if args.demo:
            print("SYNTHETIC DEMO: no live financial data or model calls.")
            result = demo_result()
            result.response_format = (
                "report" if args.format == "auto" else args.format
            )
        else:
            settings = Settings.load(args.env_file)
            if args.memory_file:
                settings = settings.model_copy(
                    update={
                        "memory_path": args.memory_file,
                    }
                )
            supervisor = Supervisor(settings)
            request, intake_calls = prepare_request(
                supervisor,
                args.question,
                ticker=args.ticker,
                company=args.company,
                period_basis=args.period_basis,
                response_format=args.format,
                clarify=args.clarify,
                callback=clarification_reply,
                audit=conversation,
            )
            if not isinstance(request, ResearchRequest):
                return 2
            result = supervisor.run(request)
            result.model_calls += intake_calls
        args.output_dir.mkdir(parents=True, exist_ok=True)
        prefix = "demo" if args.demo else result.request.ticker
        stem = f"{prefix}_{result.run_id}"
        json_path = args.output_dir / f"{stem}.json"
        html_path = args.output_dir / f"{stem}.html"
        if conversation:
            intake_path = args.output_dir / f"{stem}_conversation.json"
            intake_path.write_text(
                json.dumps(conversation, indent=2),
                encoding="utf-8",
            )
        json_path.write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
        answer_path = args.output_dir / f"{stem}.txt"
        if result.response_format == "report":
            html = render_report(result)
            if args.demo:
                html = html.replace(
                    "<h1>", "<p>SYNTHETIC DEMO: fixture data.</p><h1>", 1
                )
            html_path.write_text(html, encoding="utf-8")
        else:
            answer = render_answer(result)
            if args.demo:
                answer = "SYNTHETIC DEMO: fixture data.\n" + answer
            answer_path.write_text(answer + "\n", encoding="utf-8")
    except Phase2Failure as exc:
        print(f"Request could not continue: {exc}")
        return 1
    except (ValueError, OSError):
        print(
            "The run could not finish. "
            "Check inputs, settings, and file access."
        )
        return 1
    print(f"Status: {result.status}. Model attempts: {result.model_calls}.")
    if result.status == "needs_review" and result.report:
        print(result.report.summary)
    print(f"JSON report: {json_path}")
    if result.response_format == "report":
        print(f"HTML report: {html_path}")
    else:
        print(answer)
        print(f"Text answer: {answer_path}")
    return int(result.status != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
