# Voucher / Extract Relationship Notes (2026-04-24)

## Direct answer on the "trend-follow ATM residuals" idea

No, that exact family had not been tried as a primary sleeve.

What had been tried before:
- ATM / near-OTM residual **mean reversion**
- flat-sigma BS overlays

What was *not* tried before this note:
- treating ATM / near-OTM residual persistence as a **trend / state**
  signal first, then asking whether that signal should trade the ATM
  voucher, `VELVETFRUIT_EXTRACT`, or the deep-ITM vouchers

## The key mathematical point

High lag-1 autocorrelation in the residual **level** does **not** imply a
good momentum trade in the residual level.

For the day-demeaned residual series `r_t`, the ATM / OTM contracts look
like slow AR(1) processes with `0 < phi < 1`:

| Symbol | mean phi | mean half-life (ticks) |
| --- | ---: | ---: |
| `VEV_5000` | `0.581` | `1.38` |
| `VEV_5100` | `0.682` | `2.30` |
| `VEV_5200` | `0.772` | `3.72` |
| `VEV_5300` | `0.893` | `7.74` |
| `VEV_5400` | `0.951` | `19.33` |
| `VEV_5500` | `0.977` | `29.72` |

That means:
- the residual level is persistent
- but the next residual **change** still tends to oppose the current
  level
- so "lag-1 autocorr is high" is **not** enough to justify raw momentum

## What the residuals actually predict

### 1. ATM residuals are informative about future `VELVETFRUIT_EXTRACT`

Using the top-decile absolute **ATM factor**:

`atm_factor = mean(zscore(resid_5000), zscore(resid_5100), zscore(resid_5200))`

Signed future `VELVETFRUIT_EXTRACT` move:

| Horizon | Signed VFE move |
| --- | ---: |
| `1` | `+0.720` |
| `3` | `+0.828` |
| `5` | `+0.886` |
| `10` | `+1.062` |
| `20` | `+1.465` |
| `30` | `+1.841` |

Interpretation:
- when near-ATM calls are rich vs current extract, extract often drifts
  the same way afterward
- but the drift is still **sub-spread** for direct VFE crossing

### 2. ATM residuals do **not** make ATM vouchers good momentum buys

Same ATM factor, signed future ATM voucher move:

| Symbol | h=1 | h=3 | h=5 | h=10 |
| --- | ---: | ---: | ---: | ---: |
| `VEV_5000` | `-0.216` | `-0.146` | `-0.075` | `+0.120` |
| `VEV_5100` | `-0.112` | `-0.014` | `+0.056` | `+0.237` |
| `VEV_5200` | `-0.140` | `-0.107` | `-0.086` | `+0.013` |

Interpretation:
- the option surface is carrying directional information
- but the ATM option itself is still too rich relative to where extract
  actually goes next
- this is why "trend-follow ATM residuals" is not a clean standalone
  trade

## Surface-level relationship that seems real

The best state variable is not one strike. It is the **surface level**:

`surface_level = mean(zscore(resid_5000..5500))`

What it means:
- `surface_level > 0`: the whole call chain is rich vs current extract
- `surface_level < 0`: the whole call chain is cheap vs current extract

This factor predicts the deep-ITM vouchers better than it predicts spot:

| Target | h=1 signed move | h=10 signed move |
| --- | ---: | ---: |
| `VEV_4000` | `-0.606` | `-0.582` |
| `VEV_4500` | `-0.548` | `-0.523` |

Interpretation:
- when the surface is rich, the deep-ITM vouchers are also slightly rich
  relative to pure spot-anchor fair
- that does **not** create a direct executable arb
- but it *does* justify using the surface as a **quote bias / take gate**
  on the deep-ITM sleeve

## OTM wing information

The OTM wing carries a separate bearish covariate:

`surface_slope = otm_factor - atm_factor`

Positive slope = OTM wing rich vs ATM, which is bearish for extract.

Average signed future `VELVETFRUIT_EXTRACT` move for positive slope:

| Horizon | Signed VFE move |
| --- | ---: |
| `5` | `+0.268` |
| `10` | `+0.462` |
| `20` | `+0.769` |
| `30` | `+1.091` |
| `50` | `+1.870` |

Here "signed" means after assigning a bearish sign to positive slope.

Interpretation:
- the OTM wing is a slower bearish state variable
- again, too weak for direct crossing
- potentially useful for passive skew / hedge throttling

## Trade-tape covariates

Among trade-based signals:
- `VEV_4000` aggressor direction predicts future extract best on short /
  medium horizons, but only around `+0.31` by 10 ticks
- 5-leg OTM sell packages are bearish for extract, but still too small
  to beat crossing the VFE spread directly

So the tape confirms the same story:
- there *is* information in the voucher chain
- direct spot crossing still does not monetize it cleanly

## New strategy branch tested

Added:
- `fundamental_surface_level_v1.py`
- `fundamental_surface_level_uploadsafe_v1.py`

Design:
- compute a live residual-surface factor from `VEV_5000..VEV_5500`
- feed it into `VEV_4000/4500` fair and edge asymmetry
- do **not** trade ATM vouchers directly

Fast historical result:
- `fundamental_surface_level_uploadsafe_v1.py`: `158,192`
- `fundamental_spot_anchor_uploadsafe_v1.py`: `160,858`

Conclusion:
- the relationship is real
- the first monetization attempt is directionally sensible
- but the current implementation still regresses vs the simpler
  spot-anchor deep-ITM sleeve

## Working model going forward

Best current description of the voucher / extract relationship:

1. `VELVETFRUIT_EXTRACT` remains the anchor truth for executable fair.
2. The ATM / OTM call surface contains **state information** about where
   extract may drift next.
3. That state information is generally too weak to justify direct VFE
   crossing.
4. The right use is probably:
   - quote bias
   - take gating
   - hedge throttling
   - directional regime control
5. The wrong use is:
   - naive ATM residual mean reversion
   - naive ATM residual momentum
   - aggressive spot-vs-voucher arb
