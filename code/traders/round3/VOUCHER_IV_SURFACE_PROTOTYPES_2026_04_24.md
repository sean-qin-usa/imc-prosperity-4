# Voucher IV Surface Prototypes (2026-04-24)

## Question

Research a separate round-3 idea:

- per-strike implied-vol EMA
- quadratic smile fit in `k = log(K / S)`
- fair each voucher from Black-Scholes on the fitted surface
- passive inside-touch quoting around that fair
- aggregate voucher delta hedged with `VELVETFRUIT_EXTRACT`

Be pessimistic about fills.

## Is this already done?

Not exactly.

Closest existing work in this repo:

1. `baseline_v15.py` / `baseline_v17.py`
   - per-strike **price residual EMA** on `VEV_5300/5400/5500`
   - fair = flat-`sigma` BS + residual EMA
   - this is surface-adjacent, but **not** a fitted IV curve

2. `fundamental_v1.py`
   - already has **aggregate voucher delta hedging** into `VELVETFRUIT_EXTRACT`
   - but only for the deep-ITM vouchers, not a full smile-driven chain

3. `fundamental_surface_level_v1.py` / `fundamental_surface_gate_v1.py`
   - use the chain as a **surface state / richness factor**
   - do **not** quote vouchers directly off a fitted IV smile

So the exact proposal is new in this repo: fitted IV surface + passive voucher MM + spot hedge.

## Prototypes added

- `traders/round3/voucher_iv_surface_all_v1.py`
  - fits on all voucher strikes
  - quotes all voucher strikes

- `traders/round3/voucher_iv_surface_liquid_v1.py`
  - fits on `VEV_5000..VEV_5500`
  - only quotes `VEV_5300/5400/5500`
  - stricter, more execution-aware variant

Both:

- persist per-strike IV EMAs in `traderData`
- fit a quadratic smile each tick
- quote passively inside the spread only
- sweep `VELVETFRUIT_EXTRACT` when voucher net delta breaches a threshold

## Fast sanity checks

The strategies are not dead code; they do submit quotes.

First 50 day-0 ticks:

- `voucher_iv_surface_all_v1.py`: `226` orders
  - first quote at `t=0` on `VEV_4000` and `VEV_4500`
- `voucher_iv_surface_liquid_v1.py`: `28` orders
  - first quote at `t=800` on `VEV_5300`

## Honest execution read

### 1. Extreme pessimistic lower bound: jmerle `--match-trades none`

Commands:

```bash
python3 IMCP2026/tools/jmerle_backtester.py IMCP2026/traders/round3/voucher_iv_surface_all_v1.py 3 --merge-pnl --no-out --match-trades none --no-progress
python3 IMCP2026/tools/jmerle_backtester.py IMCP2026/traders/round3/voucher_iv_surface_liquid_v1.py 3 --merge-pnl --no-out --match-trades none --no-progress
```

Result:

- both prototypes: `0` total PnL over all 3 visible days

Interpretation:

- this matcher does **not** carry passive inside-spread orders forward
- so a pure passive strategy is structurally invisible there
- useful only as a hard lower bound, not as a realistic passive-fill estimate

### 2. Conservative passive-fill check: official-hybrid + `local_bundles_profile`

Small day-0 prefix (`timestamp <= 50000`) to keep runtime reasonable:

```bash
python3 tools/backtester.py traders/round3/voucher_iv_surface_liquid_v1.py \
  --input /tmp/round3_day0_50k \
  --dataset round3_day0_50k_csv \
  --fill-model official-hybrid \
  --exchange-calibration tools/calibrations/local_bundles_profile.json \
  --no-plots \
  --reuse-trader-instance
```

Same for `voucher_iv_surface_all_v1.py`.

Results:

- `voucher_iv_surface_liquid_v1.py`
  - `134` orders submitted
  - `0` executed qty
  - `0.0` PnL

- `voucher_iv_surface_all_v1.py`
  - `3398` orders submitted
  - `0` executed qty
  - `0.0` PnL

