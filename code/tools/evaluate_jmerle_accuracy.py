from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from backtester import load_run_log
from jmerle_backtester import (
    TradeMatchingMode,
    market_dataset_to_backtest_data,
    run_backtest_data,
)


SUBMISSION_TAG = "SUBMISSION"
DEFAULT_SEARCH_ROOT = Path("/Users/sean_tsu_/Downloads")
DEFAULT_OUTPUT_ROOT = Path("/Users/sean_tsu_/Downloads/prosperity/gen/jmerle_accuracy")


@dataclass
class Bundle:
    bundle_id: str
    root: Path
    json_path: Path
    log_path: Path
    strategy_path: Path


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the jmerle-style same-tick backtester against official Prosperity bundle logs."
    )
    parser.add_argument(
        "--search-root",
        type=Path,
        default=DEFAULT_SEARCH_ROOT,
        help="Root directory to scan for official bundle directories.",
    )
    parser.add_argument(
        "--bundle",
        action="append",
        default=[],
        help="Optional bundle id(s) to restrict evaluation to, e.g. 125928.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory for CSV outputs.",
    )
    parser.add_argument(
        "--match-trades",
        choices=[mode.value for mode in TradeMatchingMode],
        default=TradeMatchingMode.all.value,
        help="Trade matching mode for the jmerle-style same-tick replay.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="How many worst bundles by absolute final-PnL error to print.",
    )
    return parser.parse_args(argv)


def parse_graph_log(graph_log: str) -> Optional[pd.DataFrame]:
    if not graph_log:
        return None
    rows: List[Tuple[int, float]] = []
    for line in graph_log.splitlines()[1:]:
        parts = line.split(";")
        if len(parts) != 2:
            continue
        try:
            rows.append((int(parts[0]), float(parts[1])))
        except ValueError:
            continue
    if not rows:
        return None
    return pd.DataFrame(rows, columns=["timestamp", "official_value"]).sort_values("timestamp")


def compare_graph(official: pd.DataFrame, local: pd.DataFrame) -> Tuple[float, float, int]:
    merged = official.merge(local[["timestamp", "total_pnl"]], on="timestamp", how="inner")
    if merged.empty:
        return float("nan"), float("nan"), 0
    error = merged["total_pnl"] - merged["official_value"]
    mae = float(error.abs().mean())
    rmse = float(math.sqrt((error**2).mean()))
    return mae, rmse, int(len(merged))


