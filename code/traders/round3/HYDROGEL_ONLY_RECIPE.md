# HYDROGEL_PACK Stand-Alone Strategy — Recipe (v8, 2026-04-24)

## TL;DR

`traders/round3/h_only_v8.py` ships at **171,890** over 3 historical
days (61,791 / 52,465 / 57,634), HYDROGEL ONLY. That is +22,535
(+15.1 %) over the v5 HYDROGEL-only baseline (149,355) and +3,859 over
the v5 ship total of 168,031 *that included VEV trading*. In other
words, optimised HYDROGEL alone now beats HYDROGEL+VEV in v5 net.

```
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/jmerle_backtester.py traders/round3/h_only_v8.py 3 --merge-pnl --no-out
```

## Verdict from the covariate hunt — HYDROGEL is INDEPENDENT

Three independent passes (`covariate_hunt.py`, `..._v2.py`, `..._v3.py`)
across days 0/1/2:

| Test | Result |
|---|---|
| Δmid(H) vs Δmid(X) at lags ±5, all products | best \|R\| = 0.03, sign-flip across days |
| Pooled (3-day) regression with day-FE | all \|t\| ≤ 1.26 |
| Partial corr after controlling own-imbalance + AR(1) | best \|t\| = 3.24 day 2 only, doesn't replicate |
| Out-of-sample R² with 36 cross features (train 2 days, test 3rd) | **NEGATIVE** for all 3 rotations (-0.0033, -0.0024, -0.0020) |
| Sign-only IC for X→H at K∈{1,5,20} | best \|z\| = 1.34, all within sampling noise |
| Composite basket Σsign(ΔX) | HR ≈ 0.50, \|z\| ≤ 1.21 |
| Hour-of-day stable diurnal pattern | per-bucket means 10⁻² ticks, no consistent shape |
| Block returns (K=50/200/500) cointegration | sign flip across days → spurious common-trend |
| Walked-spread regime gating | nothing significant at \|t\|>4 |
| Signed trade flow in X (any product) → ΔH | one z=-3.10 day 1 only, doesn't replicate |

**Conclusion**: every cross-product candidate is noise once tested
out-of-sample or for sign-stability. Build HYDROGEL strictly from its
own microstructure.

## Real signals (own-microstructure only)

| Signal | Strength | How it's used |
|---|---|---|
| Own L1 imbalance, spread<16 | E[ΔH] = +4.1, z=20 | Spread-gated micro-price as fair input |
| Own L1 imbalance, spread=16 (typical) | E[ΔH] ≈ 0, z<1 | DEAD — fall back to touch_mid |
| AR(1) Δmid_H | R = -0.13 | Lean fair against last move (β=0.18) |
| \|ΔH\| ↔ spread | R = -0.32 | Inform CLIP_VOL_K (volatility-adaptive CLIP) |
| Per-day mid mean | 9990.96 / 9992.06 / 9989.40 | Fixed anchor 9985 (works even though true mean is +5) |

## Final tuned parameters

| Param | v5 baseline | v8 ship | Δ contribution |
|---|---|---|---|
| `H_ANCHOR` | 9990 | **9985** | +6.2k (joint, anchor sweep) |
| `H_CLIP` | 30 | **33** | +0.3k (joint with anchor) |
| `H_INV_SKEW` | 0.015 | 0.015 | plateau 0.014–0.016 |
| `H_REDUCE_EDGE` | 1.0 | **0.0** | +3.0k |
| `AR1_BETA` | — | **0.18** | +1.5k (cliff at <0.15) |
| `H_PENNY_EDGE` | 1.5 | 2.0 | flat 0.5–4.0 |
| `H_MAX_POST_SIZE` | 20 | **18** | plateau 16–22, cliff at 30 (-17k day 1) |
| `H_PASSIVE_OFFSET` | 8 | 8 | irrelevant (only fires at spread<8, rare) |
| `H_WIDE_SPREAD` | 8 | 8 | plateau 4–14 |
| `TYPICAL_SPREAD` (NEW) | n/a | **16** | +1.9k (micro-price gate) |
| `CLIP_VOL_K` (NEW) | n/a | **0.3** | +1.5k (vol-adaptive CLIP) |
| `ANCHOR_EMA_ALPHA` | n/a | 0.0 | OFF — even α=1e-4 loses 7.5k |
| `ASYM_REDUCE_*` | n/a | 0.0 | OFF — neutral or worse |
| `LAYER2_FRACTION` | n/a | 0.0 | OFF — fills already saturate |

## Why anchor=9985 < true mean (9990)

Anchor controls the desired-flat point. Setting it 5 below the actual
mean biases inventory toward shorts when mid is at ~9990: skew = anchor
- 0.015·pos, so at pos=0 we're already pricing 5 below mid. We sell
when mid ≥ 9990 (above anchor), hold the short until mid drops back to
~9985. Combined with `H_REDUCE_EDGE=0.0` (no premium for closing), we
patiently capture the mean-reversion. This is the single biggest lever
in v8.

## CLIP_VOL_K = 0.3

`CLIP = 33 + 0.3 × stdev(last 20 ΔH)`. When realised volatility spikes,
the fair tracks the touch_mid more loosely; we don't get whipsawed by
short bursts that revert. Adds +1.5k. K∈{0.2, 0.3, 0.5} all near peak;
K=1.0 hurts.

## Don't (verified bad in this regime)

1. **EMA anchor**: even α = 1e-4 loses 7.5k. Anchor must be fixed.
2. **Cross-product features**: any cross-product feature regresses PnL
   under OOS validation. Ignore VEV / VELVETFRUIT / strikes for
   HYDROGEL fair.
3. **`H_REDUCE_EDGE > 0`**: every step up loses ~4k.
4. **`H_INV_SKEW > 0.018`**: collapses to 156k at 0.025, 140k at 0.025.
5. **`H_MAX_POST_SIZE ≥ 30`**: day 1 craters by ~16k (still don't know
   why a single oversized fill cascades that hard).
6. **`H_PENNY_EDGE > 5`**: posting too deep skips fills, -3k+.
7. **Layered passive quotes (Layer-2)**: 0 PnL contribution; fills
   already saturate at single-layer post sizes.
8. **`AR1_BETA ≤ 0.13` or ≥ 0.25**: there is a cliff at 0.15 (drops to
   143k). Plateau is exactly 0.15-0.20.

## Reproduction & verification commands

```bash
# Final ship file
python3 tools/jmerle_backtester.py traders/round3/h_only_v8.py 3 --merge-pnl --no-out
# Expected: total 171,890  (61,791 / 52,465 / 57,634)

# Covariate-hunt rerun (all three passes)
python3 traders/round3/covariate_hunt.py
python3 traders/round3/covariate_hunt_v2.py
python3 traders/round3/covariate_hunt_v3.py

# Param-sweep harness (sweep_h.py / sweep_combo.py / sweep_v7*.py) all
# in traders/round3/.
```

## File map

| File | Purpose |
|---|---|
| `h_only_v8.py` | **SHIP** — final HYDROGEL-only strategy |
| `h_only_v7.py` | sweep template (kept for reproducing the search) |
| `h_only_v6.py` | first iteration adding micro-price + AR1 lean |
| `h_only_v5.py` | v5-equivalent HYDROGEL-only baseline (149,355) |
| `covariate_hunt*.py` | the 3 covariate-hunt passes (v1/v2/v3) |
| `imb_regime.py` | spread-conditional own-imbalance analysis |
| `sweep_h.py` / `sweep_combo.py` | v6 1-D and combo sweepers |
| `sweep_v7*.py` | v7 phase-2/3/4b sweepers |
