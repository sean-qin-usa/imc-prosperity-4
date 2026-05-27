from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

from visualizer import discover_files, load_prices


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan causal cross-asset propagation between raw and derived series."
    )
    parser.add_argument("--data-dir", type=Path, required=True, help="Directory with price files.")
    parser.add_argument("--spec", type=Path, required=True, help="JSON spec describing derived series and tests.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional markdown output path. Defaults to <data-dir>/../propagation_signal_report.md.",
    )
    parser.add_argument("--max-lag", type=int, default=5, help="Max causal lag to scan in ticks.")
    parser.add_argument(
        "--horizons",
        type=int,
        nargs="*",
        default=[1, 3, 5],
        help="Forward horizons for event studies.",
    )
    parser.add_argument(
        "--event-quantile",
        type=float,
        default=0.90,
        help="Upper quantile for large-move leader events. Lower tail uses 1-q.",
    )
    return parser.parse_args(argv)


def load_spec(path: Path) -> dict:
    payload = json.loads(path.read_text())
    if "series" not in payload or "tests" not in payload:
        raise ValueError(f"Spec {path} must contain `series` and `tests`.")
    return payload


def symbol_series(prices: pd.DataFrame, symbol: str, column: str = "mid_price") -> pd.DataFrame:
    subset = prices[prices["symbol"] == symbol][["day", "timestamp", column]].copy()
    subset = subset.rename(columns={column: "value"})
    subset["value"] = pd.to_numeric(subset["value"], errors="coerce")
    subset = subset.dropna(subset=["value"]).sort_values(["day", "timestamp"]).reset_index(drop=True)
    return subset


def merge_value_frames(
    frames: List[pd.DataFrame],
    names: List[str],
) -> pd.DataFrame:
    merged: pd.DataFrame | None = None
    for frame, name in zip(frames, names):
        renamed = frame.rename(columns={"value": name})
        if merged is None:
            merged = renamed
        else:
            merged = merged.merge(renamed, on=["day", "timestamp"], how="inner")
    return merged if merged is not None else pd.DataFrame(columns=["day", "timestamp"])


def linear_combo_series(series_map: Dict[str, pd.DataFrame], components: Dict[str, float]) -> pd.DataFrame:
    names = list(components.keys())
    merged = merge_value_frames([series_map[name] for name in names], names)
    value = pd.Series(0.0, index=merged.index, dtype=float)
    for name, weight in components.items():
        value = value + float(weight) * merged[name]
    return merged[["day", "timestamp"]].assign(value=value)


def difference_series(series_map: Dict[str, pd.DataFrame], lhs: str, rhs: str) -> pd.DataFrame:
    merged = merge_value_frames([series_map[lhs], series_map[rhs]], ["lhs", "rhs"])
    return merged[["day", "timestamp"]].assign(value=merged["lhs"] - merged["rhs"])


def detrended_series(series_map: Dict[str, pd.DataFrame], base: str) -> pd.DataFrame:
    frame = series_map[base].copy()
    frame = frame.sort_values(["day", "timestamp"]).reset_index(drop=True)

    def _fit(group: pd.DataFrame) -> pd.DataFrame:
        x = group["timestamp"].to_numpy(dtype=float)
        y = group["value"].to_numpy(dtype=float)
        if len(group) < 2:
            group = group.copy()
            group["value"] = np.nan
            return group
        xmat = np.column_stack([np.ones(len(group)), x])
        beta, *_ = np.linalg.lstsq(xmat, y, rcond=None)
        fitted = xmat @ beta
        out = group.copy()
        out["value"] = y - fitted
        return out

    parts: List[pd.DataFrame] = []
    for _, group in frame.groupby("day", sort=False):
        parts.append(_fit(group))
    frame = pd.concat(parts, ignore_index=True) if parts else frame.iloc[0:0].copy()
    return frame.dropna(subset=["value"]).reset_index(drop=True)


