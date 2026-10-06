"""Forecasting rules added to the template's prompts.

Each rule answers a failure that another entrant measured on resolved questions
(No-Stream/nostreambot-metaculus-bot, docs/prompts.md), restated in our own words. A rule is
stated once, with its reason, because that entrant found models follow a reasoned rule better
than a repeated one.
"""

from datetime import datetime, timezone
from typing import Literal

QuestionKind = Literal["binary", "multiple_choice", "numeric", "date", "other"]

COMMON_RULES = """\
Rules for this forecast, each with its reason:
- Only events inside the question's window count, because the question is settled on what happens in that window. Check that each fact you rely on falls inside it.
- A target date that someone announced is not a deadline unless something binds them to it. Announced dates slip often, so estimate separately how likely the event is to land inside the window.
- When you use a rate (events per month, a yearly frequency), apply it to the time that is left, and count the time already passed without the event as evidence.
- A search that found nothing means "not found", not "did not happen". Weigh it by how well the source would have covered the event.
- Name the exact figure, series or page that settles the question, and its variants (seasonally adjusted or not, preliminary or final). A nearby figure that looks plausible settles nothing.
- For each dated claim in the research, note its publication date, and prefer the newest relevant fact when two disagree.
- If your final number moves far from what your base rate or computation gave, name the one specific piece of evidence that justifies the move."""

BINARY_RULES = """\
- A price from a prediction market on the same event is strong evidence when the market is liquid; a market on a different threshold or date must be translated, not copied."""

MULTIPLE_CHOICE_RULES = """\
- Give every option at least 1%, because an option at zero costs heavily if it happens. Write probabilities as decimals or percentages that sum to 100%, using the option names exactly as given."""

NUMERIC_RULES = """\
- First decide whether the quantity is predictable or moves like a random walk. For a random walk, centre on the latest value and take the width from how much it has moved over a span as long as the time left.
- Do not stack several percentiles on a bound that the question allows to be exceeded. If you believe the outcome can fall beyond it, give values beyond it.
- Give your answer in the question's units."""

_RULES_BY_KIND: dict[str, str] = {
    "binary": BINARY_RULES,
    "multiple_choice": MULTIPLE_CHOICE_RULES,
    "numeric": NUMERIC_RULES,
    "date": NUMERIC_RULES,
}


def rules_for(kind: QuestionKind) -> str:
    """The rule block for one kind of question."""
    extra = _RULES_BY_KIND.get(kind)
    return COMMON_RULES if extra is None else f"{COMMON_RULES}\n{extra}"


def _iso(moment: datetime | None) -> str:
    if moment is None:
        return "not stated"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def window_block(
    open_time: datetime | None,
    close_time: datetime | None,
    resolve_time: datetime | None,
    now: datetime | None = None,
) -> str:
    """The question's dates, so the models reason about the right window."""
    now = now or datetime.now(timezone.utc)
    return (
        "## Question window\n"
        f"Now: {_iso(now)}. Question opened: {_iso(open_time)}. "
        f"Forecasting closes: {_iso(close_time)}. Scheduled to resolve: {_iso(resolve_time)}."
    )
