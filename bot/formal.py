"""The consistency checker: does a model's set of answers obey the rules of probability?

A model writes a question's resolution criteria as a statement over events it named itself
("A and (B or not C)") and gives each event a probability. From those probabilities alone the
statement's probability must lie in a range, whatever the dependence between the events. An
answer outside that range contradicts the model's own event probabilities.

The statement is read by the parser below, over a fixed set of tokens. It is never evaluated
as code, and anything outside the token set is refused.

The checker only reports. It never changes an answer.
"""

import re
from dataclasses import dataclass, field

LABELS = ("A", "B", "C", "D", "E", "F")
MAX_STATEMENT_TOKENS = 200  # a statement over six events never needs more
EPSILON = 1e-9  # "more than the tolerance" must not fire on float noise at the boundary

_TOKEN = re.compile(r"\s*(\(|\)|[A-Za-z]+)")


class StatementError(ValueError):
    """The statement, or the events it refers to, cannot be used by the checker."""


# --- parser: statement text -> tree of ("var", label) | ("not", tree) | ("and"|"or", [trees]) ---


def tokenize(statement: str) -> list[str]:
    """Split into the tokens "(", ")", "and", "or", "not" and the labels A to F; refuse the rest."""
    if not isinstance(statement, str):
        raise StatementError("the statement is not text")
    tokens: list[str] = []
    position = 0
    text = statement.rstrip()
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            raise StatementError(f"character not allowed at position {position + 1}")
        word = match.group(1)
        position = match.end()
        if word in ("(", ")") or word in LABELS:
            tokens.append(word)
        elif word.lower() in ("and", "or", "not"):
            tokens.append(word.lower())
        else:
            raise StatementError(f"word not allowed: {word[:20]}")
        if len(tokens) > MAX_STATEMENT_TOKENS:
            raise StatementError("the statement is too long")
    if not tokens:
        raise StatementError("the statement is empty")
    return tokens


class _Parser:
    """or_part := and_part ("or" and_part)*; and_part := not_part ("and" not_part)*;
    not_part := "not" not_part | label | "(" or_part ")"."""

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.position = 0

    def peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self) -> str:
        token = self.peek()
        if token is None:
            raise StatementError("the statement ends too early")
        self.position += 1
        return token

    def or_part(self):
        parts = [self.and_part()]
        while self.peek() == "or":
            self.take()
            parts.append(self.and_part())
        return parts[0] if len(parts) == 1 else ("or", parts)

    def and_part(self):
        parts = [self.not_part()]
        while self.peek() == "and":
            self.take()
            parts.append(self.not_part())
        return parts[0] if len(parts) == 1 else ("and", parts)

    def not_part(self):
        token = self.take()
        if token == "not":
            return ("not", self.not_part())
        if token == "(":
            inner = self.or_part()
            if self.take() != ")":
                raise StatementError("a bracket is not closed")
            return inner
        if token in LABELS:
            return ("var", token)
        raise StatementError(f"unexpected '{token}'")


def parse(statement: str):
    """Parse a statement into a tree. Raises StatementError for anything outside the grammar."""
    parser = _Parser(tokenize(statement))
    tree = parser.or_part()
    if parser.peek() is not None:
        raise StatementError(f"unexpected '{parser.peek()}'")
    return tree


def labels_in(tree) -> set[str]:
    kind = tree[0]
    if kind == "var":
        return {tree[1]}
    if kind == "not":
        return labels_in(tree[1])
    found: set[str] = set()
    for part in tree[1]:
        found |= labels_in(part)
    return found


def evaluate(tree, truth: dict[str, bool]) -> bool:
    """Truth value of the statement for one assignment of the events (used by the tests)."""
    kind = tree[0]
    if kind == "var":
        return truth[tree[1]]
    if kind == "not":
        return not evaluate(tree[1], truth)
    if kind == "and":
        return all(evaluate(part, truth) for part in tree[1])
    return any(evaluate(part, truth) for part in tree[1])


