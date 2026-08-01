"""
alloc.py — equal-split allocation with capacity limits and remainder handling.

Shared by two places:
  • selector.py — split a section total across its chapters
  • modes.py   — split a chapter count across question types (stratified mode)

Ported/generalized from the original resolve_equal_split(): base = target // n,
remainder distributed one-at-a-time in a randomized order (so the same buckets
aren't always favored), then leftover shortfall redistributed to buckets that
still have spare capacity.
"""


def equal_allocate(target: int, capacity: dict, rng, strategy: str = "redistribute"):
    """
    target: desired total to hand out
    capacity: {key -> max available}
    Returns (take: {key->count}, warnings: [str]).
    """
    warnings = []
    keys = [k for k, n in capacity.items() if n > 0]
    zero = [k for k, n in capacity.items() if n <= 0]
    if zero:
        warnings.append(f"buckets with 0 available skipped: {zero}")
    if not keys:
        return {}, warnings + ["no buckets had any available questions"]

    n_keys = len(keys)
    base = target // n_keys
    remainder = target % n_keys

    take = {k: min(base, capacity[k]) for k in keys}

    order = list(keys)
    rng.shuffle(order)
    i, r, guard = 0, remainder, 0
    while r > 0 and guard < 100000:
        k = order[i % len(order)]
        if take[k] < capacity[k]:
            take[k] += 1
            r -= 1
        i += 1
        guard += 1

    shortfall = target - sum(take.values())
    if shortfall > 0 and strategy == "redistribute":
        cap_order = [k for k in keys if take[k] < capacity[k]]
        rng.shuffle(cap_order)
        j = 0
        while shortfall > 0 and cap_order:
            k = cap_order[j % len(cap_order)]
            if take[k] < capacity[k]:
                take[k] += 1
                shortfall -= 1
            cap_order = [k2 for k2 in cap_order if take[k2] < capacity[k2]]
            j += 1
    if shortfall > 0:
        total_cap = sum(capacity.values())
        if strategy == "redistribute":
            warnings.append(
                f"could not reach target {target}; only {total_cap} available. Short by {shortfall}."
            )
        else:
            warnings.append(
                f"shortfall of {shortfall} allowed; got {sum(take.values())} instead of {target}."
            )

    return {k: v for k, v in take.items() if v > 0}, warnings
