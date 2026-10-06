"""Read how much donated credit is left on the OpenRouter key and pick the line-up to match."""

import json
import urllib.request
from typing import Callable, Literal

from bot import config

Lineup = Literal["full", "single", "stop"]

KEY_STATUS_URL = "https://openrouter.ai/api/v1/key"


def remaining_from_payload(payload: dict) -> float | None:
    """Dollars left according to OpenRouter's key-status reply; None when the key has no limit."""
    data = payload.get("data") or {}
    remaining = data.get("limit_remaining")
    if remaining is None:
        limit, usage = data.get("limit"), data.get("usage")
        if limit is None or usage is None:
            return None
        remaining = limit - usage
    return float(remaining)


def decide(remaining_usd: float | None) -> Lineup:
    """An unknown balance keeps the full line-up: a failed status read must not forfeit questions."""
    if remaining_usd is None:
        return "full"
    if remaining_usd < config.STOP_BELOW_USD:
        return "stop"
    if remaining_usd < config.FULL_LINEUP_MIN_USD:
        return "single"
    return "full"


def fetch_remaining(
    api_key: str,
    opener: Callable = urllib.request.urlopen,
    timeout: float = 15,
) -> float | None:
    """Ask OpenRouter for the key's balance. Any failure reads as unknown (None)."""
    request = urllib.request.Request(
        KEY_STATUS_URL, headers={"Authorization": f"Bearer {api_key}"}
    )
    try:
        with opener(request, timeout=timeout) as response:
            return remaining_from_payload(json.loads(response.read()))
    except Exception:  # noqa: BLE001 - network, HTTP and JSON errors all mean "unknown"
        return None
