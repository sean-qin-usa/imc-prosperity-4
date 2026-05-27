from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional, Sequence

import pandas as pd
from pandas.errors import EmptyDataError

from backtester import (
    DEFAULT_OUTPUT_ROOT,
    plot_equity_curve,
    plot_execution_summary,
    plot_fill_activity,
    plot_order_activity,
    plot_positions,
    plot_symbol_market,
    write_html_report,
)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regenerate plots and report.html from an existing backtest run."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="latest",
        help="Run directory, dataset directory, or 'latest' under the workspace gen/backtests",
    )
    parser.add_argument(
        "--dataset",
        nargs="*",
        default=None,
        help="Optional dataset directory names to plot within a run directory",
    )
    return parser.parse_args(argv)


def resolve_latest_run(run_root: Path) -> Path:
    latest_link = run_root / "latest"
    if latest_link.exists():
        return latest_link.resolve()

    latest_txt = run_root / "LATEST.txt"
    if latest_txt.exists():
        return Path(latest_txt.read_text().strip()).expanduser().resolve()

    raise FileNotFoundError(f"Could not resolve latest run from {run_root}")


def resolve_target(path_arg: str) -> Path:
    if path_arg == "latest":
        return resolve_latest_run(DEFAULT_OUTPUT_ROOT)
    return Path(path_arg).expanduser().resolve()


def is_dataset_dir(path: Path) -> bool:
    return path.is_dir() and (path / "equity_curve.csv").exists()


def discover_dataset_dirs(run_dir: Path) -> List[Path]:
    dataset_dirs = [
        child
        for child in sorted(run_dir.iterdir())
        if child.is_dir() and (child / "equity_curve.csv").exists()
    ]
    if not dataset_dirs:
        raise FileNotFoundError(f"No dataset directories found under {run_dir}")
    return dataset_dirs


def load_csv(path: Path, empty_columns: Sequence[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=list(empty_columns))
    try:
        frame = pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame(columns=list(empty_columns))
    if frame.empty:
        return pd.DataFrame(columns=frame.columns if len(frame.columns) else list(empty_columns))
    return frame


def load_summary(dataset_dir: Path, run_dir: Path) -> pd.DataFrame:
    summary_path = dataset_dir / "summary.csv"
    if summary_path.exists():
        return pd.read_csv(summary_path)

    run_summary_path = run_dir / "run_summary.csv"
    if run_summary_path.exists():
        run_summary = pd.read_csv(run_summary_path)
        filtered = run_summary[run_summary["dataset"] == dataset_dir.name]
        if not filtered.empty:
            return filtered

    raise FileNotFoundError(f"Could not find summary data for {dataset_dir}")


def infer_symbols(equity_curve: pd.DataFrame) -> List[str]:
    return sorted(
        column.removeprefix("position_")
        for column in equity_curve.columns
        if column.startswith("position_")
    )


def regenerate_dataset_plots(dataset_dir: Path, run_dir: Path) -> List[Path]:
    summary = load_summary(dataset_dir, run_dir)
    equity_curve = pd.read_csv(dataset_dir / "equity_curve.csv")
    fills = load_csv(
        dataset_dir / "fills.csv",
        empty_columns=["dataset", "day", "timestamp", "step", "symbol", "side", "quantity", "price", "liquidity", "order_price"],
    )
    orders = load_csv(
        dataset_dir / "orders.csv",
        empty_columns=["dataset", "day", "timestamp", "step", "symbol", "side", "price", "requested_qty", "executed_qty", "remaining_qty", "immediate_qty", "passive_qty", "fill_count", "cancelled_by_limit"],
    )

    if equity_curve.empty:
        raise ValueError(f"equity_curve.csv is empty for {dataset_dir}")

    symbols = infer_symbols(equity_curve)
    chart_paths: List[Path] = []

    equity_path = dataset_dir / "equity_curve.png"
    plot_equity_curve(equity_curve, equity_path, f"{dataset_dir.name} equity curve")
    chart_paths.append(equity_path)

    order_activity_path = dataset_dir / "order_activity.png"
    plot_order_activity(orders, order_activity_path, f"{dataset_dir.name} order activity")
    if order_activity_path.exists():
        chart_paths.append(order_activity_path)

    execution_summary_path = dataset_dir / "execution_summary.png"
    plot_execution_summary(orders, fills, execution_summary_path, f"{dataset_dir.name} execution summary")
    if execution_summary_path.exists():
        chart_paths.append(execution_summary_path)

    fill_activity_path = dataset_dir / "fill_activity.png"
    plot_fill_activity(fills, fill_activity_path, f"{dataset_dir.name} fill activity")
    if fill_activity_path.exists():
        chart_paths.append(fill_activity_path)

    positions_path = dataset_dir / "positions.png"
    plot_positions(equity_curve, positions_path, symbols)
    chart_paths.append(positions_path)

    if not fills.empty:
        for symbol in symbols:
            symbol_path = dataset_dir / f"{symbol.lower()}_market.png"
            plot_symbol_market(equity_curve, fills, symbol, symbol_path)
            chart_paths.append(symbol_path)

    write_html_report(dataset_dir, summary, chart_paths)
    return chart_paths


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    target = resolve_target(args.path)

    if is_dataset_dir(target):
        dataset_dirs = [target]
        run_dir = target.parent
    else:
        run_dir = target
        dataset_dirs = discover_dataset_dirs(run_dir)
        if args.dataset:
            wanted = set(args.dataset)
            dataset_dirs = [dataset_dir for dataset_dir in dataset_dirs if dataset_dir.name in wanted]
            if not dataset_dirs:
                raise ValueError(f"No dataset directories matched: {sorted(wanted)}")

    print(f"Plot target: {run_dir}")
    for dataset_dir in dataset_dirs:
        chart_paths = regenerate_dataset_plots(dataset_dir, run_dir)
        print()
        print(f"Dataset: {dataset_dir.name}")
        print(f"Report: {dataset_dir / 'report.html'}")
        for chart_path in chart_paths:
            print(f"Chart:  {chart_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
