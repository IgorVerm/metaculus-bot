# How the bot forecasts

`run_bot.py` subclasses the template's bot (`FallTemplateBot2026` in `main.py`). The template's
prompts, its research, its parsing of answers and its building of numeric distributions are
used unchanged. What we add is described here; the specification is issue #9, and what we will
not try is in `avoid.md`.

## Our method: yes/no and multiple-choice questions

Two models, one from OpenAI and one from Anthropic, both at high effort, answer each question
in several framings. A checker flags a model whose answers contradict each other under the
rules of probability, and a flagged model answers once more. The framework then combines all
answers as it always did: the median for yes/no, the mean per option for multiple choice.

The check is a signal, never a correction. Paleka et al. (ICLR 2025) found that a forecaster's
consistency predicts its accuracy, and that forcing consistency mechanically did not reliably
improve accuracy. So our code never moves an answer toward consistency; it only asks the
model again.

### Framings

| Question | Framing | Prompt | Becomes |
|---|---|---|---|
| Yes/no | direct | the template's | the answer |
| Yes/no | reversed | ours: the probability of No | 1 − q |
| Yes/no | structured | ours: events, a statement, an overall answer | the overall answer |
| Multiple choice | direct | the template's | the answer |
| Multiple choice | reversed | ours: per option, the probability that it is not the outcome | 1 − q per option, rescaled to sum to 1 |

The prompt texts and conversions are in `bot/framings.py`. Our framings are parsed by the
framework's `structure_output` into small models defined in `run_bot.py`. Yes/no answers are
kept in [0.01, 0.99] as in the template; every multiple-choice option is kept at 0.01 or more.

In the structured framing the model names at most six events (A to F) with a probability each,
writes the resolution criteria as a statement over the labels with `and`, `or`, `not` and
brackets, may give one conditional split (its answer if a named event happens, and if it does
not), and gives its overall answer. The structured answer is parsed once, not twice as the
others are: event descriptions are free text, and two parses of free text rarely match exactly.

### The checker

`bot/formal.py` reads the statement with its own parser over a fixed set of tokens. A statement
is never evaluated as code, and anything outside the token set is refused. From the event
probabilities alone it computes the range the statement's probability must lie in, bottom-up:

- `not` → [1 − u, 1 − l]
- `and` of k parts → [max(0, Σl − (k − 1)), min(u)]
- `or` of k parts → [max(l), min(1, Σu)]

These hold for any dependence between the events. The tests check that against the exact
probabilities of 3,000 random joint distributions.

A model contradicts itself on a yes/no question when its direct answer, its converted reversed
answer or its structured overall answer lies outside the range by more than the range
tolerance; when direct and converted reversed differ by more than the pair tolerance; or when
the conditional split, combined with that event's probability, differs from the structured
overall answer by more than the range tolerance. On a multiple-choice question it contradicts
itself when an option's two answers differ by more than the pair tolerance, or the converted
reversed answers miss a sum of 1 by more than the sum tolerance. The tolerances are settings in
`bot/config.py`.

### Second look

A model that contradicted itself gets one more call. It is shown the question, its own answers
and the contradiction in plain words, and asked for one final answer in the direct form, which
is parsed as the template parses a direct answer. That answer replaces the model's first direct
answer. There is one second look per model per question.

### Research per framing

Research runs once per framing and both models read it.

- **Direct:** the template's research (AskNews when its credentials are set, otherwise the
  search model, built with the same time limit as our own requests). Other question types use
  this same research.
  A research source must be named `openrouter/...`, `asknews/...` or exactly `no_research`
  (`bot/researcher.py`); a run with any other `BOT_RESEARCHER` stops before it spends
  anything, because the framework puts a credential into the published model settings for
  other routes such as `metaculus/...` and `exa/...`.
- **Reversed:** a request to the search model (a cheap model with its vendor's web search,
  `SEARCH_MODEL` in `bot/config.py`) for reasons and evidence that the outcome will
  not happen.
- **Structured:** a request to the search model for the current status of what the question
  depends on.

Every request to a search model states today's date and the close date, and asks for the
newest developments first, each claim with its source and publication date, the site named in
the resolution criteria, and a last line `NEWEST_EVIDENCE_DATE: YYYY-MM-DD` (or `unknown`).
When the template's research comes from a search model, the same requirements are appended to
its prompt; this happens only for questions our method answers.

