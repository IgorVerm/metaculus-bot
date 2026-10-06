# What we will not try

Project decision of 2026-10-06 (`DESIGN_DECISIONS.md`): we build our own method, and the only
thing we take from the open-source bot `No-Stream/nostreambot-metaculus-bot` is its record of
what did not work. This is that record, as its author documented it (`FUTURE.md`,
`docs/performance_analysis.md`, read 2026-10-06). The numbers are his and were not re-measured
by us. Trying one of these again needs new evidence of our own.

## Adjusting forecasts after the models answered
- Calibration layers of every kind (isotonic, Platt, shrinking toward 50%, one-sided shaves).
  The direction of his bot's error flipped between periods, so no fit held.
- Tighter clipping of extreme probabilities. A floor of 5% cost him 217 points over 447
  forecasts.
- Widening the tails of numeric forecasts.
- Guards that pull a forecast back toward the model's own starting estimate. Forecasts that
  moved away from it scored better.

## Combining the forecasts
- A further model that rewrites or judges the combined forecast. No better than the median on
  88 questions.
- The mean, the geometric mean of odds, averaging of quantiles, or a trimmed mean in place of
  the median.
- Weighting models by past performance, or choosing models for diversity.
- More than three forecasts. Six scored no better than three.

## Extra reasoning steps
- A critic pass that advises the forecasters.
- Separate research run by each forecaster.
- Arithmetic helpers that recompute the models' stated probabilities.
- Fitting a parametric or mixture distribution to numeric answers.
- Further rounds of prompt tweaks. Models often ignored them.

## Research
- A second research pass that looks up a list of "missing facts": the largest cost per
  question, and about a third of its lookups added nothing.
- Asking the research step for prediction-market odds that another step already fetched.

## Operations
- Relying on GitHub's scheduler alone: it delivered about 22% of his scheduled runs in one
  twelve-day stretch.
- Sending a `verbosity` setting together with a reasoning-effort setting to an Anthropic
  model: the first silently overrode the second for months.
- Paid replays of old questions as a routine test: too costly to be rigorous, and old
  questions risk the model already knowing the answer.
