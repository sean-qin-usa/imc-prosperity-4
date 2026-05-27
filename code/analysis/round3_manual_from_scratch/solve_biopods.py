from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Iterable


FAIR_VALUE = 920
RESERVES = tuple(range(670, 921, 5))


@dataclass(frozen=True)
class BidPair:
    b1: int
    b2: int


def levels_captured(bid: int) -> int:
    return sum(reserve < bid for reserve in RESERVES)


def min_bid_for_levels(levels: int) -> int:
    if levels <= 0:
        return 0
    return RESERVES[levels - 1] + 1


def second_fill_profit(b2: int, mean_b2: float) -> float:
    spread = FAIR_VALUE - b2
    if spread <= 0:
        return float("-inf")
    if b2 > mean_b2:
        return spread
    return spread * ((FAIR_VALUE - mean_b2) / spread) ** 3


def expected_profit(first_levels: int, second_levels: int, pair: BidPair, mean_b2: float) -> float:
    first_profit = first_levels * (FAIR_VALUE - pair.b1)
    second_profit = (second_levels - first_levels) * second_fill_profit(pair.b2, mean_b2)
    return (first_profit + second_profit) / len(RESERVES)


def candidate_pairs() -> list[tuple[int, int, BidPair]]:
    pairs: list[tuple[int, int, BidPair]] = []
    for first_levels in range(0, 51):
        b1 = min_bid_for_levels(first_levels)
        if b1 > FAIR_VALUE:
            continue
        for second_levels in range(first_levels, 51):
            b2 = min_bid_for_levels(second_levels)
            if b2 > FAIR_VALUE:
                continue
            pairs.append((first_levels, second_levels, BidPair(b1, b2)))
    return pairs


def best_responses(mean_b2: float, pairs: Iterable[tuple[int, int, BidPair]]) -> tuple[float, list[BidPair]]:
    best_value = float("-inf")
    best_pairs: list[BidPair] = []
    for first_levels, second_levels, pair in pairs:
        value = expected_profit(first_levels, second_levels, pair, mean_b2)
        if value > best_value + 1e-12:
            best_value = value
            best_pairs = [pair]
        elif abs(value - best_value) <= 1e-12:
            best_pairs.append(pair)
    return best_value, best_pairs


def scan_intervals(pairs: Iterable[tuple[int, int, BidPair]], step: float = 0.1) -> list[tuple[float, float, float, list[BidPair]]]:
    intervals: list[tuple[float, float, float, list[BidPair]]] = []
    current_start = 670.0
    current_value = float("-inf")
    current_pairs: list[BidPair] = []
    first = True
    n_steps = int(round((FAIR_VALUE - 670) / step))

    for index in range(n_steps + 1):
        mean_b2 = 670 + index * step
        value, pairs_here = best_responses(mean_b2, pairs)
        if first:
            current_start = mean_b2
            current_value = value
            current_pairs = pairs_here
            first = False
            continue
        if pairs_here != current_pairs:
            intervals.append((current_start, mean_b2 - step, current_value, current_pairs))
            current_start = mean_b2
            current_value = value
            current_pairs = pairs_here

    intervals.append((current_start, float(FAIR_VALUE), current_value, current_pairs))
    return intervals


def self_consistent_candidates(pairs: Iterable[tuple[int, int, BidPair]]) -> list[tuple[int, float, list[BidPair]]]:
    rows: list[tuple[int, float, list[BidPair]]] = []
    for mean_b2 in range(670, FAIR_VALUE + 1):
        value, best_pairs_for_mean = best_responses(mean_b2, pairs)
        matching = [pair for pair in best_pairs_for_mean if pair.b2 == mean_b2]
        if matching:
            rows.append((mean_b2, value, matching))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Solve Prosperity 4 Round 3 Ornamental Bio-Pods from scratch.")
    parser.add_argument("--mean", type=float, help="Evaluate best response for a specific assumed field mean second bid.")
    args = parser.parse_args()

    pairs = candidate_pairs()

    if args.mean is not None:
        value, best_pairs_for_mean = best_responses(args.mean, pairs)
        print(f"Assumed field mean second bid: {args.mean:.2f}")
        print(f"Best-response EV per counterparty: {value:.6f}")
        for pair in best_pairs_for_mean:
            print(f"  best pair: b1={pair.b1}, b2={pair.b2}")
        return

    baseline_value, baseline_pairs = best_responses(670.0, pairs)
    print("Baseline low-mean optimum")
    print(f"  EV per counterparty: {baseline_value:.6f}")
    for pair in baseline_pairs:
        print(f"  pair: b1={pair.b1}, b2={pair.b2}")

    print()
    print("Self-consistent symmetric candidates (mean second bid equals your b2)")
    for mean_b2, value, matching in self_consistent_candidates(pairs):
        pretty = ", ".join(f"({pair.b1}, {pair.b2})" for pair in matching)
        print(f"  mean={mean_b2}: EV={value:.6f}, pairs={pretty}")

    print()
    print("Best-response intervals for the assumed field mean")
    for start, end, value, pairs_here in scan_intervals(pairs):
        pretty = ", ".join(f"({pair.b1}, {pair.b2})" for pair in pairs_here)
        print(f"  {start:5.1f} to {end:5.1f}: EV={value:.6f}, best={pretty}")


if __name__ == "__main__":
    main()
