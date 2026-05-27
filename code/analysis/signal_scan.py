from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

import numpy as np
import pandas as pd

from visualizer import discover_files, load_prices


FEATURE_COLUMNS = [
    "imb1",
    "micro_gap",
    "gap_asym",
    "deplete_asym",
    "depth3_imb",
    "ofi1_norm",
    "spread",
    "l1_depth",
]


@dataclass
class FeatureMetric:
    feature: str
    auc: float
    corr: float
    top_hit_rate: float
    bottom_hit_rate: float
    sample_size: int


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan LOB-style signals on Prosperity price data.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="Directory containing prices_round_*_day_*.csv files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional markdown output path. Defaults to <data-dir>/../signal_scan_report.md.",
    )
    parser.add_argument("--symbols", nargs="*", default=None, help="Optional symbol filter.")
    parser.add_argument(
        "--quantile",
        type=float,
        default=0.80,
        help="Tail quantile for top/bottom bucket hit-rate reporting.",
    )
    return parser.parse_args(argv)


def auc_score(scores: pd.Series, y: pd.Series) -> float:
    mask = scores.notna() & y.notna()
    if mask.sum() == 0:
        return math.nan
    values = scores[mask].to_numpy(dtype=float)
    labels = (y[mask].to_numpy(dtype=float) > 0).astype(int)
    pos = int(labels.sum())
    neg = int(len(labels) - pos)
    if pos == 0 or neg == 0:
        return math.nan
    order = np.argsort(values)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(values) + 1, dtype=float)
    pos_rank_sum = ranks[labels == 1].sum()
    return float((pos_rank_sum - pos * (pos + 1) / 2.0) / (pos * neg))


def safe_corr(left: pd.Series, right: pd.Series) -> float:
    mask = left.notna() & right.notna()
    if mask.sum() < 5:
        return math.nan
    return float(left[mask].corr(right[mask]))


def fit_linear_probability_r2(frame: pd.DataFrame, target_col: str, features: Sequence[str]) -> float:
    cols = [target_col, *features]
    subset = frame[cols].dropna()
    if len(subset) < max(50, len(features) + 5):
        return math.nan
    y = (subset[target_col] > 0).astype(float).to_numpy()
    x = np.column_stack([np.ones(len(subset))] + [subset[col].to_numpy(dtype=float) for col in features])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    fitted = x @ beta
    ss_res = np.square(y - fitted).sum()
    ss_tot = np.square(y - y.mean()).sum()
    if ss_tot <= 0:
        return math.nan
    return float(1.0 - ss_res / ss_tot)


def next_nonzero_direction(series: pd.Series) -> pd.Series:
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    for idx in range(len(values) - 1):
        future = values[idx + 1 :] - values[idx]
        nonzero = np.flatnonzero(future)
        if len(nonzero) > 0:
            out[idx] = np.sign(future[nonzero[0]])
    return pd.Series(out, index=series.index)


def fit_day_trend(series: pd.Series, x_positions: np.ndarray) -> tuple[float, float, float]:
    mask = series.notna().to_numpy()
    if mask.sum() < 2:
        return 0.0, 0.0, math.nan
    x = x_positions[mask]
    values = series[mask].to_numpy(dtype=float)
    slope, intercept = np.polyfit(x, values, 1)
    fitted = slope * x + intercept
    ss_res = np.square(values - fitted).sum()
    ss_tot = np.square(values - values.mean()).sum()
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else math.nan
    return float(slope), float(intercept), float(r2)


