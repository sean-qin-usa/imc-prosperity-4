"""Phase 4b: smaller smart sweep — focus on size × clip_vol_k × clip × wide."""
from __future__ import annotations
import itertools, re, subprocess, tempfile
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

REPO = Path("/Users/sean_tsu_/Downloads/prosperity/IMCP2026")
TEMPLATE = REPO / "traders/round3/h_only_v7.py"
RUNS_DIR = Path(tempfile.mkdtemp(prefix="hv7p4b_"))


def render(overrides):
    src = TEMPLATE.read_text()
    for key, val in overrides.items():
        pat = rf"^(    {key}\s*=\s*)[^#\n]+(.*)$"
        src = re.sub(pat, lambda m, v=val: f"{m.group(1)}{v}{m.group(2)}",
                     src, count=1, flags=re.MULTILINE)
    return src


def run_one(args):
    label, overrides = args
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
    if total is None: raise RuntimeError(f"{label}")
    return label, overrides, total, days


BASE = {"H_ANCHOR": 9985.0, "AR1_BETA": 0.18, "H_PENNY_EDGE": 2.0,
        "H_INV_SKEW": 0.015, "H_REDUCE_EDGE": 0.0}


def main():
    print(f"runs dir: {RUNS_DIR}")
    grid = list(itertools.product(
        [33.0, 34.0],            # H_CLIP
        [16, 18, 20, 22],        # H_MAX_POST_SIZE
        [8, 10, 14],             # H_WIDE_SPREAD (3 only)
        [0.0, 0.3, 0.5],         # CLIP_VOL_K (3 only)
    ))
    cells = []
    for cl, sz, wd, cvk in grid:
        o = dict(BASE)
        o.update({"H_CLIP": cl, "H_MAX_POST_SIZE": sz, "H_WIDE_SPREAD": wd, "CLIP_VOL_K": cvk})
        label = f"cl{cl}_sz{sz}_wd{wd}_cvk{cvk}"
        cells.append((label, o))
    print(f"  cells: {len(cells)}")

    rows = []
    with ProcessPoolExecutor(max_workers=6) as ex:
        for label, o, t, d in ex.map(run_one, cells):
            rows.append((label, o, t, d))
            print(f"  {label:48s}  total={t:>7d}  days={d}", flush=True)

    rows.sort(key=lambda r: -r[2])
    print(f"\n--- TOP 15 ---")
    for label, o, t, d in rows[:15]:
        print(f"  {label:48s}  total={t:>7d}  days={d}")


if __name__ == "__main__":
    main()
