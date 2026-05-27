"""Per-day sweep of HYDROGEL params to find day-1 specific optima.

Generates a temp trader file for each param combo, runs the local
backtester on day 1 only, and prints PnL.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "traders" / "round3" / "h_only_v16.py"
BT = ROOT / "tools" / "jmerle_backtester.py"

with open(BASE) as f:
    src = f.read()


def patch(replacements: dict) -> str:
    s = src
    for k, v in replacements.items():
        # match "    KEY = ..." (class-level constant) up to end of line
        pat = re.compile(rf"^(    {re.escape(k)}\s*=\s*)[^\n#]+", re.MULTILINE)
        s, n = pat.subn(rf"\g<1>{v}", s, count=1)
        if n == 0:
            raise SystemExit(f"failed to patch {k}")
    return s


def run(combo: dict, day_arg: str = "3-1"):
    s = patch(combo)
    with tempfile.NamedTemporaryFile(
        suffix=".py", dir=ROOT / "traders" / "round3", delete=False, mode="w"
    ) as tf:
        tf.write(s)
        path = tf.name
    try:
        r = subprocess.run(
            ["python3", str(BT), path, day_arg, "--no-out", "--no-progress"],
            capture_output=True, text=True, cwd=ROOT,
        )
        out = r.stdout + r.stderr
        m = re.search(r"Total profit: ([\d,\-]+)", out)
        if not m:
            return None
        return int(m.group(1).replace(",", ""))
    finally:
        os.unlink(path)


def sweep(name, combos, day_arg="3-1", baseline_pnl=None):
    print(f"\n==== {name}  (day {day_arg}) ====")
    if baseline_pnl is not None:
        print(f"  baseline: {baseline_pnl:,}")
    for c in combos:
        pnl = run(c, day_arg)
        if pnl is None:
            print(f"  {c}: FAIL")
            continue
        delta = "" if baseline_pnl is None else f"  Δ {pnl - baseline_pnl:+,}"
        print(f"  {c}: {pnl:,}{delta}")


def main():
    base = run({}, "3-1")
    print(f"baseline v16 day 1: {base:,}")

    # 1) CLIP_VOL_K alone
    sweep("CLIP_VOL_K sweep", [
        {"CLIP_VOL_K": v} for v in [0.0, 0.3, 0.5, 0.76, 1.0, 1.3]
    ], baseline_pnl=base)

    # 2) DMID_HISTORY alone
    sweep("DMID_HISTORY sweep", [
        {"DMID_HISTORY": v} for v in [20, 50, 100, 150, 300, 500]
    ], baseline_pnl=base)

    # 3) H_ANCHOR sweep
    sweep("H_ANCHOR sweep", [
        {"H_ANCHOR": v} for v in [9978.0, 9980.0, 9983.0, 9985.0, 9988.0, 9990.0, 9993.0, 9996.0, 10000.0]
    ], baseline_pnl=base)

    # 4) AR1_BETA sweep
    sweep("AR1_BETA sweep", [
        {"AR1_BETA": v} for v in [0.0, 0.05, 0.1, 0.13, 0.17, 0.20, 0.25, 0.30]
    ], baseline_pnl=base)

    # 5) H_INV_SKEW sweep
    sweep("H_INV_SKEW sweep", [
        {"H_INV_SKEW": v} for v in [0.005, 0.010, 0.014, 0.020, 0.030, 0.050, 0.080, 0.100]
    ], baseline_pnl=base)

    # 6) H_CLIP base sweep
    sweep("H_CLIP base sweep", [
        {"H_CLIP": v} for v in [25.0, 30.0, 33.0, 40.0, 50.0, 60.0, 80.0, 100.0]
    ], baseline_pnl=base)

    # 7) H_TAKE_EDGE
    sweep("H_TAKE_EDGE sweep", [
        {"H_TAKE_EDGE": v} for v in [0.0, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0]
    ], baseline_pnl=base)

    # 8) H_MAX_POST_SIZE
    sweep("H_MAX_POST_SIZE sweep", [
        {"H_MAX_POST_SIZE": v} for v in [10, 14, 18, 22, 30]
    ], baseline_pnl=base)


if __name__ == "__main__":
    main()
