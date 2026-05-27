from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKTEST_ROOT = REPO_ROOT.parent / "gen" / "backtests"
DEFAULT_CONFIG = REPO_ROOT / "analysis" / "visualizer_config.json"
PREFERRED_CONFIGS = [
    REPO_ROOT / "analysis" / "visualizer_report" / "round1" / "resolved_config.json",
    DEFAULT_CONFIG,
]


def default_config_path() -> Path:
    for path in PREFERRED_CONFIGS:
        if path.exists():
            return path
    return DEFAULT_CONFIG


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a strategy if requested, rebuild the unified interactive visualizer, and open the HTML report."
    )
    parser.add_argument(
        "strategy",
        nargs="?",
        help="Optional strategy file to backtest before rebuilding the dashboard.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="Visualizer config path. Defaults to the round1 resolved config when present.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Optional visualizer data directory override.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional explicit HTML output path.",
    )
    parser.add_argument(
        "--group-output",
        action="store_true",
        help="Apply the visualizer group-output rule when computing the default output path.",
    )
    parser.add_argument(
        "--backtest",
        default=None,
        help="Existing backtest run/dataset dir to visualize, or 'latest'. Ignored when a new strategy run is launched.",
    )
    parser.add_argument(
        "--no-backtest",
        action="store_true",
        help="Skip launching a new backtest. The report will use --backtest or the latest discovered run when available.",
    )
    parser.add_argument(
        "--input",
        nargs="+",
        default=None,
        help="Backtester input paths. Defaults to the backtester's normal dataset discovery.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_BACKTEST_ROOT,
        help="Backtester run root.",
    )
    parser.add_argument(
        "--run-name",
        default=None,
        help="Optional short label appended to the generated backtest folder name.",
    )
    parser.add_argument(
        "--reuse-trader-instance",
        action="store_true",
        help="Reuse a single Trader instance across ticks during backtesting.",
    )
    parser.add_argument(
        "--queue-alpha",
        type=float,
        default=1.0,
        help="Queue-ahead assumption for interval-style passive fill logic.",
    )
    parser.add_argument(
        "--fill-model",
        choices=["same-tick", "interval", "book-delta", "official-hybrid"],
        default="same-tick",
        help="Backtester fill model.",
    )
    parser.add_argument(
        "--match-trades",
        choices=["all", "worse", "none"],
        default="all",
        help="How same-tick market trades are matched after visible depth is consumed.",
    )
    parser.add_argument(
        "--trade-fill-price",
        choices=["order", "trade"],
        default="order",
        help="Price used for market-trade fills in the backtester.",
    )
    parser.add_argument(
        "--market-trades",
        choices=["all", "external-only", "none"],
        default="all",
        help="Which trades are exposed in state.market_trades during backtesting.",
    )
    parser.add_argument(
        "--fill-trades",
        choices=["auto", "all", "external-only", "none"],
        default="auto",
        help="Which trades are available to the fill simulator.",
    )
    parser.add_argument(
        "--exchange-calibration",
        type=Path,
        default=None,
        help="Optional calibration JSON for official-hybrid fills.",
    )
    parser.add_argument(
        "--dataset",
        nargs="*",
        default=None,
        help="Optional dataset names to run after discovery.",
    )
    parser.add_argument(
        "--all-datasets",
        action="store_true",
        help="Run every discovered dataset instead of the backtester's default subset.",
    )
    parser.add_argument(
        "--keep-run-plots",
        action="store_true",
        help="Keep the backtester's PNG/report generation instead of forcing --no-plots.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Build the HTML but do not open it.",
    )
    return parser.parse_args(argv)


def resolve_user_path(path: Path) -> Path:
    path = path.expanduser()
    if path.is_absolute():
        return path.resolve()
    return (Path.cwd() / path).resolve()


def resolve_repo_path(path: Path) -> Path:
    path = path.expanduser()
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def resolve_output_path(
    config_path: Path,
    explicit_output: Optional[Path],
    data_dir_override: Optional[Path],
    group_output_override: bool,
) -> Path:
    if explicit_output is not None:
        return resolve_user_path(explicit_output)

    if config_path.name == "resolved_config.json":
        return (config_path.parent / "report_interactive.html").resolve()

    raw = read_json(config_path)
    output_dir = resolve_repo_path(Path(raw["output_dir"])) if raw.get("output_dir") else REPO_ROOT / "analysis" / "visualizer_report"
    data_dir = data_dir_override
    if data_dir is None and raw.get("data_dir"):
        data_dir = resolve_repo_path(Path(raw["data_dir"]))
    group_output = bool(raw.get("group_output", False)) or group_output_override

    if group_output:
        suffix = data_dir.name if data_dir else "dataset"
        output_dir = output_dir / suffix

    return (output_dir / "report_interactive.html").resolve()


