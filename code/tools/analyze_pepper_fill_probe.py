#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Sequence

import pandas as pd

from analyze_official_run import build_official_frames, resolve_bundle


DEFAULT_STRATEGY = Path("traders/round1/pepper_fill_probe.py")
TARGET_SYMBOL = "INTARIAN_PEPPER_ROOT"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze a PEPPER fill-probe official bundle by reconstructing the "
            "probe regime and active inside distance at each timestamp."
        )
    )
    parser.add_argument(
        "path",
        help="Official run directory, .log file, or .json file.",
    )
    parser.add_argument(
        "--strategy",
        type=Path,
        default=DEFAULT_STRATEGY,
        help="Probe strategy file used to recover thresholds and schedule constants.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Optional path to save the summary as JSON.",
    )
    return parser.parse_args(argv)


def load_trader_class(strategy_path: Path):
    path = strategy_path.expanduser().resolve()
    module_ast = ast.parse(path.read_text(), filename=str(path))
    trader_node = None
    for node in module_ast.body:
        if isinstance(node, ast.ClassDef) and node.name == "Trader":
            trader_node = node
            break
    if trader_node is None:
        raise ValueError(f"Could not find Trader class in {path}")

    attrs: Dict[str, object] = {}
    for stmt in trader_node.body:
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            attrs[target.id] = ast.literal_eval(stmt.value)
        except Exception:
            continue
    return SimpleNamespace(**attrs)