def build_series(prices: pd.DataFrame, spec: dict) -> Dict[str, pd.DataFrame]:
    series_map: Dict[str, pd.DataFrame] = {}
    for entry in spec["series"]:
        name = str(entry["name"])
        kind = str(entry["type"])
        if kind == "symbol":
            symbol = str(entry["symbol"])
            column = str(entry.get("column", "mid_price"))
            series_map[name] = symbol_series(prices, symbol, column=column)
        elif kind == "linear_combo":
            components = entry["components"]
            if not isinstance(components, dict) or not components:
                raise ValueError(f"Series `{name}` has invalid components.")
            missing = [component for component in components if component not in series_map]
            if missing:
                raise KeyError(f"Series `{name}` references unknown components: {missing}")
            series_map[name] = linear_combo_series(series_map, components)
        elif kind == "difference":
            lhs = str(entry["lhs"])
            rhs = str(entry["rhs"])
            if lhs not in series_map or rhs not in series_map:
                raise KeyError(f"Series `{name}` references unknown parents: {lhs}, {rhs}")
            series_map[name] = difference_series(series_map, lhs, rhs)
        elif kind == "detrended":
            base = str(entry["base"])
            if base not in series_map:
                raise KeyError(f"Series `{name}` references unknown base: {base}")
            series_map[name] = detrended_series(series_map, base)
        else:
            raise ValueError(f"Unknown series type `{kind}` for `{name}`")
    return series_map


def aligned_pair_frame(leader: pd.DataFrame, follower: pd.DataFrame, horizons: Sequence[int]) -> pd.DataFrame:
    merged = leader.merge(follower, on=["day", "timestamp"], how="inner", suffixes=("_leader", "_follower"))
    merged = merged.sort_values(["day", "timestamp"]).reset_index(drop=True)
    merged["leader_move_in"] = merged.groupby("day")["value_leader"].diff()
    for horizon in horizons:
        merged[f"follower_fwd_{horizon}"] = (
            merged.groupby("day")["value_follower"].shift(-horizon) - merged["value_follower"]
        )
    return merged


def lagged_follower_ret(frame: pd.DataFrame, lag: int) -> pd.Series:
    start = frame.groupby("day")["value_follower"].shift(-lag)
    end = frame.groupby("day")["value_follower"].shift(-(lag + 1))
    return end - start


def best_causal_lag(frame: pd.DataFrame, max_lag: int) -> tuple[int, float]:
    best_lag = 0
    best_corr = 0.0
    for lag in range(max_lag + 1):
        follower_ret = lagged_follower_ret(frame, lag)
        mask = frame["leader_move_in"].notna() & follower_ret.notna()
        if int(mask.sum()) < 20:
            continue
        corr = float(frame.loc[mask, "leader_move_in"].corr(follower_ret[mask]))
        if abs(corr) > abs(best_corr):
            best_corr = corr
            best_lag = lag
    return best_lag, best_corr


def tail_event_summary(frame: pd.DataFrame, horizons: Sequence[int], event_quantile: float) -> dict:
    move = frame["leader_move_in"]
    up_cut = move.quantile(event_quantile)
    dn_cut = move.quantile(1.0 - event_quantile)
    up_tail = frame[move >= up_cut].copy()
    dn_tail = frame[move <= dn_cut].copy()

    summary: dict = {
        "up_cut": float(up_cut) if pd.notna(up_cut) else np.nan,
        "dn_cut": float(dn_cut) if pd.notna(dn_cut) else np.nan,
        "up_n": int(len(up_tail)),
        "dn_n": int(len(dn_tail)),
        "horizons": {},
    }
    for horizon in horizons:
        up_ret = up_tail[f"follower_fwd_{horizon}"]
        dn_ret = dn_tail[f"follower_fwd_{horizon}"]
        up_mask = up_ret.notna()
        dn_mask = dn_ret.notna()
        summary["horizons"][horizon] = {
            "up_mean": float(up_ret[up_mask].mean()) if int(up_mask.sum()) else np.nan,
            "up_hit": float((up_ret[up_mask] > 0).mean()) if int(up_mask.sum()) else np.nan,
            "dn_mean": float(dn_ret[dn_mask].mean()) if int(dn_mask.sum()) else np.nan,
            "dn_hit": float((dn_ret[dn_mask] < 0).mean()) if int(dn_mask.sum()) else np.nan,
            "signed_mean": float(
                pd.concat([up_ret[up_mask], -dn_ret[dn_mask]], ignore_index=True).mean()
            )
            if int(up_mask.sum()) or int(dn_mask.sum())
            else np.nan,
        }
    return summary


