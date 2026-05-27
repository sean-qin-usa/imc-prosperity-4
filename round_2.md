# Round 2 — Drift-carry, MAF auction, manual budget split

**Products:** Same as R1 — `ASH_COATED_OSMIUM` (ACO) and `INTARIAN_PEPPER_ROOT` (IPR), limit 80 each. New mechanic: `Trader.bid()` for the **Market Access Fee** blind auction. Manual challenge is the **Research / Scale / Speed** budget allocation.

**Final ship:** [`traders/round2/final_strat.py`](./code/traders/round2/final_strat.py), with the full reasoning frozen in [`ROUND2_RECIPE.md`](./code/traders/round2/ROUND2_RECIPE.md).

## What R2 fixed from R1

The R1 ship treated IPR's upward shape as a *forecast* (path anchor) rather than a *mechanical carry*. R2 reframed it correctly:

- IPR drift is **+0.001 / ts**, deterministic, the same every day. At limit 80 that's `80 × 1000 = 80 000 / day / market` of pure carry.
- **Optimal IPR strategy is never flat, never short during the day**. Target = +80 long, unwind only in the last 1 % of day.

This single reframe was worth roughly 25–30 k / day over the R1 ship, and is the only reason the R2 numbers improved at all.

## Data sanity (per-day, reproduces across all 3 days)

| Product | drift / 1e6 ts | residual sd | AR(1) mid-diff | mode spread |
|---|---|---|---|---|
| ACO | ≈ 0 | ~400 | −0.50 | 16 (~58 % of ticks) |
| IPR | +984 to +1026 (≡ +0.001/ts) | ~500 | −0.50 | 12–14 |

**L1 imbalance → next-Δmid**: P(up \| imb > +0.5) = 88–96 % on both products; aggregate r ≈ +0.59. The critical caveat below shows why that headline correlation is misleading.

## The ACO "micro-price is wrong" lesson

Pure micro-price as fair *sounds* correct given the +0.59 imbalance-Δmid correlation. It is wrong for ACO in the common regime, and finding this out cost the better part of one day:

> **At spread ≤ 16 (the 58 % typical state), L1 imbalance ↔ next-Δmid ≈ 0.** The +0.59 aggregate correlation is almost entirely carried by *walked* states (spread 18–19). A strategy that uses pure micro-price as fair at normal spreads is *tracking noise* and regresses PnL by ~20 k / day.

The fix is to spread-gate the micro-price shift: fall back to the touch midpoint when spread ≤ typical, only enable the micro-price shift when the book is walked. For ACO specifically that becomes the clipped anchor:

```
fair_ACO = 10_000 + clip(micro − 10_000, ±4)
```

For IPR the drift-corrected anchor plays the same role.

## Sizing — large is correct

Naive size 18–22 leaves ~50 k / day on the floor. The tuned grid sits on a plateau at `(ACO_MM_SIZE=75, ACO_WALKED_EXTRA=55)`; smaller is strictly worse, larger gives tiny gains for noticeably more drawdown. IPR uses a 2-level passive bid (primary size 12 at `best_bid+1`, secondary size 6 at `best_bid+2`), with the secondary skipped on adverse imbalance or limit risk.

## Walked-spread rebound (+10–20 k / day, free)

When observed spread > typical, one side has "walked". The walked side snaps back +1.4 to +2.4 on the next tick (measured: at spread 19, ±1.4; spread 21, ±2.4 on ACO). Detect by `spread > TYPICAL_SPREAD`, identify which side walked by `max(bid_gap, ask_gap)` against the anchor, post an inside-spread quote on the rebound side (`ACO_WALKED_EXTRA = 55`, `IPR_WALKED_EXTRA = 12`) and shift fair toward the non-walked side by `typical_spread / 2`. This works on both products; it's pure microstructure alpha that requires nothing about the generative story.

## IPR early-accumulation window

