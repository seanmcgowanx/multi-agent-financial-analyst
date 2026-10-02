"""Keep report claims tied to retrieved source values."""

import re
from datetime import date

from agent.historical import HistoricalEPS, dated_earnings, requested_period
from agent.schemas import Finding

RULES = (
    "Use filed_at for filing dates and period_of_report for SEC periods. "
    "Never substitute one for the other. "
    "Label Yahoo period values as provider "
    "period labels when they differ from SEC periods. Do not assume statement "
    "currency when it is null or absent, including earnings-history EPS. "
    "Keep statement diluted EPS separate from "
    "earnings-history actual EPS. State macro observation dates rather than "
    "calling monthly observations current rates. The filings tool reads "
    "metadata only. Historical EPS evidence may include XBRL facts or "
    "quoted earnings-release text; use only the supplied fields. "
    "Name unavailable specialist coverage in "
    "limitations. Include at least one cited finding from each successful "
    "specialist. Reserve space for news before adding more financial details. "
    "Summary claims need the same source support as findings."
)


def date_forms(value: str) -> list[str]:
    """Return supported display forms of a source date."""
    try:
        parsed = date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return []
    return [value[:10], f"{parsed:%B} {parsed.day}, {parsed.year}"]


def grounding_issues(
    report, references: dict, coverage: list[dict]
) -> list[str]:
    """Flag specific known errors without claiming full fact verification."""
    issues = []
    texts = [report.summary] + [f.claim for f in report.findings]
    all_text = " ".join(texts + report.limitations)
    filings = [
        filing
        for ref in references.values()
        for filing in (ref.get("data") or {}).get("filings", [])
    ]
    for text in texts:
        for filing in filings:
            form = filing.get("form_type", "")
            period = filing.get("period_of_report") or ""
            filed = filing.get("filed_at") or ""
            if not form or period[:10] == filed[:10]:
                continue
            for display in date_forms(period):
                pattern = (
                    rf"\b{re.escape(form)}\b[^.;]*?filed\s+on\s+"
                    rf"{re.escape(display)}|filed[^.;]*?\b{re.escape(form)}"
                    rf"\b[^.;]*?\bon\s+{re.escape(display)}"
                )
                if re.search(pattern, text, re.I):
                    issues.append(
                        f"Use filed_at {filed[:10]} for the {form} filing. "
                        f"The date {period[:10]} is its reporting period."
                    )
    earnings = [
        row
        for ref in references.values()
        for row in (ref.get("data") or {}).get("earnings", [])
    ]
    for text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            match = re.search(
                r"(?:actual EPS|earnings per share|EPS actual)"
                r"(?:\s+(?:of|was|is|were|around|approximately|about))*"
                r"\s+([0-9]+(?:\.[0-9]+)?)",
                sentence,
                re.I,
            )
            if not match or not earnings:
                continue
            value = float(match.group(1))
            candidates = earnings
            if re.search(r"latest|most recent", sentence, re.I):
                candidates = [max(earnings, key=lambda row: row["period"])]
            dated = [
                row
                for row in earnings
                if any(form in sentence for form in date_forms(row["period"]))
            ]
            if dated:
                candidates = dated
            if not any(
                row.get("eps_actual") is not None
                and abs(row["eps_actual"] - value) < 0.005
                for row in candidates
            ):
                issues.append(
                    "The actual EPS value does not match the stated or latest "
                    "earnings-history period. "
                    "Copy the value and period together."
                )
    unknown_currency = any(
        ref.get("tool") in ("statements", "earnings")
        and (ref.get("data") or {}).get("currency") is None
        for ref in references.values()
    )
    if unknown_currency:
        for text in texts:
            for sentence in re.split(r"(?<=[.!?])\s+", text):
                if re.search(
                    r"net income|revenue|cash flow|total assets|"
                    r"earnings per share|\bEPS\b",
                    sentence,
                    re.I,
                ):
                    if re.search(r"\bUSD\b|\bdollars\b|\$", sentence, re.I):
                        issues.append(
                            "Statement currency is unknown. "
                            "Remove unsupported "
                            "currency labels from statement amounts."
                        )
    if filings and re.search(
        r"filing (?:contents|texts?) (?:are|were|is|was) summarized",
        all_text,
        re.I,
    ):
        issues.append(
            "Only filing metadata was read. Remove claims about filing text."
        )
    if filings and re.search(
        r"filing metadata (?:was|is) not used", all_text, re.I
    ):
        issues.append(
            "Filing metadata is present. Do not claim it was unused."
        )
    if re.search(r"current (?:interest )?rate", " ".join(texts), re.I):
        if any(ref.get("source") == "FRED" for ref in references.values()):
            issues.append(
                "Describe the FRED observation with its date, "
                "not as a current rate."
            )
    limitations = " ".join(report.limitations).lower()
    cited = {
        key for finding in report.findings for key in finding.evidence_ids
    }
    for item in coverage:
        role = item["role"]
        available = {key for key in references if key.startswith(role + ":")}
        if (
            item.get("status") in ("ok", "partial")
            and available
            and not available.intersection(cited)
        ):
            issues.append(
                f"Include a cited finding from the {role} specialist."
            )
        if item.get("status") in ("empty", "error"):
            role = item["role"]
            if role not in limitations:
                issues.append(f"State that {role} coverage was unavailable.")

    required_topics = {
        source_topic(ref)
        for key, ref in references.items()
        if source_finding(key, ref) is not None
    }
    cited_topics = {
        source_topic(references[key]) for key in cited if key in references
    }
    for topic in sorted(required_topics - cited_topics):
        issues.append(f"Include a cited finding for the {topic} topic.")
    return list(dict.fromkeys(issues))


