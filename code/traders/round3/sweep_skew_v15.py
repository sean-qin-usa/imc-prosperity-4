"""Sweep SKEW_WEIGHT and SKEW_CARRY_GATE on combined_ship_v15_skew.py."""
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "traders" / "round3" / "combined_ship_v15_skew.py"
BT = ROOT / "tools" / "jmerle_backtester.py"

with open(BASE) as f:
    src = f.read()


def patch(replacements):
    s = src
    for k, v in replacements.items():
        pat = re.compile(rf"^(    {re.escape(k)}\s*=\s*)[^\n#]+", re.MULTILINE)
        s, n = pat.subn(rf"\g<1>{v}", s, count=1)
        if n == 0:
            raise SystemExit(f"failed to patch {k}")
    return s


def run3(combo):
    s = patch(combo)
    with tempfile.NamedTemporaryFile(suffix=".py", dir=ROOT / "traders" / "round3",
                                     delete=False, mode="w") as tf:
        tf.write(s); path = tf.name
    try:
        r = subprocess.run(
            ["python3", str(BT), path, "3", "--merge-pnl", "--no-out", "--no-progress"],
            capture_output=True, text=True, cwd=ROOT)
        out = r.stdout + r.stderr
        days = {}
        for m in re.finditer(r"Round 3 day (\d+): ([\-\d,]+)", out):
            days[int(m.group(1))] = int(m.group(2).replace(",", ""))
        totals = re.findall(r"Total profit: ([\-\d,]+)", out)
        total = int(totals[-1].replace(",", "")) if totals else None
        return days, total
    finally:
        os.unlink(path)


BASE_TOTAL = 443484
BASE_DAYS = {0: 136310, 1: 156750, 2: 150423}


def fmt(combo, days, total):
    if total is None:
        print(f"  {combo} → FAIL", flush=True); return
    delta = total - BASE_TOTAL
    d0 = days.get(0, 0); d1 = days.get(1, 0); d2 = days.get(2, 0)
    print(f"  {combo} → {total:>7,} ({delta:+,})  d0:{d0:>7,}({d0-BASE_DAYS[0]:+,})  d1:{d1:>7,}({d1-BASE_DAYS[1]:+,})  d2:{d2:>7,}({d2-BASE_DAYS[2]:+,})", flush=True)


def main():
    print(f"baseline v15 (no skew lever): {BASE_TOTAL:,}", flush=True)

    # First test: zero skew (must equal baseline)
    print("\n--- sanity: SKEW_WEIGHT=0, GATE=9999 (must equal baseline) ---", flush=True)
    days, total = run3({"SKEW_WEIGHT": 0.0, "SKEW_CARRY_GATE": 9999.0})
    fmt({"W": 0.0, "G": 9999}, days, total)

    print("\n--- SKEW_WEIGHT sweep, GATE=9999 (no carry-gate) ---", flush=True)
    for w in [0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0, -0.1, -0.3]:
        days, total = run3({"SKEW_WEIGHT": w, "SKEW_CARRY_GATE": 9999.0})
        fmt({"W": w, "G": 9999}, days, total)

    print("\n--- carry-gate-only (W=0): SKEW_CARRY_GATE sweep ---", flush=True)
    for g in [-9999, -10, -6, -3, 0, 3, 6, 12, 9999]:
        days, total = run3({"SKEW_WEIGHT": 0.0, "SKEW_CARRY_GATE": g})
        fmt({"W": 0.0, "G": g}, days, total)

    print("\n--- joint W x G (top-half scan) ---", flush=True)
    for w in [0.05, 0.1, 0.2]:
        for g in [3, 6, 12]:
            days, total = run3({"SKEW_WEIGHT": w, "SKEW_CARRY_GATE": g})
            fmt({"W": w, "G": g}, days, total)


if __name__ == "__main__":
    main()
