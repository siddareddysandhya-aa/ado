"""Safe, deterministic natural-language filter extraction for dashboard queries."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryIntent:
    """Recognized dashboard filters and preferred metric from a natural-language request."""

    metric: str | None = None
    iteration_terms: tuple[str, ...] = ()
    tag: str | None = None
    assignee: str | None = None


def parse_natural_language(query: str) -> QueryIntent:
    """Extract only explicit safe filters; users retain control over final selections."""
    normalized = query.lower()
    metric = next((name for name in ("Velocity", "Burndown", "Burnup", "Lead Time", "Cycle Time", "Throughput") if name.lower() in normalized), None)
    sprint_terms = tuple(re.findall(r"(?:sprint|iteration)\s*\d+", query, re.IGNORECASE))
    tag_match = re.search(r"(?:tagged|tag)\s+(?:with\s+)?([\w.-]+)", query, re.IGNORECASE)
    assignee_match = re.search(r"assignee\s*(?:=|is)?\s*([\w .'-]+?)(?:\s+(?:in|over|for|and)|$)", query, re.IGNORECASE)
    return QueryIntent(metric, sprint_terms, tag_match.group(1) if tag_match else None, assignee_match.group(1).strip() if assignee_match else None)