"""
Intra-day correlated-drawdown report.

Reason this exists: R3 day-3 reveal lost -74,894 in a single 100k-ts bucket
(ts 400k-499k) as VFE swung and every delta-1 voucher marked against
position simultaneously. The 3-day bt EOD totals (154k/179k/186k) showed
nothing wrong because each day closed positive. Mid-day correlated
drawdowns of this scale must be visible BEFORE submitting a strategy.

Inputs:
- Prosperity submission bundle JSON (test_results/<N>/<N>.json)
- Jmerle backtester output .log (Activities log section)
- Raw CSV in the prices_round_*_day_*.csv format with profit_and_loss

Output: per-day per-bucket PnL delta table + max correlated drawdown
bucket per day + per-product breakdown of the worst bucket.

Threshold (default 30k abs correlated drawdown) is a tripwire — if the
worst bucket loses more than this with all/most products contributing,
the strategy needs an inventory brake before shipping.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


BUCKET_SIZE = 100_000
DEFAULT_THRESHOLD = 30_000


@dataclass
class Row:
    day: int
    timestamp: int
    product: str
    pnl: float


@dataclass
class BucketResult:
    day: int
    bucket: int
    total_delta: float
    per_product_delta: Dict[str, float] = field(default_factory=dict)

    @property
    def ts_range(self) -> Tuple[int, int]:
        return self.bucket * BUCKET_SIZE, (self.bucket + 1) * BUCKET_SIZE - 1

    @property
    def n_negative_products(self) -> int:
        return sum(1 for v in self.per_product_delta.values() if v < 0)


def parse_activities_text(text: str) -> List[Row]:
    rows: List[Row] = []
    lines = text.strip().split("\n")
    if not lines:
        return rows
    header = lines[0].split(";")
    if "profit_and_loss" not in header:
        raise ValueError("activitiesLog missing profit_and_loss column")
    pnl_idx = header.index("profit_and_loss")
    for line in lines[1:]:
        parts = line.split(";")
        if len(parts) <= pnl_idx:
            continue
        try:
            day = int(parts[0])
            ts = int(parts[1])
            prod = parts[2]
            pnl = float(parts[pnl_idx]) if parts[pnl_idx] else 0.0
        except (ValueError, IndexError):
            continue
        rows.append(Row(day=day, timestamp=ts, product=prod, pnl=pnl))
    return rows


def parse_bundle_json(path: Path) -> List[Row]:
    j = json.loads(path.read_text())
    return parse_activities_text(j["activitiesLog"])


def parse_jmerle_log(path: Path) -> List[Row]:
    text = path.read_text()
    marker = "Activities log:"
    idx = text.find(marker)
    if idx < 0:
        raise ValueError(f"{path} does not contain an 'Activities log:' section")
    return parse_activities_text(text[idx + len(marker):].strip())


def parse_prices_csv(path: Path) -> List[Row]:
    return parse_activities_text(path.read_text())


def compute_drawdown_report(rows: Iterable[Row]) -> List[BucketResult]:
    """Per-day per-bucket PnL delta, where delta = (last pnl in bucket) - (last pnl in prior bucket).

    Last-pnl-in-bucket is the mark-to-mid PnL at the end of that 100k-ts window
    for each product. Sum across products gives the total bucket delta.
    """
    by_day_prod_bucket: Dict[Tuple[int, str, int], float] = {}
    for row in rows:
        bucket = row.timestamp // BUCKET_SIZE
        by_day_prod_bucket[(row.day, row.product, bucket)] = row.pnl

    days = sorted({day for (day, _, _) in by_day_prod_bucket})
    products = sorted({prod for (_, prod, _) in by_day_prod_bucket})

    results: List[BucketResult] = []
    for day in days:
        buckets = sorted({b for (d, _, b) in by_day_prod_bucket if d == day})
        if not buckets:
            continue
        prev_pnl_per_prod: Dict[str, float] = {p: 0.0 for p in products}
        for b in buckets:
            per_prod_delta: Dict[str, float] = {}
            for prod in products:
                if (day, prod, b) in by_day_prod_bucket:
                    end_pnl = by_day_prod_bucket[(day, prod, b)]
                else:
                    end_pnl = prev_pnl_per_prod[prod]
                per_prod_delta[prod] = end_pnl - prev_pnl_per_prod[prod]
                prev_pnl_per_prod[prod] = end_pnl
            total = sum(per_prod_delta.values())
            results.append(
                BucketResult(
                    day=day,
                    bucket=b,
                    total_delta=total,
                    per_product_delta=per_prod_delta,
                )
            )
    return results


def format_report(
    buckets: List[BucketResult],
    threshold: float = DEFAULT_THRESHOLD,
    show_all_buckets: bool = False,
) -> str:
    if not buckets:
        return "(no activity rows found)"
    lines: List[str] = []
    days = sorted({b.day for b in buckets})

    lines.append("Intra-day P&L bucket report (per 100k-ts windows)")
    lines.append("=" * 78)

    worst_per_day: Dict[int, BucketResult] = {}
    for b in buckets:
        if b.day not in worst_per_day or b.total_delta < worst_per_day[b.day].total_delta:
            worst_per_day[b.day] = b

    for day in days:
        day_buckets = [b for b in buckets if b.day == day]
        day_total = sum(b.total_delta for b in day_buckets)
        n_buckets = len(day_buckets)
        lines.append("")
        lines.append(f"DAY {day}  ({n_buckets} buckets, {n_buckets * BUCKET_SIZE // 1000}k-ts day)  EOD={day_total:+,.0f}")
        if show_all_buckets:
            for b in day_buckets:
                lo, hi = b.ts_range
                neg_n = b.n_negative_products
                tot_n = len(b.per_product_delta)
                marker = "  !!" if abs(b.total_delta) >= threshold else "    "
                lines.append(
                    f"{marker}ts {lo:>7,}-{hi:>7,}  delta={b.total_delta:>+10,.0f}  "
                    f"({neg_n}/{tot_n} products negative)"
                )
        worst = worst_per_day[day]
        lo, hi = worst.ts_range
        lines.append(
            f"  worst bucket: ts {lo:,}-{hi:,}  delta={worst.total_delta:+,.0f}  "
            f"({worst.n_negative_products}/{len(worst.per_product_delta)} products negative)"
        )
        sorted_contribs = sorted(worst.per_product_delta.items(), key=lambda kv: kv[1])
        for prod, dv in sorted_contribs[:5]:
            if dv < 0:
                lines.append(f"      {prod:25s} {dv:>+10,.0f}")

    overall_worst = min(buckets, key=lambda b: b.total_delta)
    lines.append("")
    lines.append("Overall worst correlated bucket:")
    lo, hi = overall_worst.ts_range
    lines.append(
        f"  day {overall_worst.day}  ts {lo:,}-{hi:,}  delta={overall_worst.total_delta:+,.0f}  "
        f"({overall_worst.n_negative_products}/{len(overall_worst.per_product_delta)} products negative)"
    )

    flagged = [b for b in buckets if b.total_delta <= -threshold]
    lines.append("")
    if flagged:
        lines.append(
            f"WARNING: {len(flagged)} bucket(s) lost more than {threshold:,.0f} in 100k ticks "
            f"with correlated product moves."
        )
        lines.append(
            "  This is a regime your 1k-tick provisional scoring will NOT show. "
            "Add an inventory brake or position cap before shipping."
        )
    else:
        lines.append(
            f"OK: no bucket lost more than {threshold:,.0f} in 100k ticks. "
            "(Lower the threshold to inspect smaller drawdowns.)"
        )

    return "\n".join(lines)


def load_rows(path: Path) -> List[Row]:
    if path.suffix == ".json":
        return parse_bundle_json(path)
    if path.suffix == ".log":
        return parse_jmerle_log(path)
    if path.suffix == ".csv":
        return parse_prices_csv(path)
    raise ValueError(f"unsupported input type: {path.suffix} (expected .json, .log, .csv)")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Per-bucket intra-day correlated-drawdown report. "
        "Operates on prosperity bundle JSON, jmerle .log, or raw prices CSV."
    )
    parser.add_argument(
        "input",
        nargs="+",
        help="One or more activity-log files (.json | .log | .csv)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"abs delta in a single 100k-ts bucket that triggers WARNING (default {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--all-buckets",
        action="store_true",
        help="Print every bucket per day, not just the worst.",
    )
    args = parser.parse_args(argv)

    all_rows: List[Row] = []
    for raw in args.input:
        path = Path(raw).expanduser().resolve()
        rows = load_rows(path)
        if len(args.input) > 1:
            print(f"# Loaded {len(rows):,} rows from {path}")
        all_rows.extend(rows)

    buckets = compute_drawdown_report(all_rows)
    print(format_report(buckets, threshold=args.threshold, show_all_buckets=args.all_buckets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
