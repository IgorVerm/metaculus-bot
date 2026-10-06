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

# Three forecasts per question; the published forecast is their median. Two vendors, with a
# second, independent answer from the first (no Google model: DESIGN_DECISIONS.md).
# "reasoning" is passed through to the provider.
FORECASTERS: tuple[dict, ...] = (
    {"model": "openrouter/openai/gpt-6.1-sol", "reasoning": {"effort": "high"}},
    {"model": "openrouter/anthropic/claude-opus-5.5", "reasoning": {"effort": "high"}},
    {"model": "openrouter/openai/gpt-6.1-sol", "reasoning": {"effort": "high"}},
)
FORECASTER_TIMEOUT_SECONDS = 480
FORECASTER_TRIES = 2

# Turns a model's free-text answer into structured values. A cheap model saturates this job.
PARSER_MODEL = "openrouter/openai/gpt-6-luna"
SUMMARIZER_MODEL = "openrouter/openai/gpt-6-luna"

# Research. AskNews is free for tournament entrants once granted; without its credentials the
# bot falls back to a search-backed model on the donated key. BOT_RESEARCHER overrides both.
RESEARCHER_WITH_ASKNEWS = "asknews/news-summaries"
RESEARCHER_WITHOUT_ASKNEWS = "openrouter/perplexity/sonar"
RESEARCHER_ENV = "BOT_RESEARCHER"

# Donated credit left on the OpenRouter key, in US dollars.
FULL_LINEUP_MIN_USD = 5.0  # below this, forecast with the first model only
STOP_BELOW_USD = 1.0  # below this, publish nothing and fail the run

# A question closing sooner than this is skipped: the forecast could not land in time.
# Our own estimate of one question's run time; measure it on the first runs and adjust.
SKIP_BELOW_SECONDS = 300

# A run that does not publish forecasts at most this many questions unless told otherwise,
# because unpublished questions stay "open" and would be forecast again on every run.
DRY_RUN_DEFAULT_MAX_QUESTIONS = 3
