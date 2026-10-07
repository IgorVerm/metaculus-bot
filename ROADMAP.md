# Metaculus bot: roadmap

Concrete work lives in GitHub issues on IgorVerm/metaculus-bot. This file holds direction only.

## Direction

A small, auditable forecasting bot for the Metaculus FutureEval bot tournaments, built on the
official template, with a forecasting method of our own. The tournament asks entrants to try
something others have not. From another entrant we take only the list of what did not work
(`docs/design/avoid.md`). Changes are judged on our own resolved questions, one per two-week
cycle.

Later, the same pipeline can answer forecasting questions outside the tournament: forecasts on
other projects, a public record of forecasts and outcomes, and standing questions that are
re-forecast on a schedule.

## Phases and dependencies

1. **Base.** The template with three forecasts from two vendors, the median, and our safety
   layer: publish switch, credit guard, locked-down workflows. Done.
2. **Our method.** Specified on issue #9. Milestone 1 (yes/no and multiple choice) is built;
   milestone 2 (numeric, discrete and date questions) is not.
3. **Prove the pipe.** A published run on the test area, then dry runs on live questions.
   Depends on the owner's bot account, the donated key and the repository secrets.
4. **Live.** MiniBench and the main tournament, on the owner's word.
5. **Cycles.** One change per cycle, from the review of our own resolved questions.
6. **Outside the tournament.** Depends on a track record from phase 4.
