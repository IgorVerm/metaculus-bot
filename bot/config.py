"""The one place for model names and thresholds.

Model names are checked against the live OpenRouter list (https://openrouter.ai/api/v1/models)
before a line-up change; last checked 2026-10-06.
"""

# One forecaster per vendor; the published forecast is the median of their answers.
# "reasoning" is passed through to the provider. The Google slot runs at provider defaults.
FORECASTERS: tuple[dict, ...] = (
    {"model": "openrouter/openai/gpt-6.1-sol", "reasoning": {"effort": "high"}},
    {"model": "openrouter/anthropic/claude-opus-5.5", "reasoning": {"effort": "high"}},
    {"model": "openrouter/google/gemini-3.1-pro-preview"},
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

# Seconds until a question closes.
FULL_PIPELINE_MIN_SECONDS = 1800  # below this, skip the optional page fetches
SKIP_BELOW_SECONDS = 300  # below this, the forecast cannot land before close

# Resolution-source pages.
MAX_SOURCE_PAGES = 2
MAX_CHARS_PER_PAGE = 6000