def source_facts(references: dict) -> list[dict]:
    """Keep values and their meaning together for model synthesis."""
    facts = []
    for identifier, ref in references.items():
        data = ref.get("data") or {}
        rows = []
        if data.get("bars"):
            row = max(data["bars"], key=lambda item: item["date"])
            rows.append(
                {
                    "metric": "daily close",
                    "date": row["date"],
                    "value": row["close"],
                    "currency": data.get("currency"),
                }
            )
        if data.get("observations"):
            row = max(data["observations"], key=lambda item: item["date"])
            rows.append(
                {
                    "metric": data.get("series_id"),
                    "observation_date": row["date"],
                    "value": row["value"],
                    "meaning": "dated observation, not a live rate",
                }
            )
        if data.get("earnings"):
            row = max(data["earnings"], key=lambda item: item["period"])
            rows.append(
                {
                    "metric": "earnings-history actual EPS",
                    "provider_period_label": row["period"],
                    "value": row.get("eps_actual"),
                    "currency": None,
                    "meaning": "latest record in this bounded history",
                }
            )
        for section in ("income_statement", "balance_sheet", "cash_flow"):
            if data.get(section):
                row = max(data[section], key=lambda item: item["period_end"])
                rows.append(
                    {
                        "metric": section,
                        "provider_period_label": row["period_end"],
                        "values": row["values"],
                        "currency": data.get("currency"),
                    }
                )
        for row in data.get("filings", []):
            rows.append(
                {
                    "metric": "filing metadata",
                    "form": row["form_type"],
                    "filing_date": row["filed_at"],
                    "reporting_period": row.get("period_of_report"),
                    "meaning": "filing text was not read",
                }
            )
        if rows:
            facts.append({"source_id": identifier, "facts": rows})
    return facts


def apply_source_limits(report, references: dict, coverage: list[dict]):
    """Build factual limitations from execution state."""
    limits = [
        "Evidence is a bounded sample. Source accuracy needs human review."
    ]
    for item in coverage:
        if item.get("status") != "ok":
            limits.append(
                f"The {item['role']} specialist returned {item['status']}. "
                "Its requested coverage is incomplete."
            )
    for ref in references.values():
        data = ref.get("data") or {}
        limits.extend(ref.get("warnings", []))
        if ref.get("tool") in ("statements", "earnings"):
            if not data.get("currency"):
                limits.append(
                    "Currency is unspecified for financial statement or EPS "
                    "values. Stock quote currency does not establish it."
                )
        if data.get("filings"):
            limits.append(
                "Only SEC filing metadata and links were loaded. "
                "Full filing text was not read."
            )
        if data.get("observations"):
            limits.append(
                "Macro values are dated series observations, not live rates."
            )
        if ref.get("quote"):
            limits.append(
                "News excerpts are bounded source claims, not independently "
                "verified financial facts."
            )
    report = report.model_copy(deep=True)
    report.limitations = list(dict.fromkeys(limits))[:12]
    return report


def _latest(rows, field, text):
    """Use a mentioned source date when present, otherwise the latest row."""

    matched = [
        row
        for row in rows
        if any(value in text for value in date_forms(row[field]))
    ]
    return max(matched or rows, key=lambda row: row[field])


