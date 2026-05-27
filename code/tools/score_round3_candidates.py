from __future__ import annotations

import argparse
import csv
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable, List, Optional


IMCP_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = IMCP_ROOT.parent

JMERLE = IMCP_ROOT / "tools" / "jmerle_backtester.py"
OFFICIAL_COMPARE = IMCP_ROOT / "tools" / "official_compare.py"
CALIBRATE = IMCP_ROOT / "tools" / "calibrate_exchange_model.py"
UPLOAD_CHECK = IMCP_ROOT / "tools" / "check_single_file_upload.py"


@dataclass
class OfficialReplayResult:
    official_profit: float
    local_final: float
    diff: float
    fill_qty: int
    executed_qty: int


@dataclass
class CandidateScore:
    strategy: Path
    upload_safe: Optional[bool]
    visible_3day: float
    official_generic: OfficialReplayResult
    official_calibrated: OfficialReplayResult


def run_command(args: List[str], cwd: Path = WORKSPACE_ROOT) -> str:
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    return proc.stdout


def parse_last_total_profit(output: str) -> float:
    matches = re.findall(r"Total profit:\s*([-+]?\d[\d,]*(?:\.\d+)?)", output)
    if not matches:
        raise ValueError("Could not find `Total profit:` in backtester output.")
    return float(matches[-1].replace(",", ""))


def parse_float_label(output: str, label: str) -> float:
    match = re.search(rf"{re.escape(label)}:\s*([-+]?\d[\d,]*(?:\.\d+)?)", output)
    if match is None:
        raise ValueError(f"Could not find `{label}:` in official_compare output.")
    return float(match.group(1).replace(",", ""))


def load_single_summary_csv(output_dir: Path) -> dict:
    summaries = sorted(output_dir.glob("**/summary.csv"))
    if not summaries:
        raise FileNotFoundError(f"No summary.csv found under {output_dir}")
    with summaries[0].open() as fh:
        reader = csv.DictReader(fh)
        row = next(reader, None)
    if row is None:
        raise ValueError(f"summary.csv under {output_dir} was empty")
    return row


def slugify_strategy(path: Path) -> str:
    stem = path.stem.lower()
    return re.sub(r"[^a-z0-9._-]+", "_", stem)


def resolve_bundle(bundle_arg: str) -> Path:
    bundle = Path(bundle_arg).expanduser().resolve()
    if bundle.is_file():
        return bundle.parent
    return bundle


def find_bundle_strategy(bundle_dir: Path) -> Path:
    strategies = sorted(bundle_dir.glob("*.py"))
    if len(strategies) != 1:
        raise ValueError(
            f"Bundle dir {bundle_dir} must contain exactly one .py strategy; found {len(strategies)}."
        )
    return strategies[0]


def check_upload_safety(strategy: Path) -> Optional[bool]:
    try:
        run_command([sys.executable, str(UPLOAD_CHECK), str(strategy)])
        return True
    except subprocess.CalledProcessError:
        return False


def run_visible_backtest(strategy: Path) -> float:
    output = run_command(
        [sys.executable, str(JMERLE), str(strategy), "3", "--merge-pnl", "--no-out"]
    )
    return parse_last_total_profit(output)


def run_official_replay(
    bundle_dir: Path,
    strategy: Path,
    output_dir: Path,
    calibration: Optional[Path],
) -> OfficialReplayResult:
    jsons = sorted(bundle_dir.glob("*.json"))
    logs = sorted(bundle_dir.glob("*.log"))
    if len(jsons) != 1 or len(logs) != 1:
        raise ValueError(
            f"Bundle dir {bundle_dir} must contain exactly one .json and one .log."
        )
    cmd = [
        sys.executable,
        str(OFFICIAL_COMPARE),
        "--official-json",
        str(jsons[0]),
        "--official-log",
        str(logs[0]),
        "--strategy",
        str(strategy),
        "--fill-model",
        "official-hybrid",
        "--output",
        str(output_dir),
    ]
    if calibration is not None:
        cmd.extend(["--exchange-calibration", str(calibration)])
    stdout = run_command(cmd)
    summary = load_single_summary_csv(output_dir)
    return OfficialReplayResult(
        official_profit=parse_float_label(stdout, "official_profit"),
        local_final=float(summary["final_total_pnl"]),
        diff=parse_float_label(stdout, "diff"),
        fill_qty=int(summary["fill_qty"]),
        executed_qty=int(summary["executed_qty"]),
    )


