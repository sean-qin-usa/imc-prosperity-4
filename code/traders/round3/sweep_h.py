"""
Parameter sweep harness for HYDROGEL-only strategies.

Generates parameterized Trader files in /tmp/, runs jmerle_backtester
on each across days 0/1/2, captures total PnL. Used to find PnL plateau.

Usage:
  python3 sweep_h.py    # runs the configured grid
"""
from __future__ import annotations
import itertools
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path("/Users/sean_tsu_/Downloads/prosperity/IMCP2026")
TEMPLATE = REPO / "traders/round3/h_only_v6.py"
RUNS_DIR = Path(tempfile.mkdtemp(prefix="hsweep_"))


def render(overrides: dict) -> str:
    src = TEMPLATE.read_text()
    for key, val in overrides.items():
        # exactly match `KEY = ...` lines
        pat = rf"^(    {key}\s*=\s*)[^#\n]+(.*)$"
        repl = lambda m, v=val: f"{m.group(1)}{v}{m.group(2)}"
        new_src, n = re.subn(pat, repl, src, count=1, flags=re.MULTILINE)
        if n == 0:
            raise RuntimeError(f"could not find param '{key}' in template")
        src = new_src
    return src


def run_one(label: str, overrides: dict) -> tuple[int, list[int]]:
    fp = RUNS_DIR / f"{label}.py"
    fp.write_text(render(overrides))
    proc = subprocess.run(
        ["python3", str(REPO / "tools/jmerle_backtester.py"), str(fp), "3",
         "--merge-pnl", "--no-out"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    out = proc.stdout + proc.stderr
    days = []
    total = None
    for line in out.splitlines():
        m = re.match(r"Round 3 day (\d+): ([\-\d,]+)", line)
        if m:
            days.append(int(m.group(2).replace(",", "")))
        m = re.match(r"^Total profit: ([\-\d,]+)$", line)
        if m:
            total = int(m.group(1).replace(",", ""))
    if total is None:
        print(out[-2000:])
        raise RuntimeError(f"no total for {label}")
    # last "Total profit" line may be the merged total; days has the per-day values
    return total, days


def fmt(o):
    return ", ".join(f"{k}={v}" for k, v in o.items())


def main():
    sweeps = []
    if len(sys.argv) > 1:
        sweeps = [sys.argv[1]]
    else:
        sweeps = ["ablate", "ar1", "layer", "anchor", "clip", "size", "skew",
                  "penny", "wide", "passive_offset", "reduce_edge", "typical_spread"]
    print(f"runs dir: {RUNS_DIR}")
    base_total, base_days = run_one("BASE", {})
    print(f"\nBASE  : total={base_total:>7d}   days={base_days}\n")

    for sweep in sweeps:
        print(f"\n=== sweep: {sweep} ===")
        rows = []
        if sweep == "ablate":
            # Turn each feature off individually
            grids = [
                {"AR1_BETA": 0.0},                           # no AR1 lean
                {"TYPICAL_SPREAD": 0},                       # always touch_mid (effective: micro never used since spread<0 never)
                {"TYPICAL_SPREAD": 999},                     # always micro-price
                {"LAYER2_FRACTION": 0.0},                    # no layer 2
                {"AR1_BETA": 0.0, "TYPICAL_SPREAD": 0, "LAYER2_FRACTION": 0.0},  # all off (≈v5)
            ]
            labels = ["no_ar1", "no_micro", "always_micro", "no_layer2", "all_off"]
            for o, lab in zip(grids, labels):
                t, d = run_one(f"abl_{lab}", o)
                delta = t - base_total
                rows.append((lab, o, t, d, delta))
        elif sweep == "ar1":
            for v in [-0.05, 0.0, 0.05, 0.08, 0.10, 0.13, 0.15, 0.20, 0.25]:
                t, d = run_one(f"ar1_{v}", {"AR1_BETA": v})
                rows.append((f"AR1={v}", {"AR1_BETA": v}, t, d, t - base_total))
        elif sweep == "layer":
            for off, frac in itertools.product([2, 3, 4, 5, 6], [0.0, 0.3, 0.5, 0.7, 1.0]):
                o = {"LAYER2_OFFSET": off, "LAYER2_FRACTION": frac}
                t, d = run_one(f"layer_o{off}_f{frac}", o)
                rows.append((f"L2_off={off} frac={frac}", o, t, d, t - base_total))
        elif sweep == "anchor":
            for v in [9985, 9988, 9990, 9992, 9995, 9998, 10000]:
                o = {"H_ANCHOR": float(v)}
                t, d = run_one(f"anchor_{v}", o)
                rows.append((f"anchor={v}", o, t, d, t - base_total))
        elif sweep == "clip":
            for v in [15, 20, 25, 28, 30, 32, 35, 40, 50]:
                o = {"H_CLIP": float(v)}
                t, d = run_one(f"clip_{v}", o)
                rows.append((f"clip={v}", o, t, d, t - base_total))
        elif sweep == "size":
            for v in [10, 15, 20, 25, 30, 40, 60]:
                o = {"H_MAX_POST_SIZE": v}
                t, d = run_one(f"size_{v}", o)
                rows.append((f"size={v}", o, t, d, t - base_total))
        elif sweep == "skew":
            for v in [0.005, 0.010, 0.012, 0.015, 0.018, 0.020, 0.025]:
                o = {"H_INV_SKEW": v}
                t, d = run_one(f"skew_{v}", o)
                rows.append((f"skew={v}", o, t, d, t - base_total))
        elif sweep == "penny":
            for v in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
                o = {"H_PENNY_EDGE": v}
                t, d = run_one(f"penny_{v}", o)
                rows.append((f"penny={v}", o, t, d, t - base_total))
        elif sweep == "wide":
            for v in [4, 6, 8, 10, 12, 14, 16]:
                o = {"H_WIDE_SPREAD": v}
                t, d = run_one(f"wide_{v}", o)
                rows.append((f"wide={v}", o, t, d, t - base_total))
        elif sweep == "passive_offset":
            for v in [4, 6, 8, 10, 12]:
                o = {"H_PASSIVE_OFFSET": float(v)}
                t, d = run_one(f"poff_{v}", o)
                rows.append((f"passive_off={v}", o, t, d, t - base_total))
        elif sweep == "reduce_edge":
            for v in [0.0, 0.5, 1.0, 1.5, 2.0]:
                o = {"H_REDUCE_EDGE": v}
                t, d = run_one(f"red_{v}", o)
                rows.append((f"reduce_edge={v}", o, t, d, t - base_total))
        elif sweep == "typical_spread":
            for v in [0, 13, 14, 15, 16, 17, 999]:
                o = {"TYPICAL_SPREAD": v}
                t, d = run_one(f"ts_{v}", o)
                rows.append((f"TYPICAL_SPREAD={v}", o, t, d, t - base_total))
        # print summary
        rows.sort(key=lambda r: -r[2])
        for lab, o, t, d, delta in rows:
            sign = "+" if delta >= 0 else ""
            print(f"  {lab:34s}  total={t:>7d}  days={d}  Δ={sign}{delta}")


if __name__ == "__main__":
    main()
