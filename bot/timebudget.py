"""Decide whether a question still has time for a forecast before it closes."""

from datetime import datetime, timezone

from bot import config


def seconds_until(close_time: datetime | None, now: datetime | None = None) -> float | None:
    """Seconds from now until close_time; None when the close time is unknown."""
    if close_time is None:
        return None
    now = now or datetime.now(timezone.utc)
    if close_time.tzinfo is None:
        close_time = close_time.replace(tzinfo=timezone.utc)
    return (close_time - now).total_seconds()


def too_late(seconds_to_close: float | None) -> bool:
    """An unknown close time is not too late: forfeiting a question costs more than a late try."""
    return seconds_to_close is not None and seconds_to_close < config.SKIP_BELOW_SECONDS
