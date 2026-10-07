"""The one place for model names and thresholds.

Model names are checked against the live OpenRouter list (https://openrouter.ai/api/v1/models)
before a line-up change; last checked 2026-10-06.
"""

# Tournaments, by the name in their Metaculus address. The framework's own "current
# tournament" constant lags a season in the pinned version, so the names are stated here.
# Update MAIN_TOURNAMENT at the start of each season (January, May, September).
MAIN_TOURNAMENT = "fall-futureeval-2026"
MINIBENCH_TOURNAMENT = "minibench"
TEST_TOURNAMENT = "bot-testing-area"

# The two models of our method: one OpenAI, one Anthropic, both at high effort (no Google
# model: DESIGN_DECISIONS.md). "reasoning" is passed through to the provider. When credit runs
# low the first model works alone.
FORECASTERS: tuple[dict, ...] = (
    {"model": "openrouter/openai/gpt-6.1-sol", "reasoning": {"effort": "high"}},
    {"model": "openrouter/anthropic/claude-opus-5.5", "reasoning": {"effort": "high"}},
)

# Yes/no and multiple-choice questions: every model answers in each of these framings
# (bot/framings.py). The published forecast combines all answers.
FRAMINGS: dict[str, tuple[str, ...]] = {
    "binary": ("direct", "reversed", "structured"),
    "multiple_choice": ("direct", "reversed"),
}

# Every other question type: three plain forecasts, by position in FORECASTERS, so the first
# vendor answers twice, independently. The published forecast is their median.
PLAIN_FORECAST_SLOTS: tuple[int, ...] = (0, 1, 0)

# The consistency check (bot/formal.py). A model contradicts itself when an answer lies outside
# the range its own event probabilities allow by more than RANGE_TOLERANCE (also used for the
# conditional split), when its direct and converted reversed answers differ by more than
# PAIR_TOLERANCE, or when its converted reversed multiple-choice answers miss a sum of 1 by
# more than SUM_TOLERANCE. Our own first settings; adjust from measured contradiction rates.
RANGE_TOLERANCE = 0.05
PAIR_TOLERANCE = 0.10
SUM_TOLERANCE = 0.15
MAX_EVENTS = 6

# Published answers stay inside these, as in the template.
MIN_PROBABILITY = 0.01
MAX_PROBABILITY = 0.99
MIN_OPTION_PROBABILITY = 0.01

FORECASTER_TIMEOUT_SECONDS = 480
FORECASTER_TRIES = 2
# Output cap per call ("max_tokens"). Reasoning tokens count against it, so it stays generous:
# a cap that binds returns an empty answer.
FORECASTER_MAX_OUTPUT_TOKENS = 12000

# Turns a model's free-text answer into structured values. A cheap model saturates this job.
PARSER_MODEL = "openrouter/openai/gpt-6-luna"
SUMMARIZER_MODEL = "openrouter/openai/gpt-6-luna"
HELPER_MAX_OUTPUT_TOKENS = 4000  # output cap per call of the parser and the summarizer
PARSER_TRIES = 2
# How the template and the framework call the parser (main.py and structure_output in the
# pinned framework): samples per answer, and tries per sample when the format is wrong.
TEMPLATE_PARSER_SAMPLES = 2
STRUCTURE_OUTPUT_TRIES = 3

# The search model: a cheap model with its vendor's own web search, through the ":online"
# suffix. It answers our own research requests (the reversed and structured framings and the
# freshness retry) and is the template's research source when AskNews is not available. The
# donated key serves only OpenAI, Anthropic and Google models; ours is OpenAI or Anthropic.
SEARCH_MODEL = "openrouter/openai/gpt-6-luna:online"
SEARCH_TIMEOUT_SECONDS = 300
SEARCH_TRIES = 2
SEARCH_MAX_OUTPUT_TOKENS = 6000  # output cap per call

# The template's research. AskNews is free for tournament entrants once granted (1,000 calls a
# month, 4,000 for the tournament; the template's news search uses six calls per question).
# Without its credentials the search model does it. BOT_RESEARCHER overrides both.
RESEARCHER_WITH_ASKNEWS = "asknews/news-summaries"
RESEARCHER_WITHOUT_ASKNEWS = SEARCH_MODEL
RESEARCHER_ENV = "BOT_RESEARCHER"

# Research from a search model whose newest evidence is older than this, or undated, gets one
# more search for the newest developments.
FRESHNESS_MAX_AGE_DAYS = 7

# Domains the research requests name as not to be relied on. Starts empty.
BLOCKED_DOMAINS: tuple[str, ...] = ()

# The published comment shows at most this many characters of each framing's research; the
# forecasters read all of it. SOURCES log lines list at most MAX_LOGGED_SOURCES addresses.
RESEARCH_CHARS_IN_COMMENT = 3000
MAX_LOGGED_SOURCES = 60

# Limits (bot/limits.py). A research text is cut to RESEARCH_MAX_CHARS before it goes into a
# prompt (the freshness retry's part of it to RESEARCH_RETRY_MAX_CHARS); each of a model's own
# answers quoted back to it in a second look is cut to QUOTED_ANSWER_MAX_CHARS. A run answers at
# most MAX_QUESTIONS_PER_RUN questions; the rest stay unforecast and the next run takes them.
RESEARCH_MAX_CHARS = 16000
RESEARCH_RETRY_MAX_CHARS = 5000
QUOTED_ANSWER_MAX_CHARS = 4000
# A conditional question is forecast in parts, and the template appends each earlier part's
# forecast and reasoning to the research of the later ones. Each appended reasoning is cut to
# APPENDED_REASONING_MAX_CHARS; APPENDED_FRAME_CHARS allows for the template's text around it
# and the forecast value. At most CONDITIONAL_PARTS - 1 parts are appended.
APPENDED_REASONING_MAX_CHARS = 4000
APPENDED_FRAME_CHARS = 2000
CONDITIONAL_PARTS = 4
MAX_QUESTIONS_PER_RUN = 5

# The bound on a run's cost (limits.worst_case_run_cost_usd). List prices in US dollars per
# million tokens, (input, output), checked 2026-10-06. A test fails when the bound for a run of
# any kind of question exceeds the ceiling.
PRICES_USD_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    "openrouter/openai/gpt-6.1-sol": (2.0, 10.0),
    "openrouter/anthropic/claude-opus-5.5": (4.0, 20.0),
    "openrouter/openai/gpt-6-luna": (0.10, 0.50),
}
CHARS_PER_TOKEN = 4
PROMPT_ALLOWANCE_TOKENS = 3000  # the question and our instructions, per call
RUN_COST_CEILING_USD = 25.0

# Donated credit left on the OpenRouter key, in US dollars.
FULL_LINEUP_MIN_USD = 5.0  # below this, forecast with the first model only
STOP_BELOW_USD = 1.0  # below this, publish nothing and fail the run

# A question closing sooner than this is skipped: the forecast could not land in time.
# Our own estimate of one question's run time; measure it on the first runs and adjust.
SKIP_BELOW_SECONDS = 300

# A run that does not publish forecasts at most this many questions unless told otherwise,
# because unpublished questions stay "open" and would be forecast again on every run.
DRY_RUN_DEFAULT_MAX_QUESTIONS = 3
