# Metaculus bot: current state

Checked on 2026-10-07.

## State
- Public fork of `Metaculus/metac-bot-template`. Our bot is `run_bot.py` plus the modules in
  `bot/`; the upstream files are unchanged.
- Milestone 1 of our method (issue #9) is built: on yes/no and multiple-choice questions two
  models answer in several framings, each framing has its own research with a freshness gate,
  a checker flags a model that contradicts itself, and a flagged model answers once more.
  Other question types keep three plain forecasts from two vendors. Milestone 2 (numeric,
  discrete and date questions) is not built.
- The unit tests of the pure modules pass locally. `tests_framework/` runs our method against
  the installed framework with stand-in models; it can only run on a runner.
- `METACULUS_TOKEN` is configured; the donated model key is still pending (issue #4).
  End-to-end operation against Metaculus and model providers is not yet validated (issue #5).
- Not verified until that first run, the first item first:
  1. Whether 12,000 output tokens is enough for an answer at high reasoning effort. A cap that
     binds returns an empty answer; look for `FALLBACK` lines for answers that could not be
     parsed, and raise `FORECASTER_MAX_OUTPUT_TOKENS` if they appear (the cost test then says
     whether the run cap must drop).
  2. Whether `max_tokens` reaches each vendor through OpenRouter, the model names resolve on
     the donated key and the `reasoning` setting is accepted.
  3. Whether the `:online` search models work and return the `NEWEST_EVIDENCE_DATE` line, and
     whether the parser model fills the structured answer reliably.
  4. Whether the models follow the structured prompt's rules for events (separate factors,
     conditional steps only beside their condition); a local trial on one model did.
  5. How often models contradict themselves, how often a fallback fires, and the cost per
     question (estimated at $0.70 to $1.60 from list prices; not measured).
- Hard limits are in place (`docs/design/bot.md`, "Limits"): output caps per call, caps on
  research and quoted text in prompts, five questions per run taken soonest-closing first,
  and a computed worst case of $24.72 per run (conditional questions; $17.94 for yes/no) under
  a ceiling of $25.
- The donated key serves OpenAI, Anthropic and Google models only, and its credit is not
  refilled within a season. AskNews allows 1,000 calls a month; the template's news search
  uses six per question.
- Nothing publishes. The repository variable `BOT_LIVE` is unset, so scheduled runs are skipped
  and manual runs are dry runs. Switching it on is issue #6, the owner's decision.
- The owner disabled the three bot workflows on GitHub by hand and enabled only `ci.yaml`. Only he
  switches a workflow on (`AGENTS.md`).

## Build, test, run
```bash
python3 -m unittest discover -s tests          # our modules; standard library only
gh workflow run ci.yaml                        # by hand, once per landing that touches code:
                                               # the same tests, a build check and tests_framework
gh workflow run test_bot.yaml                  # dry run on the testing area, three questions
gh workflow run run_main.yaml                  # dry run on the main tournament, three questions
gh workflow run run_minibench.yaml             # dry run on MiniBench, three questions
gh run list --workflow run_main.yaml --json createdAt,event,conclusion   # delivery of scheduled runs
```
`tests_framework/` needs the framework, which is installed on runners only:
`poetry run python -m unittest discover -s tests_framework -v` (a step of `ci.yaml`).

A run prints `CREDIT_REMAINING`, `QUESTIONS_SELECTED`, `RUN_SUMMARY` and, when it left
questions for the next run, `RUN_CAPPED`; per question `CONSISTENCY`, `SECOND_LOOK`, `FALLBACK`, `SOURCES` and `FRESHNESS`; search the run log for
those words (`docs/design/bot.md` says what each means).

The first dry run with the donated key must show, for a yes/no question: three research
sections, six answers labelled with model and framing, a `CONSISTENCY` line per model, a
`SOURCES` line and no failed question.

Repository variables: `BOT_LIVE` (`true` publishes and enables the schedule), `BOT_RESEARCHER`
(optional override of the research source; it must start with `openrouter/` or `asknews/`, or
be exactly `no_research`, because the framework would publish a credential in the comment for
other routes, and any other value stops the run).

Secrets: `METACULUS_TOKEN`, `OPENROUTER_API_KEY`, and, when granted, `ASKNEWS_API_KEY` (or
`ASKNEWS_CLIENT_ID` with `ASKNEWS_SECRET`). `OPENROUTER_API_KEY` must be the key Metaculus
donates and no other key; it is unset until that key arrives.

GitHub switches scheduled workflows off after 60 days without a commit.

## What to read for which work
| Work on | Read |
|---|---|
| Any change | `AGENTS.md`, then the issue |
| How the bot forecasts and why | `docs/design/bot.md` |
| The method's specification | issue #9 |
| A new forecasting idea | `docs/design/avoid.md` first |
| Why a choice was made | `DESIGN_DECISIONS.md` |
| Tournament rules and setup | `README.md` (upstream) and https://www.metaculus.com/futureeval/participate/ |

## Standing permissions (owner)
- Push verified work to `main` of this repository (2026-10-06, `DESIGN_DECISIONS.md`). Ends
  when the owner withdraws it. Does not cover live publishing or changing repository secrets.