def build_probe_schedule(prices: pd.DataFrame, trader_cls) -> pd.DataFrame:
    ipr = prices[prices["product"] == TARGET_SYMBOL].copy().sort_values(["day", "timestamp"]).reset_index(drop=True)
    if ipr.empty:
        return ipr

    ipr["bid_price_1"] = pd.to_numeric(ipr["bid_price_1"], errors="coerce")
    ipr["ask_price_1"] = pd.to_numeric(ipr["ask_price_1"], errors="coerce")
    ipr["bid_volume_1"] = pd.to_numeric(ipr["bid_volume_1"], errors="coerce")
    ipr["ask_volume_1"] = pd.to_numeric(ipr["ask_volume_1"], errors="coerce")
    ipr["two_sided"] = ipr["bid_price_1"].notna() & ipr["ask_price_1"].notna()
    ipr["touch_mid"] = 0.5 * (ipr["bid_price_1"] + ipr["ask_price_1"])
    ipr["spread"] = ipr["ask_price_1"] - ipr["bid_price_1"]

    bid_qty = ipr["bid_volume_1"].fillna(0.0)
    ask_qty = ipr["ask_volume_1"].fillna(0.0)
    denom = bid_qty + ask_qty
    ipr["imbalance"] = 0.0
    valid = denom > 0
    ipr.loc[valid, "imbalance"] = (bid_qty.loc[valid] - ask_qty.loc[valid]) / denom.loc[valid]

    phase_length = int(getattr(trader_cls, "IPR_PHASE_LENGTH"))
    probe_window_end = int(getattr(trader_cls, "IPR_PROBE_WINDOW_END"))
    drift = float(getattr(trader_cls, "IPR_DRIFT_PER_TIMESTAMP"))
    var_alpha = float(getattr(trader_cls, "IPR_VAR_ALPHA"))
    zscore_threshold = float(getattr(trader_cls, "IPR_ZSCORE_CHEAP_THRESHOLD"))
    imbalance_threshold = float(getattr(trader_cls, "IPR_IMBALANCE_SUPPORT_THRESHOLD"))
    regime_targets = dict(getattr(trader_cls, "IPR_REGIME_TARGETS"))
    regime_sizes = dict(getattr(trader_cls, "IPR_REGIME_SIZES"))

    rows: List[Dict[str, object]] = []
    current_day = None
    anchor = None
    variance = 9.0

    for row in ipr.itertuples(index=False):
        day = int(row.day)
        timestamp = int(row.timestamp)
        if day != current_day:
            current_day = day
            anchor = None
            variance = 9.0

        if not bool(row.two_sided):
            rows.append(
                {
                    "day": day,
                    "timestamp": timestamp,
                    "two_sided": False,
                    "probe_active": False,
                    "regime": "no_book",
                    "distance": None,
                    "target_inventory": None,
                    "quote_size": None,
                    "touch_mid": None,
                    "spread": None,
                    "imbalance": None,
                    "zscore": None,
                }
            )
            continue

        touch_mid = float(row.touch_mid)
        if anchor is None:
            anchor = touch_mid

        benchmark_path = float(anchor) + drift * timestamp
        residual = touch_mid - benchmark_path
        variance = (1.0 - var_alpha) * variance + var_alpha * (residual * residual)
        sigma = max(1.0, variance ** 0.5)
        zscore = residual / sigma
        imbalance = float(row.imbalance)

        cheap = zscore <= zscore_threshold
        supportive = imbalance >= imbalance_threshold
        if cheap and supportive:
            regime = "both"
        elif cheap:
            regime = "cheap_only"
        elif supportive:
            regime = "support_only"
        else:
            regime = "control"

        phase_index = (timestamp // phase_length) % 2
        distance = 1 if phase_index == 0 else 2
        rows.append(
            {
                "day": day,
                "timestamp": timestamp,
                "two_sided": True,
                "probe_active": timestamp < probe_window_end,
                "regime": regime,
                "distance": distance,
                "target_inventory": int(regime_targets[regime]),
                "quote_size": int(regime_sizes[regime]),
                "touch_mid": touch_mid,
                "spread": float(row.spread),
                "imbalance": imbalance,
                "zscore": zscore,
            }
        )

    schedule = pd.DataFrame(rows).sort_values(["day", "timestamp"]).reset_index(drop=True)
    for horizon in (1, 5, 10):
        schedule[f"touch_mid_fwd_{horizon}"] = schedule.groupby("day")["touch_mid"].shift(-horizon)
    return schedule


def add_position_and_fills(schedule: pd.DataFrame, own_trades: pd.DataFrame) -> pd.DataFrame:
    buy_trades = own_trades[
        (own_trades["symbol"] == TARGET_SYMBOL) & (own_trades["side"] == "buy")
    ].copy()
    sell_trades = own_trades[
        (own_trades["symbol"] == TARGET_SYMBOL) & (own_trades["side"] == "sell")
    ].copy()

    buy_by_ts = (
        buy_trades.groupby(["day", "timestamp"], as_index=False)
        .agg(
            buy_fill_qty=("quantity", "sum"),
            buy_fill_count=("quantity", "size"),
            buy_fill_notional=("price", lambda s: float((s * buy_trades.loc[s.index, "quantity"]).sum())),
        )
    )
    if not buy_by_ts.empty:
        buy_by_ts["buy_fill_avg_price"] = buy_by_ts["buy_fill_notional"] / buy_by_ts["buy_fill_qty"]
    else:
        buy_by_ts = pd.DataFrame(
            columns=["day", "timestamp", "buy_fill_qty", "buy_fill_count", "buy_fill_notional", "buy_fill_avg_price"]
        )

    if own_trades.empty:
        signed_by_ts = pd.DataFrame(columns=["day", "timestamp", "net_signed_qty"])
    else:
        signed_by_ts = own_trades.copy()
        signed_by_ts["signed_qty"] = signed_by_ts["quantity"].astype(int)
        signed_by_ts.loc[signed_by_ts["side"] == "sell", "signed_qty"] *= -1
        signed_by_ts = (
            signed_by_ts.groupby(["day", "timestamp"], as_index=False)
            .agg(net_signed_qty=("signed_qty", "sum"))
            .sort_values(["day", "timestamp"])
        )

    merged = schedule.merge(signed_by_ts, on=["day", "timestamp"], how="left")
    merged["net_signed_qty"] = pd.to_numeric(merged["net_signed_qty"], errors="coerce").fillna(0).astype(int)
    merged["position_after"] = merged.groupby("day")["net_signed_qty"].cumsum()
    merged["position_before"] = merged["position_after"] - merged["net_signed_qty"]

    merged = merged.merge(buy_by_ts, on=["day", "timestamp"], how="left")
    merged["buy_fill_qty"] = pd.to_numeric(merged["buy_fill_qty"], errors="coerce").fillna(0).astype(int)
    merged["buy_fill_count"] = pd.to_numeric(merged["buy_fill_count"], errors="coerce").fillna(0).astype(int)
    merged["buy_fill_notional"] = pd.to_numeric(merged["buy_fill_notional"], errors="coerce").fillna(0.0)
    merged["buy_fill_avg_price"] = pd.to_numeric(merged["buy_fill_avg_price"], errors="coerce").fillna(0.0)
    merged["quote_sent"] = (
        merged["probe_active"]
        & merged["two_sided"]
        & (merged["position_before"] < merged["target_inventory"].fillna(-1))
        & (merged["spread"] > merged["distance"].fillna(99))
    )
    merged["filled"] = merged["buy_fill_qty"] > 0
    return merged


def summarize_probe(merged: pd.DataFrame) -> Dict[str, object]:
    active = merged[merged["quote_sent"]].copy()
    if active.empty:
        return {"rows": [], "overall": {}}

    active["entry_edge_total"] = (active["touch_mid"] - active["buy_fill_avg_price"]) * active["buy_fill_qty"]
    for horizon in (1, 5, 10):
        active[f"markout_total_{horizon}"] = (
            active[f"touch_mid_fwd_{horizon}"] - active["buy_fill_avg_price"]
        ) * active["buy_fill_qty"]

    rows: List[Dict[str, object]] = []
    grouped = active.groupby(["regime", "distance"], sort=True)
    for (regime, distance), group in grouped:
        fill_qty = int(group["buy_fill_qty"].sum())
        opportunities = int(len(group))
        filled_timestamps = int(group["filled"].sum())
        row: Dict[str, object] = {
            "regime": str(regime),
            "distance": int(distance),
            "opportunities": opportunities,
            "filled_timestamps": filled_timestamps,
            "fill_rate": float(filled_timestamps / opportunities) if opportunities else 0.0,
            "fill_qty": fill_qty,
            "avg_fill_qty_when_filled": float(group.loc[group["filled"], "buy_fill_qty"].mean())
            if filled_timestamps
            else 0.0,
            "avg_zscore": float(group["zscore"].mean()),
            "avg_imbalance": float(group["imbalance"].mean()),
            "avg_spread": float(group["spread"].mean()),
        }
        if fill_qty > 0:
            row["entry_edge_vs_touch"] = float(group["entry_edge_total"].sum() / fill_qty)
            for horizon in (1, 5, 10):
                valid = group[group[f"touch_mid_fwd_{horizon}"].notna()]
                valid_qty = int(valid["buy_fill_qty"].sum())
                row[f"markout_{horizon}"] = (
                    float(valid[f"markout_total_{horizon}"].sum() / valid_qty) if valid_qty > 0 else 0.0
                )
        else:
            row["entry_edge_vs_touch"] = 0.0
            for horizon in (1, 5, 10):
                row[f"markout_{horizon}"] = 0.0
        rows.append(row)

    overall = {
        "quote_timestamps": int(len(active)),
        "filled_timestamps": int(active["filled"].sum()),
        "fill_qty": int(active["buy_fill_qty"].sum()),
    }
    return {"rows": rows, "overall": overall}


def print_summary(summary: Dict[str, object]) -> None:
    overall = summary["overall"]
    print(
        "overall:"
        f" quote_timestamps={overall.get('quote_timestamps', 0)},"
        f" filled_timestamps={overall.get('filled_timestamps', 0)},"
        f" fill_qty={overall.get('fill_qty', 0)}"
    )
    print()
    print(
        "regime,distance,opportunities,filled_timestamps,fill_rate,fill_qty,"
        "avg_fill_qty_when_filled,avg_zscore,avg_imbalance,avg_spread,"
        "entry_edge_vs_touch,markout_1,markout_5,markout_10"
    )
    for row in summary["rows"]:
        print(
            f"{row['regime']},{row['distance']},{row['opportunities']},{row['filled_timestamps']},"
            f"{row['fill_rate']:.4f},{row['fill_qty']},{row['avg_fill_qty_when_filled']:.3f},"
            f"{row['avg_zscore']:.3f},{row['avg_imbalance']:.3f},{row['avg_spread']:.3f},"
            f"{row['entry_edge_vs_touch']:.3f},{row['markout_1']:.3f},{row['markout_5']:.3f},"
            f"{row['markout_10']:.3f}"
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    bundle = resolve_bundle(args.path, official_log=None, official_json=None, strategy=args.strategy)
    trader_cls = load_trader_class(args.strategy)

    _, prices, _, own_trades = build_official_frames(bundle.log_path)
    schedule = build_probe_schedule(prices, trader_cls)
    merged = add_position_and_fills(schedule, own_trades)
    summary = summarize_probe(merged)
    print_summary(summary)

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
