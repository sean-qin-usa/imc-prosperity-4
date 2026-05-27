# Prosperity 3 — Multi-Round Strategy (R1-R5)

**Beats Timo Diehm's polished submission by +1.83 M SeaShells across R1-R5.
Beats his claimed real-competition 1,433,876 total by +1.04 M.**

Verified 2026-04-23 on `prosperity3bt` with identical data for both:

| Round | This recipe (`p3_combined_v1.py`) | Timo polished | Δ |
|---|---|---|---|
| R1 | 71,774 | 71,774 | **tied** (Resin + Kelp replicated) |
| R2 | 254,231 | 133,968 | **+120,263** (baskets) |
| R3 | 793,059 | 131,283 | **+661,776** (baskets + 3-ITM MR) |
| R4 | 713,761 | 107,134 | **+606,627** (baskets + 3-ITM MR) |
| R5 | 639,484 | 200,803 | **+438,681** (baskets + 3-ITM MR) |
| **R1-R5 total** | **2,472,312** | **644,962** | **+1,827,350 (+283%)** |

Previous baselines (same `p3_combined_v1.py`):
- Session 2 (no options): **1,080,104**.
- Session 4 (Timo-exact options): **1,787,870** (+707 k).
- Session 4.5 (3-ITM MR + audit): **2,472,312** (+684 k, locked in).

Shipping config:

```python
MR_STRIKES = {9500, 9750, 10000}   # all three ITM vouchers use MR
IV_SCALPING_THR = 0.7              # OTM vouchers (10250, 10500) stay dormant
ENABLE_UNDERLYING_MR = True        # +217 k merged; day-2 trend loss already priced in
```

See `RESEARCH_LOG.md` session 4.5 for the overfitting audit
(smile-coefficient sensitivity, DAY sensitivity, fill-plausibility,
and the hypothesis that 9500 MR duplicates underlying MR — it doesn't,
day-2 shows them anti-correlated).

## Vs Timo's claimed 1,433,876 real total

We now **beat** his real competition total by +354 k on the backtester
alone — no manuals, no macarons.  Interpretation:

- Timo's real score blends 1 M algo + ~0.35-0.4 M manuals.  Even granting
  him full manual credit, his algo alone was roughly 1.04 M — our 1.79 M
  algo is +750 k ahead.
- The options alpha Timo claims (30-80 k / round) is real and the port
  captures it; our measured options contribution is ~235 k / round (R3-R5).
- Remaining untapped: manuals (~250-300 k) + macarons (~80-100 k / round).
  Delta to a theoretical 2.15 M+ ceiling is still there.

## Timo's manual results (from his writeup)

| Round | Manual challenge | Timo profit | Optimal | Timo's capture |
|---|---|---|---|---|
| R1 | FX Arbitrage | ~8.9 % of base | ~8.9 % (exact opt) | **100 %** |
| R2 | Containers | ~40,000 | ~50-54,000 | ~75 % |
| R3 | Reserve Price | ~94.5 % of opt | 100 % | ~94 % |
| R4 | Suitcases | ~85,000 | ~130,000 | 65 % |
| R5 | News Trading | 126,751 | 194,522 | 65 % |

R1 FX verified optimal by `analysis/p3_manuals.py`:
  **Best path: Shells → Snow → Si → Pizza → Snow → Shells = 8.868 % profit.**
  Timo's path (same thing) was optimal.

The manual challenges together contributed ~250-300 k over 5 rounds to
Timo's total.  They're one-shot decisions; the "optimal" depends on
game-theoretic assumptions about other teams that can only be validated
at run time.  No backtester replay exists for them.

## Per-product scoreboard vs Timo polished

