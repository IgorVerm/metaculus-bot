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

# Turns a model's free-text answer into structured values. A cheap model saturates this job.
PARSER_MODEL = "openrouter/openai/gpt-6-luna"
SUMMARIZER_MODEL = "openrouter/openai/gpt-6-luna"

# Research. AskNews is free for tournament entrants once granted (1,000 calls a month, 4,000
# for the tournament; the template's news search uses six calls per question). Without its
# credentials the bot uses a model with its vendor's own web search, through the ":online"
# suffix. The donated key serves only OpenAI, Anthropic and Google models, so the fallback
# must be one of those. BOT_RESEARCHER overrides both.
RESEARCHER_WITH_ASKNEWS = "asknews/news-summaries"
RESEARCHER_WITHOUT_ASKNEWS = "openrouter/openai/gpt-6.1-sol:online"
RESEARCHER_ENV = "BOT_RESEARCHER"

# The search model for our own research requests (the reversed and structured framings and the
# freshness retry): a cheap model with its vendor's web search. OpenAI or Anthropic only.
SEARCH_MODEL = "openrouter/openai/gpt-6-luna:online"
SEARCH_TIMEOUT_SECONDS = 300
SEARCH_TRIES = 2

# Research from a search model whose newest evidence is older than this, or undated, gets one
# more search for the newest developments.
FRESHNESS_MAX_AGE_DAYS = 7

# Domains the research requests name as not to be relied on. Starts empty.
BLOCKED_DOMAINS: tuple[str, ...] = ()

# The published comment shows at most this many characters of each framing's research; the
# forecasters read all of it. SOURCES log lines list at most MAX_LOGGED_SOURCES addresses.
RESEARCH_CHARS_IN_COMMENT = 3000
MAX_LOGGED_SOURCES = 60

# Donated credit left on the OpenRouter key, in US dollars.
FULL_LINEUP_MIN_USD = 5.0  # below this, forecast with the first model only
STOP_BELOW_USD = 1.0  # below this, publish nothing and fail the run

# A question closing sooner than this is skipped: the forecast could not land in time.
# Our own estimate of one question's run time; measure it on the first runs and adjust.
SKIP_BELOW_SECONDS = 300

# A run that does not publish forecasts at most this many questions unless told otherwise,
# because unpublished questions stay "open" and would be forecast again on every run.
DRY_RUN_DEFAULT_MAX_QUESTIONS = 3
