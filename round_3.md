# Round 3 — HYDROGEL anchor MM + VEV voucher chain

**Products:** `HYDROGEL_PACK` (stationary anchor ≈ 9990), `VELVETFRUIT_EXTRACT` (VFE, the underlying ≈ 5248), and the **`VEV_*` voucher chain** at strikes 4000 / 4500 / 5000 / 5100 / 5200 / 5300 / 5400 / 5500 / 6000 / 6500. Position limits 200 (HYDROGEL, VFE), 300 (each voucher). 48-hour round, **PnL resets to zero** for the GOAT (R3 + R4 + R5) leg.

**Final ship:** [`traders/round3/combined_ship_v29_mirror.py`](./code/traders/round3/combined_ship_v29_mirror.py), with the full ladder of 30+ versions preserved in the same folder and the reasoning in [`ROUND3_RECIPE.md`](./code/traders/round3/ROUND3_RECIPE.md).

## Generative-process read

Three independent product classes layered into one strategy:

| Class | Products | Story | Strategy |
|---|---|---|---|
| Stationary MM anchor | HYDROGEL_PACK | Anchor ≈ 9990, std 25–38, mode spread 16 | ACO-class clipped-anchor MM |
| Delta-1 underlying | VELVETFRUIT_EXTRACT | ≈ 5248, mild drift, tight 5-spread | Take-only is −EV; use as hedge / vega-bearer |
| Voucher chain | VEV_4000 … VEV_6500 | Calls on VFE; flat-ish σ ≈ 0.23 across liquid strikes | Strike-conditional: ITM synth-MM, ATM IV-residual MR, OTM lottery / skip |

Structurally this is **Prosperity 3 Round 3** (one delta-1 underlying + voucher chain). The structural code is transferable; the fitted numeric values (smile coefficients, thresholds) are not — see [`P3R3_TRANSFER_NOTE.md`](./code/traders/round3/P3R3_TRANSFER_NOTE.md).

## HYDROGEL — the load-bearing sleeve

HYDROGEL is the round's stationary-MM workhorse. The numbers that mattered:

```python
H_ANCHOR        = 9990.0   # 3-day mean, NOT 10000. 10 ticks is huge on a 16-spread book.
H_CLIP          = 30.0     # fair follows touch_mid within ±30 of anchor.
                            # CLIP < 20 crashed PnL ~40 k.
H_INV_SKEW      = 0.015    # 0.035 was too aggressive (−20 % PnL).
H_MAX_POST_SIZE = 20       # plateau 15–30; larger just costs $.
H_PENNY_EDGE    = 1.5
H_PASSIVE_OFFSET= 8.0
H_TAKE_EDGE     = 0.0
H_REDUCE_EDGE   = 1.0
```

The plateau (size ∈ {15–30}, skew ∈ {0.010–0.020}, CLIP ∈ {28–30}) all yields 145–150 k 3-day on the alpha-floor scoring. Critically, **HYDROGEL converted ~99 % of its backtest alpha to live**, while voucher MR alpha converted at ~1–3 %. The implication ran the rest of the round: tune the passive-make sleeves, don't chase voucher signal residuals.

## VEV_4000 / VEV_4500 — synthetic-underlying MM

These are deep-ITM calls. For HYDROGEL-strike pairs the option mid is essentially `S − K + tiny_time_value`, with basis std < 1 tick. Treat as synthetic underlying:

```python
SIGMA           = 0.23     # flat smile, valid across strikes 5000-5500
VS_TAKE_EDGE    = 0.0      # 0 is the peak; 0.5 → −6 k PnL
VS_INV_SKEW     = 0.005
VS_MAX_POST_SIZE= 40
VS_PENNY_EDGE   = 1.0
VS_WIDE_SPREAD  = 3
```

Most of VEV_4500's PnL comes from the take side. Together VEV_4000 + 4500 add ~5–13 k per voucher across the 3 days. The deep-ITM ⇆ underlying basis gives three parallel measurements of the same price — any 3-tick divergence is theoretically tradeable; I started, but didn't finish, the 3-way arb between `S`, `(VEV_4000 + 4000)`, and `(VEV_4500 + 4500)`. That's logged as pending work.

## VEV_5000 / 5100 / 5200 / 5300 — IV-residual MR (Timo-port from P3R3)

The near-ATM strikes (delta 0.9–1.0) responded to a Timo-style IV-residual mean-reversion sleeve, ported from the prior year's P3R3 winning approach. Critical constants:

```python
OPT_MR_WINDOW   = 30   # EMA window for underlying mid (peak — sensitive)
OPT_MR_THR      = 5    # threshold on EMA dev (peak — sensitive)
THEO_NORM_WINDOW= 20   # EMA window for theo_diff
IV_SCALPING_WIN = 100
IV_SCALPING_THR = 0.7
UNDER_MR_THR    = 5
```

Threshold sensitivity is brutal — the signal lives in *rare large deviations*. Trading the small ones is noise:

| Knob | −2 | −1 | peak | +1 | +2 |
|---|---:|---:|---:|---:|---:|
| `OPT_MR_THR` (3/4/**5**/6/7) | −542 k | −66 k | **+249 k** | +235 k | +248 k |
| `UNDER_MR_THR` (3/4/**5**/6/7) | +175 k | +251 k | **+268 k** | +255 k | +254 k |
| `OPT_MR_WINDOW` (20/25/**30**/40/50) | +222 k | +242 k | **+268 k** | +117 k | −410 k |

