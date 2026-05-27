#!/usr/bin/env python3
"""Summarize the strongest data-mined passive layering patterns.

This script combines two signals already present in the workspace:

1. Public price-path structure, especially the near-deterministic repeated
   `INTARIAN_PEPPER_ROOT` template across days.
2. Official inside-spread fill calibration captured from uploaded probe runs.

The goal is to surface the most plausible "hidden pattern" candidates where a
layered passive quote can rest below fair for buys or above fair for sells and
still earn hidden bot fills.
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUND1_DIR = REPO_ROOT / "data" / "round1"
ROUND2_DIR = REPO_ROOT / "data" / "round2"
HIDDEN_DAY_PATH = ROUND1_DIR / "benchmark_data_day_0" / "115164.json"
CALIBRATION_PATH = REPO_ROOT / "tools" / "calibrations" / "combined_official_passive_profile.json"


def load_prices(paths: Iterable[Path]) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for path in paths:
        frame = pd.read_csv(path, sep=";")
        frame["day"] = pd.to_numeric(frame["day"], errors="coerce")
        frame["timestamp"] = pd.to_numeric(frame["timestamp"], errors="coerce")
        frame["mid_price"] = pd.to_numeric(frame["mid_price"], errors="coerce")
        frame["bid_price_1"] = pd.to_numeric(frame["bid_price_1"], errors="coerce")
        frame["ask_price_1"] = pd.to_numeric(frame["ask_price_1"], errors="coerce")
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def load_hidden_prices(path: Path) -> pd.DataFrame:
    payload = json.loads(path.read_text())
    frame = pd.read_csv(StringIO(payload["activitiesLog"]), sep=";")
    frame["day"] = pd.to_numeric(frame["day"], errors="coerce")
    frame["timestamp"] = pd.to_numeric(frame["timestamp"], errors="coerce")
    frame["mid_price"] = pd.to_numeric(frame["mid_price"], errors="coerce")
    frame["bid_price_1"] = pd.to_numeric(frame["bid_price_1"], errors="coerce")
    frame["ask_price_1"] = pd.to_numeric(frame["ask_price_1"], errors="coerce")
    return frame


def ipr_path_summary(frame: pd.DataFrame) -> Dict[str, object]:
    ipr = frame[
        (frame["product"] == "INTARIAN_PEPPER_ROOT")
        & frame["mid_price"].gt(0)
    ].copy()
    pivot = (
        ipr.pivot_table(index="timestamp", columns="day", values="mid_price", aggfunc="first")
        .dropna()
        .sort_index()
    )
    corr = pivot.corr()

    day_pairs: List[Dict[str, float]] = []
    days = list(pivot.columns)
    for i, day_a in enumerate(days):
        for day_b in days[i + 1 :]:
            diff = pivot[day_b] - pivot[day_a]
            day_pairs.append(
                {
                    "day_a": int(day_a),
                    "day_b": int(day_b),
                    "mean_offset": float(diff.mean()),
                    "std_offset": float(diff.std()),
                    "corr": float(corr.loc[day_a, day_b]),
                }
            )
    return {
        "rows": int(len(ipr)),
        "common_points": int(len(pivot)),
        "day_pairs": day_pairs,
    }


def hidden_vs_public_summary(hidden_frame: pd.DataFrame, public_frame: pd.DataFrame) -> Dict[str, object]:
    hidden = hidden_frame[
        (hidden_frame["product"] == "INTARIAN_PEPPER_ROOT")
        & hidden_frame["mid_price"].gt(0)
    ][["timestamp", "mid_price"]].rename(columns={"mid_price": "hidden_mid"})

    public = public_frame[
        (public_frame["product"] == "INTARIAN_PEPPER_ROOT")
        & public_frame["mid_price"].gt(0)
    ][["day", "timestamp", "mid_price"]]

    merged = public.merge(hidden, on="timestamp", how="inner")
    rows: List[Dict[str, float]] = []
    for day, group in merged.groupby("day"):
        diff = group["hidden_mid"] - group["mid_price"]
        rows.append(
            {
                "day": int(day),
                "mean_offset": float(diff.mean()),
                "std_offset": float(diff.std()),
                "corr": float(group["hidden_mid"].corr(group["mid_price"])),
            }
        )
    return {"rows": rows}


def expected_fill_fraction(stats: Dict[str, object]) -> float:
    hit_probability = float(stats.get("hit_probability", 0.0))
    fill_ratio = float(stats.get("fill_ratio", 0.0))
    return hit_probability * fill_ratio


def candidate_rows(calibration: Dict[str, object]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    inside = calibration.get("inside_spread", {})

    for symbol, symbol_cfg in inside.items():
        for side, side_cfg in (symbol_cfg.get("sides") or {}).items():
            size_buckets = side_cfg.get("size_buckets") or {}
            distances = side_cfg.get("distances") or {}
            for size_bucket, size_stats in size_buckets.items():
                rows.append(
                    {
                        "symbol": str(symbol),
                        "side": str(side),
                        "kind": "size_bucket",
                        "bucket": str(size_bucket),
                        "expected_fill_fraction": expected_fill_fraction(size_stats),
                        "hit_probability": float(size_stats.get("hit_probability", 0.0)),
                        "fill_ratio": float(size_stats.get("fill_ratio", 0.0)),
                        "order_count": int(size_stats.get("order_count", 0)),
                    }
                )
            for distance, distance_stats in distances.items():
                rows.append(
                    {
                        "symbol": str(symbol),
                        "side": str(side),
                        "kind": "distance",
                        "bucket": str(distance),
                        "expected_fill_fraction": expected_fill_fraction(distance_stats),
                        "hit_probability": float(distance_stats.get("hit_probability", 0.0)),
                        "fill_ratio": float(distance_stats.get("fill_ratio", 0.0)),
                        "order_count": int(distance_stats.get("order_count", 0)),
                    }
                )
    rows.sort(
        key=lambda row: (
            row["symbol"],
            row["side"],
            row["kind"],
            -row["expected_fill_fraction"],
            -row["order_count"],
        )
    )
    return rows


def strongest_candidates(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    best: List[Dict[str, object]] = []
    seen: set[Tuple[str, str, str]] = set()
    for row in rows:
        key = (row["symbol"], row["side"], row["kind"])
        if key in seen:
            continue
        if row["order_count"] < 100:
            continue
        best.append(row)
        seen.add(key)
    return best


def print_section(title: str) -> None:
    print(title)
    print("=" * len(title))


def main() -> int:
    round1 = load_prices(sorted(ROUND1_DIR.glob("prices_round_1_day_*.csv")))
    round2 = load_prices(sorted(ROUND2_DIR.glob("prices_round_2_day_*.csv")))
    hidden = load_hidden_prices(HIDDEN_DAY_PATH)
    calibration = json.loads(CALIBRATION_PATH.read_text())

    round1_path = ipr_path_summary(round1)
    round2_path = ipr_path_summary(round2)
    hidden_cmp = hidden_vs_public_summary(hidden, round1)

    candidates = candidate_rows(calibration)
    best = strongest_candidates(candidates)

    print_section("IPR Repeated Path")
    for label, summary in (("round1", round1_path), ("round2", round2_path)):
        print(f"{label}: common_points={summary['common_points']} rows={summary['rows']}")
        for row in summary["day_pairs"]:
            print(
                f"  day {row['day_a']} -> {row['day_b']}: "
                f"mean_offset={row['mean_offset']:.3f}, std={row['std_offset']:.3f}, corr={row['corr']:.6f}"
            )

    print()
    print_section("Hidden Day Match")
    for row in hidden_cmp["rows"]:
        print(
            f"public day {row['day']}: "
            f"mean_offset={row['mean_offset']:.3f}, std={row['std_offset']:.3f}, corr={row['corr']:.6f}"
        )

    print()
    print_section("Best Passive Buckets")
    for row in best:
        print(
            f"{row['symbol']} {row['side']} {row['kind']}={row['bucket']}: "
            f"exp_fill_frac={row['expected_fill_fraction']:.5f}, "
            f"hit_prob={row['hit_probability']:.5f}, fill_ratio={row['fill_ratio']:.5f}, "
            f"orders={row['order_count']}"
        )

    print()
    print_section("Pattern Take")
    print(
        "INTARIAN_PEPPER_ROOT behaves like a scripted benchmark path with roughly +1000 day offsets. "
        "The hidden benchmark day also matches the public day-0 path almost exactly."
    )
    print(
        "The strongest execution-specific edge in the official calibration is not a single large passive order. "
        "It is layered medium-sized inside-spread quotes, especially 5-12 lot orders."
    )
    print(
        "The most credible candidate is IPR buy-side passive layering around the repeated fair path: "
        "primary +2 inside, medium size, with an optional smaller +3 secondary clip when the spread is wide."
    )
    print(
        "ASH_COATED_OSMIUM also prefers 5-12 lot inside-spread quotes, but the path is much less time-scripted "
        "than IPR, so the edge there looks more like size-aware market making than a hidden schedule."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