# --- bounds ---


def bounds(tree, probabilities: dict[str, float]) -> tuple[float, float]:
    """Lowest and highest probability the statement can have, given only each event's probability.

    Applied bottom-up; each rule holds for any dependence between its parts:
    not -> [1 - u, 1 - l]; and of k parts -> [max(0, sum(l) - (k - 1)), min(u)];
    or of k parts -> [max(l), min(1, sum(u))].
    """
    kind = tree[0]
    if kind == "var":
        if tree[1] not in probabilities:
            raise StatementError(f"event {tree[1]} has no probability")
        value = probabilities[tree[1]]
        return (value, value)
    if kind == "not":
        low, high = bounds(tree[1], probabilities)
        return (1.0 - high, 1.0 - low)
    parts = [bounds(part, probabilities) for part in tree[1]]
    lows = [low for low, _ in parts]
    highs = [high for _, high in parts]
    if kind == "and":
        return (max(0.0, sum(lows) - (len(parts) - 1)), min(highs))
    return (max(lows), min(1.0, sum(highs)))


def _is_probability(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 <= value <= 1.0


def check_events(events: dict[str, float], max_events: int) -> None:
    """Refuse event sets the checker cannot use."""
    if not events:
        raise StatementError("no events were named")
    if len(events) > max_events:
        raise StatementError(f"more than {max_events} events were named")
    for label, value in events.items():
        if label not in LABELS:
            raise StatementError(f"event label not allowed: {str(label)[:20]}")
        if not _is_probability(value):
            raise StatementError(f"event {label} has no probability between 0 and 1")


def events_from_pairs(pairs) -> dict[str, float]:
    """{label: probability} from (label, probability) pairs; refuses a label given twice."""
    events: dict[str, float] = {}
    for label, value in pairs:
        label = str(label).strip().upper()
        if label in events:
            raise StatementError(f"event label used twice: {label[:20]}")
        events[label] = value
    return events


def statement_range(
    statement: str, events: dict[str, float], max_events: int
) -> tuple[float, float]:
    """The range for a statement written by a model, or StatementError when it cannot be used."""
    check_events(events, max_events)
    tree = parse(statement)
    missing = sorted(labels_in(tree) - set(events))
    if missing:
        raise StatementError(f"the statement uses events that were not named: {', '.join(missing)}")
    return bounds(tree, events)


# --- contradiction tests ---


@dataclass
class Consistency:
    """What the checker found for one model on one question."""

    value_range: tuple[float, float] | None = None  # None when no range could be computed
    findings: list[str] = field(default_factory=list)  # contradictions, in plain words
    skipped: list[str] = field(default_factory=list)  # checks that could not run, and why

    @property
    def contradicted(self) -> bool:
        return bool(self.findings)


def percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def outside_range(value: float, value_range: tuple[float, float], tolerance: float) -> bool:
    low, high = value_range
    return value < low - tolerance - EPSILON or value > high + tolerance + EPSILON


def differ(first: float, second: float, tolerance: float) -> bool:
    return abs(first - second) > tolerance + EPSILON


def split_implied(event_probability: float, if_yes: float, if_no: float) -> float:
    """The overall probability a conditional split implies (law of total probability)."""
    return event_probability * if_yes + (1.0 - event_probability) * if_no


def check_binary(
    direct: float | None,
    reversed_converted: float | None,
    structured: dict | None,
    *,
    range_tolerance: float,
    pair_tolerance: float,
    max_events: int,
) -> Consistency:
    """Check one model's answers to a yes/no question. Every answer is a probability of Yes.

    structured is None when that framing gave no answer, otherwise a dict with
    "events" (a list of (label, probability) pairs), "statement" (text), "overall"
    (probability) and "split" (None or {"event": label, "if_yes": p, "if_no": p}).
    A missing answer skips the tests that need it; nothing here raises on model output.
    """
    result = Consistency()
    overall = None
    events: dict[str, float] = {}

    if structured is None:
        result.skipped.append("no structured answer, so no range")
    else:
        overall = structured.get("overall")
        if not _is_probability(overall):
            overall = None
            result.skipped.append("the structured answer has no usable overall probability")
        try:
            events = events_from_pairs(structured.get("events") or [])
            result.value_range = statement_range(structured.get("statement"), events, max_events)
        except (StatementError, TypeError, ValueError) as error:
            result.skipped.append(f"no range: {error}")

    if result.value_range is not None:
        low, high = result.value_range
        named = (
            ("direct answer", direct),
            ("reversed answer, converted to a probability of Yes,", reversed_converted),
            ("overall answer in the structured framing", overall),
        )
        for name, value in named:
            if value is not None and outside_range(value, result.value_range, range_tolerance):
                result.findings.append(
                    f"Your {name} is {percent(value)}, but the probabilities you gave for your own "
                    f"events allow the statement \"{structured['statement'].strip()}\" only a "
                    f"probability between {percent(low)} and {percent(high)}."
                )

    if direct is not None and reversed_converted is not None:
        if differ(direct, reversed_converted, pair_tolerance):
            result.findings.append(
                f"Asked for the probability of Yes you answered {percent(direct)}. Asked for the "
                f"probability of No you answered {percent(1.0 - reversed_converted)}, which means "
                f"{percent(reversed_converted)} for Yes. These two must be the same number."
            )

    split = structured.get("split") if structured else None
    if split is not None and overall is not None:
        label = str(split.get("event")).strip().upper()
        event_probability = events.get(label)
        if_yes, if_no = split.get("if_yes"), split.get("if_no")
        if all(_is_probability(value) for value in (event_probability, if_yes, if_no)):
            implied = split_implied(event_probability, if_yes, if_no)
            if differ(implied, overall, range_tolerance):
                result.findings.append(
                    f"You gave event {label} a probability of {percent(event_probability)}, and "
                    f"answered {percent(if_yes)} if it happens and {percent(if_no)} if it does "
                    f"not. Together these give {percent(implied)}, but your overall answer in "
                    f"the structured framing is {percent(overall)}."
                )
        else:
            result.skipped.append("the conditional split is incomplete or names an unknown event")

    return result


def check_multiple_choice(
    direct: dict[str, float] | None,
    reversed_converted: dict[str, float] | None,
    *,
    pair_tolerance: float,
    sum_tolerance: float,
) -> Consistency:
    """Check one model's answers to a multiple-choice question.

    Both arguments map option name to the probability that the option is the outcome;
    reversed_converted is 1 - "probability that it is not the outcome", before any rescaling.
    """
    result = Consistency()
    if reversed_converted is None:
        result.skipped.append("no reversed answer")
        return result

    total = sum(reversed_converted.values())
    if differ(total, 1.0, sum_tolerance):
        result.findings.append(
            "Exactly one option will be the outcome, so the probabilities must add up to 100%. "
            "Your answers to \"what is the probability that this option is not the outcome\" "
            f"give probabilities that add up to {percent(total)}."
        )

    if direct is None:
        result.skipped.append("no direct answer to compare with")
        return result
    for option, converted in reversed_converted.items():
        if option not in direct:
            result.skipped.append(f"option missing from the direct answer: {option[:40]}")
            continue
        if differ(direct[option], converted, pair_tolerance):
            result.findings.append(
                f"For option \"{option}\" you answered {percent(direct[option])} when asked "
                f"for its probability, and {percent(1.0 - converted)} when asked for the "
                f"probability that it is not the outcome, which means {percent(converted)}."
            )
    return result


def describe(findings: list[str]) -> str:
    """The contradictions as a numbered list for the second-look prompt."""
    return "\n".join(f"{number}. {finding}" for number, finding in enumerate(findings, start=1))
