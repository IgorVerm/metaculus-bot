"""The texts of our own framings, research requests and second looks, and the conversions.

A question is asked in several framings: directly (the template's prompt, not in this file),
reversed (the probability that it does not happen) and structured (events, a statement over
them and an overall answer). Answers in the reversed framing are converted back with 1 - q.

Every function takes plain text and numbers and returns text or numbers. Question text and
research are quoted into the prompts as material; they decide nothing in the code.
"""

from dataclasses import dataclass
from datetime import date

DIRECT = "direct"
REVERSED = "reversed"
STRUCTURED = "structured"

# First line of each prompt. The tests with stand-in models recognise a prompt by it.
REVERSED_TITLE = "Task: estimate the probability that this question resolves NO."
STRUCTURED_TITLE = "Task: break this question into events and estimate each one."
REVERSED_OPTIONS_TITLE = "Task: for each option, estimate the probability that it is NOT the outcome"
SECOND_LOOK_TITLE = "Task: your earlier answers to this question contradict each other; answer again."
REVERSED_RESEARCH_TITLE = "Research task: find reasons and evidence that the outcome will NOT happen"
STRUCTURED_RESEARCH_TITLE = "Research task: report the status of what this question depends on."
FRESHNESS_RESEARCH_TITLE = "Research task: report only what has happened since a given date."


@dataclass(frozen=True)
class QuestionText:
    """The parts of a question that the prompts quote."""

    text: str
    background: str = ""
    criteria: str = ""
    fine_print: str = ""
    options: tuple[str, ...] = ()


def _or_none(value: str | None) -> str:
    return (value or "").strip() or "(none given)"


def _question_block(question: QuestionText) -> str:
    lines = [f"The question is:\n{question.text}"]
    if question.options:
        lines.append(f"The options are: {list(question.options)}")
    lines.append(f"Question background:\n{_or_none(question.background)}")
    lines.append(
        "The outcome is determined by the criteria below. They have not been satisfied yet:\n"
        f"{_or_none(question.criteria)}\n\n{(question.fine_print or '').strip()}".rstrip()
    )
    return "\n\n".join(lines)


def _show(day: date | None) -> str:
    return day.isoformat() if day else "not stated"


# --- conversions ---


def complement(probability: float) -> float:
    """A probability that something does not happen, as the probability that it does."""
    return 1.0 - probability


def clamp(probability: float, low: float, high: float) -> float:
    return max(low, min(high, probability))


def _key(name: str) -> str:
    return " ".join(str(name).split()).casefold()


def match_options(answer: dict[str, float], options: list[str]) -> dict[str, float]:
    """Re-key an answer by the question's own option names; refuse a missing or unknown option."""
    by_key = {}
    for name, value in answer.items():
        if _key(name) in by_key:
            raise ValueError("an option was answered twice")
        by_key[_key(name)] = value
    if set(by_key) != {_key(option) for option in options} or len(by_key) != len(options):
        raise ValueError("the answer does not cover exactly the question's options")
    return {option: by_key[_key(option)] for option in options}


def convert_reversed_options(not_outcome: dict[str, float], options: list[str]) -> dict[str, float]:
    """1 - q per option, keyed and ordered by the question's options. Not rescaled."""
    matched = match_options(not_outcome, options)
    for value in matched.values():
        if not 0.0 <= value <= 1.0:
            raise ValueError("a probability is not between 0 and 1")
    return {option: complement(value) for option, value in matched.items()}


def rescale(probabilities: dict[str, float]) -> dict[str, float]:
    """Scale a set of option probabilities so that it sums to 1."""
    total = sum(probabilities.values())
    if total <= 0:
        raise ValueError("the probabilities sum to zero")
    return {option: value / total for option, value in probabilities.items()}


def floor_and_renormalise(probabilities: dict[str, float], floor: float) -> dict[str, float]:
    """Sum to 1 with every option at the floor or above.

    Options under the floor are set to it and the others share what is left in proportion;
    repeated until no option is under the floor.
    """
    if len(probabilities) * floor > 1.0:
        raise ValueError("too many options for this floor")
    values = rescale(probabilities)
    floored: set[str] = set()
    while True:
        under = {name for name, value in values.items() if name not in floored and value < floor}
        if not under:
            return values
        floored |= under
        free_total = sum(value for name, value in values.items() if name not in floored)
        left = 1.0 - floor * len(floored)
        values = {
            name: floor if name in floored else value / free_total * left
            for name, value in values.items()
        }


# --- research ---


def dates_block(
    today: date, open_day: date | None, close_day: date | None, resolve_day: date | None
) -> str:
    return (
        f"Dates. Today: {today.isoformat()}. Question opened: {_show(open_day)}. "
        f"Question closes for forecasts: {_show(close_day)}. "
        f"Scheduled resolution: {_show(resolve_day)}."
    )