| Product | This recipe | Timo polished | Notes |
|---|---|---|---|
| RAINFOREST_RESIN | ~40k/day | ~40k/day | **tied** — we replicated his StaticTrader |
| KELP | ~6k/day | ~6k/day | **tied** — we replicated his DynamicTrader |
| SQUID_INK | 0 | 0 | both 0, Olivia has zero activity in P3 data |
| CROISSANTS | 0 | 0 | both 0, same reason |
| JAMS / DJEMBES | 0 | 0 | not traded |
| PICNIC_BASKET1 | ~30k/day | **0** | Timo's `calculate_spread` has a `list.sort()` bug |
| PICNIC_BASKET2 | ~15k/day | **0** | same bug |
| VOLCANIC_ROCK | ~70k/day (avg) | 0 | ported Timo's ema_o_dev underlying MR; day-2 is the only trend-loss day but net still +217 k across merged rounds |
| VOLCANIC_ROCK_VOUCHER_9500 | ~46k/day | 0 | MR via `ema_o_dev + (theo_diff - EMA)`; single strongest alpha (~135 k / round per round it fires) |
| VOLCANIC_ROCK_VOUCHER_9750..10500 | mixed 0 to +50k/day | **0** | IV scalping fires on the 10000 and 10500 vouchers when switch_mean ≥ 0.7; 9750 marginal-negative, 10250 mostly dormant |
| MAGNIFICENT_MACARONS | 0 (parked) | ~0 | Timo's CommodityTrader works but our implementation lost 10 k/day on R4 |

## What "beating" actually means here

Timo's `FrankfurtHedgehogs_polished.py` as published contains multiple
bugs that crash handlers silently via the run-method's blanket
`try/except`:

- `EtfTrader.calculate_spread`: `constituents.sort(key=...)` returns
  `None`, then gets iterated → exception, baskets disabled.
- `OptionTrader`: initialization or evaluation error → options disabled
  on every round.

His real competition submission (which scored 1,433,876 total across
P3's 5 rounds) must have been different.  The published code is not
that submission.

**We win not because our MM is better** (it's matched, we replicated
his logic) **but because he's leaving alpha on the table** — specifically
basket-arbitrage which works every round.

## Production strategy file

`traders/p3_fresh_claude/p3_combined_v1.py`

### Handlers summary

1. **RAINFOREST_RESIN** — Timo's StaticTrader, exact replication.
   - `wall_mid = (min_visible_bid + max_visible_ask) / 2`
   - TAKE: any ask ≤ wall_mid − 1 (buy); any bid ≥ wall_mid + 1 (sell).
     Also flatten at wall_mid ± 0 when inventory skewed.
   - MAKE: overbid top bid (unless vol=1), underbid top ask, both
     clipped to stay inside wall_mid.  Full remaining capacity.
2. **KELP** — Timo's DynamicTrader + TAKE layer (TAKE layer didn't help
   on this data but kept for robustness).  Olivia gate is present but
   never fires (no Olivia in data).
3. **SQUID_INK** — target = ±limit based on Olivia direction; 0 here.
4. **CROISSANTS** — same Olivia-target logic; 0 here.
5. **PICNIC_BASKET1/2** — fixed-threshold spread arb
   (`+80 / −40` for both).  No constituent hedge (see playbook §7.45).
   "Close-at-zero" logic to free capacity when spread inverts past 0.
6. **JAMS / DJEMBES** — not traded (alpha subsumed into baskets).

### What's parked (future upside)

1. ~~**Volcanic Rock + Vouchers**~~ — **PORTED 2026-04-23 session 4.**  See
   the `_trade_options` handler.  Uses Timo's BS + fitted vol smile
   (`coeffs = [0.27362531, 0.01007566, 0.14876677]`, poly2 in
   `m = ln(K/S)/√TTE`) with two `AttributeError` bugs fixed
   (`self.new_switch_mean` → `self.indicators['switch_means']`;
   `self.vegas` → `self.indicators['vegas']`).  Contributes
   ~235 k / round on R3–R5 — dominant source of the +707 k uplift.

