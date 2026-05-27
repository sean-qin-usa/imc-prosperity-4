"""Joint sweep of v7 winners: anchor + asym_short + penny + AR1 + skew."""
from __future__ import annotations
import itertools, re, subprocess, sys, tempfile
from pathlib import Path

REPO = Path("/Users/sean_tsu_/Downloads/prosperity/IMCP2026")
TEMPLATE = REPO / "traders/round3/h_only_v7.py"
RUNS_DIR = Path(tempfile.mkdtemp(prefix="hv7c_"))


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


def main():
    print(f"runs dir: {RUNS_DIR}")

    # Phase A: fine-tune anchor with reduce_edge=0 base
    print("\n=== anchor fine-grain (sk=0.015, rd=0.0, ar=0.15) ===")
    rows = []
    for a in [9985, 9986, 9987, 9988, 9989, 9990]:
        for c in [28, 29, 30, 31, 32, 33]:
            o = {"H_ANCHOR": float(a), "H_CLIP": float(c)}
            t, d = run_one(f"a{a}_c{c}", o)
            rows.append((f"a={a} c={c}", o, t, d))
    rows.sort(key=lambda r: -r[2])
    print("--- TOP 10 ---")
    for label, o, t, d in rows[:10]:
        print(f"  {label:30s}  total={t:>7d}  days={d}")

    # Phase B: combine new winners with best anchor
    best_a = float(rows[0][1]["H_ANCHOR"])
    best_c = float(rows[0][1]["H_CLIP"])
    print(f"\n=== layer combos (anchor={best_a}, clip={best_c}) ===")
    rows2 = []
    grid = list(itertools.product(
        [0.0, 0.5, 1.0, 1.5],   # ASYM_REDUCE_SHORT
        [0.10, 0.13, 0.15, 0.18, 0.20],  # AR1_BETA
        [1.5, 2.0, 3.0, 4.0],   # H_PENNY_EDGE
    ))
    for asym, ar, pn in grid:
        o = {
            "H_ANCHOR": best_a, "H_CLIP": best_c,
            "ASYM_REDUCE_SHORT": asym, "AR1_BETA": ar, "H_PENNY_EDGE": pn,
        }
        label = f"asym{asym}_ar{ar}_pn{pn}"
        t, d = run_one(label, o)
        rows2.append((label, o, t, d))
    rows2.sort(key=lambda r: -r[2])
    print(f"--- TOP 15 of {len(rows2)} ---")
    for label, o, t, d in rows2[:15]:
        print(f"  {label:35s}  total={t:>7d}  days={d}")


if __name__ == "__main__":
    main()