def age_note(newest: date | None, age_days: int | None) -> str:
    """One line that tells the forecaster how old the newest evidence in the research is."""
    if newest is None or age_days is None:
        return (
            "Age of this research: the date of its newest evidence is unknown. "
            "It may miss recent developments."
        )
    unit = "day" if age_days == 1 else "days"
    return (
        f"Age of this research: its newest evidence is dated {newest.isoformat()}, "
        f"{age_days} {unit} before today."
    )


def research_requirements(
    today: date, close_day: date | None, blocked_domains: tuple[str, ...]
) -> str:
    """What every request to a search model asks for, whatever its subject."""
    lines = [
        f"Today is {today.isoformat()}. The question closes on {_show(close_day)}.",
        "Requirements for your answer:",
        "- Report the newest developments first.",
        "- Give each claim with its source (the web address) and the source's publication date.",
        "- Consult the site that the resolution criteria name as the source of the outcome, "
        "if they name one, and report what it shows now.",
    ]
    if blocked_domains:
        lines.append("- Do not rely on these sites: " + ", ".join(blocked_domains) + ".")
    lines += [
        "- Do not produce a forecast yourself.",
        "- End with one line of exactly this form, giving the publication date of the newest "
        "evidence you found: NEWEST_EVIDENCE_DATE: YYYY-MM-DD "
        "(write NEWEST_EVIDENCE_DATE: unknown if you cannot date any of it).",
    ]
    return "\n".join(lines)


def _research_request(title: str, task: str, question: QuestionText, requirements: str) -> str:
    return f"{title}\n\n{task}\n\n{_question_block(question)}\n\n{requirements}"


def reversed_research_request(question: QuestionText, requirements: str) -> str:
    if question.options:
        task = (
            "You assist a forecaster. For each option of the question below, find the "
            "strongest reasons and evidence that this option will NOT be the outcome."
        )
    else:
        task = (
            "You assist a forecaster. Find the strongest reasons and evidence that the question "
            "below will resolve No: what stands in the way, what would have to happen first and "
            "has not, and how often comparable things failed to happen."
        )
    return _research_request(REVERSED_RESEARCH_TITLE, task, question, requirements)


def structured_research_request(question: QuestionText, requirements: str) -> str:
    task = (
        "You assist a forecaster. Name the separate things the outcome of the question below "
        "depends on (decisions, events, thresholds, deadlines) and report the current status of "
        "each: what has already happened, what is scheduled, and what is still open."
    )
    return _research_request(STRUCTURED_RESEARCH_TITLE, task, question, requirements)


def freshness_research_request(question: QuestionText, since: date, requirements: str) -> str:
    task = (
        f"You assist a forecaster. Report only developments since {since.isoformat()} that bear "
        "on the question below. If there are none, say so."
    )
    return _research_request(FRESHNESS_RESEARCH_TITLE, task, question, requirements)


def join_research(first: str, retry: str) -> str:
    return f"{first.rstrip()}\n\nLater search, for the newest developments only:\n{retry.strip()}"


def for_forecaster(dates: str, note: str, research: str) -> str:
    """The research text a forecaster reads: dates, age of the evidence, then the research."""
    head = "\n".join(line for line in (dates, note) if line)
    return f"{head}\n\n{research.strip() or '(no research available)'}"


def for_comment(research: str, max_chars: int) -> str:
    """Research as shown in the published comment: no heading marks, and capped in length."""
    lines = [
        line.lstrip("#").lstrip() if line.startswith("#") else line
        for line in research.splitlines()
    ]
    text = "\n".join(lines).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n[shortened here; the forecasters read the full text]"


# --- forecasting prompts of our own framings ---


def _research_block(research: str) -> str:
    return f"Your research assistant says:\n{research.strip() or '(no research available)'}"


def reversed_binary_prompt(question: QuestionText, research: str, today: date) -> str:
    return "\n\n".join(
        [
            REVERSED_TITLE,
            "You are a professional forecaster.",
            _question_block(question),
            _research_block(research),
            f"Today is {today.isoformat()}.",
            "Before answering you write:\n"
            "(a) The time left until the outcome is known.\n"
            "(b) What has to be true at the end for the question to resolve No.\n"
            "(c) The strongest reasons to expect No.\n"
            "(d) The strongest reasons to expect Yes.",
            "You are asked for the probability of No, not of Yes. The last thing you write is "
            'your final answer as: "Probability of No: ZZ%", 0-100',
        ]
    )


