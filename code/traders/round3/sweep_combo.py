"""Combined sweep: explore interactions among winning levers."""
from __future__ import annotations
import itertools, re, subprocess, tempfile
from pathlib import Path

REPO = Path("/Users/sean_tsu_/Downloads/prosperity/IMCP2026")
TEMPLATE = REPO / "traders/round3/h_only_v6.py"
RUNS_DIR = Path(tempfile.mkdtemp(prefix="hcombo_"))


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
        raise RuntimeError(f"no total for {label}: {out[-500:]}")
    return total, days


def main():
    print(f"runs dir: {RUNS_DIR}")
    rows = []

    # Phase 1: combine the two big winners (skew × reduce_edge × AR1 × size)
    skews = [0.008, 0.010, 0.012, 0.015]
    reds = [0.0, 0.5, 1.0]
    ar1s = [0.10, 0.15, 0.20, 0.25, 0.30]
    sizes = [20, 25]
    print("\n=== combo grid: skew × reduce_edge × AR1 × size ===")
    print(f"  cells: {len(skews) * len(reds) * len(ar1s) * len(sizes)}")
    for sk, rd, ar, sz in itertools.product(skews, reds, ar1s, sizes):
        o = {"H_INV_SKEW": sk, "H_REDUCE_EDGE": rd, "AR1_BETA": ar,
             "H_MAX_POST_SIZE": sz}
        label = f"sk{sk}_rd{rd}_ar{ar}_sz{sz}"
        try:
            t, d = run_one(label, o)
        except Exception as e:
            print(f"  ERR {label}: {e}")
            continue
        rows.append((label, o, t, d))

    rows.sort(key=lambda r: -r[2])
    print(f"\n--- TOP 25 ---")
    for label, o, t, d in rows[:25]:
        print(f"  {label:40s}  total={t:>7d}  days={d}")
    print(f"\n--- BOTTOM 5 ---")
    for label, o, t, d in rows[-5:]:
        print(f"  {label:40s}  total={t:>7d}  days={d}")


if __name__ == "__main__":
    main()
