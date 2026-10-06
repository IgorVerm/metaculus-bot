"""How fresh is a research text, and which web addresses does it cite?

Research requests ask the search model to end with a line "NEWEST_EVIDENCE_DATE: YYYY-MM-DD"
(or "unknown"). This module reads that line, computes the age against a given "today" and
decides whether the one allowed retry runs.

Web addresses are only found with a regular expression and reported. Nothing here, or anywhere
else in the bot, fetches an address that a model or a page supplied.
"""

import re
from datetime import date, timedelta
from urllib.parse import urlsplit

EVIDENCE_LINE = "NEWEST_EVIDENCE_DATE"

_EVIDENCE = re.compile(
    r"NEWEST_EVIDENCE_DATE\s*:\s*\**\s*(\d{4}-\d{2}-\d{2}|unknown)", re.IGNORECASE
)
_URL = re.compile(r"https?://[^\s<>\"'\]\[)(}{|\\^`]+", re.IGNORECASE)
_TRAILING = ".,;:!?*_"

# Sources that are not a search model's own answer: they are not asked for the evidence line.
_NOT_A_SEARCH_MODEL = ("asknews/", "smart-searcher")
_NO_RESEARCH = ("", "none", "no_research")


def from_search_model(researcher_name: str | None) -> bool:
    """Whether the template's research comes from a search model, which gets our evidence line."""
    name = (researcher_name or "").strip()
    if name.lower() in _NO_RESEARCH:
        return False
    return not name.startswith(_NOT_A_SEARCH_MODEL)


def newest_evidence_date(text: str | None) -> date | None:
    """The date on the last evidence line; None when it is missing, "unknown" or not a date."""
    matches = _EVIDENCE.findall(text or "")
    if not matches:
        return None
    try:
        return date.fromisoformat(matches[-1])
    except ValueError:  # "unknown", or digits that are not a calendar date
        return None


def age_in_days(newest: date | None, today: date) -> int | None:
    """Days between the newest evidence and today; None when unknown or dated in the future.

    One day ahead is read as today: the search model may be in a later time zone.
    """
    if newest is None:
        return None
    days = (today - newest).days
    if days < -1:
        return None
    return max(days, 0)


def needs_retry(
    age_days: int | None, max_age_days: int, *, from_search: bool, already_retried: bool
) -> bool:
    """One more search runs when the search model's evidence is undated or too old."""
    if not from_search or already_retried:
        return False
    return age_days is None or age_days > max_age_days


def retry_since(newest: date | None, today: date, max_age_days: int) -> date:
    """The date from which the retry asks for developments."""
    if age_in_days(newest, today) is None:
        return today - timedelta(days=max_age_days)
    return min(newest, today)


def newest_of(*dates: date | None) -> date | None:
    known = [value for value in dates if value is not None]
    return max(known) if known else None


def extract_urls(text: str | None) -> list[str]:
    """Web addresses in a text, in order of first appearance, without duplicates."""
    found: list[str] = []
    for match in _URL.findall(text or ""):
        url = match.rstrip(_TRAILING)
        if url not in found:
            found.append(url)
    return found


def domain_of(url: str) -> str | None:
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def domains(urls: list[str]) -> list[str]:
    """The distinct domains of the addresses, in order of first appearance."""
    found: list[str] = []
    for url in urls:
        domain = domain_of(url)
        if domain and domain not in found:
            found.append(domain)
    return found


def without_query(url: str) -> str:
    """The address up to its path. Query strings can carry tokens and run logs are public."""
    return re.split(r"[?#]", url, maxsplit=1)[0]


def blocked_among(found_domains: list[str], blocked: tuple[str, ...]) -> list[str]:
    """The found domains that are a blocked domain or one of its subdomains."""
    block = [entry.lower().lstrip(".") for entry in blocked if entry]
    return [
        domain
        for domain in found_domains
        if any(domain == entry or domain.endswith("." + entry) for entry in block)
    ]