def _statement(data, text):
    """Keep statement metrics separate from earnings-history metrics."""
    metrics = {
        "net income": "NetIncome",
        "revenue": "TotalRevenue",
        "diluted eps": "DilutedEPS",
        "diluted earnings per share": "DilutedEPS",
        "basic eps": "BasicEPS",
        "operating income": "OperatingIncome",
    }
    for phrase, key in metrics.items():
        matches_metric = phrase in text.lower() or re.search(
            rf"\b{key}\b", text, re.I
        )
        if matches_metric and data.get("income_statement"):
            row = _latest(data["income_statement"], "period_end", text)
            value = row["values"].get(key)
            if value is None:
                continue
            currency = data.get("currency") or "unspecified"
            return (
                f"The statement reports {key} = {value:.15g} "
                "for Yahoo provider "
                f"period label {row['period_end']}. "
                f"Statement currency: {currency}."
            )
    return None


def render_source_values(report, references):
    """Replace vulnerable financial wording while keeping cited source IDs."""
    result = report.model_copy(deep=True)
    changed = False
    for finding in result.findings:
        text = finding.claim
        for identifier in finding.evidence_ids:
            data = (references.get(identifier) or {}).get("data") or {}
            claim = _statement(data, text)
            if (
                claim is None
                and data.get("earnings")
                and re.search(r"\bEPS\b|earnings per share", text, re.I)
            ):
                row = _latest(data["earnings"], "period", text)
                value = row.get("eps_actual")
                if value is not None:
                    claim = (
                        f"Yahoo earnings-history actual EPS is {value:.15g} "
                        "for "
                        f"provider period label {row['period']}. "
                        "The earnings-history source "
                        "does not specify currency."
                    )
            if claim is None and re.search(
                r"period|quarter|earnings report", text, re.I
            ):
                rows = data.get("earnings") or data.get("income_statement")
                if rows:
                    field = "period" if data.get("earnings") else "period_end"
                    row = _latest(rows, field, text)
                    claim = (
                        f"The Yahoo source uses provider period label "
                        f"{row[field]}. This label is not the SEC reporting "
                        "period or filing date."
                    )
            if claim is None and data.get("observations"):
                row = _latest(data["observations"], "date", text)
                claim = (
                    f"FRED series {data['series_id']} has observation value "
                    f"{row['value']:.15g} dated {row['date']}. "
                    "This is a dated series observation."
                )
            if claim is None and data.get("filings"):
                rows = data["filings"]
                forms = re.findall(r"\b(?:10-K|10-Q|8-K)(?:/A)?\b", text)
                selected = [row for row in rows if row["form_type"] in forms]
                if not selected and re.search(
                    r"latest|most recent", text, re.I
                ):
                    selected = [max(rows, key=lambda row: row["filed_at"])]
                if selected:
                    row = _latest(selected, "filed_at", text)
                    claim = (
                        f"SEC metadata lists form {row['form_type']}, filed "
                        f"on {row['filed_at'][:10]}, with reporting period "
                        f"{row.get('period_of_report') or 'unspecified'}. "
                        "Full filing text was not read."
                    )
            if claim is not None:
                finding.claim = claim
                finding.evidence_ids = [identifier]
                changed = changed or claim != text
                break
    if changed:
        result.summary = " ".join(
            f"{finding.claim} [{', '.join(finding.evidence_ids)}]"
            for finding in result.findings
        )
    return result


def source_topic(reference):
    """Group related provider records into the six bounded report topics."""
    tool = reference.get("tool", "")
    if tool.startswith("fred:"):
        return "macro"
    if tool == "historical_eps":
        return "historical_eps"
    if tool in ("prices", "statements", "earnings", "filings"):
        return tool
    if reference.get("source") == "NewsAPI article":
        return "news"
    return None


def source_finding(identifier, reference):
    """Build a conservative fallback using only the cited source fields."""
    data = reference.get("data") or {}
    topic = source_topic(reference)
    claim = None
    if topic == "historical_eps" and data.get("facts"):
        claims = []
        for row in data["facts"]:
            period = (
                f"{row['start']} through {row['end']}"
                if row.get("start")
                else f"the quarter ended {row['end']}"
            )
            requested = data.get("requested", {})
            label = (
                f"Fiscal Q{requested.get('quarter')} {requested.get('year')}: "
                if row.get("source_kind") == "release"
                else ""
            )
            claims.append(
                f"{label}{row['metric']} was {row['value']} {row['unit']} "
                f"for {period}. Filing: {row['url']}"
            )
        claim = " ".join(claims)
    elif topic == "prices" and data.get("bars"):
        row = max(data["bars"], key=lambda item: item["date"])
        value = row.get("close")
        if value is not None:
            currency = data.get("currency") or "unspecified currency"
            claim = (
                f"The daily closing price was {value:.2f} {currency} "
                f"on {row['date']}."
            )
    elif topic == "macro" and data.get("observations"):
        claim = "The latest dated macro observation is available."
    elif topic == "statements" and data.get("income_statement"):
        row = max(
            data["income_statement"], key=lambda item: item["period_end"]
        )
        for phrase, field in (
            ("revenue", "TotalRevenue"),
            ("net income", "NetIncome"),
        ):
            if row["values"].get(field) is not None:
                claim = f"The latest statement reports {phrase}."
                break
    elif topic == "earnings" and data.get("earnings"):
        row = max(data["earnings"], key=lambda item: item["period"])
        if row.get("eps_actual") is not None:
            claim = "The latest actual EPS is available."
    elif topic == "filings" and data.get("filings"):
        claim = "The latest filing metadata is available."
    elif topic == "news" and reference.get("claim") and reference.get("quote"):
        claim = "The news source reports: " + reference["claim"]
    if claim is None:
        return None
    return Finding(claim=claim, evidence_ids=[identifier])