The OPT_MR_THR cliff between 4 and 5 is the kind of result that should make you very nervous about overfitting, and did — it's one of the reasons I conservatized the final ship rather than chasing the next 50 k of backtest.

## What didn't work

1. **VFE take-only**. Tested at v_te ∈ {0.5, 1, 1.5, 2, 3}; −EV at every threshold. Best non-trading config is 0.
2. **VFE inside-touch MM**. −60 k / day. Tight 5-spread means any inside-touch quote gets adverse-selected.
3. **Flat-IV MM on ATM strikes (5000–5300) without IV-residual logic**. −25 k / day 2; σ=0.23 is ~0.005 off market IV, enough to bleed the take side.
4. **Anchor 10000 for HYDROGEL** (off by 10 from the true 9990 mean). 10 ticks on a 16-spread book is big.
5. **P3 R3 session-4.5 winning move** (moving ITM strikes from IV-scalp to MR). Regressed by −25 k to −485 k across 8 variants in P4. P4 microstructure differs — deep-ITM has 21-tick spread; OTM has vega < 1.
6. **High HYDROGEL inv_skew (≥ 0.035)**. Crashed PnL from 149 k to 32 k.
7. **Citadel-class deep-ITM mirror tuning**. The V4000 / V4500 TARGET=282 mirror added +63 k backtest and only +171 live (see "live conversion" below).

## Backtest / live ladder

The full session log of 30+ versions is in [`combined_ship_v*.py`](./code/traders/round3/) and `RESEARCH_LOG.md`. The trajectory I actually shipped, with live verification where available:

| Ship | Backtest 3-day | Live | Conversion |
|---|---:|---:|---:|
| v11 (HYDROGEL retune + synth IMB sizing) | 428,754 | 399,113 | 0.931× |
| v15 (VFE passive drift carry) | 443,484 | 417,605 | **0.942×** |
| v25 (Citadel cap=15) | 497,324 | 425,560 | 0.856× |
| 427141 (v27 chassis port) | 516,679 | 427,141 | 0.827× |
| v28_warmup65 | 519,679 | 442,623 | 0.852× |
| **v29_mirror (final)** | **582,866** | **442,794** | **0.760×** |

The conversion ratio is the story. Earlier in the round I (incorrectly) read the test-result directory names as evidence that backtest *under-estimated* live — that was a misread; the actual relationship is the opposite. Citadel-class sleeves under-convert vs jmerle backtest; the jmerle backtest should be treated as an upper bound, not a lower bound.

The single biggest live-converting change in the ladder was `WARMUP=65` in v28 — a one-knob retune that added 3 k backtest and 15,482 live. Single-knob retunes can multiply 5× bt-to-live when they fix a real timing issue. Mirror-style cap tweaks behave the opposite way.

## Manual challenge — Celestial Gardeners' Guild (Ornamental Bio-Pod bids)

Reserves uniform on the 51-point grid {670, 675, …, 920}. Fair sale at 920. Two-bid auction with second-bid penalty.

The clean theoretical first-principles solve (under the assumption of no field clustering) is **`(751, 836)`**, EV ≈ 84.33 per gardener. Derivation: if `k` reserve levels are captured, `bid(k) = 666 + 5k`; optimizing `[k1 (254 − 5k1) + (k2 − k1)(254 − 5k2)] / 51` with `k1 ≈ k2/2` gives `k2 ≈ 33.87` → `k2 = 34, k1 = 17` → `b1 = 751, b2 = 836`. Full solver in [`analysis/round3_manual_from_scratch/`](./code/analysis/round3_manual_from_scratch/).

Layered with field-clustering analysis (six-scenario prior sweep, AI-cluster-aware prior at {855, 870, 880, 890}), the recommended submission shifted to **`(775, 875)`** — EV 80.2, worst-case 71.5, sitting on a reserve cliff (next reserve up is 880) and capturing 21/26 b2-eligible reserves above all plausible avg_b2 p95 thresholds. Reasoning, MC sensitivity, six-scenario table in [`analysis/round3_manual/RECOMMENDATION.md`](./code/analysis/round3_manual/RECOMMENDATION.md).

I submitted `(775, 875)`.

## What I'd change

1. **Stop adding sleeves before re-verifying conversion ratios.** The v29 mirror added backtest that didn't materialize. A single conversion-check step between shipping versions would have caught it.
2. **Build the live-conversion calibration earlier.** The fact that test-result directory IDs were R3 *cumulative leaderboard scores* (not strategy-PnL) was something I figured out mid-session 9. Earlier framing would have saved a full session of misread tuning.
3. **Build the 3-way basis arb across VFE / VEV_4000 / VEV_4500.** Three parallel measurements with std < 1 tick is unambiguous alpha; I ran out of time.
4. **Finish the aggregate delta hedge.** Multi-strike voucher exposure was untracked at the portfolio level; I was running gross greeks per leg. Summing delta and hedging via VFE would have reduced day-3 drawdown materially.
5. **Don't chase a 50 k backtest gain when the previous 50 k converted at 1 %.** The session-9 voucher-residual chase was a discipline problem more than a research problem.
