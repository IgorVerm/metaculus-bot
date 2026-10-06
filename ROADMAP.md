# Metaculus bot: roadmap

Concrete work lives in GitHub issues on IgorVerm/metaculus-bot. This file holds direction only.

## Direction

A small, auditable forecasting bot for the Metaculus FutureEval bot tournaments, built on the
official template. It keeps only ideas that another entrant measured as working, and it
improves by one change per two-week cycle, judged on resolved questions.

Later, the same pipeline can answer forecasting questions outside the tournament: forecasts on
other projects, a public record of forecasts and outcomes, and standing questions that are
re-forecast on a schedule.

## Phases and dependencies

1. **First build.** Three flagship models, one forecast each, median; prompt rules that fixed
   measured failures; the resolution-source page as research; reliability and spending checks.
2. **Prove the pipe.** A published run on the test area, then dry runs on live questions.
   Depends on the owner's bot account, the donated key and the repository secrets.
3. **Live.** MiniBench and the main tournament, on the owner's word.
4. **Cycles.** Candidates, one per cycle and only when the review of resolved questions
   supports it: a ranked snapshot of public prediction-market prices; thirteen percentiles for
   numeric questions; an empirical band from a data series' own history.
5. **Outside the tournament.** Depends on a track record from phase 3.

Not planned, because the entrant we learned from measured no gain: calibration layers, a model
that rewrites the forecast, mean or geometric-mean aggregation, tail widening, more than three
models, per-model weighting, backtesting on paid credits.