def ensure_bundle_calibration(bundle_dir: Path, calibration_path: Path) -> Path:
    if calibration_path.exists():
        return calibration_path
    run_command(
        [
            sys.executable,
            str(CALIBRATE),
            "--bundle-dir",
            str(bundle_dir),
            "--output",
            str(calibration_path),
        ]
    )
    return calibration_path


def format_bool(value: Optional[bool]) -> str:
    if value is None:
        return "n/a"
    return "yes" if value else "no"


def print_score_table(scores: Iterable[CandidateScore]) -> None:
    rows = []
    for score in scores:
        rows.append(
            {
                "strategy": score.strategy.name,
                "upload_safe": format_bool(score.upload_safe),
                "visible_3day": f"{score.visible_3day:,.0f}",
                "official_generic": f"{score.official_generic.local_final:.1f}",
                "official_calibrated": f"{score.official_calibrated.local_final:.1f}",
                "cal_minus_official": f"{score.official_calibrated.local_final - score.official_calibrated.official_profit:+.1f}",
                "generic_to_cal": f"{score.official_calibrated.local_final - score.official_generic.local_final:+.1f}",
            }
        )

    headers = [
        "strategy",
        "upload_safe",
        "visible_3day",
        "official_generic",
        "official_calibrated",
        "cal_minus_official",
        "generic_to_cal",
    ]
    widths = {
        h: max(len(h), *(len(row[h]) for row in rows))
        for h in headers
    }
    line = "  ".join(h.ljust(widths[h]) for h in headers)
    print(line)
    print("  ".join("-" * widths[h] for h in headers))
    for row in rows:
        print("  ".join(row[h].ljust(widths[h]) for h in headers))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Score round-3 candidates using the visible 3-day backtest plus "
            "generic and bundle-calibrated official hidden-day replays."
        )
    )
    parser.add_argument("strategies", nargs="+", help="Strategy file paths to score.")
    parser.add_argument(
        "--bundle-dir",
        required=True,
        help="Official bundle directory containing one .log, one .json, and one .py.",
    )
    parser.add_argument(
        "--skip-upload-check",
        action="store_true",
        help="Skip the single-file upload safety check.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle_dir = resolve_bundle(args.bundle_dir)

    if not bundle_dir.exists():
        raise SystemExit(f"Bundle dir not found: {bundle_dir}")

    bundle_strategy = find_bundle_strategy(bundle_dir)

    with TemporaryDirectory(prefix="round3_scorecard_") as tmp_dir_raw:
        tmp_dir = Path(tmp_dir_raw)
        calibration_path = ensure_bundle_calibration(
            bundle_dir, tmp_dir / f"{bundle_dir.name}_passive_profile.json"
        )

        scores: List[CandidateScore] = []
        for strategy_arg in args.strategies:
            strategy = Path(strategy_arg).expanduser().resolve()
            upload_safe = None if args.skip_upload_check else check_upload_safety(strategy)
            visible = run_visible_backtest(strategy)

            generic_dir = tmp_dir / f"{slugify_strategy(strategy)}_generic"
            calibrated_dir = tmp_dir / f"{slugify_strategy(strategy)}_calibrated"

            generic = run_official_replay(
                bundle_dir=bundle_dir,
                strategy=strategy,
                output_dir=generic_dir,
                calibration=None,
            )
            calibrated = run_official_replay(
                bundle_dir=bundle_dir,
                strategy=strategy,
                output_dir=calibrated_dir,
                calibration=calibration_path,
            )
            scores.append(
                CandidateScore(
                    strategy=strategy,
                    upload_safe=upload_safe,
                    visible_3day=visible,
                    official_generic=generic,
                    official_calibrated=calibrated,
                )
            )

        print(f"bundle_dir: {bundle_dir}")
        print(f"bundle_strategy: {bundle_strategy.name}")
        print(f"bundle_calibration: {calibration_path}")
        print()
        print_score_table(scores)


if __name__ == "__main__":
    main()
