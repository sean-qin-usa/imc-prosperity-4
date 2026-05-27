# Hydro Cross-Regime Findings (2026-04-24)

Source script:

`python3 IMCP2026/tools/analyze_round3_execution_covariates.py --bundle-json /Users/sean_tsu_/Downloads/389872/389872.json`

## Core result

The most useful cross-asset signal found so far is **not** direct Hydro
vs voucher arbitrage. It is a **Hydro crash-state regime filter**:

- enter the study only when `HYDROGEL_PACK` is already depressed:
  - `HYDROGEL mid <= 9990 - 25`
  - `HYDROGEL spread >= 14`
- then look at:
  - `VFE` 20-tick momentum
  - OTM voucher-wing richness (`VEV_5300/5400/5500` residual z-score)

## What changes on the official hidden day

On official bundle `389872`, Hydro cheap by itself was **not** enough.
Crash-state Hydro only bounced reliably in one bucket:

- `VFE` 20-tick momentum in the most negative quintile:
  - roughly `vfe_mom20 <= -3.5`
  - `fwd20 ≈ +5.58`
  - `fwd50 ≈ +17.56`
  - `hit20 ≈ 84.6%`

Bad official crash-state buckets:

- flat-to-positive `VFE` momentum:
  - `fwd20` around `-2.3` to `-2.6`
  - `hit20` only `24%` to `38%`
- rich OTM wing:
  - top `otm_rich_z` quintile had `fwd20 ≈ -3.01`
  - `hit20 ≈ 33.9%`

That means the hidden day looked like a **downturn regime** where
cross-asset strength in extract or the OTM wing was a warning that
Hydro would not mean-revert immediately.

## Visible-day comparison

The visible days still show Hydro as broadly mean-reverting in crash
states, but the same directional structure is present often enough to
matter:

- day 1:
  - strong negative `VFE` momentum is the best Hydro crash bucket
  - strong positive `VFE` momentum is the worst bucket
- day 2:
  - strongest negative `VFE` momentum is again the best bucket
- day 0:
  - effect is weaker and less monotone, so this is not a universally
    stable signal

Interpretation:

- this is **not** a clean visible-day alpha engine
- it **is** a plausible hidden-day robustness overlay

## Practical implication

Do not trade Hydro “against vouchers” directly.

Instead, use cross-asset state to decide **how aggressively to lean into
Hydro crashes**:

- if Hydro is cheap **and** `VFE` momentum is strongly negative:
  - allow Hydro crash size-up
  - keep bid posting large
  - avoid early panic reduction
- if Hydro is cheap **and** `VFE` momentum is flat or positive:
  - suppress new Hydro bids
  - reduce long inventory more easily
- if the OTM wing is unusually rich:
  - treat it as an extra bearish veto on Hydro crash buying

## Ranking of crash-state covariates

1. `VFE` 20-tick momentum: strongest, cleanest hidden-day discriminator.
2. OTM wing richness: useful bearish veto, weaker than `VFE` momentum.
3. Deep-ITM basis: inconsistent and lower signal.

## Next branch to test

The right branch is a **Hydro execution overlay**, not a new voucher
strategy:

- keep the spot-anchor deep-ITM sleeve unchanged
- only modify Hydro crash aggression using `VFE` momentum
- optionally add a light OTM-rich veto after the `VFE` version is tested

## Tested branch result

Implemented files:

- `fundamental_spot_anchor_hydro_vfe_regime_v1.py`
- `fundamental_spot_anchor_hydro_vfe_regime_uploadsafe_v1.py`

Workflow result on official bundle `389872`:

| Strategy | Visible 3-day | Generic official replay | Bundle-calibrated replay |
|---|---:|---:|---:|
| `fundamental_spot_anchor_uploadsafe_v1.py` | `160,858` | `7,619` | `8,805` |
| `fundamental_spot_anchor_hydro_crash_sizeup_uploadsafe_v1.py` | `160,520` | `7,619` | `8,823` |
| `fundamental_spot_anchor_hydro_vfe_regime_uploadsafe_v1.py` | `161,312` | `7,919` | `9,024` |

Interpretation:

- this is the first Hydro cross-asset overlay that improved both:
  - visible 3-day backtest
  - bundle-calibrated hidden-day replay
- the gain still comes from the Hydro sleeve, not from new voucher alpha
- the cross-asset relationship is therefore best understood as a
  **Hydro execution regime filter**, not as an extract-voucher arb
