"""Which research sources the bot accepts.

The framework publishes the settings of every model object it holds with each forecast's
comment. For some routes (a name starting with "metaculus/" or "exa/") it puts a credential
into those settings. So only the routes below are accepted, and a refused name stops the run.
"""

OPENROUTER_PREFIX = "openrouter/"
ASKNEWS_PREFIX = "asknews/"
NO_RESEARCH = "no_research"

ALLOWED_FORMS = (
    f'a name starting with "{OPENROUTER_PREFIX}" or "{ASKNEWS_PREFIX}", or exactly "{NO_RESEARCH}"'
)


def allowed(name: str | None) -> bool:
    """Whether a researcher name may be used. Exact prefixes; nothing is trimmed or lowered."""
    if not isinstance(name, str):
        return False
    return name == NO_RESEARCH or name.startswith((OPENROUTER_PREFIX, ASKNEWS_PREFIX))


def is_openrouter_model(name: str | None) -> bool:
    """Whether the name is a model reached through OpenRouter, built as a model object by us."""
    return isinstance(name, str) and name.startswith(OPENROUTER_PREFIX)
