# How the bot forecasts

`run_bot.py` subclasses the template's bot (`FallTemplateBot2026` in `main.py`). The prompts,
the research, the parsing of answers and the building of numeric distributions are the
template and the `forecasting-tools` framework, unchanged. What we add is listed here. Our own
forecasting method is still to be designed; what we will not try is in `avoid.md`.

## One forecast per model, then the median

The framework runs a fixed number of forecasts per question and asks for "the default model"
inside each. `MedianBot._make_prediction` gives each forecast a slot number and binds that
slot's model to the running task (`bot/slots.py`); `MedianBot.get_llm` returns the bound model.
The line-up is in `bot/config.py`: three forecasts from two vendors' flagship models, the first
vendor answering twice, independently.

The framework then aggregates: the median for binary questions, the pointwise median of the
distributions for numeric and date questions, the mean per option for multiple choice.

## Research

The template's research: AskNews when its credentials are set, otherwise a search-backed model
on the donated key. If the source fails, `MedianBot.run_research` returns no research and the
question is still forecast.

## Spending and timing

At the start of a run `bot/credits.py` reads the credit left on the OpenRouter key. Above the
first floor the full line-up runs; between the floors only the first model; below the second
floor the run publishes nothing and fails, so it shows red. An unreadable balance counts as
unknown and keeps the full line-up.

`bot/timebudget.py` drops a question that closes in under five minutes, because its forecast
could not land. The five minutes is our estimate, to be replaced by a measured run time.

## Publishing switch

`run_bot.py` publishes only when `BOT_PUBLISH` is `true` and `--dry-run` is absent. Any other
value than `true`, `false` or empty stops the run before it spends anything. A run that does
not publish forecasts at most three questions unless told otherwise, because unpublished
questions stay open and would be forecast again on every run. The scheduled workflows set
`BOT_PUBLISH` from the repository variable `BOT_LIVE` and do not start on schedule until it is
`true`.
