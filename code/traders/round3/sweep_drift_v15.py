"""Sweep drift-gate params on combined_ship_v15_hdrift.py chassis.

v15 has CLIP_VOL_K=0.795 + TE=0.6 + AR1=0.25 (vs v11's 0.76/0.5/0.17), so
the gate's optimum may differ.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "traders" / "round3" / "combined_ship_v15_hdrift.py"
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


# baseline of bare v15 (no gate, B=0): from earlier backtest
BASE_TOTAL = 443484
BASE_DAYS = {0: 136310, 1: 156750, 2: 150423}


def fmt(combo, days, total):
    if total is None:
        print(f"  {combo} → FAIL", flush=True); return
    delta = total - BASE_TOTAL
    d0 = days.get(0, 0); d1 = days.get(1, 0); d2 = days.get(2, 0)
    print(
        f"  {combo} → {total:>7,} ({delta:+,})  "
        f"d0:{d0:>7,}({d0-BASE_DAYS[0]:+,})  "
        f"d1:{d1:>7,}({d1-BASE_DAYS[1]:+,})  "
        f"d2:{d2:>7,}({d2-BASE_DAYS[2]:+,})", flush=True
    )


def main():
    print(f"baseline v15: total={BASE_TOTAL:,}", flush=True)
    print(f"v15 + gate (R=53, B=1.6) was 444,306 (+822)", flush=True)

    print("\n--- BOOST sweep @ R=53 ---", flush=True)
    for b in [0.3, 0.5, 0.7, 0.85, 1.0, 1.15, 1.3, 1.5, 1.7, 2.0]:
        days, total = run3({"DRIFT_GATE_RANGE": 53, "DRIFT_CLIP_BOOST": b})
        fmt({"R": 53, "B": b}, days, total)

    print("\n--- RANGE sweep @ B=1.0 ---", flush=True)
    for r in [40, 45, 50, 52, 53, 55, 60, 65, 70, 80, 100]:
        days, total = run3({"DRIFT_GATE_RANGE": r, "DRIFT_CLIP_BOOST": 1.0})
        fmt({"R": r, "B": 1.0}, days, total)

    print("\n--- joint @ best R candidates ---", flush=True)
    for r in [55, 60, 65, 70]:
        for b in [0.5, 0.7, 1.0, 1.3]:
            days, total = run3({"DRIFT_GATE_RANGE": r, "DRIFT_CLIP_BOOST": b})
            fmt({"R": r, "B": b}, days, total)


if __name__ == "__main__":
    main()