def markdown_report(
    series_map: Dict[str, pd.DataFrame],
    tests: List[dict],
    data_dir: Path,
    max_lag: int,
    horizons: Sequence[int],
    event_quantile: float,
) -> str:
    lines: List[str] = []
    lines.append(f"# Propagation Signal Report — `{data_dir}`")
    lines.append("")
    lines.append("This report asks a causal question:")
    lines.append("")
    lines.append("- after observing a move in leader series A, does follower series B move in the same direction later?")
    lines.append("")
    lines.append("It is intended for:")
    lines.append("")
    lines.append("- constituent -> basket premium propagation")
    lines.append("- underlying -> option residual propagation")
    lines.append("- raw product -> derived residual propagation")
    lines.append("")

    for test in tests:
        leader_name = str(test["leader"])
        follower_name = str(test["follower"])
        title = str(test.get("name", f"{leader_name}_to_{follower_name}"))
        if leader_name not in series_map or follower_name not in series_map:
            lines.append(f"## `{title}`")
            lines.append("")
            lines.append(f"- Missing series: leader=`{leader_name}`, follower=`{follower_name}`")
            lines.append("")
            continue

        frame = aligned_pair_frame(series_map[leader_name], series_map[follower_name], horizons)
        if frame.empty:
            lines.append(f"## `{title}`")
            lines.append("")
            lines.append("- No overlapping timestamps.")
            lines.append("")
            continue

        best_lag, best_corr = best_causal_lag(frame, int(test.get("max_lag", max_lag)))
        event_summary = tail_event_summary(frame, horizons, float(test.get("event_quantile", event_quantile)))

        lines.append(f"## `{title}`")
        lines.append("")
        lines.append(f"- Leader: `{leader_name}`")
        lines.append(f"- Follower: `{follower_name}`")
        lines.append(f"- Overlapping rows: `{len(frame)}`")
        lines.append(
            f"- Best causal return lag: leader move into `t` vs follower one-tick return starting `t+{best_lag}`"
            f", corr=`{best_corr:+.3f}`"
        )
        lines.append(
            f"- Leader tail cuts: up >= `{event_summary['up_cut']:+.3f}`, down <= `{event_summary['dn_cut']:+.3f}`"
            f" with n_up=`{event_summary['up_n']}`, n_down=`{event_summary['dn_n']}`"
        )
        for horizon in horizons:
            horizon_summary = event_summary["horizons"][horizon]
            lines.append(
                f"- Follower forward `{horizon}`-tick response:"
                f" signed_mean=`{horizon_summary['signed_mean']:+.3f}`,"
                f" up_mean=`{horizon_summary['up_mean']:+.3f}`, up_hit=`{horizon_summary['up_hit']:.3f}`,"
                f" down_mean=`{horizon_summary['dn_mean']:+.3f}`, down_hit=`{horizon_summary['dn_hit']:.3f}`"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    price_files = discover_files(args.data_dir, "prices_")
    if not price_files:
        raise FileNotFoundError(f"No price files found under {args.data_dir}")

    prices = load_prices(price_files).sort_values(["symbol", "day", "timestamp"]).reset_index(drop=True)
    spec = load_spec(args.spec)
    series_map = build_series(prices, spec)

    output_path = args.output or (args.data_dir.parent / "propagation_signal_report.md")
    report = markdown_report(series_map, list(spec["tests"]), args.data_dir, args.max_lag, args.horizons, args.event_quantile)
    output_path.write_text(report)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
