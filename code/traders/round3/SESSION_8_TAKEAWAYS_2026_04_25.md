# Round 3 — Session 8 takeaways (2026-04-25)

## Backtest ladder (3-day, jmerle, --merge-pnl)

| File | bt total | alpha-floor | Δ vs v15_hdrift | Status |
|---|---|---|---|---|
| **combined_ship_v25.py** | **497,324** | **341,134** | **+51,876** | v23 chassis + Citadel VFE MR + cap=15. **NEW high water mark.** Alpha-floor jumped +60k over v23 → real take-side alpha, not matching-engine wallpaper. |
| combined_ship_v24.py | 493,785 | TBD | +48,337 | v23 chassis + Citadel VFE MR (default cap=80). Clean port of dad.py's sleeve onto v23. |
| dad.py | 485,676 | TBD | +40,228 | Citadel bipolar VFE long-EMA z-score MR on v11 chassis (no v15+ improvements). |
| combined_ship_v23.py | 451,331 | 280,836 | +5,883 | Asym H_INV_SKEW (LONG=-0.004, SHORT=+0.014). Stacks v22 + v15_hdrift. |
| combined_ship_v22.py | 447,042 | +1,594 | VEV drift carry on V5000-5300, target=300. |
| combined_ship_v15_hdrift_aggr.py | 445,498 | +50 | "Aggr" knobs add nothing on hdrift base. |
| combined_ship_v15_hdrift.py | 445,448 | (baseline) | HYDROGEL drift-regime CLIP gate. |
| combined_ship_v21.py | 445,078 | -370 | VEV carry on v20 chassis (pre-hdrift). |
| combined_ship_v15_aggr.py | 443,534 | -1,914 | "Aggr" knobs minus drift-gate regress. |
| combined_ship_v22_parity.py | 428,042 | -17,406 | Parity-fair on V4000/V4500 KILLS lead-lag alpha. |

## What dad.py does differently (vs v23 chassis)

dad.py is a parallel branch built on the **v11 chassis**, NOT the v15+ ladder.
It is missing every session-7/8 improvement EXCEPT one big new sleeve.

**Missing from dad.py (recoverable upside if ported):**
- HYDROGEL drift-regime CLIP gate (v15_hdrift, +1,964)
- VEV drift carry on V5000-5300 (v22, +1,594)
- Asymmetric H_INV_SKEW LONG/SHORT (v23, +4,289)
- Newer HYDROGEL constants (TE=0.6, AR1=0.25, CLIP_VOL_K=0.795)
  — dad.py uses v11's looser (TE=0.5, AR1=0.17, CLIP_VOL_K=0.76)

**New in dad.py:**
- **Citadel bipolar VFE long-EMA z-score MR**:
  - `VFE_EMA_ALPHA = 0.0005` → half-life ~1386 ticks (~14% of a day)
  - `VFE_SIGMA_ALPHA = 0.0005` (same window)
  - `VFE_Z_ENTER = 2.0`
  - On |z|≥2 enter side; flip on opposite cross; hold at ±LIMIT (200)
  - `VFE_WARMUP_TICKS = 500` (no trades until EMA stabilises)
  - `VFE_MAX_TAKE_PER_TICK = 80`
- Replaces the Timo P3R3 short-window underlying MR (`ENABLE_UNDERLYING_MR = False`)
- Self-reported: original short-window MR ~+20k gross; Citadel ~+93k gross.
  My run: dad.py minus v11 base = +56,922 (485,676 - 428,754) — broadly consistent.

## What this means for shipping

**The "best by backtest" answer is dad.py at 485,676.** But it has the highest
**live-conversion risk** of any sleeve we've ever shipped:

1. The Citadel layer is a **directional position bet**, not a market-make.
   It holds full-limit (±200) for thousands of ticks. Per memory
   "voucher MR alpha converts ~1-3% to live" — though that's voucher MR,
   not underlying. Underlying directional MR has zero precedent in our
   live ladder.
2. Long-EMA mean-reversion may be capturing the day's overall drift
   trajectory, which **does not reproduce in live** (live data is a
   different sample path).
3. The +93k claimed vs +20k for short-window MR is a 4.6× ratio. If
   only the +20k portion is "real" (small enough to be cross-spread
   trade alpha), the Citadel layer's marginal contribution above that
   is +73k of which an unknown fraction is sample-path luck.

**Risk-adjusted recommendation hierarchy** (assuming ship today):

| Pick | bt | Reason |
|---|---|---|
| **AGGRESSIVE** | dad.py 485,676 | Bet that Citadel VFE MR works live; +34k+ upside if it does. Worst case: VFE leg loses ~30-50k vs the v11 short-window MR baseline. |
| **CONSERVATIVE** | v23 451,331 | All sleeves verified or alpha-floor-checked. Stack of 3 independently-validated improvements over v15. |
| **DEFENSIVE** | v22 447,042 | If v23's asym skew feels too "in-sample-fit", v22 is the honest +VEV-carry stack. |

