"""Tighter drift-gate sweep around R=55 (best from v1 sweep).

Tests BOOST and HISTORY at R=55, then joint search.
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
    if total is None:
        print(f"  {combo} → FAIL", flush=True)
        return
    delta_total = total - base_total
    d0 = days.get(0, 0); d1 = days.get(1, 0); d2 = days.get(2, 0)
    dd = "  ".join([
        f"d0:{d0:>6,}({d0-base_days[0]:+,})",
        f"d1:{d1:>6,}({d1-base_days[1]:+,})",
        f"d2:{d2:>6,}({d2-base_days[2]:+,})",
    ])
    print(f"  {combo} → {total:>7,} ({delta_total:+,})  {dd}", flush=True)


def main():
    print(f"==== drift_v1 BOOST sweep @ R=55 ====", flush=True)
    for b in [0.3, 0.5, 0.7, 0.85, 1.0, 1.15, 1.3, 1.5, 2.0, 3.0, 5.0]:
        days, total = run3({"DRIFT_GATE_RANGE": 55, "DRIFT_CLIP_BOOST": b})
        fmt({"R": 55, "B": b}, days, total)

    print(f"\n==== drift_v1 HISTORY sweep @ R=55 BOOST=1.0 ====", flush=True)
    for h in [50, 75, 100, 150, 200, 300, 500, 1000]:
        days, total = run3({"DRIFT_GATE_RANGE": 55, "MID_RANGE_HISTORY": h})
        fmt({"R": 55, "H": h}, days, total)

    print(f"\n==== drift_v1 R fine sweep @ BOOST=1.0 H=200 ====", flush=True)
    for r in [52, 53, 54, 55, 56, 57, 58]:
        days, total = run3({"DRIFT_GATE_RANGE": r})
        fmt({"R": r}, days, total)

    print(f"\n==== JOINT R x BOOST around (55,1.0) ====", flush=True)
    for r in [54, 55, 56]:
        for b in [0.7, 1.0, 1.3, 1.5]:
            days, total = run3({"DRIFT_GATE_RANGE": r, "DRIFT_CLIP_BOOST": b})
            fmt({"R": r, "B": b}, days, total)


if __name__ == "__main__":
    main()
