# Round 3 Session 8 Deep Research Log — 2026-04-25

## Mission

Session 8 summary said retunes are saturating; the +100k breakthrough has to
come from fundamentally new alpha categories. This session: a comprehensive
signal hunt across all 12 R3 products covering temporal patterns, vol
dynamics, trade-flow leading indicators, IV smile dynamics, basket
arbitrage, and time-weighted carry.

## Tools

`traders/round3/deep_research_s8{.py,b.py,c.py,d.py,e.py}` — five-stage
pipeline:
- `s8` — broad signal survey (vol clustering, trade flow, time-of-day,
  EOD reversal, butterfly/skew stationarity, skew→spot, K-block
  autocorrelation, time-weighted VFE carry).
- `s8b` — OOS-validate top signals per-day; toy strategy PnL.
- `s8c` — cross-product trade-flow leading indicator; VFE block vol
  clustering; skew-residual stationarity.
- `s8d` — skew-residual level → forward VFE return at K = 1, 5, 20, 100.
- `s8e` — partial-corr controlling for VFE own AR(1); toy paper-trade
  with edge over AR(1) baseline.

## Headline findings

### REAL signals (OOS-stable, partial-corr-survives, NOT yet captured)

#### 1. Skew-residual leads VFE — STRONGEST UNTAPPED SIGNAL

`residual = (V5500_mid - V5000_mid) - (a + b * VFE_mid)` where (a, b) is
a per-day OLS fit (a≈+4170, b≈-0.85; daily level shifts).

| | day 0 | day 1 | day 2 |
|---|---|---|---|
| raw corr(residual_t, ΔVFE_{t+1}) | -0.240 | -0.233 | -0.228 |
| **partial corr (control: ΔVFE_t)** | **-0.213** | **-0.202** | **-0.203** |
| Δresidual partial corr | +0.379 | +0.391 | +0.413 |

VFE own Δm AR(1) = -0.15 to -0.17 (strong own MR). After controlling, the
skew-residual signal SURVIVES at corr ≈ -0.20 across all 3 days — uniformly
consistent. **Δresidual** signal is even stronger at +0.38–0.41 (note:
positive sign because Δresidual and ΔVFE are concurrent through the fit;
the LAG-1 partial corr is the actionable form).

Paper-trade edge over pure AR(1) baseline (LIMIT=200, full rebalance):
- Day 0: +8,318
- Day 1: +5,623
- Day 2: +10,246
- **Total: +24,187 paper PnL** beyond what AR(1) captures.

##### Spread-cost wall

Implementation as a take-side trader (`vfe_skew_v1.py`) **LOSES -10,116** in
the local backtester. Same family as the recent "Flow-burst take needs
alpha > half-spread" memory: VFE half-spread ~2.5 ticks; predicted
ΔVFE_{t+1} from typical residual is well under 2.5 ticks; every take pays
the spread. The signal can only be monetized via **MM-side bias** —
shifting `vfe_fair` or gating drift-carry posts based on residual sign.

##### Why this is the right alpha to chase next

- Robust across days, partial-corr-stable, large effect size.
- Orthogonal to current sleeves (HYDROGEL, drift carry, voucher MR).
- Estimated live impact at full conversion: +5–15k bt → ~+1–3k live
  (assuming voucher MR class conversion ratio).
