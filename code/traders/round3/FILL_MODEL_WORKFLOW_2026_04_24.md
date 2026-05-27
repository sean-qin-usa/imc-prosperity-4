# Round 3 Fill-Model Workflow (2026-04-24)

## Problem

Round-3 candidate ranking was getting distorted by the choice of fill
 model. On hidden official bundles, many candidate strategies looked
 artificially similar under a generic local fill model even when the
 realized official path showed meaningful execution-specific edge.

This was the trap behind:

- over-trusting optimistic same-tick / generic community fills
- over-correcting to one harsh fill proxy like `--match-trades none`
- debating whether alpha was "real" without tying the answer to an
  official bundle

## Fixed workflow

Use **three** views, not one:

1. visible 3-day backtest
2. official hidden-day replay with generic `official-hybrid`
3. official hidden-day replay with a **bundle-calibrated passive-fill
   profile**

The new script for this is:

`python3 IMCP2026/tools/score_round3_candidates.py --bundle-dir <bundle> <strategy1> <strategy2> ...`

Example:

```bash
python3 IMCP2026/tools/score_round3_candidates.py \
  --bundle-dir /Users/sean_tsu_/Downloads/389872 \
  IMCP2026/traders/round3/fundamental_spot_anchor_uploadsafe_v1.py \
  IMCP2026/traders/round3/fundamental_spot_anchor_hydro_crash_sizeup_uploadsafe_v1.py \
  IMCP2026/traders/round3/baseline_v12.py
```

What it does:

- runs the 3-day visible jmerle backtest
- runs generic `official-hybrid` replay on the chosen official bundle
- calibrates a passive-fill profile from that exact bundle
- reruns the official replay with the bundle-specific calibration
- prints one compact score table

## Why this is better

On official bundle `389872`:

- uploaded strategy official profit: `8630.48`
- same strategy under generic `official-hybrid`: about `7545`
- same strategy under bundle-calibrated replay: about `8603`

So the generic model was materially underestimating the actual official
path. That means "all variants are the same" under a generic fill model
was partly a tooling artifact.

## Current interpretation

1. Alpha is real, but the realized hidden-day PnL is concentrated in the
   sleeves that actually fill.
2. For `389872`, that is mostly:
   - `HYDROGEL_PACK`
   - `VEV_4000`
   - `VEV_4500`
3. `VELVETFRUIT_EXTRACT` and the middle / OTM vouchers had essentially no
   realized official contribution in that bundle.
4. Therefore, candidate variants only separate materially when they
   change the **hydro + deep-ITM execution path**.

## Practical rule

Do not promote a round-3 strategy just because it wins one visible
backtest or one generic hidden-day replay.

Prefer candidates that are:

- competitive on visible 3-day data
- competitive on bundle-calibrated hidden-day replay
- not relying on `VFE` / surface sleeves that never actually fill in the
  official bundle being studied
