# How the bot forecasts

`run_bot.py` subclasses the template's bot (`FallTemplateBot2026` in `main.py`) and changes five
things. Everything else, including the prompts' wording, the parsing of answers and the
building of numeric distributions, is the template and the `forecasting-tools` framework.

## One forecast per model, then the median

The framework runs a fixed number of forecasts per question and asks for "the default model"
inside each. `MedianBot._make_prediction` gives each forecast a slot number and binds that
slot's model to the running task (`bot/slots.py`); `MedianBot.get_llm` returns the bound model.
The line-up is in `bot/config.py`: three forecasts from two vendors' flagship models, the first
vendor answering twice, independently.

The framework then aggregates: the median for binary questions, the pointwise median of the
distributions for numeric and date questions, the mean per option for multiple choice. We keep
those. The bot we learned from measured three models against six and found no difference, and
measured mean, geometric-mean and weighted aggregation as no better than the median.

## Research

`MedianBot.run_research` returns three parts:

1. The question's dates (`bot/prompts.py`, `window_block`), so the models reason about the
   right window.
2. The template's research: AskNews when its credentials are set, otherwise a search-backed
   model on the donated key. If this source fails, the question is still forecast.
3. The text of the pages the resolution criteria link to (`bot/research.py`, `bot/fetch.py`).
   Skipped when the question closes within thirty minutes.

Page text comes from addresses that question authors choose. `bot/fetch.py` therefore fetches
only http and https on ports 80 and 443, refuses any host that resolves to a non-public
address, follows redirects by hand so each hop is checked again, caps size and time, and keeps
only visible text. The text is handed to the models under a heading that says it is source
material and not an instruction. It reaches the models' prompts and, as part of the research,
the private comment the bot posts on Metaculus; nothing else.

## Prompt rules

`bot/prompts.py` holds about ten rules, each with its reason. They are appended to the
template's prompts through `_get_conditional_disclaimer_if_necessary`, which every template
prompt places just before its final-answer instructions. Each rule answers a failure the other
bot measured on resolved questions; the largest was treating an announced date as a deadline.

## Spending and timing

At the start of a run `bot/credits.py` reads the credit left on the OpenRouter key. Above the
first floor the full line-up runs; between the floors only the first model; below the second
floor the run publishes nothing and fails, so it shows red. An unreadable balance counts as
unknown and keeps the full line-up.

`bot/timebudget.py` drops a question that closes in under five minutes, because its forecast
could not land, and marks one that closes in under thirty for the fast path.

## Distribution check

After aggregation `bot/cdf_check.py` checks the final numeric distribution against the rules
Metaculus enforces (length, strictly increasing, step limits, bound values). A failure is
logged as `CDF_CHECK_FAIL` and counted. It does not block the forecast: the rules come from
another entrant's notes and are unconfirmed, and the server rejects an invalid distribution
itself.

## Publishing switch

`run_bot.py` publishes only when `BOT_PUBLISH` is `true` and `--dry-run` is absent. The
scheduled workflows set `BOT_PUBLISH` from the repository variable `BOT_LIVE` and do not start
on schedule until it is `true`.