def add_feature_columns(prices: pd.DataFrame) -> pd.DataFrame:
    frame = prices.copy()
    for level in (1, 2, 3):
        frame[f"bid_volume_{level}"] = frame[f"bid_volume_{level}"].fillna(0.0)
        frame[f"ask_volume_{level}"] = frame[f"ask_volume_{level}"].fillna(0.0)
    frame["l1_depth"] = frame["bid_volume_1"] + frame["ask_volume_1"]
    frame["imb1"] = (frame["bid_volume_1"] - frame["ask_volume_1"]) / frame["l1_depth"].replace(0, np.nan)
    frame["micro_gap"] = (
        (frame["ask_price_1"] * frame["bid_volume_1"]) + (frame["bid_price_1"] * frame["ask_volume_1"])
    ) / frame["l1_depth"].replace(0, np.nan) - frame["mid_price"]
    bid_total = frame[[f"bid_volume_{level}" for level in (1, 2, 3)]].sum(axis=1)
    ask_total = frame[[f"ask_volume_{level}" for level in (1, 2, 3)]].sum(axis=1)
    frame["depth3_imb"] = (bid_total - ask_total) / (bid_total + ask_total).replace(0, np.nan)
    frame["gap_asym"] = (frame["ask_price_2"] - frame["ask_price_1"]) - (frame["bid_price_1"] - frame["bid_price_2"])
    frame["deplete_asym"] = (
        (frame["ask_price_2"] - frame["ask_price_1"]) / frame["ask_volume_1"].replace(0, np.nan)
        - (frame["bid_price_1"] - frame["bid_price_2"]) / frame["bid_volume_1"].replace(0, np.nan)
    )

    by = ["symbol", "day"]
    for column in ["bid_price_1", "ask_price_1", "bid_volume_1", "ask_volume_1"]:
        frame[f"prev_{column}"] = frame.groupby(by)[column].shift(1)

    frame["ofi1"] = (
        (frame["bid_price_1"] >= frame["prev_bid_price_1"]).astype(float) * frame["bid_volume_1"].fillna(0.0)
        - (frame["bid_price_1"] <= frame["prev_bid_price_1"]).astype(float) * frame["prev_bid_volume_1"].fillna(0.0)
        - (frame["ask_price_1"] <= frame["prev_ask_price_1"]).astype(float) * frame["ask_volume_1"].fillna(0.0)
        + (frame["ask_price_1"] >= frame["prev_ask_price_1"]).astype(float) * frame["prev_ask_volume_1"].fillna(0.0)
    )
    frame["ofi1_norm"] = frame["ofi1"] / frame["l1_depth"].replace(0, np.nan)

    frame["ret_1"] = frame.groupby(by)["mid_price"].shift(-1) - frame["mid_price"]
    frame["next_nonzero_dir"] = frame.groupby(by)["mid_price"].transform(next_nonzero_direction)
    frame["idx_in_day"] = frame.groupby(by).cumcount()

    trend_rows: List[pd.DataFrame] = []
    for (symbol, day), part in frame.groupby(by, sort=False):
        positions = part["idx_in_day"].to_numpy(dtype=float)
        slope, intercept, r2 = fit_day_trend(part["mid_price"], positions)
        trend = slope * positions + intercept
        enriched = part.copy()
        enriched["trend_slope"] = slope
        enriched["trend_intercept"] = intercept
        enriched["trend_r2"] = r2
        enriched["trend_value"] = trend
        trend_rows.append(enriched)
    frame = pd.concat(trend_rows, ignore_index=False).sort_index()
    frame["resid_mid"] = frame["mid_price"] - frame["trend_value"]
    frame["resid_ret_1"] = frame.groupby(by)["resid_mid"].shift(-1) - frame["resid_mid"]
    frame["resid_sign_1"] = np.sign(frame["resid_ret_1"])
    return frame


def select_target(frame: pd.DataFrame) -> tuple[str, str]:
    trend_stats = frame.groupby("day").agg(
        slope=("trend_slope", "first"),
        r2=("trend_r2", "first"),
    )
    slope_signs = trend_stats["slope"].apply(np.sign).replace(0, np.nan).dropna()
    consistent_slope = slope_signs.nunique() <= 1 and len(slope_signs) > 0
    strong_trend = float(trend_stats["r2"].median()) >= 0.90 and consistent_slope
    if strong_trend:
        return "resid_sign_1", "drifting product -> detrended residual direction"
    return "next_nonzero_dir", "stationary product -> next non-zero mid move direction"


def feature_metrics(frame: pd.DataFrame, target_col: str, quantile: float) -> List[FeatureMetric]:
    output: List[FeatureMetric] = []
    for feature in FEATURE_COLUMNS:
        subset = frame[[feature, target_col]].dropna()
        if subset.empty:
            continue
        hi = subset[feature].quantile(quantile)
        lo = subset[feature].quantile(1.0 - quantile)
        top = subset[subset[feature] >= hi]
        bottom = subset[subset[feature] <= lo]
        output.append(
            FeatureMetric(
                feature=feature,
                auc=auc_score(subset[feature], subset[target_col]),
                corr=safe_corr(subset[feature], subset[target_col]),
                top_hit_rate=float((top[target_col] > 0).mean()) if not top.empty else math.nan,
                bottom_hit_rate=float((bottom[target_col] < 0).mean()) if not bottom.empty else math.nan,
                sample_size=int(len(subset)),
            )
        )
    output.sort(key=lambda item: (math.isnan(item.auc), -(item.auc if not math.isnan(item.auc) else -1.0)))
    return output


def regime_lines(frame: pd.DataFrame, target_col: str, quantile: float) -> List[str]:
    lines: List[str] = []
    depth_median = frame["l1_depth"].median()
    spread_q75 = frame["spread"].quantile(0.75)
    regimes = [
        ("all", frame),
        ("thin", frame[frame["l1_depth"] <= depth_median]),
        ("thick", frame[frame["l1_depth"] > depth_median]),
        ("wide_spread", frame[frame["spread"] >= spread_q75]),
    ]
    for name, subset in regimes:
        data = subset[["micro_gap", target_col]].dropna()
        if data.empty:
            continue
        auc = auc_score(data["micro_gap"], data[target_col])
        cutoff = data["micro_gap"].abs().quantile(quantile)
        tail = data[data["micro_gap"].abs() >= cutoff]
        hit_rate = (
            float((np.sign(tail["micro_gap"]).to_numpy() == np.sign(tail[target_col]).to_numpy()).mean())
            if not tail.empty
            else math.nan
        )
        lines.append(
            f"- `{name}`: `micro_gap` auc=`{auc:.3f}`, tail-hit=`{hit_rate:.3f}`, n=`{len(data)}`"
        )
    return lines


