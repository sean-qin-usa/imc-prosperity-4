"""Phase 3: re-explore all knobs at the new (a=9985, c=33) base."""
from __future__ import annotations
import itertools, re, subprocess, sys, tempfile
from pathlib import Path

REPO = Path("/Users/sean_tsu_/Downloads/prosperity/IMCP2026")
TEMPLATE = REPO / "traders/round3/h_only_v7.py"
RUNS_DIR = Path(tempfile.mkdtemp(prefix="hv7p3_"))


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
        raise RuntimeError(f"{label}: {out[-300:]}")
    return total, days


# Base config from phase 2
BASE = {"H_ANCHOR": 9985.0, "H_CLIP": 33.0, "AR1_BETA": 0.18, "H_PENNY_EDGE": 4.0}


def sweep(name, knob, values):
    print(f"\n=== {name} ===")
    rows = []
    for v in values:
        o = dict(BASE); o[knob] = v
        t, d = run_one(f"{name}_{v}", o)
        rows.append((f"{knob}={v}", o, t, d))
    rows.sort(key=lambda r: -r[2])
    for label, o, t, d in rows:
        print(f"  {label:32s}  total={t:>7d}  days={d}")
    return rows


def main():
    print(f"runs dir: {RUNS_DIR}")
    base_t, base_d = run_one("BASE", BASE)
    print(f"\nBASE (a=9985 c=33 ar=0.18 pn=4.0): total={base_t} days={base_d}")

    sweep("anchor", "H_ANCHOR", [float(v) for v in [9982, 9983, 9984, 9985, 9986, 9987, 9988]])
    sweep("clip",   "H_CLIP",   [float(v) for v in [29, 30, 31, 32, 33, 34, 35, 36, 38, 40]])
    sweep("size",   "H_MAX_POST_SIZE", [12, 15, 18, 20, 22, 25, 28, 30, 35, 40])
    sweep("skew",   "H_INV_SKEW", [0.005, 0.008, 0.010, 0.012, 0.015, 0.018, 0.020, 0.025])
    sweep("reduce", "H_REDUCE_EDGE", [-0.5, 0.0, 0.5, 1.0, 1.5, 2.0])
    sweep("ar1",    "AR1_BETA", [0.05, 0.10, 0.13, 0.15, 0.18, 0.20, 0.22, 0.25, 0.30])
    sweep("penny",  "H_PENNY_EDGE", [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0])
    sweep("wide",   "H_WIDE_SPREAD", [4, 6, 8, 10, 12, 14])
    sweep("typical", "TYPICAL_SPREAD", [0, 13, 14, 15, 16, 17, 999])
    sweep("clip_vol", "CLIP_VOL_K", [0.0, 0.1, 0.2, 0.3, 0.5, 1.0])
    sweep("ema",    "ANCHOR_EMA_ALPHA", [0.0, 1e-5, 5e-5, 1e-4, 5e-4, 1e-3])
    sweep("asym_S", "ASYM_REDUCE_SHORT", [0.0, 0.5, 1.0, 1.5])
    sweep("asym_L", "ASYM_REDUCE_LONG", [-1.0, -0.5, 0.0, 0.5, 1.0])
    sweep("layer2_frac", "LAYER2_FRACTION", [0.0, 0.3, 0.5, 0.7, 1.0])


if __name__ == "__main__":
    main()
