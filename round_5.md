# Round 5 — 50-product sentiment-directional + news manual

**Products:** 50 new products across 10 themed families — Galaxy Sounds, Sleep Pods, Microchips, Pebbles, Robots, UV Visors, Translators, Panels, Oxygen Shakes, Snackpacks. Position limit **10 per product**. Algorithmic challenge is directional MM driven by per-product sentiment bias. Manual challenge is the **News Trading** allocation across 9 volcanic-themed products with a quadratic transaction fee.

**Final ship:** [`traders/round5/final_strategy.py`](./code/traders/round5/final_strategy.py). The variants `ll_pair_*` files in the same folder were experiments on a pairs-trading overlay that didn't make it into the ship.

## Approach — sentiment as side-bias on small per-product limits

The clean version of the algo strategy is intentionally simple:

1. Pre-compute a per-product **side bias** (`"buy"` or `"sell"`) from the round-5 uplink transcript and product descriptions — this is the only "research" input.
2. After `timestamp ≥ 10000` (skipping the first 1 % of day to let the book settle), **take aggressively up to a directional target of ±6** at the touch.
3. Outside the taking band, post passive quotes inside the spread at size 4, **with an imbalance gate**: if `imb > +0.3`, suppress the ask; if `imb < −0.3`, suppress the bid. No quoting when the inside-spread improvement would cross.

Key constants (from `final_strategy.py`):

```python
DIRECTIONAL_TARGET = 6
TAKE_SIZE          = 8
PASSIVE_SIZE       = 4
IMPROVEMENT        = 1
IMB_THR            = 0.3
```

Per-product limit is 10 (`LIMITS = {p: 10 for p in PRODUCTS}`), so a `DIRECTIONAL_TARGET = 6` leaves 4 units of room above the target for passive-make on the same side and meaningful capacity to lean into adverse fills.

## Where the bias table came from

The side-bias dict is mechanical: read each product's news / description, classify as bullish or bearish, post that side as the target. No machine-learning, no scoring — explicit decisions for each of the 50 products. The full dict is at the top of `final_strategy.py`; representative entries:

- `SLEEP_POD_*` — all "buy" (uniform positive demand story across the family).
- `MICROCHIP_*` — mixed (CIRCLE / SQUARE buy; OVAL / RECTANGLE / TRIANGLE sell).
- `PANEL_*` — biased "sell" (capacity glut narrative), with `PANEL_2X4` as the exception.
- `UV_VISOR_*` — mixed by color (positive for RED / MAGENTA / YELLOW; negative for AMBER / ORANGE).
- `TRANSLATOR_*` — mostly "sell" (commoditization), `VOID_BLUE` exception.

## Pairs-trading overlay (not shipped)

`ll_pair_base_561965.py` and its variants tested a basket / family-pair MM overlay where the directional-bias signal was rotated into long-short pairs within each themed family. The intent was to neutralize family-level beta (e.g. a panel-supply-glut story should hit all panels; pairing the two strongest sells against the one buy isolates the per-product alpha).

The base ship (v5_safe) was built by layering one signal at a time. Backtest progression on days 2/3/4 of the supplied data, with the live PnL on the actual round:

| Stage | Signal added | Backtest 3-day | Per-day |
|---|---|---:|---:|
| v1 | 1-tick BBO improvement on every leg | $401 k | $134 k |
| v2 | + per-leg L1 imbalance skew | $433 k | $144 k |
| v3 | + category-basket-z overlay (Robots/UV/Translators) | $510 k | $170 k |
| v4 | + per-leg-mid-z on 5 snack-pack legs | $556 k | $185 k |
| **v5** | per-leg-mid-z on 13 robust mean-reverters | **$693 k** | **$231 k** (+72.6 % vs v1) |
| **v5_safe** (`ll_pair_base_561965`) | v5 + PEBBLES Σmid kill-switch | same as v5 in bt | **live $561,965** |

