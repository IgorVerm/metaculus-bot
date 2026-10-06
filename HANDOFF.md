# Metaculus bot: current state

Checked on 2026-10-06.

## State
- Public fork of `Metaculus/metac-bot-template`. Our bot is `run_bot.py` plus the modules in
  `bot/`; the upstream files are unchanged.
- The bot is the template's method with three forecasts from two vendors and our safety layer.
  Everything adopted from another entrant's bot was removed by project decision; the replacement
  forecasting method awaits the owner's design decision.
- Unit tests pass and the bot builds on a runner. It has never run against Metaculus or a
  model: the repository has no secrets yet (issue #4, the owner's steps).
- Not verified until that first run: the model names resolve on the donated key, the
  `reasoning` setting is accepted, and the `:online` research fallback works and what it costs.
- The donated key serves OpenAI, Anthropic and Google models only, and its credit is not
  refilled within a season. AskNews allows 1,000 calls a month; the template's news search
  uses six per question.
- Nothing publishes. The repository variable `BOT_LIVE` is unset, so scheduled runs are skipped
  and manual runs are dry runs. Switching it on is issue #6, the owner's decision.

## Build, test, run
```bash
python3 -m unittest discover -s tests          # our modules; standard library only
gh workflow run ci.yaml                        # same tests plus a build check on a runner
gh workflow run test_bot.yaml                  # dry run on the testing area, three questions
gh workflow run run_main.yaml                  # dry run on the main tournament, three questions
gh workflow run run_minibench.yaml             # dry run on MiniBench, three questions
gh run list --workflow run_main.yaml --json createdAt,event,conclusion   # delivery of scheduled runs
```
A run prints `CREDIT_REMAINING`, `QUESTIONS_SELECTED` and `RUN_SUMMARY`; search the run log for
those words.

Repository variables: `BOT_LIVE` (`true` publishes and enables the schedule), `BOT_RESEARCHER`
(optional override of the research source). Secrets: `METACULUS_TOKEN`, `OPENROUTER_API_KEY`,
and, when granted, `ASKNEWS_API_KEY` (or `ASKNEWS_CLIENT_ID` with `ASKNEWS_SECRET`).
`OPENROUTER_API_KEY` must be the key
Metaculus donates and no other key; it is unset until that key
arrives.

GitHub switches scheduled workflows off after 60 days without a commit, and a fork starts with
them off; check the Actions tab if runs stop.

## What to read for which work
| Work on | Read |
|---|---|
| Any change | `AGENTS.md`, then the issue |
| How the bot forecasts and why | `docs/design/bot.md` |
| A new forecasting idea | `docs/design/avoid.md` first |
| Why a choice was made | `DESIGN_DECISIONS.md` |
| Tournament rules and setup | `README.md` (upstream) and https://www.metaculus.com/futureeval/participate/ |

## Standing permissions (owner)
- Push verified work to `main` of this repository (2026-10-06, `DESIGN_DECISIONS.md`). Ends
  when the owner withdraws it. Does not cover live publishing or changing repository secrets.
