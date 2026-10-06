"""Hard limits on what one call and one run can consume, and the arithmetic that bounds a run.

Three limits, all set in bot/config.py: every model call has an output cap; every research
text and quoted answer is cut to a maximum length before it goes into a prompt; a run answers
at most a fixed number of questions. From these and the list prices, the functions at the end
compute the most a run can cost, and a test fails when a config change lifts it over the
ceiling.
"""

from bot import config

CUT_MARKER = "\n[cut here: the text was longer than the limit]"

BINARY = "binary"
MULTIPLE_CHOICE = "multiple_choice"
PLAIN = "plain"  # numeric, discrete and date questions
CONDITIONAL = "conditional"
KINDS = (BINARY, MULTIPLE_CHOICE, PLAIN, CONDITIONAL)


def cap_text(text: str | None, max_chars: int) -> str:
    """The text, cut to at most max_chars characters; a cut text ends with a marker saying so."""
    text = text or ""
    if len(text) <= max_chars:
        return text
    if max_chars <= len(CUT_MARKER):
        return text[: max(max_chars, 0)]
    return text[: max_chars - len(CUT_MARKER)] + CUT_MARKER


def split_for_run(items: list, per_run: int) -> tuple[list, list]:
    """The items this run takes, and those left for the next run."""
    per_run = max(per_run, 0)
    return items[:per_run], items[per_run:]


# --- the most a run can cost ---


def price_per_million(model_name: str) -> tuple[float, float]:
    """(input, output) list price in US dollars per million tokens; KeyError if not listed."""
    return config.PRICES_USD_PER_MILLION_TOKENS[model_name.removesuffix(":online")]


def call_cost_usd(model_name: str, input_tokens: float, output_tokens: float) -> float:
    price_in, price_out = price_per_million(model_name)
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def prompt_tokens(text_chars: int) -> float:
    """Most input tokens of a prompt that quotes text_chars characters of capped text."""
    return text_chars / config.CHARS_PER_TOKEN + config.PROMPT_ALLOWANCE_TOKENS


def worst_case_calls(kind: str) -> dict[str, int]:
    """Most calls one question can cause with the full line-up, before retries.

    "flagship" and "second_looks" are per model of the line-up for our method, and totals for
    the other kinds; "search" counts research requests and "parser" parser samples.
    """
    samples = config.TEMPLATE_PARSER_SAMPLES
    if kind in (BINARY, MULTIPLE_CHOICE):
        framing_names = config.FRAMINGS[kind]
        once = 1 if "structured" in framing_names else 0  # the structured answer: one sample
        models = len(config.FORECASTERS)
        return {
            "flagship": models * (len(framing_names) + 1),
            "second_looks": models,
            "search": len(framing_names) + 1,  # one per framing and the freshness retry
            "parser": models * (samples * (len(framing_names) + 1) - once),
        }
    forecasts = len(config.PLAIN_FORECAST_SLOTS)
    # A conditional question forecasts its parent, its child and both branches in each forecast.
    parts = 4 if kind == CONDITIONAL else 1
    if kind not in (PLAIN, CONDITIONAL):
        raise ValueError(f"unknown kind: {kind}")
    return {
        "flagship": forecasts * parts,
        "second_looks": 0,
        "search": 1,
        "parser": forecasts * parts * samples,
    }


def worst_case_question_cost_usd(kind: str = BINARY) -> float:
    """Upper bound in US dollars for one question, from the settings in bot/config.py alone.

    Every call is taken at its limits: the input is the research cap (four characters per
    token) plus an allowance for the question and the instructions, the output is the output
    cap, and every flagship and search call is attempted as often as its tries allow. A second
    look also quotes the model's answers and the contradictions, each at its cap. A parser
    sample reads a whole flagship answer and is attempted as often as the framework's and the
    parser model's tries allow.

    Not included, because they are not known: web-search fees, and the tokens of search
    results that a vendor adds to a search model's input. The bound assumes that the question
    with our instructions fits in the allowance, that the research source is the search model
    (AskNews costs no credit; another BOT_RESEARCHER model has another price), and list prices.
    """
    calls = worst_case_calls(kind)
    research_input = prompt_tokens(config.RESEARCH_MAX_CHARS)
    total = 0.0

    if kind in (BINARY, MULTIPLE_CHOICE):
        quoted = (len(config.FRAMINGS[kind]) + 1) * config.QUOTED_ANSWER_MAX_CHARS
        second_look_input = prompt_tokens(config.RESEARCH_MAX_CHARS + quoted)
        answers_per_model = len(config.FRAMINGS[kind])
        for spec in config.FORECASTERS:
            inputs = answers_per_model * research_input + second_look_input
            outputs = (answers_per_model + 1) * config.FORECASTER_MAX_OUTPUT_TOKENS
            total += config.FORECASTER_TRIES * call_cost_usd(spec["model"], inputs, outputs)
    else:
        per_forecast = calls["flagship"] // len(config.PLAIN_FORECAST_SLOTS)
        for slot in config.PLAIN_FORECAST_SLOTS:
            total += (
                per_forecast
                * config.FORECASTER_TRIES
                * call_cost_usd(
                    config.FORECASTERS[slot]["model"],
                    research_input,
                    config.FORECASTER_MAX_OUTPUT_TOKENS,
                )
            )

    total += (
        calls["search"]
        * config.SEARCH_TRIES
        * call_cost_usd(config.SEARCH_MODEL, research_input, config.SEARCH_MAX_OUTPUT_TOKENS)
    )
    parser_input = config.FORECASTER_MAX_OUTPUT_TOKENS + config.PROMPT_ALLOWANCE_TOKENS
    total += (
        calls["parser"]
        * config.STRUCTURE_OUTPUT_TRIES
        * config.PARSER_TRIES
        * call_cost_usd(config.PARSER_MODEL, parser_input, config.HELPER_MAX_OUTPUT_TOKENS)
    )
    return total


def worst_case_run_cost_usd(kind: str = BINARY) -> float:
    """Upper bound in US dollars for one run in which every question is of this kind.

    The default is a yes/no question, the most expensive kind our method answers; a
    conditional question, which the template forecasts in four parts, costs more. See
    worst_case_question_cost_usd for what is and is not included; web-search fees are not,
    because they are not known.
    """
    return config.MAX_QUESTIONS_PER_RUN * worst_case_question_cost_usd(kind)
