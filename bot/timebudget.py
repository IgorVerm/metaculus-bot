"""Decide how much of the pipeline a question gets, from the time left until it closes."""

from datetime import datetime, timezone
from typing import Literal

from bot import config

Plan = Literal["full", "fast", "skip"]


def seconds_until(close_time: datetime | None, now: datetime | None = None) -> float | None:
    """Seconds from now until close_time; None when the close time is unknown."""
    if close_time is None:
        return None
    now = now or datetime.now(timezone.utc)
    if close_time.tzinfo is None:
        close_time = close_time.replace(tzinfo=timezone.utc)
    return (close_time - now).total_seconds()


def plan_for(seconds_to_close: float | None) -> Plan:
    """An unknown close time gets the full pipeline: forfeiting a question costs more than a late try."""
    if seconds_to_close is None:
        return "full"
    if seconds_to_close < config.SKIP_BELOW_SECONDS:
        return "skip"
    if seconds_to_close < config.FULL_PIPELINE_MIN_SECONDS:
        return "fast"
    return "full"
