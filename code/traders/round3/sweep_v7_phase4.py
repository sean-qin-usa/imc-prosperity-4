"""Phase 4: combine new winners (size=18, clip_vol_k=0.3, wide=10, clip=34)."""
from __future__ import annotations
import itertools, re, subprocess, tempfile
from pathlib import Path

REPO = Path("/Users/sean_tsu_/Downloads/prosperity/IMCP2026")
TEMPLATE = REPO / "traders/round3/h_only_v7.py"
RUNS_DIR = Path(tempfile.mkdtemp(prefix="hv7p4_"))


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
    if total is None: raise RuntimeError(f"{label}: {out[-300:]}")
    return total, days


BASE = {"H_ANCHOR": 9985.0, "AR1_BETA": 0.18, "H_PENNY_EDGE": 2.0,
        "H_INV_SKEW": 0.015, "H_REDUCE_EDGE": 0.0}


def main():
    print(f"runs dir: {RUNS_DIR}")
    rows = []
    grid = list(itertools.product(
        [33.0, 34.0],            # H_CLIP
        [16, 18, 20, 22],        # H_MAX_POST_SIZE
        [8, 10, 12],             # H_WIDE_SPREAD
        [0.0, 0.2, 0.3, 0.4, 0.5],  # CLIP_VOL_K
        [0.15, 0.18, 0.20],      # AR1_BETA
    ))
    print(f"  cells: {len(grid)}")
    for cl, sz, wd, cvk, ar in grid:
        o = dict(BASE)
        o.update({"H_CLIP": cl, "H_MAX_POST_SIZE": sz, "H_WIDE_SPREAD": wd,
                  "CLIP_VOL_K": cvk, "AR1_BETA": ar})
        label = f"cl{cl}_sz{sz}_wd{wd}_cvk{cvk}_ar{ar}"
        try:
            t, d = run_one(label, o)
        except Exception as e:
            print(f"  ERR {label}: {e}")
            continue
        rows.append((label, o, t, d))

    rows.sort(key=lambda r: -r[2])
    print(f"\n--- TOP 30 ---")
    for label, o, t, d in rows[:30]:
        print(f"  {label:55s}  total={t:>7d}  days={d}")
    print(f"\n--- BOTTOM 5 ---")
    for label, o, t, d in rows[-5:]:
        print(f"  {label:55s}  total={t:>7d}  days={d}")


if __name__ == "__main__":
    main()