Interpretation:

- even under a passive-fill model that can fill inside-spread quotes,
  the conservative calibration gave **zero fills** in the early visible sample
- the issue is therefore not just "prototype forgot to quote"
- it is more likely that the surface names do not realize enough passive flow

## Additional surface observation

A quick day-level probe on visible data showed:

- quadratic fit errors are small enough to build a surface
- fitted fair moves materially versus mid mainly on `VEV_5100..VEV_5500`
- deep-ITM `VEV_4000/4500` barely move versus the fitted fair despite wide spreads

That is the bad combination:

- the part of the chain where the fitted surface says something interesting
  is exactly the part the repo's prior fill notes already distrusted
- the part that actually fills (`VEV_4000/4500`) is better explained by
  simple spot-anchor pricing than by smile fitting

## Current verdict

Pessimistic read: **not promising enough to prioritize over the existing deep-ITM / HYDROGEL work.**

Reason:

1. the idea is structurally distinct and now prototyped
2. the prototype definitely posts quotes
3. under a conservative passive-fill read, those quotes are not getting hit
4. existing repo research already says realized round-3 contribution is concentrated in
   `HYDROGEL_PACK`, `VEV_4000`, and `VEV_4500`, not the middle/OTM surface

## Follow-up research after the pure IV-surface prototypes

### 1. Existing surface-bias variants still regress under harsh visible fills

Using the pessimistic local matcher:

```bash
python3 IMCP2026/tools/jmerle_backtester.py IMCP2026/traders/round3/fundamental_spot_anchor_uploadsafe_v1.py 3 --merge-pnl --no-out --match-trades none --no-progress
python3 IMCP2026/tools/jmerle_backtester.py IMCP2026/traders/round3/fundamental_surface_level_uploadsafe_v1.py 3 --merge-pnl --no-out --match-trades none --no-progress
python3 IMCP2026/tools/jmerle_backtester.py IMCP2026/traders/round3/fundamental_surface_gate_uploadsafe_v1.py 3 --merge-pnl --no-out --match-trades none --no-progress
```

Results:

- `fundamental_spot_anchor_uploadsafe_v1.py`: `40,468`
- `fundamental_surface_level_uploadsafe_v1.py`: `37,678`
- `fundamental_surface_gate_uploadsafe_v1.py`: `31,930`

Interpretation:

- even when the surface is only used as a bias on the deep-ITM sleeve,
  it still makes the executable path worse under a pessimistic fill read

### 2. Spot-anchor surface-gate tuning variants collapse to the same harsh-fill result

Tested:

- `fundamental_spot_anchor_surface_gate_v1.py`
- `fundamental_spot_anchor_surface_gate_mid_v1.py`
- `fundamental_spot_anchor_surface_gate_strong_v1.py`

All three also finished at `40,468`, exactly matching plain
`fundamental_spot_anchor_uploadsafe_v1.py`.

Interpretation:

- under harsh visible fills, the surface gate mostly changes passive or
  marginal behavior, not the realized core execution path

### 3. Hidden official bundle agrees with the pessimistic local ranking

Bundle:

- `/Users/sean_tsu_/Downloads/389872`
- official bundle profit from `389872.json`: `8630.482421875`

Calibrated hidden-day replay using:

- `official_compare.py`
- `fill-model official-hybrid`
- `exchange-calibration IMCP2026/tools/calibrations/local_bundles_profile.json`

Local replay results on the bundle:

- `fundamental_spot_anchor_uploadsafe_v1.py`: `7619.0`
- `fundamental_surface_level_uploadsafe_v1.py`: `7549.0`
- `fundamental_surface_gate_uploadsafe_v1.py`: `7401.0`

Interpretation:

- hidden-bundle execution keeps the same ranking:
  plain spot-anchor > surface-level bias > surface-gate bias
- so this is not just a visible-day or `jmerle` artifact

### 4. Signal-to-spread check on the deep-ITM names is extremely weak