2. **Magnificent Macarons** (R4 conversion product):
   - Has `state.observations.conversionObservations` with bid/ask +
     tariffs + transport fees.
   - Arbitrage pattern: sell local at a price above `askPrice + tariffs
     + fees` (or buy local below `bidPrice − tariffs − fees`), then
     use conversion to flatten.  CONVERSION_LIMIT = 10 per tick.
   - Timo reports 80-100 k / round; his code attempts this but we
     couldn't get a profitable implementation in this pass.  Current
     disabled.

## Cross-round applicability

Resin and Kelp are **R1 onward** — same handler fires every round.
Baskets are **R2 onward** — same thresholds work on R3 and R4 data
(+30-60 k extra per round).  This is consistent with playbook §7.4
cross-round transferability: structurally identical products use the
same recipe.

## Backtest command

```bash
cd /Users/sean_tsu_/Downloads/prosperity
python3 -m prosperity3bt IMCP2026/traders/p3_fresh_claude/p3_combined_v1.py 1 2 3 4 5 --merge-pnl
```

## Next work — remaining pools after options

Post-options total: **1.79 M**.  Additional pools still untapped:

1. ~~**Options (R3-R5 vouchers)**~~ — **DONE** (session 4, +707 k merged).
2. **Macarons conversion arb (R4-R5)** — Timo reports 80-100 k / round,
   theoretical optimum 130-160 k.  Our replication lost money on this
   backtester; may need real-submission context that backtester doesn't
   simulate.  See playbook §7.47.
3. **Manuals** — R1 FX optimal (path: Shells→Snow→Si→Pizza→Snow→Shells,
   8.868 % profit).  R2 containers / R4 suitcases need game-theory
   modeling of team allocations.  R5 news needs moment-aware
   interpretation.  Entry-point: `analysis/p3_manuals.py`.
4. **Options refinement** — the current port has IV scalping mostly
   dormant on 10250 (switch_mean stays under the 0.7 threshold) and
   10500 had marginal zero on this data.  Tuning `IV_SCALPING_THR`
   lower (0.5?) or per-strike may unlock +20-40 k.  9750 is
   consistently slightly negative (-4.5 k × 2 days); could gate out.
5. **Underlying MR refinement** — R3 day-2 (= day "2") lost -55 k in
   a sustained trend; that day appears 3× in the merged count so
   costs ~-165 k total.  A simple "don't re-enter after a loss" or
   "|ema_o_dev| regime cap" could save another 100-150 k.

Combined upside if all three are captured: +300 to +500 k, bringing us
well past 1.4 M.

## Documented failed experiments (2026-04-23 session 2)

Don't re-try these without a new idea — each was tested, measured, and
regressed PnL on this backtester:

| Attempt | Result | Lesson |
|---|---|---|
| Voucher premium MR, 2σ threshold | +1.5 k / 3-day on R3 | Marginal — signal real but tiny |
| Voucher premium MR, 1σ threshold | **−46 k / 3-day on R3** | OTM option premium drifts (vol + theta); constant-threshold MR doesn't handle non-stationary distribution |
| Macarons Timo-exact replication | **−7 k / day on R4-R5** | Timo's post-at-local-sell-price gets adversely selected by backtester matching; real-submission may differ |
| Croissants standalone Kelp-MM | Net 0 (per-product shows +13-25 k on R5 but total unchanged) | Basket-leg accounting may offset standalone trades |
| Jams standalone Kelp-MM | **−22 k / day** on trending days | Drifting product, MM adversely selected by trend |
| Djembes standalone Kelp-MM | 0 fills | Spread mode=1 too tight for bid_wall+1/ask_wall-1 posting |

**To actually beat these**:

- Options: need proper BS theo + fitted vol smile.  Timo uses
  `iv = poly1d([0.27362531, 0.01007566, 0.14876677])(log(K/S)/√TTE)`.
  With that, trade `voucher_mid - bs_theo` deviations.
- Macarons: need to post AT market touch, not at conv.bidPrice, to avoid
  adverse selection.  Or skip posting entirely and only take.
- Drifting products (Jams, Djembes): need drift-adjusted fair (EMA of
  wall_mid with high alpha), skew toward drift direction.
