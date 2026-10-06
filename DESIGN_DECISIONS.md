# Metaculus bot: design decisions

The owner's rulings, newest first, in summary. Re-opening one needs the owner and a new entry.

## Build our own; take only what did not work, 2026-10-06
**Decision (owner):** Drop everything adopted from the other entrant's bot and build our
own; keep only its record of what did not work. All four adopted pieces go. **Why:** not stated. **Rejected:** keeping the adopted pieces as plain engineering; keeping
them switched off. **Binds:** the prompt rules, the question-dates block, reading of linked
pages and the distribution check are removed. `docs/design/avoid.md` is the one thing kept from
that bot. This replaces the "learn from the winner" half of the entry "Start from the
template, learn from the winner"; starting from the template stands.

## No Google model, 2026-10-06
**Decision (owner):** No Google model is used. **Why:** not stated. **Rejected:**
a third forecast from a Google model, as the bot we learned from uses. **Binds:** the line-up
in `bot/config.py` is two vendors (OpenAI and Anthropic), with OpenAI answering twice so the
median still has three forecasts; a test fails if a Google model is added.

## Pushing verified work to `main`, 2026-10-06
**Decision (owner):** Verified work may be pushed to `main` of this repository. **Why:** the bot runs from GitHub Actions, so nothing can be tested end to end
until it is on GitHub. **Rejected:** asking before every push. **Binds:** recorded as a
standing permission in `HANDOFF.md`; it does not cover switching on live publishing.

## Live publishing only on the owner's word, 2026-10-06
**Decision (owner):** Live publishing to Metaculus requires explicit owner approval. **Why:** forecasts are public and scored; the reference bot on the plain
template with an old model finished the Summer 2026 season at −2,565. **Rejected:** going live
with the template as soon as keys exist. **Binds:** the `BOT_LIVE` repository variable.

## Donated credits only, 2026-10-06
**Decision (owner):** Use only the credits donated by Metaculus. **Why:** the project
operates within its donated allocation. **Rejected:** spending beyond donated credits. **Binds:** research uses free sources only; the line-up shrinks to fit the
donated credit; no paid key is added.

## Public repository, 2026-10-06
**Decision (owner):** The repository is public. **Why:** free GitHub Actions minutes, and it meets
the rule that prize winners show their code. **Rejected:** a private repository with a
description submitted to Metaculus. **Binds:** code, documents, issues and run logs are public.

## Runs on GitHub Actions, 2026-10-06
**Decision (owner):** The bot runs on GitHub Actions. **Why:** nothing runs on a private machine and
keys sit in GitHub secrets. **Rejected:** an always-on machine; both together.
**Binds:** scheduling and secrets live in `.github/workflows/`; a backup trigger from another
place needs a new decision.

## Start from the template, learn from the winner, 2026-10-06
**Decision (owner):** Start from the official template and study what failed and what
worked for the open-source bot. **Why:** the official template is fifteen files and can be audited;
the open-source bot `No-Stream/nostreambot-metaculus-bot` is 4.4 MB with 33 dependencies.
**Rejected:** forking that bot. **Binds:** we take its measured lessons, not its code.
