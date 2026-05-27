"""
Compare local backtester results against an official Prosperity submission log.

Usage example:
  python3 tools/official_compare.py \
    --official-json /tmp/prosperity_submission_84960/86769.json \
    --official-log /tmp/prosperity_submission_84960/86769.log \
    --strategy /tmp/prosperity_submission_84960/86769.py \
    --fill-model same-tick \
    --match-trades all

  python3 tools/official_compare.py \
    --official-json /tmp/prosperity_submission_84960/86769.json \
    --official-log /tmp/prosperity_submission_84960/86769.log \
    --strategy /tmp/prosperity_submission_84960/86769.py \
    --fill-model interval \
    --sweep-queue-alpha 0.1,0.25,0.5,0.75,1,1.25,1.5,2,3
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import pandas as pd

from backtester import (
    DEFAULT_EXCHANGE_CALIBRATION_PATH,
    load_exchange_calibration,
    load_run_log,
    run_backtest,
)


def parse_graph_log(graph_log: str) -> Optional[pd.DataFrame]:
    if not graph_log:
        return None
    rows: List[Tuple[int, float]] = []
    reader = csv.DictReader(graph_log.splitlines(), delimiter=";")
    for row in reader:
        try:
            ts = int(row["timestamp"])
            val = float(row["value"])
            rows.append((ts, val))
        except Exception:
            continue
    if not rows:
        return None
    frame = pd.DataFrame(rows, columns=["timestamp", "official_value"]).sort_values("timestamp")
    return frame


def compare_graph(official: pd.DataFrame, local: pd.DataFrame) -> Tuple[float, float, int, pd.DataFrame]:
    """
    Returns (mae, rmse, matched_points). Requires local to have columns timestamp, total_pnl.
    """
    local_sorted = local.sort_values("timestamp").copy()
    local_sorted["timestamp"] = local_sorted["timestamp"].astype(int)
    official_sorted = official.sort_values("timestamp").copy()
    official_sorted["timestamp"] = official_sorted["timestamp"].astype(int)

    merged = official_sorted.merge(local_sorted[["timestamp", "total_pnl"]], on="timestamp", how="left")
    merged = merged.dropna(subset=["total_pnl"]).copy()
    if merged.empty:
        return float("nan"), float("nan"), 0, merged
    errors = merged["total_pnl"] - merged["official_value"]
    mae = float(errors.abs().mean())
    rmse = float(math.sqrt((errors**2).mean()))
    merged["error"] = errors
    merged["abs_error"] = errors.abs()
    return mae, rmse, int(len(merged)), merged


def replay_official_equity(dataset, timing: str) -> pd.DataFrame:
    prices = dataset.prices.copy().sort_values(["day", "timestamp", "product"]).reset_index(drop=True)
    trades = dataset.trades.copy().sort_values(["day", "timestamp", "symbol"]).reset_index(drop=True)
    symbols = sorted(prices["product"].unique().tolist())
    positions = {symbol: 0 for symbol in symbols}
    cash = {symbol: 0.0 for symbol in symbols}

    equity_rows: List[dict] = []

    for day in sorted(prices["day"].unique().tolist()):
        day_prices = prices[prices["day"] == day].copy()
        day_trades = trades[trades["day"] == day].copy()
        timestamps = sorted(day_prices["timestamp"].unique().tolist())

        for timestamp in timestamps:
            tick_trades = day_trades[day_trades["timestamp"] == timestamp]
            if timing == "before":
                positions, cash = _apply_official_trades(tick_trades, positions, cash)

            tick_rows = day_prices[day_prices["timestamp"] == timestamp]
            mids = {str(row.product): float(row.mid_price) for row in tick_rows.itertuples(index=False)}

            total = 0.0
            for symbol in symbols:
                total += cash[symbol] + positions[symbol] * float(mids.get(symbol, 0.0))

            equity_rows.append(
                {
                    "day": int(day),
                    "timestamp": int(timestamp),
                    "total_pnl": total,
                }
            )

            if timing == "after":
                positions, cash = _apply_official_trades(tick_trades, positions, cash)

    return pd.DataFrame(equity_rows)


def _apply_official_trades(
    tick_trades: pd.DataFrame,
    positions: dict,
    cash: dict,
) -> Tuple[dict, dict]:
    for trade in tick_trades.itertuples(index=False):
        buyer = str(getattr(trade, "buyer", "")) if getattr(trade, "buyer", "") is not None else ""
        seller = str(getattr(trade, "seller", "")) if getattr(trade, "seller", "") is not None else ""
        if buyer != "SUBMISSION" and seller != "SUBMISSION":
            continue
        signed_qty = int(trade.quantity)
        if seller == "SUBMISSION":
            signed_qty = -signed_qty
        symbol = str(trade.symbol)
        price = float(trade.price)
        cash[symbol] -= signed_qty * price
        positions[symbol] += signed_qty
    return positions, cash


def activities_pnl_equity(dataset) -> pd.DataFrame:
    prices = dataset.prices.copy().sort_values(["day", "timestamp", "product"]).reset_index(drop=True)
    if "profit_and_loss" not in prices.columns:
        return pd.DataFrame(columns=["day", "timestamp", "total_pnl"])
    grouped = (
        prices.groupby(["day", "timestamp"], as_index=False)["profit_and_loss"]
        .sum()
        .rename(columns={"profit_and_loss": "total_pnl"})
    )
    return grouped


def official_log_diagnostics(dataset) -> dict:
    trades = dataset.trades.copy()
    if trades.empty:
        own_trades = trades
    else:
        buyer = trades.get("buyer", pd.Series([""] * len(trades))).fillna("").astype(str)
        seller = trades.get("seller", pd.Series([""] * len(trades))).fillna("").astype(str)
        own_trades = trades.loc[buyer.eq("SUBMISSION") | seller.eq("SUBMISSION")].copy()

    activities = activities_pnl_equity(dataset)
    final_activities_total = float(activities["total_pnl"].iloc[-1]) if not activities.empty else 0.0
    own_fill_qty = int(own_trades["quantity"].abs().sum()) if not own_trades.empty else 0

    return {
        "dataset_name": dataset.name,
        "submission_trade_count": int(len(own_trades)),
        "submission_fill_qty": own_fill_qty,
        "final_activities_total": final_activities_total,
        "looks_like_benchmark_data_market_log": int(len(own_trades)) == 0 and abs(final_activities_total) < 1e-9,
    }


def normalize_fill_modes(fill_model: str, market_trades_mode: str, fill_trades_mode: str) -> tuple[str, str]:
    resolved_market_trades_mode = market_trades_mode
    resolved_fill_trades_mode = fill_trades_mode
    if fill_model == "official-hybrid":
        if resolved_market_trades_mode == "all":
            resolved_market_trades_mode = "external-only"
        if resolved_fill_trades_mode == "auto":
            resolved_fill_trades_mode = "external-only"
    return resolved_market_trades_mode, resolved_fill_trades_mode


def run_single(
    dataset_path: Path,
    strategy_path: Path,
    output_root: Path,
    fill_model: str,
    match_trades: str,
    queue_alpha: float,
    trade_fill_price: str,
    book_delta_on_disappear: str,
    market_trades_mode: str,
    fill_trades_mode: str,
    exchange_calibration: Optional[Path],
    run_label: str,
) -> Tuple[float, pd.DataFrame]:
    dataset = load_run_log(dataset_path)
    run_dir = output_root / run_label
    run_dir.mkdir(parents=True, exist_ok=True)
    calibration_path = exchange_calibration
    if calibration_path is None and fill_model == "official-hybrid" and DEFAULT_EXCHANGE_CALIBRATION_PATH.exists():
        calibration_path = DEFAULT_EXCHANGE_CALIBRATION_PATH
    result = run_backtest(
        strategy_path=strategy_path,
        dataset=dataset,
        output_dir=run_dir,
        reuse_trader_instance=False,
        queue_alpha=queue_alpha,
        make_plots=False,
        fill_model=fill_model,
        match_trades=match_trades,
        trade_fill_price=trade_fill_price,
        book_delta_on_disappear=book_delta_on_disappear,
        market_trades_mode=market_trades_mode,
        fill_trades_mode=fill_trades_mode,
        exchange_calibration=load_exchange_calibration(calibration_path),
    )
    summary = result.summary
    if summary.empty:
        raise RuntimeError("Backtest summary is empty.")
    final_total = float(summary.iloc[0]["final_total_pnl"])
    equity_curve = result.equity_curve
    return final_total, equity_curve


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare local backtester vs official submission log.")
    parser.add_argument("--official-json", type=Path, required=True)
    parser.add_argument("--official-log", type=Path, required=True)
    parser.add_argument("--strategy", type=Path, required=True)
    parser.add_argument("--fill-model", choices=["same-tick", "interval", "book-delta", "official-hybrid"], default="same-tick")
    parser.add_argument("--match-trades", choices=["all", "worse", "none"], default="all")
    parser.add_argument("--trade-fill-price", choices=["order", "trade"], default="order")
    parser.add_argument("--book-delta-on-disappear", choices=["never", "if-through", "always"], default="if-through")
    parser.add_argument("--market-trades", choices=["all", "external-only", "none"], default="all")
    parser.add_argument(
        "--fill-trades",
        choices=["auto", "all", "external-only", "none"],
        default="auto",
        help="Which trades to use for fill simulation. auto follows --market-trades.",
    )
    parser.add_argument(
        "--replay-official",
        action="store_true",
        help="Replay the official tradeHistory as fills to validate PnL math instead of simulating fills.",
    )
    parser.add_argument(
        "--replay-activities",
        action="store_true",
        help="Use profit_and_loss from activitiesLog to reconstruct the official PnL series exactly.",
    )
    parser.add_argument(
        "--replay-timing",
        choices=["before", "after"],
        default="before",
        help="Apply official trades before or after marking PnL for each timestamp.",
    )
    parser.add_argument("--queue-alpha", type=float, default=1.0)
    parser.add_argument("--exchange-calibration", type=Path, default=None)
    parser.add_argument("--sweep-queue-alpha", type=str, default="")
    parser.add_argument("--export-diff", type=Path, default=None)
    parser.add_argument("--top-errors", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("/tmp/prosperity_compare"))
    args = parser.parse_args()

    if not args.official_json.exists():
        raise SystemExit(f"Official json not found: {args.official_json}")
    if not args.official_log.exists():
        raise SystemExit(f"Official log not found: {args.official_log}")
    if not args.strategy.exists():
        raise SystemExit(f"Strategy file not found: {args.strategy}")

    official = json.loads(args.official_json.read_text())
    official_profit = float(official.get("profit", 0.0))
    graph_df = parse_graph_log(official.get("graphLog", ""))
    dataset = load_run_log(args.official_log)
    diagnostics = official_log_diagnostics(dataset)
    resolved_market_trades_mode, resolved_fill_trades_mode = normalize_fill_modes(
        fill_model=str(args.fill_model),
        market_trades_mode=str(args.market_trades),
        fill_trades_mode=str(args.fill_trades),
    )

    output_root = args.output
    output_root.mkdir(parents=True, exist_ok=True)

    if args.sweep_queue_alpha:
        alphas = [float(x.strip()) for x in args.sweep_queue_alpha.split(",") if x.strip()]
        if not alphas:
            raise SystemExit("--sweep-queue-alpha provided but empty.")
        rows = []
        for alpha in alphas:
            label = f"{args.fill_model}_qa_{alpha}"
            final_total, equity = run_single(
                dataset_path=args.official_log,
                strategy_path=args.strategy,
                output_root=output_root,
                fill_model=args.fill_model,
                match_trades=args.match_trades,
                queue_alpha=alpha,
                trade_fill_price=args.trade_fill_price,
                book_delta_on_disappear=args.book_delta_on_disappear,
                market_trades_mode=resolved_market_trades_mode,
                fill_trades_mode=resolved_fill_trades_mode,
                exchange_calibration=args.exchange_calibration,
                run_label=label,
            )
            mae = rmse = float("nan")
            matched = 0
            if graph_df is not None and "total_pnl" in equity.columns:
                mae, rmse, matched, merged = compare_graph(graph_df, equity)
                if args.export_diff:
                    export_path = args.export_diff.with_suffix(f".qa_{alpha}.csv")
                    merged.to_csv(export_path, index=False)
            else:
                merged = None
            rows.append(
                {
                    "queue_alpha": alpha,
                    "local_final": final_total,
                    "official_profit": official_profit,
                    "diff": official_profit - final_total,
                    "abs_diff": abs(official_profit - final_total),
                    "graph_mae": mae,
                    "graph_rmse": rmse,
                    "graph_points": matched,
                }
            )

        frame = pd.DataFrame(rows).sort_values("abs_diff")
        print(frame.to_string(index=False))
        return 0

    # single run
    if args.replay_official and args.replay_activities:
        raise SystemExit("Choose only one of --replay-official or --replay-activities.")

    if args.replay_activities:
        equity = activities_pnl_equity(dataset)
        final_total = float(equity["total_pnl"].iloc[-1]) if not equity.empty else 0.0
    elif args.replay_official:
        equity = replay_official_equity(dataset, timing=str(args.replay_timing))
        final_total = float(equity["total_pnl"].iloc[-1]) if not equity.empty else 0.0
    else:
        label = f"{args.fill_model}_qa_{args.queue_alpha}_match_{args.match_trades}"
        final_total, equity = run_single(
            dataset_path=args.official_log,
            strategy_path=args.strategy,
            output_root=output_root,
            fill_model=args.fill_model,
            match_trades=args.match_trades,
            queue_alpha=args.queue_alpha,
            trade_fill_price=args.trade_fill_price,
            book_delta_on_disappear=args.book_delta_on_disappear,
            market_trades_mode=resolved_market_trades_mode,
            fill_trades_mode=resolved_fill_trades_mode,
            exchange_calibration=args.exchange_calibration,
            run_label=label,
        )

    print(f"official_log_dataset: {diagnostics['dataset_name']}")
    print(f"official_log_submission_trades: {diagnostics['submission_trade_count']}")
    print(f"official_log_submission_fill_qty: {diagnostics['submission_fill_qty']}")
    print(f"official_log_activities_final: {diagnostics['final_activities_total']}")
    if diagnostics["looks_like_benchmark_data_market_log"]:
        print(
            "warning: official-log has no SUBMISSION-tagged trades and activitiesLog ends at 0.0; "
            "this looks like a benchmark-data market log, not an official submission result."
        )
    if abs(diagnostics["final_activities_total"] - official_profit) > 1e-6:
        print(
            "warning: official json profit and official log activitiesLog final differ by "
            f"{diagnostics['final_activities_total'] - official_profit}"
        )
    print(f"resolved_market_trades: {resolved_market_trades_mode}")
    print(f"resolved_fill_trades: {resolved_fill_trades_mode}")
    print(f"official_profit: {official_profit}")
    print(f"local_final: {final_total}")
    print(f"diff: {official_profit - final_total}")

    if graph_df is not None and "total_pnl" in equity.columns:
        mae, rmse, matched, merged = compare_graph(graph_df, equity)
        print(f"graph_mae: {mae}")
        print(f"graph_rmse: {rmse}")
        print(f"graph_points: {matched}")
        if args.export_diff:
            merged.to_csv(args.export_diff, index=False)
        if args.top_errors and args.top_errors > 0 and matched > 0 and "abs_error" in merged.columns:
            top = merged.sort_values("abs_error", ascending=False).head(args.top_errors)
            print("top_errors:")
            print(top[["timestamp", "official_value", "total_pnl", "error", "abs_error"]].to_string(index=False))
        elif matched == 0:
            print("top_errors: skipped (no overlapping timestamps for graph comparison).")
    else:
        print("graph comparison skipped (no graphLog or total_pnl).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