def structured_binary_prompt(
    question: QuestionText, research: str, today: date, max_events: int
) -> str:
    labels = "ABCDEF"[:max_events]
    return "\n\n".join(
        [
            STRUCTURED_TITLE,
            "You are a professional forecaster.",
            _question_block(question),
            _research_block(research),
            f"Today is {today.isoformat()}.",
            f"Work in these steps:\n"
            f"1. Name the events the outcome depends on: at least one and at most {max_events}, "
            f"labelled {', '.join(labels)} in order. Describe each precisely enough that it "
            "clearly happens or does not, and give each its probability. The events are "
            "separate factors: no event may contain another (if B can only happen when A has "
            "happened, B contains A), and no event may be the question itself in other words. "
            "Where the outcome needs a sequence of steps, describe each later step as what "
            "happens given that the earlier steps happened (\"if it reaches a vote, the vote "
            "passes\"), and give the probability of that.\n"
            "2. Write the resolution criteria as one statement over those labels that is true "
            "exactly when the question resolves Yes. Use only the labels, the words and, or, "
            "not, and brackets. Example: A and (B or not C). An event you described as \"if "
            "... happened\" may appear only joined by and to the events it depends on.\n"
            "3. Optionally give one conditional split: choose one of your events that is not "
            "described as \"if ... happened\" and give the "
            "probability of Yes if it happens and the probability of Yes if it does not.\n"
            "4. Give your overall probability that the question resolves Yes.",
            "The last thing you write is your final answer in exactly this form:\n"
            "EVENTS:\n"
            "A: <description> | probability: NN%\n"
            "B: <description> | probability: NN%\n"
            "STATEMENT: <statement over the labels>\n"
            "CONDITIONAL SPLIT: event <label> | if it happens: NN% | if it does not happen: NN%"
            "   (or: CONDITIONAL SPLIT: none)\n"
            "OVERALL PROBABILITY: NN%",
        ]
    )


def reversed_options_prompt(question: QuestionText, research: str, today: date) -> str:
    return "\n\n".join(
        [
            REVERSED_OPTIONS_TITLE,
            "You are a professional forecaster.",
            _question_block(question),
            _research_block(research),
            f"Today is {today.isoformat()}.",
            "Exactly one option will be the outcome. Take the options one at a time. For each, "
            "write the strongest reasons it will not be the outcome and the strongest reasons "
            "it will, then give the probability that it is NOT the outcome.",
            f"The last thing you write is your final answer for the options in this order "
            f"{list(question.options)} as:\n"
            "Option_A: probability that it is NOT the outcome: NN%\n"
            "Option_B: probability that it is NOT the outcome: NN%\n"
            "...",
        ]
    )


def second_look_binary_prompt(
    question: QuestionText, research: str, today: date, answers: str, contradictions: str
) -> str:
    return "\n\n".join(
        [
            SECOND_LOOK_TITLE,
            "You are a professional forecaster.",
            _question_block(question),
            _research_block(research),
            f"Today is {today.isoformat()}.",
            "You answered this question earlier in several forms. Your answers were:\n" + answers,
            "They contradict each other under the rules of probability:\n" + contradictions,
            "Work out which of your earlier numbers was wrong and why, then give one final "
            "answer. Do not simply average them.",
            'The last thing you write is your final answer as: "Probability: ZZ%", 0-100',
        ]
    )


def second_look_options_prompt(
    question: QuestionText, research: str, today: date, answers: str, contradictions: str
) -> str:
    return "\n\n".join(
        [
            SECOND_LOOK_TITLE,
            "You are a professional forecaster.",
            _question_block(question),
            _research_block(research),
            f"Today is {today.isoformat()}.",
            "You answered this question earlier in two forms. Your answers were:\n" + answers,
            "They contradict each other under the rules of probability:\n" + contradictions,
            "Work out which of your earlier numbers was wrong and why, then give one final set "
            "of probabilities that add up to 100%. Do not simply average them.",
            f"The last thing you write is your final probabilities for the options in this "
            f"order {list(question.options)} as:\n"
            "Option_A: Probability_A\n"
            "Option_B: Probability_B\n"
            "...\n"
            "Option_N: Probability_N",
        ]
    )


# --- parsing instructions for the model that turns an answer into numbers ---

REVERSED_PARSING = (
    "The text gives the probability that a yes/no question resolves NO. Return that stated "
    "probability of No as a decimal between 0 and 1. Do not convert it into a probability of Yes."
)
STRUCTURED_PARSING = (
    "The text ends with a list of events (label, description, probability), a statement over "
    "the labels, an optional conditional split and an overall probability. Return every "
    "probability as a decimal between 0 and 1 (35% becomes 0.35). Copy the statement exactly as "
    "written, without the word STATEMENT. If the conditional split is \"none\" or absent, leave "
    "it out. Do not add, drop or reword events."
)


def reversed_options_parsing(options: tuple[str, ...]) -> str:
    return (
        "The text gives, for each option, the probability that the option is NOT the outcome. "
        "Return those stated probabilities as decimals between 0 and 1, without converting them. "
        f"Every option name must be one of: {list(options)}. Remove a prefix such as \"Option\" "
        "if it is not part of those names. Do not skip an option."
    )


# --- plain-text lines shown to a model and in the comment ---


def percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def options_line(probabilities: dict[str, float]) -> str:
    return "; ".join(f"{option}: {percent(value)}" for option, value in probabilities.items())
