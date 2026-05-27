# Voucher / Extract Regime Findings (2026-04-24)

## What finally monetized

The voucher surface is not strong enough as a smooth fair-value shift.
It *is* strong enough as a discrete bearish regime overlay on the
deep-ITM sleeve.

Working rule:
- treat `VELVETFRUIT_EXTRACT` as the primary fair anchor
- compute online residual z-scores for `VEV_5000..5500`
- if the OTM wing is unusually rich, assume extract risk is skewed down
- do **not** cross spot directly
- instead:
  - stop or sharply reduce new `VEV_4000/4500` buying
  - let long inventory reduce more easily
  - keep the hedge optional; it regressed in the fast backtest

## Empirical state summary

Using day-standardized residual factors:

- `otm_factor = mean(z(resid_5300), z(resid_5400), z(resid_5500))`
- `atm_factor = mean(z(resid_5000), z(resid_5100), z(resid_5200))`
- `surface_slope = otm_factor - atm_factor`

Strong bearish states:

- `otm_factor` very rich:
  - current `VEV_4000/4500` residual is positive on average
  - future `VELVETFRUIT_EXTRACT` drifts down
  - future `VEV_4000/4500` also drift down
  - this is the cleanest "do not buy here" state

- `surface_slope` very high and `atm_factor` cheap:
  - current deep-ITM residual can look neutral or cheap
  - but extract still tends to drift down afterward
  - this is a weaker but still useful soft-bear filter

## Branch comparison

Fast 3-day jmerle backtest totals:

- `fundamental_spot_anchor_uploadsafe_v1.py`: `160,858`
- `fundamental_spot_anchor_regime_guard_uploadsafe_v1.py`: `163,350`
- `fundamental_spot_anchor_regime_guard_loose_otm_uploadsafe_v1.py`: `163,710`

Other tests:

- hard OTM-only regime: ~baseline, little benefit
- underlying hedge in bearish regime: regressed
- looser OTM trigger improved the guard

## Current model

Best current read on the relationship:

1. `VELVETFRUIT_EXTRACT` is still the executable truth source.
2. The voucher surface carries regime information, especially in the OTM
   wing.
3. That information is best used to **veto or throttle** deep-ITM long
   risk, not to trade the surface directly.
4. A light, earlier OTM-rich veto is the first relationship-driven
   overlay that improved the fast historical backtest.