def resolve_latest_run(run_root: Path) -> Optional[Path]:
    latest_link = run_root / "latest"
    if latest_link.exists():
        return latest_link.resolve()

    latest_txt = run_root / "LATEST.txt"
    if latest_txt.exists():
        target = latest_txt.read_text().strip()
        if target:
            return Path(target).expanduser().resolve()

    return None


def resolve_backtest_target(raw_value: Optional[str], run_root: Path) -> Optional[Path]:
    if raw_value is None:
        return resolve_latest_run(run_root)
    if raw_value == "latest":
        return resolve_latest_run(run_root)
    return resolve_user_path(Path(raw_value))


def run_command(cmd: Sequence[str]) -> None:
    print(f"$ {shlex.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def build_backtester_command(args: argparse.Namespace) -> Sequence[str]:
    strategy_path = resolve_user_path(Path(args.strategy))
    output_root = resolve_user_path(args.output_dir)

    cmd = [sys.executable, "tools/backtester.py", str(strategy_path), "--output-dir", str(output_root)]
    if args.input:
        cmd += ["--input", *[str(resolve_user_path(Path(value))) for value in args.input]]
    if args.run_name:
        cmd += ["--run-name", args.run_name]
    if args.reuse_trader_instance:
        cmd.append("--reuse-trader-instance")
    if args.queue_alpha != 1.0:
        cmd += ["--queue-alpha", str(args.queue_alpha)]
    if args.fill_model != "same-tick":
        cmd += ["--fill-model", args.fill_model]
    if args.match_trades != "all":
        cmd += ["--match-trades", args.match_trades]
    if args.trade_fill_price != "order":
        cmd += ["--trade-fill-price", args.trade_fill_price]
    if args.market_trades != "all":
        cmd += ["--market-trades", args.market_trades]
    if args.fill_trades != "auto":
        cmd += ["--fill-trades", args.fill_trades]
    if args.exchange_calibration:
        cmd += ["--exchange-calibration", str(resolve_user_path(args.exchange_calibration))]
    if args.dataset:
        cmd += ["--dataset", *args.dataset]
    if args.all_datasets:
        cmd.append("--all-datasets")
    if not args.keep_run_plots:
        cmd.append("--no-plots")
    return cmd


def build_visualizer_command(
    config_path: Path,
    output_path: Path,
    data_dir_override: Optional[Path],
    backtest_target: Optional[Path],
    group_output_override: bool,
) -> Sequence[str]:
    cmd = [
        sys.executable,
        "analysis/visualizer_interactive.py",
        "--config",
        str(config_path),
        "--output",
        str(output_path),
    ]
    if data_dir_override is not None:
        cmd += ["--data-dir", str(resolve_user_path(data_dir_override))]
    if backtest_target is not None:
        cmd += ["--backtest", str(backtest_target)]
    if group_output_override:
        cmd.append("--group-output")
    return cmd


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if args.strategy and args.no_backtest:
        raise SystemExit("Cannot provide a strategy path together with --no-backtest.")
    if args.strategy and args.backtest:
        raise SystemExit("Cannot provide a strategy path together with --backtest.")

    config_path = resolve_user_path(args.config)
    output_path = resolve_output_path(config_path, args.output, args.data_dir, args.group_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_root = resolve_user_path(args.output_dir)

    backtest_target: Optional[Path] = None
    if args.strategy:
        run_command(build_backtester_command(args))
        backtest_target = resolve_latest_run(run_root)
        if backtest_target is None:
            raise FileNotFoundError(f"Backtester finished, but no latest run pointer was found under {run_root}")
    else:
        backtest_target = resolve_backtest_target(args.backtest, run_root)

    if backtest_target is None:
        print("No backtest run found. Rebuilding the dashboard with market data only.", flush=True)
    else:
        print(f"Using backtest data from {backtest_target}", flush=True)

    run_command(
        build_visualizer_command(
            config_path=config_path,
            output_path=output_path,
            data_dir_override=args.data_dir,
            backtest_target=backtest_target,
            group_output_override=args.group_output,
        )
    )

    if not args.no_open:
        run_command(["open", str(output_path)])

    print(f"Report: {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
