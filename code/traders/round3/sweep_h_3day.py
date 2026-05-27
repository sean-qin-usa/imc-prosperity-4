"""3-day sweep of HYDROGEL params from v16 baseline (181,675).

Verify cliff cross-day for the most promising day-1 levers.
"""
import os
import re
import subprocess
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
        # parse per-day from "Round 3 day X: NN" and total
        days = {}
        for m in re.finditer(r"Round 3 day (\d+): ([\-\d,]+)", out):
            days[int(m.group(1))] = int(m.group(2).replace(",", ""))
        m = re.search(r"Total profit: ([\-\d,]+)", out)
        total = int(m.group(1).replace(",", "")) if m else None
        return days, total
    finally:
        os.unlink(path)


def fmt(combo, days, total, base_total=181675, base_days={0: 63544, 1: 53884, 2: 64247}):
    delta_total = total - base_total
    d0 = days.get(0, 0); d1 = days.get(1, 0); d2 = days.get(2, 0)
    dd = "  ".join([
        f"d0:{d0:>7,}({d0-base_days[0]:+,})",
        f"d1:{d1:>7,}({d1-base_days[1]:+,})",
        f"d2:{d2:>7,}({d2-base_days[2]:+,})",
    ])
    print(f"  {combo} → total {total:>7,} ({delta_total:+,})   {dd}", flush=True)


def main():
    base_days, base_total = run3({})
    print(f"baseline v16: {base_total:,}  d0:{base_days[0]:,} d1:{base_days[1]:,} d2:{base_days[2]:,}", flush=True)

    # 1) CLIP_VOL_K cliff check on v16 chassis (DMID_HISTORY=150)
    print("\n--- CLIP_VOL_K with DMID_HISTORY=150 (v16 chassis) ---", flush=True)
    for v in [0.5, 0.76, 0.85, 0.95, 1.0, 1.1, 1.3, 1.5]:
        days, total = run3({"CLIP_VOL_K": v})
        fmt({"CLIP_VOL_K": v}, days, total, base_total, base_days)

    # 2) H_ANCHOR cross-day
    print("\n--- H_ANCHOR cross-day ---", flush=True)
    for v in [9981.0, 9983.0, 9984.0, 9985.0, 9986.0]:
        days, total = run3({"H_ANCHOR": v})
        fmt({"H_ANCHOR": v}, days, total, base_total, base_days)

    # 3) joint CLIP_VOL_K + H_ANCHOR
    print("\n--- joint CLIP_VOL_K + H_ANCHOR ---", flush=True)
    for vk in [0.85, 0.95, 1.0]:
        for a in [9983.0, 9984.0, 9985.0]:
            days, total = run3({"CLIP_VOL_K": vk, "H_ANCHOR": a})
            fmt({"CLIP_VOL_K": vk, "H_ANCHOR": a}, days, total, base_total, base_days)


if __name__ == "__main__":
    main()
