#!/usr/bin/env python3
"""Compute round 2 MAF EV scenarios from a test-run profit assumption.

The default assumptions match the current round 2 trader:
- latest official test profit ~= 8,991.4375
- real round monetizes ~10x that trading profit
- full market access is worth a conservative 15% uplift to trading PnL
- recommended bid is 65% of that access value, rounded to the nearest 500
"""

from __future__ import annotations

import argparse
from typing import Sequence


def round_to_step(value: float, step: int) -> int:
    return int(step * round(value / step))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-profit", type=float, default=8991.4375)
    parser.add_argument("--real-scale", type=float, default=10.0)
    parser.add_argument("--uplift-frac", type=float, default=0.15)
    parser.add_argument("--safety-frac", type=float, default=0.65)
    parser.add_argument("--round-step", type=int, default=500)
    parser.add_argument(
        "--accept-probs",
        type=float,
        nargs="*",
        default=[0.5, 0.6, 0.7, 0.8, 0.9],
        help="Acceptance probabilities used for EV sensitivity rows.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    real_base_profit = args.test_profit * args.real_scale
    access_value = real_base_profit * args.uplift_frac
    recommended_bid = round_to_step(access_value * args.safety_frac, args.round_step)
    break_even_uplift_frac = recommended_bid / real_base_profit if real_base_profit else 0.0
    monetization_ratio_vs_full_quotes = break_even_uplift_frac / 0.25 if 0.25 else 0.0

    print("Round 2 MAF EV")
    print(f"test_profit               : {args.test_profit:,.4f}")
    print(f"real_scale                : {args.real_scale:,.2f}x")
    print(f"estimated_real_profit     : {real_base_profit:,.2f}")
    print(f"access_uplift_fraction    : {args.uplift_frac:.2%}")
    print(f"estimated_access_value    : {access_value:,.2f}")
    print(f"safety_fraction           : {args.safety_frac:.2%}")
    print(f"recommended_bid           : {recommended_bid:,.0f}")
    print(f"break_even_uplift_frac    : {break_even_uplift_frac:.2%}")
    print(f"break_even_vs_25pct_quotes: {monetization_ratio_vs_full_quotes:.2%}")
    print()
    print("EV sensitivity if accepted with probability p:")
    for prob in args.accept_probs:
        ev_gain = prob * (access_value - recommended_bid)
        print(
            f"  p={prob:.1f} -> EV gain from bidding {recommended_bid:,.0f}: {ev_gain:,.2f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