**Freshness gate** (`bot/freshness.py`). When the direct framing's research came from a search
model and its evidence line is missing, `unknown` or older than seven days, one more search
asks only for developments since that date (since seven days ago when there is no date). There
is one retry per question. The forecasters read a block with today's date and the question's
open, close and resolution dates, and, for research from a search model, the age of its newest
evidence.

**Sources.** The web addresses in the research texts are found with a regular expression and
logged, without their query strings. No step fetches an address that a model or a page
supplied. `BLOCKED_DOMAINS` in `bot/config.py` starts empty; the research requests name its
entries as not to be relied on.

### A question is never lost to our additions

Independent calls run side by side, and each failure is caught on its own. A reversed or
structured answer that fails or cannot be parsed is left out. A framing whose research fails
answers on the direct framing's research. A statement the parser refuses means no range, so
only the tests that need no range run. A failed second look leaves the first answers in place.
A multiple-choice answer that does not name exactly the question's options is left out,
because the framework combines only answers with the same option names; a second look with
other names counts as failed. Each of these is
logged as `FALLBACK`. A question fails only when no answer at all was produced.

### Where it hooks into the framework

`MedianBot._research_and_make_predictions` runs the method for yes/no and multiple-choice
questions and returns one result that holds every answer. The framework fails a question that
has fewer than half of the answers it expects; for these questions `expected_total_predictions`
is 1, so the answers that survived are enough.

The published comment shows, under "Research", a consistency summary per model and each
framing's research cut to 3,000 characters (the models read all of it). Each answer's reasoning
starts with a line naming its model and framing.

### Log lines

One line per event; search a run log for the word. None of them prints a key, a header or a
model's reasoning; `SOURCES` lists the addresses the research cited.

| Word | When |
|---|---|
| `CONSISTENCY` | per model and question: the range, the answers, whether it contradicted itself |
| `SECOND_LOOK` | a second look was taken: the direct answer before and after |
| `FALLBACK` | a part was skipped: which part, and the type of the error |
| `SOURCES` | per question: the cited addresses and domains, and any blocked domain among them |
| `FRESHNESS` | per framing: the newest evidence date, its age, whether the retry ran |

## Other question types

Numeric, discrete, date and conditional questions get the template's method with three plain
forecasts on the template's research. The framework asks for "the default model" inside each
forecast; `MedianBot._make_prediction` gives each forecast a slot and binds that slot's model to
the running task (`bot/slots.py`), and `MedianBot.get_llm` returns the bound model. The slots
are OpenAI, Anthropic, OpenAI (`PLAIN_FORECAST_SLOTS`). The framework aggregates with the
pointwise median of the distributions. If the research source fails, `MedianBot.run_research`
returns no research and the question is still forecast.

## Spending and timing

At the start of a run `bot/credits.py` reads the credit left on the OpenRouter key. Above the
first floor the full line-up runs; between the floors only the first model, with all framings;
below the second floor the run publishes nothing and fails, so it shows red. An unreadable
balance counts as unknown and keeps the full line-up.

Calls per question with the full line-up; the worst case adds a second look for both models
and the freshness retry. A parser sample is one call to the cheap parser model; every answer is
parsed twice, the structured one once.

| Question | Flagship answers | Search requests | Parser samples |
|---|---|---|---|
| Yes/no, normally | 6 | 3 | 10 |
| Yes/no, at worst | 8 | 4 | 14 |
| Multiple choice, normally | 4 | 2 | 8 |
| Multiple choice, at worst | 6 | 3 | 12 |

The cost per question is not measured yet. The stages of one question run in sequence
(research, answers, second looks), and at the extremes their time limits add up to more than
the 45-minute run step of the workflows, so the run time must be measured on the first runs.

`bot/timebudget.py` drops a question that closes in under five minutes, because its forecast
could not land. The five minutes is our estimate, to be replaced by a measured run time.

## Publishing switch

`run_bot.py` publishes only when `BOT_PUBLISH` is `true` and `--dry-run` is absent. Any other
value than `true`, `false` or empty stops the run before it spends anything. A run that does
not publish forecasts at most three questions unless told otherwise, because unpublished
questions stay open and would be forecast again on every run. The scheduled workflows set
`BOT_PUBLISH` from the repository variable `BOT_LIVE` and do not start on schedule until it is
`true`.
