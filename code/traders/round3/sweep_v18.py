"""Sweep ANCHOR_SHIFT_ALPHA on h_only_v18.py.

Edits the file's ANCHOR_SHIFT_ALPHA value between backtests, runs
jmerle_backtester, parses per-day PnL.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRADER = ROOT / "traders" / "round3" / "h_only_v18.py"
BACKTESTER = ROOT / "tools" / "jmerle_backtester.py"

ALPHAS = [0.0, 0.00005, 0.0001, 0.00015, 0.0002, 0.0003, 0.0005, 0.001]


def set_alpha(alpha):
    txt = TRADER.read_text()
    new_txt = re.sub(
        r"ANCHOR_SHIFT_ALPHA\s*=\s*[0-9.eE+-]+",
        f"ANCHOR_SHIFT_ALPHA = {alpha}",
        txt,
    )
    TRADER.write_text(new_txt)


def run_bt():
    result = subprocess.run(
        [sys.executable, str(BACKTESTER), str(TRADER), "3", "--merge-pnl", "--no-out"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    out = result.stdout + result.stderr
    days = {}
    total = None
    for m in re.finditer(r"Round 3 day (\d+):\s*([-\d,]+)", out):
        days[int(m.group(1))] = int(m.group(2).replace(",", ""))
    mt = re.search(r"Total profit:\s*([-\d,]+)", out)
    if mt:
        total = int(mt.group(1).replace(",", ""))
    return days, total


def main():
    print(f"{'alpha':>10}  {'win':>6}  {'d0':>8} {'d1':>8} {'d2':>8}  {'total':>8}  {'dd0':>7} {'dd1':>7} {'dd2':>7}  {'dtot':>7}")
    base_days = {0: 63544, 1: 53884, 2: 64247}
    base_total = 181675
    for a in ALPHAS:
        set_alpha(a)
        days, total = run_bt()
        if not days or total is None:
            print(f"{a:10.5f}  ERROR")
            continue
        win = "inf" if a == 0 else f"{1/a:.0f}"
        ds = [days.get(i, 0) for i in (0, 1, 2)]
        deltas = [ds[i] - base_days[i] for i in (0, 1, 2)]
        dt = total - base_total
        print(f"{a:10.5f}  {win:>6}  {ds[0]:>8,} {ds[1]:>8,} {ds[2]:>8,}  {total:>8,}  {deltas[0]:>+7,} {deltas[1]:>+7,} {deltas[2]:>+7,}  {dt:>+7,}")


if __name__ == "__main__":
    main()
