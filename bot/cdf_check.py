"""Check a numeric forecast's cumulative distribution against the rules Metaculus enforces.

The rules are taken from another entrant's notes on the Metaculus backend and are not yet
confirmed against the server, so a failure is reported and counted, never used to block a
forecast: the server rejects an invalid distribution itself.
"""

TOLERANCE = 1e-9
DEFAULT_POINTS = 201


def check_cdf(
    values: list[float],
    open_lower_bound: bool,
    open_upper_bound: bool,
    expected_points: int = DEFAULT_POINTS,
) -> list[str]:
    """Return the list of problems found; an empty list means the distribution passes."""
    problems: list[str] = []
    if len(values) != expected_points:
        problems.append(f"expected {expected_points} points, got {len(values)}")
    if len(values) < 2:
        return problems

    intervals = len(values) - 1
    min_step = 0.01 / intervals
    max_step = 0.2 * 200 / intervals

    for index, (previous, current) in enumerate(zip(values, values[1:]), start=1):
        step = current - previous
        if step < min_step - TOLERANCE:
            problems.append(f"step {index} is {step:.3g}, below the minimum {min_step:.3g}")
            break
        if step > max_step + TOLERANCE:
            problems.append(f"step {index} is {step:.3g}, above the maximum {max_step:.3g}")
            break

    first, last = values[0], values[-1]
    if open_lower_bound:
        if first < 0.001 - TOLERANCE:
            problems.append(f"open lower bound needs a first value of at least 0.001, got {first:.6g}")
    elif abs(first) > TOLERANCE:
        problems.append(f"closed lower bound needs a first value of 0, got {first:.6g}")
    if open_upper_bound:
        if last > 0.999 + TOLERANCE:
            problems.append(f"open upper bound needs a last value of at most 0.999, got {last:.6g}")
    elif abs(last - 1) > TOLERANCE:
        problems.append(f"closed upper bound needs a last value of 1, got {last:.6g}")

    if any(value < -TOLERANCE or value > 1 + TOLERANCE for value in values):
        problems.append("a value lies outside the range 0 to 1")
    return problems
