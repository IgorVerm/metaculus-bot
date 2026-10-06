"""Give each concurrent forecast of a question its own model.

The framework starts one forecast task per slot and asks for "the default model" inside each.
A context variable carries the slot's model through that task, so tasks running side by side
never see each other's model.
"""

from contextvars import ContextVar
from typing import Any

_active_model: ContextVar[Any | None] = ContextVar("active_forecaster_model", default=None)


class SlotAssigner:
    """Hands out slot numbers 0, 1, 2, ... per question, wrapping around the line-up size."""

    def __init__(self) -> None:
        self._next: dict[Any, int] = {}

    def take(self, question_key: Any, lineup_size: int) -> int:
        # No await between read and write, so two tasks can never take the same slot.
        index = self._next.get(question_key, 0)
        self._next[question_key] = index + 1
        return index % lineup_size

    def forget(self, question_key: Any) -> None:
        self._next.pop(question_key, None)


def active_model() -> Any | None:
    """The model bound to the current task, or None outside a forecast task."""
    return _active_model.get()


def bind_model(model: Any):
    """Bind a model to the current task; pass the returned token to release()."""
    return _active_model.set(model)


def release(token) -> None:
    _active_model.reset(token)