def result_to_equity_frame(result) -> pd.DataFrame:
    rows: List[Dict[str, float]] = []
    for activity in result.activity_logs:
        rows.append(
            {
                "timestamp": int(activity.timestamp),
                "pnl": float(activity.columns[-1]),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["timestamp", "total_pnl"])
    frame = pd.DataFrame(rows)
    return (
        frame.groupby("timestamp", as_index=False)["pnl"]
        .sum()
        .rename(columns={"pnl": "total_pnl"})
        .sort_values("timestamp")
    )


def final_total_from_equity(equity: pd.DataFrame) -> float:
    if equity.empty:
        return 0.0
    return float(equity["total_pnl"].iloc[-1])


def discover_bundles(search_root: Path) -> List[Bundle]:
    candidates: Dict[str, Bundle] = {}
    for directory in sorted(search_root.iterdir()):
        if not directory.is_dir():
            continue
        prefix = directory.name.split()[0]
        if not prefix.isdigit():
            continue
        json_path = directory / f"{prefix}.json"
        log_path = directory / f"{prefix}.log"
        strategy_path = directory / f"{prefix}.py"
        if not (json_path.exists() and log_path.exists() and strategy_path.exists()):
            continue

        bundle = Bundle(
            bundle_id=prefix,
            root=directory,
            json_path=json_path,
            log_path=log_path,
            strategy_path=strategy_path,
        )
        existing = candidates.get(prefix)
        if existing is None:
            candidates[prefix] = bundle
            continue

        existing_score = (existing.root.name != prefix, len(str(existing.root)))
        new_score = (directory.name != prefix, len(str(directory)))
        if new_score < existing_score:
            candidates[prefix] = bundle

    return [candidates[key] for key in sorted(candidates)]


def bundle_log_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evaluate_bundle(bundle: Bundle, trade_matching_mode: TradeMatchingMode) -> Dict[str, object]:
    payload = json.loads(bundle.json_path.read_text())
    round_num = int(payload.get("round", 0))
    status = str(payload.get("status", "UNKNOWN"))
    official_profit_raw = payload.get("profit")

    if status != "FINISHED" or official_profit_raw is None:
        return {
            "bundle_id": bundle.bundle_id,
            "root": str(bundle.root),
            "round": round_num,
            "day": float("nan"),
            "status": status,
            "skip_reason": "bundle_not_finished_or_missing_profit",
            "official_profit": float("nan"),
            "local_final": float("nan"),
            "local_minus_official": float("nan"),
            "abs_diff": float("nan"),
            "graph_mae": float("nan"),
            "graph_rmse": float("nan"),
            "graph_points": 0,
            "submission_trade_count": float("nan"),
            "submission_fill_qty": float("nan"),
            "log_sha256": bundle_log_hash(bundle.log_path),
        }

    dataset = load_run_log(bundle.log_path)

    trades = dataset.trades.copy()
    if trades.empty:
        submission_trade_count = 0
        submission_fill_qty = 0
    else:
        buyer = trades.get("buyer", pd.Series([""] * len(trades))).fillna("").astype(str)
        seller = trades.get("seller", pd.Series([""] * len(trades))).fillna("").astype(str)
        own_trades = trades.loc[buyer.eq(SUBMISSION_TAG) | seller.eq(SUBMISSION_TAG)].copy()
        submission_trade_count = int(len(own_trades))
        submission_fill_qty = int(own_trades["quantity"].abs().sum()) if not own_trades.empty else 0

    backtest_data = market_dataset_to_backtest_data(
        dataset=dataset,
        round_num=round_num,
        day_num=None,
        exclude_submission_trades=True,
    )

    result = run_backtest_data(
        strategy_path=bundle.strategy_path,
        data=backtest_data,
        print_output=False,
        trade_matching_mode=trade_matching_mode,
        show_progress_bar=False,
    )
    local_equity = result_to_equity_frame(result)
    local_final = final_total_from_equity(local_equity)

    official_profit = float(official_profit_raw)

    graph_df = parse_graph_log(payload.get("graphLog", ""))
    graph_mae = float("nan")
    graph_rmse = float("nan")
    graph_points = 0
    if graph_df is not None and not local_equity.empty:
        graph_mae, graph_rmse, graph_points = compare_graph(graph_df, local_equity)

    diff = local_final - official_profit if not math.isnan(official_profit) else float("nan")
    abs_diff = abs(diff) if not math.isnan(diff) else float("nan")

    return {
        "bundle_id": bundle.bundle_id,
        "root": str(bundle.root),
        "round": round_num,
        "day": int(backtest_data.day_num),
        "status": status,
        "skip_reason": "",
        "official_profit": official_profit,
        "local_final": local_final,
        "local_minus_official": diff,
        "abs_diff": abs_diff,
        "graph_mae": graph_mae,
        "graph_rmse": graph_rmse,
        "graph_points": graph_points,
        "submission_trade_count": submission_trade_count,
        "submission_fill_qty": submission_fill_qty,
        "log_sha256": bundle_log_hash(bundle.log_path),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    bundles = discover_bundles(args.search_root.expanduser().resolve())
    if args.bundle:
        wanted = set(args.bundle)
        bundles = [bundle for bundle in bundles if bundle.bundle_id in wanted]
    if not bundles:
        raise SystemExit("No matching bundle directories found.")

    rows: List[Dict[str, object]] = []
    errors: List[Dict[str, str]] = []
    trade_matching_mode = TradeMatchingMode(str(args.match_trades))

    for bundle in bundles:
        try:
            rows.append(evaluate_bundle(bundle, trade_matching_mode=trade_matching_mode))
        except Exception as exc:
            errors.append(
                {
                    "bundle_id": bundle.bundle_id,
                    "root": str(bundle.root),
                    "error": repr(exc),
                }
            )

    output_dir = args.output_dir.expanduser().resolve() / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    frame = pd.DataFrame(rows).sort_values(["round", "bundle_id"]).reset_index(drop=True)
    results_path = output_dir / "results.csv"
    frame.to_csv(results_path, index=False)

    if errors:
        error_frame = pd.DataFrame(errors)
        error_frame.to_csv(output_dir / "errors.csv", index=False)
    else:
        error_frame = pd.DataFrame(columns=["bundle_id", "root", "error"])

    scored = frame[frame["skip_reason"].fillna("").eq("")]
    skipped = frame[frame["skip_reason"].fillna("").ne("")]

    print(f"Discovered bundles: {len(frame)}")
    print(f"Scored bundles: {len(scored)}")
    print(f"Skipped bundles: {len(skipped)}")
    print(f"Errors: {len(error_frame)}")
    print(f"Results CSV: {results_path}")

    if not scored.empty:
        exact = scored["abs_diff"].fillna(float("inf")).eq(0.0)
        within_10 = scored["abs_diff"].fillna(float("inf")).le(10.0)
        within_100 = scored["abs_diff"].fillna(float("inf")).le(100.0)
        print(f"Exact final-profit matches: {int(exact.sum())}/{len(scored)}")
        print(f"Within 10 PnL: {int(within_10.sum())}/{len(scored)}")
        print(f"Within 100 PnL: {int(within_100.sum())}/{len(scored)}")

        print("\nWorst bundles by absolute final-profit error:")
        top = scored.sort_values("abs_diff", ascending=False).head(max(1, int(args.top)))
        print(
            top[
                [
                    "bundle_id",
                    "round",
                    "status",
                    "official_profit",
                    "local_final",
                    "local_minus_official",
                    "abs_diff",
                    "graph_mae",
                    "graph_points",
                ]
            ].to_string(index=False)
        )

    if not skipped.empty:
        print("\nSkipped bundles:")
        print(skipped[["bundle_id", "round", "status", "skip_reason", "root"]].to_string(index=False))

    if not error_frame.empty:
        print("\nBundle evaluation errors:")
        print(error_frame.to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