During the first 2 000 ticks, take every ask ≤ benchmark up to limit 80, at most 20 / tick. The goal is to be at the +80 carry position before the book gets expensive. After ts > 2000, continue taking up to soft target 72 (leaves room for passive top-up); full 80 is the day-long carry target.

## Backtest results

Benchmark suite on `tools/calibrations/local_bundles_profile.json` (real-data proxy — expect ~10 % optimism vs real submission):

| Strategy | 3-day total | Per-day |
|---|---:|---:|
| Pure micro-price MM, size 20, no carry | ~210 k | ~70 k |
| **Recipe in [ROUND2_RECIPE.md](./code/traders/round2/ROUND2_RECIPE.md) — `final_strat.py`** | **~420 k** | **~140 k** |
| Historical `clean_alpha` v10 (best clean) | ~441 k | ~147 k |
| Backtester-artifact branches (do NOT ship) | 500–800 k | — |

The gap between "clean" and "artifact" branches mattered more than the headline numbers. `final_strat_aco_max80_chunk1.py` hit ~785 k local on a 1-lot child-order chunking variant — and produced 27–30 k on real submission. That branch is preserved in the repo as a research artifact, never shipped. See [lessons_learned.md §1](./lessons_learned.md) on local-backtester artifacts.

## MAF blind auction

`def bid(self): return 15_000`. Local backtester ignores this; real run uses it. 15 k is a mid-range guess for the top-50 % cutoff that wins 25 % extra quotes. With no public anchor for the distribution this was a near-coin-flip — I should have submitted a range of values across the practice runs to learn the cutoff before going live. Did not.

## Manual challenge — Research / Scale / Speed

The deterministic optimum (Research × Scale × Speed-multiplier rank-bid contest) lives on a stable frontier: roughly **23 % Research / 77 % Scale of whatever budget remains after Speed**, with Speed only worth it if it materially lifts the rank-based multiplier.

The actual decision is a clustering problem against the field:

- AI-default bidders converge on the obvious round-number answer (20 % Speed).
- Smooth contest-aware teams distribute over the equilibrium support (0–80 % Speed).
- "Nice number" humans cluster at 5/10/20/25/30/50/100.
- Meme focal points: 42, 69, 73.

I submitted **`19 / 60 / 21`** — one step past the contaminated `20 %` cluster. Across three plausible field priors (`mostly_nash`, `heavy_round_numbers`, `bimodal_dropout_sim`), this same split was the best response with worst-case regret of 0. Full sensitivity table and PnL grid in [`analysis/round2_manual/summary.md`](./code/analysis/round2_manual/summary.md).

## Documented dead-ends (R2)

The research log has the full list with the scan that killed each, but for the record:

- Tight-spread micro-price gate (spread ≤ 10 → use micro). Signal r = +0.87 is real but costs 2 pts on takes; net −8 k / 3-day.
- Conditional imbalance by book depth (thin vs thick). No material asymmetry (r 0.60 vs 0.62).
- L1 absolute-depth direction signal. Only a weak volatility-regime hint, no direction.
- First-/last-N-tick of day anomalies. Flat across the day except for the IPR drift itself.
- ACO top-of-book Markov transition skew. Largest observed |skew| = 0.085, below the tradable threshold (~0.10).
- IPR z-score mean-revert trades on residual. Residual half-life 0.1–0.2 ticks (white noise around drift). Trading the small ones is noise.

## What I'd change

1. **Calibrate the MAF blind-auction guess.** Submitting a single 15 k bid with no way to learn the cutoff was an avoidable lottery.
2. **Drop the chunking branches earlier.** I spent a partial session validating the 1-lot child-order variant against the calibrated profile. It was clearly a matching-engine artifact on the third scan; should have been on the first.
3. **Stress-test the EOD unwind.** The last 1 % of day is where day-3 IPR positions hit. I never simulated what happens if IPR mid drops 5 σ in those final ticks — the unwind doesn't price that risk.
