from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

from visualizer import discover_files, load_prices


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan basket / ETF / synthetic spread relationships.")
    parser.add_argument("--data-dir", type=Path, required=True, help="Directory with price files.")
    parser.add_argument("--spec", type=Path, required=True, help="JSON spec describing composite relationships.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional markdown output path. Defaults to <data-dir>/../composite_signal_report.md.",
    )
    parser.add_argument("--max-lag", type=int, default=5, help="Maximum lead/lag to scan.")
    parser.add_argument("--z-quantile", type=float, default=0.90, help="Tail quantile for spread z-score event studies.")
    return parser.parse_args(argv)


def spread_half_life(series: pd.Series) -> float:
    lagged = series.shift(1)
    current = series
    subset = pd.DataFrame({"lagged": lagged, "current": current}).dropna()
    if len(subset) < 20:
        return math.nan
    x = np.column_stack([np.ones(len(subset)), subset["lagged"].to_numpy(dtype=float)])
    y = subset["current"].to_numpy(dtype=float)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    phi = float(beta[1])
    if phi <= 0 or phi >= 1:
        return math.nan
    return float(math.log(0.5) / math.log(phi))


def best_lead_lag(target_ret: pd.Series, synth_ret: pd.Series, max_lag: int) -> tuple[int, float]:
    best_lag = 0
    best_corr = -1.0
    for lag in range(-max_lag, max_lag + 1):
        shifted = synth_ret.shift(lag)
        mask = target_ret.notna() & shifted.notna()
        if mask.sum() < 20:
            continue
        corr = abs(float(target_ret[mask].corr(shifted[mask])))
        if corr > best_corr:
            best_corr = corr
            best_lag = lag
    return best_lag, best_corr


def load_spec(path: Path) -> List[Dict[str, object]]:
    payload = json.loads(path.read_text())
    relations = payload.get("relations", [])
    if not relations:
        raise ValueError(f"No relations found in {path}")
    return relations


def relation_frame(prices: pd.DataFrame, relation: Dict[str, object]) -> pd.DataFrame:
    target = str(relation["target"])
    components = relation["components"]
    if not isinstance(components, dict) or not components:
        raise ValueError(f"Invalid components for relation {relation}")

    base = prices[prices["symbol"] == target][["day", "timestamp", "mid_price"]].rename(columns={"mid_price": "target_mid"})
    merged = base.copy()
    synthetic = pd.Series(0.0, index=merged.index, dtype=float)

    for symbol, weight in components.items():
        component = prices[prices["symbol"] == str(symbol)][["day", "timestamp", "mid_price"]].rename(
            columns={"mid_price": f"mid_{symbol}"}
        )
        merged = merged.merge(component, on=["day", "timestamp"], how="inner")
        synthetic = pd.Series(0.0, index=merged.index, dtype=float)
        for component_symbol, component_weight in components.items():
            synthetic += float(component_weight) * merged[f"mid_{component_symbol}"]
    merged["synthetic_mid"] = synthetic
    merged["spread"] = merged["target_mid"] - merged["synthetic_mid"]
    merged = merged.sort_values(["day", "timestamp"]).reset_index(drop=True)
    merged["target_ret_1"] = merged.groupby("day")["target_mid"].shift(-1) - merged["target_mid"]
    merged["synthetic_ret_1"] = merged.groupby("day")["synthetic_mid"].shift(-1) - merged["synthetic_mid"]
    merged["spread_ret_1"] = merged.groupby("day")["spread"].shift(-1) - merged["spread"]
    merged["spread_mean"] = merged.groupby("day")["spread"].transform("mean")
    merged["spread_std"] = merged.groupby("day")["spread"].transform("std").replace(0, np.nan)
    merged["spread_z"] = (merged["spread"] - merged["spread_mean"]) / merged["spread_std"]
    return merged


def markdown_report(prices: pd.DataFrame, relations: List[Dict[str, object]], data_dir: Path, max_lag: int, z_quantile: float) -> str:
    lines: List[str] = []
    lines.append(f"# Composite Signal Report — `{data_dir}`")
    lines.append("")
    lines.append("These scans are intended for ETF / basket / pair rounds.")
    lines.append("They separate mean reversion in the spread from true lead/lag between the target and synthetic legs.")
    lines.append("")

    for relation in relations:
        name = str(relation.get("name", relation["target"]))
        target = str(relation["target"])
        frame = relation_frame(prices, relation)
        if frame.empty:
            lines.append(f"## `{name}`")
            lines.append("")
            lines.append("- No overlapping timestamps between target and components.")
            lines.append("")
            continue

        lag, corr = best_lead_lag(frame["target_ret_1"], frame["synthetic_ret_1"], max_lag)
        half_life = spread_half_life(frame["spread"])
        z_cut = frame["spread_z"].abs().quantile(z_quantile)
        tails = frame[frame["spread_z"].abs() >= z_cut].copy()
        tails["revert_score"] = -np.sign(tails["spread_z"]) * tails["spread_ret_1"]

        lines.append(f"## `{name}`")
        lines.append("")
        lines.append(f"- Target: `{target}`")
        lines.append(f"- Components: `{relation['components']}`")
        lines.append(f"- Spread mean: `{frame['spread'].mean():+.3f}`")
        lines.append(f"- Spread std: `{frame['spread'].std():.3f}`")
        lines.append(f"- Spread AR(1) half-life: `{half_life:.3f}` ticks")
        lines.append(f"- Best target/synthetic lead-lag: lag=`{lag}`, |corr|=`{corr:.3f}`")
        lines.append(
            f"- Tail z-score reversion (`|z| >= q{int(z_quantile * 100)}`): "
            f"mean signed next spread move=`{tails['revert_score'].mean():+.3f}`, "
            f"hit-rate=`{(tails['revert_score'] > 0).mean():.3f}`, n=`{len(tails)}`"
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    price_files = discover_files(args.data_dir, "prices_")
    if not price_files:
        raise FileNotFoundError(f"No price files found under {args.data_dir}")

    prices = load_prices(price_files).sort_values(["symbol", "day", "timestamp"]).reset_index(drop=True)
    relations = load_spec(args.spec)
    output_path = args.output or (args.data_dir.parent / "composite_signal_report.md")
    report = markdown_report(prices, relations, args.data_dir, args.max_lag, args.z_quantile)
    output_path.write_text(report)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
