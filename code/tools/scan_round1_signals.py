#!/usr/bin/env python3
"""Scan Round 1 historical data for stable pricing relationships.

The scanner focuses on tradable two-sided quotes instead of the raw `mid_price`
column, which can include one-sided books. It reports:

- cross-day shape stability
- fixed-fair mean reversion for ASH_COATED_OSMIUM
- repeated-path residual mean reversion for INTARIAN_PEPPER_ROOT
- top-of-book imbalance predictive power
- optional hidden-day sanity checks from a benchmark bundle JSON
"""

from __future__ import annotations

import argparse
import json
import math
from io import StringIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd


PUBLIC_DAYS: Tuple[int, ...] = (-2, -1, 0)
PRODUCTS: Tuple[str, ...] = ("ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT")
DEFAULT_HIDDEN_JSON = Path("data/round1/benchmark_data_day_0/115164.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/round1"),
        help="Directory containing prices_round_1_day_*.csv files.",
    )
    parser.add_argument(
        "--hidden-json",
        type=Path,
        default=DEFAULT_HIDDEN_JSON,
        help="Optional benchmark bundle JSON used for hidden-day checks.",
    )
    parser.add_argument(
        "--skip-hidden",
        action="store_true",
        help="Skip hidden-day checks even if --hidden-json exists.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Optional path to write a machine-readable JSON summary.",
    )
    return parser.parse_args()


def clip(value: float, bound: float) -> float:
    return max(-bound, min(bound, value))


def load_public_prices(data_dir: Path, days: Iterable[int]) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for day in days:
        path = data_dir / f"prices_round_1_day_{day}.csv"
        frame = pd.read_csv(path, sep=";")
        frame["day"] = pd.to_numeric(frame["day"], errors="coerce").fillna(day).astype(int)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def load_hidden_prices(hidden_json_path: Path) -> Optional[pd.DataFrame]:
    if not hidden_json_path.exists():
        return None

    payload = json.loads(hidden_json_path.read_text())
    activities_log = payload.get("activitiesLog")
    if not activities_log:
        return None

    return pd.read_csv(StringIO(activities_log), sep=";")