Using the same EMA-style surface factor construction as the surface-gate
family, average signed future move of the deep-ITM contracts was:

- `VEV_4000`: about `0.00` to `0.02` ticks over `1-10` ticks
- `VEV_4500`: about `0.13` to `0.15` ticks over `1-10` ticks

Against average spreads of:

- `VEV_4000`: `20.81`
- `VEV_4500`: `15.85`

So the signal is roughly:

- `VEV_4000`: ~`0.01%` of spread
- `VEV_4500`: ~`0.8-0.9%` of spread

Interpretation:

- the surface factor may be statistically real
- but it is economically tiny relative to what the deep-ITM sleeve pays
  to cross or even to quote with meaningful inventory risk

### 5. Hidden official bundle `391669` shows real voucher fills, but still does not justify generalizing the sleeve

Inputs:

- official run dir: `/Users/sean_tsu_/Downloads/391669`
- strategy in that run: `391669.py` = the pure all-chain IV-surface prototype

Official outcome:

- final official profit: `26.07470703125`
- submission trades: `36`
- submission fill qty: `67`
- every fill classified as `inside_spread`

Per-strike official PnL on that bundle:

- `VEV_4000`: `+11.232178`
- `VEV_4500`: `+11.232178`
- `VEV_5000`: `+14.610352`
- `VEV_5100`: `-2.0`
- `VEV_5200`: `-9.0`
- `VEV_5300+`: `0.0`

Interpretation:

- this hidden day is not evidence that the whole smile-MM idea works
- it is evidence that a narrow inside-spread voucher basket can get hit
- the bad strikes were `VEV_5100/5200`; the only good middle strike was `VEV_5000`

Counterfactual calibrated local replay on the same hidden day:

- `baseline_v18.py`: `10513.0`
- `fundamental_spot_anchor_hydro_vfe_regime_uploadsafe_v1.py`: `7919.0`
- `fundamental_spot_anchor_uploadsafe_v1.py`: `7619.0`
- `fundamental_spot_anchor_hydro_crash_sizeup_uploadsafe_v1.py`: `7619.0`
- `fundamental_spot_anchor_regime_guard_loose_otm_uploadsafe_v1.py`: `7545.0`
- `fundamental_spot_anchor_plus_vev5000_v1.py`: `7496.0`

That means:

- even on the one hidden bundle where the pure IV-surface file actually traded,
  the stronger generalized families still dominate in calibrated replay
- adding a conservative `VEV_5000` spot-anchor sleeve did **not** help
- this was not just a no-fill artifact: the `+VEV_5000` wrapper got
  `10` hidden fills / `38` qty in `VEV_5000` on `391669` and still regressed

Portable follow-up test:

```bash
python3 IMCP2026/tools/jmerle_backtester.py IMCP2026/traders/round3/fundamental_spot_anchor_plus_vev5000_v1.py 3 --merge-pnl --no-out --match-trades none --no-progress
```

Harsh visible-fill result:

- `fundamental_spot_anchor_plus_vev5000_v1.py`: `13,106`
- plain `fundamental_spot_anchor_uploadsafe_v1.py`: `40,468`

Breakdown of the regression:

- day 0 `VEV_5000`: `-11,935`
- day 1 `VEV_5000`: `-5,500`
- day 2 `VEV_5000`: `-9,926`

Conclusion:

- bundle `391669` is a useful caution against saying "the surface never fills"
- but it still does **not** clear the bar for expanding the shipped family into
  `VEV_5000/5100/5200`
- the honest read remains: treat `391669` as an interesting hidden-day anomaly,
  not as a portable new sleeve

## If revisited later

The only versions worth a second pass are more execution-focused:

1. quote only when spread is wide *and* the fitted fair is at least 1-2 ticks from touch
2. allow selective take logic instead of pure passive-only quoting
3. use the fitted surface as a **filter / bias** for the proven deep-ITM sleeve,
   not as a standalone chain MM engine
