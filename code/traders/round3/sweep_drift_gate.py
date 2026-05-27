"""Sweep drift-gate params on h_day1_drift_v1.py.

Fast: only DRIFT_GATE_RANGE, DRIFT_CLIP_BOOST, MID_RANGE_HISTORY.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "traders" / "round3" / "h_day1_drift_v1.py"
BT = ROOT / "tools" / "jmerle_backtester.py"

with open(BASE) as f:
    src = f.read()


def patch(replacements: dict) -> str:
    s = src
    for k, v in replacements.items():
        pat = re.compile(rf"^(    {re.escape(k)}\s*=\s*)[^\n#]+", re.MULTILINE)
        s, n = pat.subn(rf"\g<1>{v}", s, count=1)
        if n == 0:
            raise SystemExit(f"failed to patch {k}")
    return s


def run3(combo: dict):
    s = patch(combo)
    with tempfile.NamedTemporaryFile(
        suffix=".py", dir=ROOT / "traders" / "round3", delete=False, mode="w"
    ) as tf:
        tf.write(s)
        path = tf.name
    try:
        r = subprocess.run(
            ["python3", str(BT), path, "3", "--merge-pnl", "--no-out", "--no-progress"],
            capture_output=True, text=True, cwd=ROOT,
        )
        out = r.stdout + r.stderr
        days = {}
        for m in re.finditer(r"Round 3 day (\d+): ([\-\d,]+)", out):
            days[int(m.group(1))] = int(m.group(2).replace(",", ""))
        totals = re.findall(r"Total profit: ([\-\d,]+)", out)
        total = int(totals[-1].replace(",", "")) if totals else None
        return days, total
    finally:
        os.unlink(path)


def fmt(combo, days, total, base_total=181675, base_days={0: 63544, 1: 53884, 2: 64247}):
    delta_total = total - base_total
    d0 = days.get(0, 0); d1 = days.get(1, 0); d2 = days.get(2, 0)
    dd = "  ".join([
        f"d0:{d0:>6,}({d0-base_days[0]:+,})",
        f"d1:{d1:>6,}({d1-base_days[1]:+,})",
        f"d2:{d2:>6,}({d2-base_days[2]:+,})",
    ])
    print(f"  {combo} → {total:>7,} ({delta_total:+,})  {dd}", flush=True)


def main():
    base_days, base_total = run3({})
    print(f"baseline drift_v1: total={base_total:,} d0={base_days[0]:,} d1={base_days[1]:,} d2={base_days[2]:,}", flush=True)

    print("\n--- DRIFT_GATE_RANGE @ BOOST=1.0 ---", flush=True)
    for r in [30, 40, 50, 55, 60, 65, 70, 80, 100, 150, 9999]:
        days, total = run3({"DRIFT_GATE_RANGE": r})
        fmt({"R": r}, days, total)

    print("\n--- DRIFT_CLIP_BOOST @ RANGE=60 ---", flush=True)
    for b in [0.0, 0.3, 0.5, 0.8, 1.0, 1.3, 1.5, 2.0, 3.0]:
        days, total = run3({"DRIFT_CLIP_BOOST": b})
        fmt({"B": b}, days, total)

    print("\n--- MID_RANGE_HISTORY @ R=60 BOOST=1.0 ---", flush=True)
    for h in [50, 100, 150, 200, 300, 500]:
        days, total = run3({"MID_RANGE_HISTORY": h})
        fmt({"H": h}, days, total)


if __name__ == "__main__":
    main()