def prepare_quotes(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()

    numeric_cols = [
        "day",
        "timestamp",
        "bid_price_1",
        "bid_volume_1",
        "ask_price_1",
        "ask_volume_1",
        "mid_price",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    symbol_col = "product" if "product" in df.columns else "symbol"
    df = df.rename(columns={symbol_col: "product"})

    df["two_sided"] = df["bid_price_1"].notna() & df["ask_price_1"].notna()
    df["touch_mid"] = 0.5 * (df["bid_price_1"] + df["ask_price_1"])
    df["spread"] = df["ask_price_1"] - df["bid_price_1"]

    bid_size = df["bid_volume_1"].fillna(0.0)
    ask_size = df["ask_volume_1"].fillna(0.0)
    denom = bid_size + ask_size
    df["l1_imbalance"] = 0.0
    valid = denom > 0
    df.loc[valid, "l1_imbalance"] = (bid_size.loc[valid] - ask_size.loc[valid]) / denom.loc[valid]

    return df.sort_values(["product", "day", "timestamp"]).reset_index(drop=True)


def future_returns(df: pd.DataFrame, value_col: str, horizons: Iterable[int]) -> pd.DataFrame:
    out = df.copy()
    for horizon in horizons:
        out[f"fret_{horizon}"] = out.groupby("day")[value_col].shift(-horizon) - out[value_col]
    return out


def summarize_day_stats(df: pd.DataFrame) -> Dict[int, Dict[str, float]]:
    stats: Dict[int, Dict[str, float]] = {}
    for day, group in df.groupby("day"):
        stats[int(day)] = {
            "two_sided_ratio": float(group["two_sided"].mean()),
        }
        tradable = group[group["two_sided"]]
        if tradable.empty:
            continue
        stats[int(day)].update(
            {
                "touch_mid_mean": float(tradable["touch_mid"].mean()),
                "touch_mid_std": float(tradable["touch_mid"].std()),
                "spread_mean": float(tradable["spread"].mean()),
                "start_touch_mid": float(tradable["touch_mid"].iloc[0]),
                "end_touch_mid": float(tradable["touch_mid"].iloc[-1]),
            }
        )
    return stats


def common_timestamp_pivot(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    return df[df["two_sided"]].pivot(index="timestamp", columns="day", values=value_col).dropna()


def cross_day_path_metrics(df: pd.DataFrame, product: str) -> Dict[str, object]:
    piv = common_timestamp_pivot(df, "touch_mid")
    metrics: Dict[str, object] = {"common_points": int(len(piv))}
    if piv.empty or -2 not in piv.columns:
        return metrics

    offsets: Dict[int, float] = {}
    normalized = piv.copy()
    for day in sorted(col for col in normalized.columns if col != -2):
        if product == "INTARIAN_PEPPER_ROOT":
            offset = float((normalized[day] - normalized[-2]).median())
        else:
            offset = float((normalized[day] - normalized[-2]).median())
        offsets[int(day)] = offset
        normalized[day] = normalized[day] - offset

    corr = normalized.corr()
    rmse = {
        int(day): float(math.sqrt(((normalized[day] - normalized[-2]) ** 2).mean()))
        for day in normalized.columns
        if day != -2
    }
    metrics["offsets_vs_day_minus_2"] = offsets
    metrics["normalized_rmse_vs_day_minus_2"] = rmse
    metrics["normalized_corr"] = {
        str(int(row_day)): {str(int(col_day)): float(corr.loc[row_day, col_day]) for col_day in corr.columns}
        for row_day in corr.index
    }
    return metrics


def summarize_condition(frame: pd.DataFrame, mask: pd.Series, value_col: str) -> Dict[str, float]:
    values = frame.loc[mask, value_col].dropna()
    return {
        "n": int(len(values)),
        "mean": float(values.mean()) if not values.empty else 0.0,
        "median": float(values.median()) if not values.empty else 0.0,
    }


def aco_mean_reversion_metrics(df: pd.DataFrame) -> Dict[str, object]:
    tradable = future_returns(df[df["two_sided"]].copy(), "touch_mid", horizons=(1, 3, 5, 10))
    tradable["fair_dev"] = tradable["touch_mid"] - 10000.0

    thresholds = {
        "<= -4": tradable["fair_dev"] <= -4.0,
        "<= -2": tradable["fair_dev"] <= -2.0,
        ">= +2": tradable["fair_dev"] >= 2.0,
        ">= +4": tradable["fair_dev"] >= 4.0,
    }

    summary: Dict[str, object] = {}
    for horizon in (1, 3, 5, 10):
        horizon_key = f"horizon_{horizon}"
        summary[horizon_key] = {
            label: summarize_condition(tradable, mask, f"fret_{horizon}")
            for label, mask in thresholds.items()
        }
    return summary


def ipr_path_residual_metrics(df: pd.DataFrame) -> Dict[str, object]:
    tradable = df[df["two_sided"]].copy()
    piv = tradable.pivot(index="timestamp", columns="day", values="touch_mid").dropna()
    offsets = {-2: 0.0}
    if -1 in piv.columns and -2 in piv.columns:
        offsets[-1] = float((piv[-1] - piv[-2]).median())
    if 0 in piv.columns and -2 in piv.columns:
        offsets[0] = float((piv[0] - piv[-2]).median())

    normalized = piv.copy()
    for day in (-1, 0):
        if day in normalized.columns:
            normalized[day] = normalized[day] - offsets.get(day, 0.0)
    template = normalized.mean(axis=1)

    tradable = tradable[tradable["timestamp"].isin(template.index)].copy()
    tradable["template_fair"] = tradable.apply(
        lambda row: template.loc[row["timestamp"]] + offsets.get(int(row["day"]), 0.0),
        axis=1,
    )
    tradable["path_resid"] = tradable["touch_mid"] - tradable["template_fair"]
    tradable = future_returns(tradable, "touch_mid", horizons=(1, 3, 5, 10))

    thresholds = {
        "<= -4": tradable["path_resid"] <= -4.0,
        "<= -2": tradable["path_resid"] <= -2.0,
        ">= +2": tradable["path_resid"] >= 2.0,
        ">= +4": tradable["path_resid"] >= 4.0,
    }

    summary: Dict[str, object] = {
        "offsets_vs_day_minus_2": {str(int(day)): float(offset) for day, offset in offsets.items() if day != -2},
    }
    for horizon in (1, 3, 5, 10):
        horizon_key = f"horizon_{horizon}"
        summary[horizon_key] = {
            label: summarize_condition(tradable, mask, f"fret_{horizon}")
            for label, mask in thresholds.items()
        }
    return summary


def imbalance_metrics(df: pd.DataFrame) -> Dict[str, float]:
    tradable = df[df["two_sided"]].copy()
    tradable["next_ret"] = tradable.groupby("day")["touch_mid"].shift(-1) - tradable["touch_mid"]
    corr = tradable[["l1_imbalance", "next_ret"]].corr().iloc[0, 1]
    hi = tradable.loc[tradable["l1_imbalance"] >= 0.5, "next_ret"].dropna()
    lo = tradable.loc[tradable["l1_imbalance"] <= -0.5, "next_ret"].dropna()
    return {
        "corr": float(corr),
        "high_imbalance_mean_next_ret": float(hi.mean()) if not hi.empty else 0.0,
        "high_imbalance_n": int(len(hi)),
        "low_imbalance_mean_next_ret": float(lo.mean()) if not lo.empty else 0.0,
        "low_imbalance_n": int(len(lo)),
    }


def hidden_checks(public_prices: pd.DataFrame, hidden_prices: pd.DataFrame) -> Dict[str, object]:
    results: Dict[str, object] = {}

    hidden_quotes = prepare_quotes(hidden_prices)
    hidden_quotes = hidden_quotes[hidden_quotes["two_sided"]]

    for product in PRODUCTS:
        public_day0 = public_prices[
            (public_prices["product"] == product)
            & (public_prices["day"] == 0)
            & (public_prices["two_sided"])
        ][["timestamp", "touch_mid"]].rename(columns={"touch_mid": "public_day_0"})

        hidden = hidden_quotes[hidden_quotes["product"] == product][["timestamp", "touch_mid"]].rename(
            columns={"touch_mid": "hidden"}
        )
        merged = hidden.merge(public_day0, on="timestamp", how="inner").sort_values("timestamp")
        if merged.empty:
            continue

        product_result: Dict[str, object] = {
            "hidden_vs_public_day_0": {
                "rmse": float(math.sqrt(((merged["hidden"] - merged["public_day_0"]) ** 2).mean())),
                "mae": float((merged["hidden"] - merged["public_day_0"]).abs().mean()),
                "median_abs": float((merged["hidden"] - merged["public_day_0"]).abs().median()),
            }
        }

        if product == "INTARIAN_PEPPER_ROOT":
            public_day_minus_1 = public_prices[
                (public_prices["product"] == product)
                & (public_prices["day"] == -1)
                & (public_prices["two_sided"])
            ][["timestamp", "touch_mid"]].rename(columns={"touch_mid": "public_day_minus_1"})
            merged = merged.merge(public_day_minus_1, on="timestamp", how="inner")
            shifted_err = merged["hidden"] - (merged["public_day_minus_1"] + 1000.0)
            product_result["hidden_vs_public_day_minus_1_plus_1000"] = {
                "rmse": float(math.sqrt((shifted_err**2).mean())),
                "mae": float(shifted_err.abs().mean()),
                "median_abs": float(shifted_err.abs().median()),
            }

            merged["path_resid"] = merged["hidden"] - merged["public_day_0"]
            for horizon in (1, 3, 5):
                merged[f"fret_{horizon}"] = merged["hidden"].shift(-horizon) - merged["hidden"]
                product_result[f"horizon_{horizon}"] = {
                    "<= -2": summarize_condition(merged, merged["path_resid"] <= -2.0, f"fret_{horizon}"),
                    ">= +2": summarize_condition(merged, merged["path_resid"] >= 2.0, f"fret_{horizon}"),
                }
        else:
            for horizon in (1, 3, 5):
                merged[f"fret_{horizon}"] = merged["hidden"].shift(-horizon) - merged["hidden"]
            merged["fair_dev"] = merged["hidden"] - 10000.0
            for horizon in (1, 3, 5):
                product_result[f"horizon_{horizon}"] = {
                    "<= -2": summarize_condition(merged, merged["fair_dev"] <= -2.0, f"fret_{horizon}"),
                    ">= +2": summarize_condition(merged, merged["fair_dev"] >= 2.0, f"fret_{horizon}"),
                }

        results[product] = product_result

    return results


def cross_product_lead_lag(public_prices: pd.DataFrame) -> Dict[str, float]:
    merged = (
        public_prices[public_prices["two_sided"]]
        .pivot_table(index=["day", "timestamp"], columns="product", values="touch_mid")
        .reset_index()
        .sort_values(["day", "timestamp"])
    )
    merged["aco_ret"] = merged.groupby("day")["ASH_COATED_OSMIUM"].diff()
    merged["ipr_ret"] = merged.groupby("day")["INTARIAN_PEPPER_ROOT"].diff()

    output: Dict[str, float] = {}
    for lag in (-5, -3, -1, 0, 1, 3, 5):
        shifted_ipr = merged.groupby("day")["ipr_ret"].shift(-lag)
        corr = pd.concat([merged["aco_ret"], shifted_ipr], axis=1).corr().iloc[0, 1]
        output[str(lag)] = float(corr)
    return output


def build_summary(public_prices: pd.DataFrame, hidden_prices: Optional[pd.DataFrame]) -> Dict[str, object]:
    summary: Dict[str, object] = {"products": {}, "cross_product": {}}

    for product in PRODUCTS:
        product_frame = public_prices[public_prices["product"] == product].copy()
        product_summary: Dict[str, object] = {
            "day_stats": summarize_day_stats(product_frame),
            "cross_day_path": cross_day_path_metrics(product_frame, product),
            "imbalance": imbalance_metrics(product_frame),
        }
        if product == "ASH_COATED_OSMIUM":
            product_summary["edge"] = aco_mean_reversion_metrics(product_frame)
        else:
            product_summary["edge"] = ipr_path_residual_metrics(product_frame)
        summary["products"][product] = product_summary

    summary["cross_product"]["lead_lag_corr"] = cross_product_lead_lag(public_prices)
    if hidden_prices is not None:
        summary["hidden_checks"] = hidden_checks(public_prices, hidden_prices)

    return summary


def print_summary(summary: Dict[str, object]) -> None:
    for product in PRODUCTS:
        print(f"\n## {product}")
        product_summary = summary["products"][product]
        day_stats = product_summary["day_stats"]
        for day in sorted(int(day) for day in day_stats.keys()):
            stats = day_stats[day]
            print(
                "day"
                f" {day}: two_sided={stats['two_sided_ratio']:.3f},"
                f" touch_mid_mean={stats.get('touch_mid_mean', 0.0):.3f},"
                f" touch_mid_std={stats.get('touch_mid_std', 0.0):.3f},"
                f" spread_mean={stats.get('spread_mean', 0.0):.3f}"
            )

        cross_day = product_summary["cross_day_path"]
        print(
            "cross-day:"
            f" common_points={cross_day.get('common_points', 0)},"
            f" offsets={cross_day.get('offsets_vs_day_minus_2', {})},"
            f" rmse={cross_day.get('normalized_rmse_vs_day_minus_2', {})}"
        )

        imbalance = product_summary["imbalance"]
        print(
            "imbalance:"
            f" corr={imbalance['corr']:.4f},"
            f" hi_mean={imbalance['high_imbalance_mean_next_ret']:.3f}"
            f" (n={imbalance['high_imbalance_n']}),"
            f" lo_mean={imbalance['low_imbalance_mean_next_ret']:.3f}"
            f" (n={imbalance['low_imbalance_n']})"
        )

        edge = product_summary["edge"]
        print("edge:")
        for horizon_key in ("horizon_1", "horizon_3", "horizon_5", "horizon_10"):
            if horizon_key not in edge:
                continue
            conditions = edge[horizon_key]
            parts = [
                f"{label}: mean={values['mean']:.3f}, n={values['n']}"
                for label, values in conditions.items()
            ]
            print(f"  {horizon_key}: " + "; ".join(parts))

    print("\n## Cross Product")
    print("lead/lag correlations:", summary["cross_product"]["lead_lag_corr"])

    hidden = summary.get("hidden_checks")
    if hidden:
        print("\n## Hidden Checks")
        for product, details in hidden.items():
            print(product + ":", json.dumps(details, sort_keys=True))


def main() -> None:
    args = parse_args()

    public_prices = prepare_quotes(load_public_prices(args.data_dir, PUBLIC_DAYS))
    hidden_prices = None
    if not args.skip_hidden:
        hidden_prices = load_hidden_prices(args.hidden_json)

    summary = build_summary(public_prices, hidden_prices)
    print_summary(summary)

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