If we have time before submission close, **port Citadel VFE MR onto v23
chassis** and re-backtest — that's the dominated-uncertainty play
(captures both alpha buckets, and reveals whether they're additive).

## Process takeaways (for future sessions)

1. **Don't trust docstring numbers.** v23 originally shipped with the
   asym-skew constants defined but not wired into the trade logic
   (backtested at 425,646 vs claimed 451,331 — 25k gap). User fixed
   the wiring after I flagged the gap. **Re-backtest after every edit
   that touches strategy state.** This already in memory as
   `feedback_backtest_every_strategy_edit.md`; reinforced this session.

2. **The v15_hdrift_aggr file added nothing.** Going forward when an
   "aggressive" variant just bumps a single knob, run the backtest before
   creating the file. Net: +50 bt = noise.

3. **v22_parity is a -17k regression** because parity-replace destroys
   the BS lead-lag alpha (Δm propagates voucher→VFE on the BS theo,
   not the parity offset). When testing "alternative fair", always
   include the BS-fair as a control variant, and prefer ADDITIVE
   bias (parity correction layered on top of BS) over REPLACEMENT.

4. **The session-8 deep research log identified the skew-residual signal
   as untapped (+24k paper PnL).** All integration attempts on v15 chassis
   regressed -33k+ because of spread cost (memory:
   `feedback_skew_residual_unmonetizable.md`). dad.py demonstrates the
   alternative: stop trying to harvest the skew residual via voucher
   take/MM-bias, and instead use a **longer-horizon underlying-only
   directional MR** which sidesteps the spread cost entirely.

5. **Submission validator regex `import\s*os` is a flat substring scan.**
   Including comments/docstrings. Re-confirmed this session: v23's
   updated docstring re-introduced the literal phrase and would have
   been rejected. Already in memory as `feedback_no_import_os.md`;
   added pre-upload grep to checklist.

## What we did this session — completed

### 1. ✓ Ported Citadel VFE MR onto v23 chassis (v24 = 493,785 bt)
Clean port: `_trade_citadel_vfe_mr` from dad.py, `ENABLE_UNDERLYING_MR=False`,
all v23 levers (drift-gate, VEV carry, asym skew) preserved. Per-asset
deltas confirmed clean addition (HYDROGEL identical to v23, VFE
identical to dad.py).

### 2. ✓ Tuned `VFE_MAX_TAKE_PER_TICK` (v25 = 497,324 bt)
Sweep cap ∈ {10, 15, 20, 25, 30, 40, 50, 60, 80, 200}: peak at 15
with smooth plateau 10-30. +3,539 over default cap=80. Slower
per-tick rebalancing reduces whipsaw on local z-score crossings.

### 3. ✓ Confirmed `VFE_Z_ENTER=2.0` and `VFE_EMA_ALPHA=5e-4` are robust peaks
Z sweep {1.5, 1.75, 2.0, 2.25, 2.5}: peak Z=2.0 with -13k to -55k
regression on either side. ALPHA sweep on cap=15 chassis: peak 5e-4
with -10k to -31k regression on either side. dad.py defaults
transferred cleanly.

### 4. ✓ Alpha-floor check on v25 — the deciding diagnostic
**+60,298 alpha-floor jump** vs v23: v25 = 341,134; v23 = 280,836.
Per `feedback_match_trades_none_for_alpha.md` (match-trades none is
a live-predictive lower bound), this means the Citadel layer is
take-side directional alpha that bots can't avoid — NOT matching-engine
wallpaper. **Downgrades the original "high live-conversion risk"
warning to "moderate".**

## Open work (next session if needed)

### 1. Bundle-cal scoring for tighter live forecast
Run `score_round3_candidates.py --bundle-dir <bundle>` on v25 if
the calibrated bundle is available — per memory it's ~99% accurate
vs live, much tighter than the ~341k–497k match-trades-none-vs-all
range we have now.

### 2. Sanity ablation: dad.py with Citadel disabled vs v11
Confirm dad.py's chassis is identical to v11 by toggling
`ENABLE_CITADEL_VFE_MR = False`. Should reproduce ~v11's 428,754.
If it doesn't, there's an undocumented chassis change worth
recording.

### 3. Re-tune HYDROGEL on Citadel chassis
Cross-correlation through the position book MAY shift H_INV_SKEW or
CLIP_VOL_K optima. Sensitivity sweep on the two main HYDROGEL knobs;
gains likely sub-2k.

## Files to delete or stop tracking
- `combined_ship_v22_parity.py` — confirmed -17k regression, no path forward
- `combined_ship_v15_aggr.py` and `combined_ship_v15_hdrift_aggr.py` — no
  alpha vs base; "aggr" knobs were a bust