The "robust 13" legs in v5 came from turning on the per-leg z-overlay one product at a time, measuring per-day uplift across all three supplied days, and keeping legs with positive contribution on all three (full ablation table in the file docstring; ~+$183 k uplift vs v3). The PEBBLES kill-switch in v5_safe defends against the empirical invariant `Σmid_pebbles ≈ 50,000` breaking live — it never triggered in backtest.

Per-variant results from experiments off the v5_safe base:

- `ll_pair_variant_v1.py` (basic pair): roughly neutral vs base.
- `v2` / `v3_narrow_pair`: small regressions.
- `v4_lead_xl` / `v5_pair_plus_xl`: small regressions.

I shipped the directional version because none of the pair variants beat it on the local backtests and I didn't have time for a calibration pass. The mistake is documented in [lessons_learned.md §3](./lessons_learned.md): the pair-trade *should* dominate on a 50-product universe with thematic families because it controls for family beta exactly the way the directional version doesn't. I think the underperformance was a calibration issue (`PASSIVE_SIZE`, `IMPROVEMENT` tuned for the single-product regime), not a strategy issue.

## Manual challenge — News Trading

9 volcanic-themed products, one quadratic-fee allocation problem. The frontend fee is:

```
investment = round(volume / 100 * 1,000,000)
fee        = round(investment^2 / 1,000,000)
```

A `p %` allocation only has positive EV if the realized absolute move exceeds `p %`. So this is a sized-conviction problem against a prior on move magnitudes per product.

My final submission, from [`analysis/round5_manual/README.md`](./code/analysis/round5_manual/README.md):

| Product | Side | Allocation |
|---|---|---:|
| Lava cake | SELL | 27 % |
| Ashes of the Phoenix | SELL | 19 % |
| Obsidian cutlery | SELL | 14 % |
| Thermalite core | BUY | 14 % |
| Pyroflex cells | SELL | 13 % |
| Magma ink | BUY | 8 % |
| Sulfur reactor | BUY | 5 % |
| Scoria paste | skip | 0 % |
| Volcanic incense | skip | 0 % |

Total 100 %. Reasoning per product:

- **Lava cake (−27 %)**: strongest short. Health-authority review, actual lava confirmed, immediate sales halted. Largest move I expected, top sizing.
- **Magma ink (+8 %)**: long but capped. Front-page launch, long queues, merger attention — but launch / hype narratives historically over-fade.
- **Pyroflex cells (−13 %)**: cell tax cut abolished, effectively doubling current levy.
- **Sulfur reactor (+5 %)**: small long. Index inclusion forces tracking-fund buying after rebalance, but index-flow effects are usually smaller than direct demand or safety shocks.
- **Thermalite core (+14 %)**: forecast points to sharp active-user growth.
- **Scoria paste (0 %)**: stockpiling call from a self-proclaimed "market medium". Maps to hype-trap prior, skip.
- **Volcanic incense (0 %)**: explicitly framed as concentrated influencer buying after extended rally. Skip.
- **Ashes of the Phoenix (−19 %)**: public backlash against sourcing — cleaner demand/PR shock than first pass suggested.
- **Obsidian cutlery (−14 %)**: production halt with cross-facility contamination warning.

This is a robust portfolio across two prior sets: a "Codex aggressive" prior that sized purely from headline strength, and a "Claude calibrated" prior anchored against P3 news-trading archetypes (where launches were often traps and serious safety/PR stories moved more). Worst-case EV across the two priors is 187.5 k; mean EV is 187.9 k. Full reconciliation in [`analysis/round5_manual/README.md`](./code/analysis/round5_manual/README.md).

## What I'd change

1. **Ship the pair-trade overlay.** With per-product limits of 10 and 50 thematically-clustered products, family-beta neutralization is the obvious structural edge. The fact that it didn't beat the directional ship is almost certainly a calibration problem.
2. **Build an explicit prior over move magnitudes.** The manual reduces to "size each product where realized |move| > allocation %". I was eyeballing this against P3 archetypes; an explicit table of historical |move| distributions per archetype would have made the sizing principled rather than rule-of-thumb.
3. **Test the side-bias dict for stability.** I classified the 50 products in one sitting from the round-5 transcript. I never re-classified independently to check that my bias dict was stable to a second reading.
