# Metaculus bot: current state

Checked on 2026-10-06.

## State
- Public fork of `Metaculus/metac-bot-template`, with the house documents added. The bot code
  is still the unmodified template.
- Nothing runs: the repository has no secrets, and scheduled workflows in a fork stay off
  until they are enabled.
- The first build is issue #2. What only the owner can do is issue #4.

## Build, test, run
Nothing of our own to build or test yet. The template's commands are in `README.md`; do not
run them locally (see `AGENTS.md`: dependencies install on GitHub's runners only).

## What to read for which work
| Work on | Read |
|---|---|
| Any change | `AGENTS.md`, then the issue |
| Why a choice was made | `DESIGN_DECISIONS.md` |
| Tournament rules and setup | `README.md` (upstream) and https://www.metaculus.com/futureeval/participate/ |

## Standing permissions (owner)
- Push verified work to `main` of this repository (2026-10-06, `DESIGN_DECISIONS.md`). Ends
  when the owner withdraws it. Does not cover live publishing or changing repository secrets.