def incremental_lines(frame: pd.DataFrame, target_col: str) -> List[str]:
    lines: List[str] = []
    base_r2 = fit_linear_probability_r2(frame, target_col, ["micro_gap"])
    if math.isnan(base_r2):
        return lines
    lines.append(f"- Base linear-probability R² with `micro_gap`: `{base_r2:.4f}`")
    for feature in ["imb1", "gap_asym", "deplete_asym", "depth3_imb", "l1_depth", "ofi1_norm"]:
        paired = frame[["micro_gap", feature, target_col]].dropna()
        uplift = fit_linear_probability_r2(paired, target_col, ["micro_gap", feature]) - fit_linear_probability_r2(
            paired, target_col, ["micro_gap"]
        )
        lines.append(f"- Add `{feature}` on matched rows: uplift=`{uplift:+.4f}`, n=`{len(paired)}`")
    return lines


def state_lines(frame: pd.DataFrame, target_col: str, min_count: int = 80) -> List[str]:
    states = (
        frame.groupby(["bid_price_1", "ask_price_1"])
        .agg(
            n=("timestamp", "size"),
            p_up=(target_col, lambda values: float((values > 0).mean())),
            avg_micro=("micro_gap", "mean"),
            avg_imb=("imb1", "mean"),
        )
        .reset_index()
    )
    states = states[states["n"] >= min_count].sort_values(["p_up", "n"], ascending=[False, False]).head(10)
    lines = []
    for row in states.itertuples(index=False):
        lines.append(
            f"- `{int(row.bid_price_1)}/{int(row.ask_price_1)}`: n=`{row.n}`, "
            f"p_up=`{row.p_up:.3f}`, avg_micro=`{row.avg_micro:.3f}`, avg_imb=`{row.avg_imb:.3f}`"
        )
    return lines


def markdown_report(frame: pd.DataFrame, data_dir: Path, quantile: float) -> str:
    lines: List[str] = []
    lines.append(f"# Signal Scan Report — `{data_dir}`")
    lines.append("")
    lines.append("This report uses direction-style targets rather than raw unbounded `Δmid`.")
    lines.append("That matches the queue-imbalance literature more closely and avoids large-jump outliers swamping otherwise real signals.")
    lines.append("")

    for symbol in sorted(frame["symbol"].unique()):
        symbol_frame = frame[frame["symbol"] == symbol].copy()
        target_col, target_reason = select_target(symbol_frame)
        lines.append(f"## `{symbol}`")
        lines.append("")
        lines.append(f"- Target: `{target_col}`")
        lines.append(f"- Reason: {target_reason}")
        lines.append(
            f"- Day trend summary: median r²=`{symbol_frame.groupby('day')['trend_r2'].first().median():.3f}`, "
            f"slope range=`{symbol_frame.groupby('day')['trend_slope'].first().min():+.4f}` .. "
            f"`{symbol_frame.groupby('day')['trend_slope'].first().max():+.4f}`"
        )
        lines.append("")
        lines.append("### Feature Table")
        lines.append("")
        lines.append("| Feature | AUC | Corr | Top bucket aligned-rate | Bottom bucket aligned-rate | n |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for metric in feature_metrics(symbol_frame, target_col, quantile):
            lines.append(
                f"| `{metric.feature}` | `{metric.auc:.3f}` | `{metric.corr:+.3f}` | "
                f"`{metric.top_hit_rate:.3f}` | `{metric.bottom_hit_rate:.3f}` | `{metric.sample_size}` |"
            )
        lines.append("")
        lines.append("### Regime Splits")
        lines.append("")
        lines.extend(regime_lines(symbol_frame, target_col, quantile))
        lines.append("")
        lines.append("### Incremental Tests")
        lines.append("")
        lines.extend(incremental_lines(symbol_frame, target_col))
        lines.append("")
        if target_col == "next_nonzero_dir":
            lines.append("### Common Book States")
            lines.append("")
            state_summary = state_lines(symbol_frame, target_col)
            if state_summary:
                lines.extend(state_summary)
            else:
                lines.append("- No top-of-book states crossed the minimum-count threshold.")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    price_files = discover_files(args.data_dir, "prices_")
    if not price_files:
        raise FileNotFoundError(f"No price files found under {args.data_dir}")

    prices = load_prices(price_files)
    if args.symbols:
        wanted = {symbol.upper() for symbol in args.symbols}
        prices = prices[prices["symbol"].str.upper().isin(wanted)].copy()
    prices = prices.sort_values(["symbol", "day", "timestamp"]).reset_index(drop=True)
    enriched = add_feature_columns(prices)

    default_output = args.data_dir.parent / "signal_scan_report.md"
    output_path = args.output or default_output
    report = markdown_report(enriched, args.data_dir, args.quantile)
    output_path.write_text(report)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
