# Voucher-Only First-Principles Findings (2026-04-24)

Goal: ignore HYDROGEL entirely and answer the narrower question:

> What voucher sleeves make **real, sustainable PnL** on their own?

This note summarizes a reset from first principles plus direct testing
of pure-voucher wrappers.

## Structural map

Three voucher regions behave differently:

1. `VEV_4000 / VEV_4500`
   - deep-ITM synthetic-underlying clones
   - wide spreads
   - low flow
   - small but robust edge

2. `VEV_5000 / VEV_5100 / VEV_5200`
   - middle strikes
   - weaker flow than the outer wing
   - previous tests repeatedly regressed

3. `VEV_5300 / VEV_5400 / VEV_5500`
   - outer OTM wing
   - tight spreads
   - active trading
   - residual level is highly persistent, which supports per-strike EMA
     fair values

## Raw visible-data microstructure

Using flat-`σ=0.23` Black-Scholes as the base theoretical value and
measuring `residual = market_mid - BS_theo`:

| Symbol | Avg spread | Trades/day | Mean residual | Residual std | Lag-1 phi |
| --- | ---: | ---: | ---: | ---: | ---: |
| `VEV_5200` | `2.888` | `6.0` | `0.917` | `1.532` | `0.925` |
| `VEV_5300` | `2.107` | `40.3` | `1.592` | `1.252` | `0.929` |
| `VEV_5400` | `1.381` | `75.0` | `-1.719` | `1.389` | `0.981` |
| `VEV_5500` | `1.150` | `89.0` | `1.047` | `0.621` | `0.931` |

Interpretation:

- `VEV_5200` is too thin to trust as a primary sleeve
- `VEV_5300/5400/5500` are liquid enough and persistent enough to justify
  a strike-specific residual EMA
- `VEV_5400/5500` are the cleanest wing names on raw structure alone

## Pure-voucher benchmark wrappers

Added local wrappers:

- `voucher_only_baseline_v5.py`
  - deep-ITM only: `VEV_4000 / VEV_4500`
- `voucher_only_baseline_v17.py`
  - deep-ITM + smile-corrected `VEV_5300 / 5400 / 5500`
- `voucher_only_baseline_v17_no_lottery.py`
  - same as above, but with `VEV_6000 / 6500` removed
- `voucher_only_baseline_v17_smile_only.py`
  - only `VEV_5300 / 5400 / 5500`
- `voucher_only_baseline_v17_outer_only.py`
  - only `VEV_5400 / 5500`

## Benchmark results

### 1. Harsh visible-fill check

Command:

```bash
python3 IMCP2026/tools/jmerle_backtester.py STRATEGY 3 --merge-pnl --no-out --match-trades none --no-progress
```

Results:

| Strategy | Total |
| --- | ---: |
| `voucher_only_baseline_v5.py` | `10,514` |
| `voucher_only_baseline_v17.py` | `47,674` |
| `voucher_only_baseline_v17_no_lottery.py` | `47,674` |
| `voucher_only_baseline_v17_smile_only.py` | `37,160` |
| `voucher_only_baseline_v17_outer_only.py` | `28,212` |

Decomposition:

- `v17` without lottery is unchanged, so lottery is irrelevant
- `smile_only` keeps most of the voucher PnL
- `outer_only` is lower but materially steadier because it removes
  `VEV_5300`

Visible per-strike behavior:

- `VEV_5300`: `+8,405`, `+5,967`, `-5,425`
- `VEV_5400`: `+3,960`, `+10,999`, `+5,355`
- `VEV_5500`: `+1,838`, `+3,878`, `+2,183`

So:

- `VEV_5400` is the strongest single smile name
- `VEV_5500` is smaller but stable
- `VEV_5300` is additive overall but also the unstable leg

### 2. Calibrated hidden replay

Command family:

```bash
python3 IMCP2026/tools/official_compare.py \
  --official-json /Users/sean_tsu_/Downloads/389872/389872.json \
  --official-log /Users/sean_tsu_/Downloads/389872/389872.log \
  --strategy STRATEGY \
  --fill-model official-hybrid \
  --exchange-calibration IMCP2026/tools/calibrations/local_bundles_profile.json
```

Results:

| Strategy | Hidden local replay |
| --- | ---: |
| `voucher_only_baseline_v5.py` | `274.0` |
| `voucher_only_baseline_v17.py` | `2898.0` |
| `voucher_only_baseline_v17_no_lottery.py` | `2898.0` |
| `voucher_only_baseline_v17_smile_only.py` | `2624.0` |
| `voucher_only_baseline_v17_outer_only.py` | `2300.0` |

Interpretation:

- lottery is again irrelevant
- the hidden voucher edge is mostly the smile sleeve
- deep-ITM adds only a small amount on the hidden day
- dropping `VEV_5300` improves visible stability but costs hidden PnL

Hidden replay fill mix:

- full smile sleeve:
  - `VEV_5500`: `928` qty
  - `VEV_5400`: `856` qty
  - `VEV_5300`: `255` qty
- deep-ITM add-on:
  - `VEV_4000`: `39`
  - `VEV_4500`: `39`

So the hidden calibrated model agrees that the outer OTM wing is the
main voucher engine.

## Live hidden-day evidence from actual official submissions

Official run `374582` = `baseline_v5`:

- hidden official voucher PnL:
  - `VEV_4000`: `+273.167969`
  - `VEV_4500`: `+238.167969`
- total voucher contribution: about `+511`

Official run `385838` = `baseline_v15`:

- hidden official voucher PnL:
  - `VEV_4000`: `+138.935547`
  - `VEV_4500`: `+138.935547`
  - `VEV_5300`: `+57.481934`
  - `VEV_5400`: `+5.000000`
  - `VEV_5500`: `+3.621525`
- total voucher contribution: about `+344`

Important point:

- the OTM smile sleeves **did** monetize live on the hidden day
- their realized official contribution was smaller than the local replay
  suggests, but it was not zero
- all official voucher fills in these runs were `take_touch_or_worse`,
  not fantasy passive inside-spread fills

## Current best read

The voucher problem is now much narrower:

1. There is a small robust deep-ITM edge in `VEV_4000 / VEV_4500`.
2. The **main** sustainable voucher edge is the smile-corrected OTM wing:
   `VEV_5300 / VEV_5400 / VEV_5500`.
3. `VEV_6000 / VEV_6500` lottery adds nothing.
4. `VEV_5000 / VEV_5100 / VEV_5200` still do not justify inclusion.

## Candidate hierarchy

Best pure-voucher candidate right now:

- `voucher_only_baseline_v17_no_lottery.py`
  - highest combined visible + hidden evidence

More conservative variant:

- `voucher_only_baseline_v17_outer_only.py`
  - lower total, but cleaner because it removes unstable `VEV_5300`

## Next tuning directions

If continuing from here, the next work should be:

1. tune `VEV_5300` separately instead of sharing the exact same parameters
   with `VEV_5400 / 5500`
2. test `VEV_5400 / 5500` with slightly larger size caps
3. inspect whether `VEV_5300` needs a wider take edge or lower per-strike
   inventory cap
4. keep HYDRO completely out of the voucher research loop so voucher PnL is
   always measured directly
