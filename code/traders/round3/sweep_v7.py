"""Sweep harness for v7 — adaptive CLIP / EMA anchor / asymmetric reduce / re-explore old."""
from __future__ import annotations
import itertools, re, subprocess, sys, tempfile
from pathlib import Path

REPO = Path("/Users/sean_tsu_/Downloads/prosperity/IMCP2026")
TEMPLATE = REPO / "traders/round3/h_only_v7.py"
RUNS_DIR = Path(tempfile.mkdtemp(prefix="hv7_"))


def render(overrides):
    src = TEMPLATE.read_text()
    for key, val in overrides.items():
        pat = rf"^(    {key}\s*=\s*)[^#\n]+(.*)$"
        src = re.sub(pat, lambda m, v=val: f"{m.group(1)}{v}{m.group(2)}",
                     src, count=1, flags=re.MULTILINE)
    return src


def run_one(label, overrides):
    fp = RUNS_DIR / f"{label}.py"
    fp.write_text(render(overrides))
    proc = subprocess.run(
        ["python3", str(REPO / "tools/jmerle_backtester.py"), str(fp), "3",
         "--merge-pnl", "--no-out"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    out = proc.stdout + proc.stderr
    days, total = [], None
    for line in out.splitlines():
        m = re.match(r"Round 3 day (\d+): ([\-\d,]+)", line)
        if m: days.append(int(m.group(2).replace(",", "")))
        m = re.match(r"^Total profit: ([\-\d,]+)$", line)
        if m: total = int(m.group(1).replace(",", ""))
    if total is None:
        raise RuntimeError(f"no total for {label}: {out[-300:]}")
    return total, days


def sweep(name, configs):
    print(f"\n=== {name} ===")
    rows = []
    for label, o in configs:
        t, d = run_one(f"{name}_{label}", o)
        rows.append((label, o, t, d))
    rows.sort(key=lambda r: -r[2])
    for label, o, t, d in rows:
        print(f"  {label:32s}  total={t:>7d}  days={d}")
    return rows


def main():
    print(f"runs dir: {RUNS_DIR}")
    base_total, base_days = run_one("BASE", {})
    print(f"\nBASE (v7 default): total={base_total}  days={base_days}")

    if len(sys.argv) > 1 and sys.argv[1] == "knobs":
        # New v7 knobs
        sweep("clip_vol_k", [(f"k={v}", {"CLIP_VOL_K": v}) for v in [0.0, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0]])
        sweep("ema_alpha", [(f"a={v}", {"ANCHOR_EMA_ALPHA": v}) for v in [0.0, 0.0001, 0.0005, 0.001, 0.005, 0.01]])
        sweep("asym_long", [(f"L={v}", {"ASYM_REDUCE_LONG": v}) for v in [-0.5, 0.0, 0.5, 1.0, 1.5]])
        sweep("asym_short", [(f"S={v}", {"ASYM_REDUCE_SHORT": v}) for v in [-0.5, 0.0, 0.5, 1.0, 1.5]])
        sweep("take_floor", [(f"tf={v}", {"TAKE_AT_FAIR_FLOOR": v}) for v in [0, 1]])
    elif len(sys.argv) > 1 and sys.argv[1] == "rerefine":
        # Re-explore winners under v7 base
        sweep("ar1_v7", [(f"ar={v}", {"AR1_BETA": v}) for v in [0.0, 0.05, 0.10, 0.15, 0.18, 0.20, 0.25, 0.30, 0.40, 0.50]])
        sweep("size_v7", [(f"sz={v}", {"H_MAX_POST_SIZE": v}) for v in [12, 15, 18, 20, 22, 25, 28, 30]])
        sweep("skew_v7", [(f"sk={v}", {"H_INV_SKEW": v}) for v in [0.008, 0.010, 0.012, 0.014, 0.015, 0.016, 0.018, 0.020]])
        sweep("anchor_v7", [(f"a={v}", {"H_ANCHOR": float(v)}) for v in [9985, 9988, 9989, 9990, 9991, 9992, 9995]])
        sweep("clip_v7", [(f"c={v}", {"H_CLIP": float(v)}) for v in [25, 27, 28, 29, 30, 31, 32, 33, 35]])
        sweep("penny_v7", [(f"p={v}", {"H_PENNY_EDGE": v}) for v in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0]])
    elif len(sys.argv) > 1 and sys.argv[1] == "combo2":
        # Joint sweep of best new knobs once individual winners known
        # Will fill in after knobs sweep
        pass


if __name__ == "__main__":
    main()
