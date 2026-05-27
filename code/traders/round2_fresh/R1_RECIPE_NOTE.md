# P4 Round 1 — pointer

P4 R1 uses the **same two products** (`ASH_COATED_OSMIUM`,
`INTARIAN_PEPPER_ROOT`) at the **same position limits** (80 / 80) as
P4 R2.  The §0.2 data sanity numbers match R2 within noise
(see `analysis/fresh_scan_round1.py` output).

**Use `ROUND2_RECIPE.md`** — it works directly on R1 data with no
changes.  Backtest verification (2026-04-23):

```
python3 tools/backtester.py traders/round2_fresh_claude/fresh_r1_from_recipe.py \
  --dataset round1_csv --fill-model official-hybrid \
  --exchange-calibration tools/calibrations/local_bundles_profile.json --no-plots
```

| Day | Total PnL | Max DD |
|---|---|---|
| −2 | +141,649 | −1,919 |
| −1 | +142,566 | −1,951 |
| 0  | +131,949 | −1,957 |
| **3-day total** | **+416,163** | — |

Targets: **200 k / 3-day** and **20 k min-single-day**.  Both cleared
by a factor of ~2 and ~6.6× respectively.

The only thing R1 strategy should change vs R2 is `MAF_BID = 0` (MAF
is a R2-only mechanic; `bid()` return is ignored in R1).

For every cross-round reuse, confirm:
1. Products match (by name and composition).
2. Position limits match.
3. §0.2 sanity numbers (drift, rsd, AR(1), mode spread) match within
   ±20%.

If any of these diverge, fall back to the first-principles §0.1 → §7
workflow in `SIGNALS_PLAYBOOK.md`.