def preserve_topic_coverage(report, references):
    """Keep one finding per available topic before repeated details."""
    # Invalid citations must reach the evaluator instead of being hidden.
    if any(
        not finding.evidence_ids
        or not set(finding.evidence_ids) <= references.keys()
        for finding in report.findings
    ):
        return report
    required = {}
    for identifier, reference in references.items():
        fallback = source_finding(identifier, reference)
        if fallback:
            required.setdefault(source_topic(reference), fallback)
    if not required:
        return report
    selected = []
    for topic, fallback in required.items():
        candidates = [
            finding
            for finding in report.findings
            if len(finding.evidence_ids) == 1
            and source_topic(references[finding.evidence_ids[0]]) == topic
        ]
        # News wording stays tied to the validated extracted source claim.
        date_only = candidates and candidates[0].claim.startswith(
            "The Yahoo source uses provider period label"
        )
        selected.append(
            fallback
            if topic in ("news", "historical_eps")
            or not candidates
            or date_only
            else candidates[0]
        )
    for finding in report.findings:
        if len(selected) == 6:
            break
        topics = {
            source_topic(references[key]) for key in finding.evidence_ids
        }
        if finding not in selected and not topics.intersection(required):
            selected.append(finding)
    result = report.model_copy(deep=True)
    result.findings = selected
    result = render_source_values(result, references)
    result.summary = " ".join(
        f"{finding.claim} [{', '.join(finding.evidence_ids)}]"
        for finding in result.findings
    )
    return result


def period_issues(request, references):
    """Require matching typed quarterly facts, not a model assurance."""
    if not dated_earnings(request.question):
        return []
    target = requested_period(request.question, request.period_basis)
    if target is None:
        return ["Specify one year and quarter, and choose fiscal or calendar."]
    for reference in references.values():
        if reference.get("tool") != "historical_eps":
            continue
        try:
            data = HistoricalEPS.model_validate(reference.get("data"))
        except (TypeError, ValueError):
            continue
        resolved = target.model_copy(
            update={
                "basis": "fiscal"
                if target.basis == "unspecified"
                else target.basis
            }
        )
        if data.ticker != request.ticker or data.requested != resolved:
            continue
        valid = []
        for fact in data.facts:
            duration_ok = (
                fact.start is not None
                and 70 <= (fact.end - fact.start).days <= 105
            )
            if fact.source_kind == "release":
                duration_ok = bool(fact.value_quote and fact.period_quote)
            if target.basis == "calendar":
                matches = (fact.start, fact.end) == target.calendar_dates()
            else:
                matches = (
                    fact.fiscal_year == target.year
                    and abs(fact.end.year - target.year) <= 1
                    and fact.fiscal_period
                    == ("FY" if target.quarter == 4 else f"Q{target.quarter}")
                )
            valid.append(duration_ok and matches)
        metrics = " ".join(f.metric.lower() for f in data.facts)
        wanted = request.question.lower()
        if re.search(r"non[- ]?gaap|adjusted", wanted):
            if "non-gaap" not in metrics:
                continue
        if "basic" in wanted and "basic" not in metrics:
            continue
        if "diluted" in wanted and "diluted" not in metrics:
            continue
        if valid and all(valid):
            return []
    return [
        "No verified quarterly EPS evidence matches the requested period. "
        "Recent records and filing dates cannot replace that evidence."
    ]


def prepare_report(report, references, coverage):
    """Apply the same source checks to every report version."""
    report = render_source_values(report, references)
    report = preserve_topic_coverage(report, references)
    return apply_source_limits(report, references, coverage)
