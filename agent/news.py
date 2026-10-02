"""Select and clean company news before the prompt chain."""

import re
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from agent.config import Settings
from agent.schemas import (
    CleanArticle,
    NewsCandidateDecision,
    NewsData,
    NewsDiagnostics,
    ResearchRequest,
)


class TextParser(HTMLParser):
    """Read visible text while dropping script and style content."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def clean_text(value: str) -> str:
    """Remove HTML markup and normalize whitespace."""
    parser = TextParser()
    parser.feed(value)
    parser.close()
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def complete_excerpts(text: str) -> list[str]:
    """Exclude fragments marked as truncated or cut at the text limit."""
    parts = re.split(r"\n+|(?<=[.!?])\s+", text)
    return [
        part.strip()
        for part in parts
        if part.strip()
        and not re.search(r"\.{3}|\u2026|\[\+\d+ chars\]", part)
    ]


def article_text(article, limit: int) -> str:
    """Keep provider fields separate and mark local truncation explicitly."""
    text = "\n".join(
        clean_text(value)
        for value in (article.title, article.description, article.content)
        if value
    )
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def news_query(request: ResearchRequest) -> str:
    """Quote company and ticker terms without accepting query operators."""
    company = re.sub(r'["\\()]', " ", request.company_name).strip()
    terms = list(dict.fromkeys([company, request.ticker]))
    return " OR ".join(f'"{term}"' for term in terms if term)


def canonical_url(url: str) -> str:
    """Remove tracking parameters while preserving article identifiers."""
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            urlencode(sorted(query)),
            "",
        )
    )


def language_hint(text: str) -> str:
    """Describe script balance, not the language or publisher location."""
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 30:
        return "uncertain"
    non_latin = sum(not ("a" <= char.lower() <= "z") for char in letters)
    return (
        "mixed_or_non_latin"
        if non_latin / len(letters) > 0.35
        else "latin_or_uncertain"
    )


def select_news(data: NewsData, request: ResearchRequest, settings: Settings):
    """Deduplicate and rank all candidates before taking the analysis limit."""
    diagnostics = NewsDiagnostics(
        query=data.query,
        total_results=data.total_results,
        received_count=len(data.articles),
    )
    seen_urls, seen_titles = set(), set()
    ranked = []
    terms = [
        term.strip()
        for term in (request.company_name, request.ticker)
        if term.strip()
    ]
    patterns = [
        re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.I)
        for term in terms
    ]
    for article in data.articles[: settings.news_candidate_limit]:
        title = clean_text(article.title)
        body = clean_text(
            " ".join(filter(None, [article.description, article.content]))
        )
        text = clean_text(
            " ".join(
                filter(
                    None, [article.title, article.description, article.content]
                )
            )
        )
        decision = NewsCandidateDecision(
            title=title[:200], url=article.url, outcome="not_selected"
        )
        diagnostics.candidates.append(decision)
        if not title or len(text.strip()) < 20:
            decision.outcome = "insufficient_text"
            diagnostics.unusable_count += 1
            continue
        url_key = canonical_url(article.url)
        title_key = re.sub(r"\W+", " ", title.casefold()).strip()
        if url_key in seen_urls or title_key in seen_titles:
            decision.outcome = "duplicate"
            diagnostics.duplicate_count += 1
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        # Prefer direct title coverage, then a mention in the available body.
        score = 8 * any(p.search(title) for p in patterns)
        score += 3 * any(p.search(body) for p in patterns)
        score += min(len(body.split()) // 25, 2)
        if score and re.search(
            r"\b(?:earnings|revenue|CEO|launches|announced|buyback|"
            r"partnership|regulation|antitrust|leadership)\b",
            title + " " + body,
            re.I,
        ):
            score += 3
        if re.search(
            r"^best\b|should you buy|\bdeals\b", title + " " + body, re.I
        ):
            score -= 3
        hint = language_hint(body or text)
        decision.language_hint = hint
        if hint == "mixed_or_non_latin":
            score -= 2
        decision.score = score
        ranked.append((score, article.published_at, article, text, decision))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = []
    for _, _, article, text, decision in ranked[: settings.news_article_limit]:
        decision.outcome = "selected"
        selected.append(
            CleanArticle(
                id=f"a{len(selected) + 1}",
                title=clean_text(article.title)[:200],
                text=article_text(article, settings.news_text_chars),
                url=article.url,
                published_at=article.published_at,
            )
        )
    diagnostics.selected_count = len(selected)
    return selected, diagnostics


def unsupported_numbers(claim: str, quote: str) -> bool:
    """Reject new numerical values while allowing common scale spellings."""
    from decimal import Decimal

    scales = {
        "bn": 10**9,
        "billion": 10**9,
        "million": 10**6,
        "trillion": 10**12,
    }

    def numbers(text):
        values = set()
        for match in re.finditer(
            r"(?<!\w)(\d[\d,]*(?:\.\d+)?)\s*"
            r"(bn\b|billion\b|million\b|trillion\b)?",
            text,
            re.I,
        ):
            value = Decimal(match.group(1).replace(",", ""))
            values.add(value * scales.get((match.group(2) or "").lower(), 1))
        return values

    return not numbers(claim) <= numbers(quote)