- Implementation hook: in `_trade_iv_residual` (combined_ship_v15.py
  line 508–630), add `combined_dev = ema_o_dev + W_SKEW * residual` and
  use this for the MR threshold check at line 616/618. Drift-carry post
  at line 626 should also be skipped when `residual > THR_HIGH` (predict
  drop, don't accumulate long).

#### 2. Vol clustering on V4000 / V4500 / V5500 — REAL but already captured

| product | |Δm| AR(1) | OLS R² | b1 |
|---|---|---|---|
| V4000 | +0.317 | 10% | 0.32 |
| V4500 | +0.242 | 6% | 0.24 |
| V5500 | +0.265 | 7% | 0.27 |
| HYDROGEL | +0.087 | 1% | 0.09 |
| VFE | +0.088 | 1% | 0.09 |

Predictive: |Δm(t)| ≈ 0.63 + 0.32·|Δm(t-1)| for V4000. After a |Δm|=2
move, predict 1.27 next vs typical 1.07. OOS-stable across 3 days.

##### Why not a new lever

V4000/V4500 already have wide spreads (21 ticks); 0.2-tick adverse
selection refinement is small relative to spread. The HYDROGEL drift-gate
(`combined_ship_v15_hdrift.py`, +1,964) already captures the same
mechanism via 200-tick mid-range gating on CLIP_VOL_K — the |Δm| AR1
signal is the within-window manifestation.

V5500 vol clustering is real (b1=0.27) but V5500 is on the lottery
sleeve (LOTTERY_BID_PRICE=0, fixed) so widening doesn't apply.

### KILLED signals

#### 3. K=500 mean reversion — bounded-range artifact

AR(1) on K=500 non-overlapping blocks ≈ -0.30 to -0.37 across ALL
products. Looks tradable. **Toy strategy LOSES on every product on every
day** (in-sample AND out-of-sample). The negative AR(1) at long horizons
is the signature of a price walk in a bounded range, not a tradable
predictor — the reversal happens stochastically and the trader pays
spread in expectation. Confirmed by per-day OOS rotation: betas shift
sign across train/test pairs.

#### 4. K=100 / K=20 mean reversion — unstable

Per-day betas SWITCH SIGN across rotations. PnL near zero with sharpe
in [-0.04, +0.12]. No tradable edge.

#### 5. VEV_5500 K=5 short-horizon MR — spread eats it

Per-day β = -0.19 / -0.26 / -0.21 (consistent). But cum_PnL_per_unit_pos
= -7 / -12 / -7. V5500 spread (1-2 ticks) consumes the per-block
prediction.

#### 6. Cross-product VEV-flow → VFE — too small

Aggregated VEV signed flow at lag 1 vs VFE next move: corrs in
[-0.014, +0.014] across days. Not actionable.

#### 7. VFE-flow → VEV strikes — noise

Lag-1 corrs in [-0.031, +0.027], inconsistent signs across days. Per
"Lead-lag needs partial-corr control" memory, raw corrs at this level
collapse under partial-corr.

#### 8. Time-of-day patterns — sign-flip across days

Per-decile mean Δmid across days has no consistent pattern. EOD/SOD
predictability fails: first-1k vs last-1k means flip per day for every
product.

#### 9. Time-weighted VFE carry (Q4 only) — inconsistent

Per-day Q4 - Q1 acceleration: -30 / -29 / +69. The "drift carry
accelerates near EOD" hypothesis fails — day 2 has the only Q4 burst.

#### 10. VFE block vol clustering — non-existent

Per-day K=5 block AR(1) on |Δblock|: -0.028 / +0.020 / -0.003. R²<0.001.
Even though tick-level |Δm| has AR(1)=0.088, it doesn't survive
block-aggregation.

### Re-confirmations (already in memory)

#### 11. Smile shape (skew, butterfly) — high R², near-random-walk

V5500-V5300 skew: AR(1) on level = 0.99, std=4-5 / day. The smile is
deterministic in the spot but the residual shape is a slow Brownian
process. Butterfly std=2-3 / day. Pair-trade attractive on residual but
mean-reversion horizon is days, not ticks — useless within 10k-tick
horizons.

#### 12. Concurrent skew vs ΔVFE — high lag-0 corr

Δskew vs ΔVFE lag-0 corr = -0.51 to -0.54 (just delta-fit identity);
lag-1 corr ≈ 0 (not a leading indicator at the diff level).
Disambiguates: the LEVEL of the skew RESIDUAL is the actionable signal,
not the diff.

## Recommended next steps (ordered by EV)

### Tier 0: ATTEMPTED & FAILED — direct integration into v15 chassis

`combined_ship_v15_skew.py` implements two integration patterns:
1. `combined_dev = ema_o_dev + W * skew_res` for MR threshold
2. Skip drift-carry bid post when `skew_res > G`

Sweep (`sweep_skew_v15.py`) over W ∈ [-0.3, 1.0] and G ∈ [-9999, 9999]:

| W | G | total | Δ |
|---|---|---|---|
| 0.0 | 9999 | 443,484 | +0 (baseline) |
| 0.05 | 9999 | 383,712 | -59,772 |
| 0.10 | 9999 | 382,128 | -61,356 |
| 0.20 | 9999 | 381,906 | -61,578 |
| 0.50 | 9999 | 382,078 | -61,406 |
| -0.10 | 9999 | 409,930 | -33,554 |
| -0.30 | 9999 | 403,232 | -40,252 |
| 0.0 | -9999 | 429,016 | -14,468 (carry skipped) |
| 0.0 | 6 | 429,016 | -14,468 (always skipped) |

**Every non-zero W LOSES ≥33k** because the MR threshold trigger crosses
the VFE spread (~5 ticks) too often, paying spread on every fire. Every
non-default G also loses because skipping the drift-carry bid forfeits
its +14.5k alpha. The signal IS real (partial-corr survives) but it has
**no extractable form on the v15 chassis**.

The deeper reason: the +24k paper-PnL edge measured in `s8e` assumes
zero spread costs. Real fills require either (1) crossing spread (-2.5
ticks/take) which exceeds the per-tick predicted alpha, or (2)
modulating passive posts (which we already maximally exploit via the
carry). There's no third lane.

This finding generalizes the recent "Flow-burst take" memory: any
fast-decaying VFE-prediction signal (corr -0.2 at lag 1) that's smaller
than half-spread per signal-unit is unmonetizable on this exchange.

### Tier 1 (theoretical): integrate skew-residual into `_trade_iv_residual`

Patch sketch (combined_ship_v15.py):

```python
SKEW_A = 4170.0           # mid-day OLS intercept
SKEW_B = -0.85            # mid-day OLS slope
SKEW_WEIGHT = 0.5         # tunable; sweep 0.2-1.0

# Inside _trade_iv_residual after computing ema_o_dev:
v5000 = self._book(ods.get("VEV_5000", OrderDepth()))
v5500 = self._book(ods.get("VEV_5500", OrderDepth()))
if v5000 and v5500:
    skew_res = (v5500["touch_mid"] - v5000["touch_mid"]) - (
        SKEW_A + SKEW_B * u_wm
    )
    combined_dev = ema_o_dev + SKEW_WEIGHT * skew_res
else:
    combined_dev = ema_o_dev

# Use combined_dev instead of ema_o_dev in the MR threshold checks at L616/618.
# Also gate the drift-carry bid post (L626): skip when skew_res > THR_HIGH.
```

Sweep SKEW_WEIGHT in [0.1, 0.3, 0.5, 0.7, 1.0]. Also sweep an asymmetric
gate for the drift-carry skip.

Predicted backtest delta: +3-8k (rough; signal converts at ~1-3% live so
+1-3k live). Worth trying because it's the only OOS-stable signal we
haven't already sleeved.

### Tier 2: re-anchor `(a, b)` daily

Pooled (a, b) shifts day-to-day (a: 4083→4373, b: -0.825→-0.880).
Replace with online OLS using a 2000-tick window so the signal adapts.
Use `(a, b)` from yesterday's data only; or compute online.

### Tier 3: skip-post on drift-carry under high residual

The +14.7k drift-carry alpha works because VFE drifts +0.002/tick. But
skew residual sign indicates which TICKS will revert. Gate: only post
the drift-carry bid when `skew_res < SKEW_DRIFT_GATE`. Should preserve
most of the carry alpha while avoiding the predicted drops.

## Negative-result archive (don't re-test)

- K=500 cross-product MR — bounded-range artifact, paper PnL negative.
- VEV-flow → VFE leading indicator — corr <0.014.
- VFE-flow → VEV leading indicator — corr <0.03 with sign-flip.
- Time-of-day / EOD / SOD on any product — flips daily.
- Time-weighted VFE drift (Q4 only) — sign-flips daily.
- VEV_5500 short-horizon MR — spread eats it.
- Vol clustering quote-width on V4000/V4500 standalone — already captured
  by HYDROGEL drift-gate equivalent.

## Files

- `deep_research_s8.py` — broad signal survey
- `deep_research_s8b.py` — OOS validation per-day
- `deep_research_s8c.py` — cross-product flow & smile
- `deep_research_s8d.py` — skew residual at multiple strike pairs
- `deep_research_s8e.py` — partial-corr & paper PnL
- `vfe_skew_v1.py` — failed take-side test (-10,116 bt; signal real but
  spread-blocked, must use as MM-side bias)

All forbidden-imports clean (no `import os`).
