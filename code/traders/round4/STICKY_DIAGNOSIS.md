# Why the first 600k ticks made no PnL — root-cause analysis

## What I checked

Day-3 reveal bundle: `test_results/484992/`. Three datasets parsed:

1. **graphLog** — cumulative PnL every 2,000 ts (501 samples)
2. **activitiesLog** — per-tick book + per-product mark-to-mid PnL
3. **tradeHistory** — every SUBMISSION trade (3,114 own trades)

## What "sticky first 600k" actually was

Not slow-vol. Not warmup. The strategy was **fully engaged from tick 0** and was **bleeding the entire time**.

### Realized vol was uniform across the day

VFE std(Δmid) per 100k bucket: `1.290 / 1.347 / 1.355 / 1.305 / 1.286 / 1.311 / 1.317 / 1.299 / 1.316 / 1.361`. Effectively flat. Same for HYDROGEL (~2.4) and the vouchers. The market was equally choppy throughout.

### The strategy maxed positions in the first 100k ticks, then sat there

Net position change in bucket 0-100k (from tradeHistory):

| Product | First 100k net change | Final position end-of-day |
|---|---|---|
| HYDROGEL | **-200** (max short) | +200 (after late reversal) |
| VFE | **+200** (max long) | -200 |
| VEV_5000 | +176 | 300 |
| VEV_5100 | +172 | 280 |
| VEV_5200 | +199 | 300 |
| VEV_5300 | +176 | 272 |
| VEV_5400 | +231 | 255 |
| VEV_5500 | +255 | 255 |

The strategy hit max gross exposure within the first 100k ticks, holding ~+200 long delta on the option book and -200 short HYDROGEL.

### Why those directions? Because of opening-tick distance from anchor.

- HYDROGEL opened at **mid=10008** vs anchor=9983 → strategy fair clipped at anchor+33=10016, posted ask near touch → got hit by buyers → went short -200.
- VFE opened at **mid=5295.5**, drifted down. Maker bid sat in the book → got hit by sellers → went long +200.
- Vouchers tracked VFE → long inventory accumulated through delta-1 maker fills.

### Then the market moved against every one of those bets for 600k ticks

VFE level trajectory:
- ts 0: 5295.5
- ts 200k: 5238.5 (-57 ticks)
- ts 400k: 5223.5 (-72 ticks)
- ts 500k: 5199.5 (-96 ticks, **the bleed**)
- ts 700k: 5246.5 (recovered)
- ts 1M: 5232.0 (settled)

HYDROGEL stayed **above** anchor (10008-10041) for the entire first 600k ticks. The MR strategy is short and the price won't revert. Pure bleed.

The strategy had:
- Max long voucher delta (+200 across each strike) into a falling VFE
- Max long VFE (+200) into a falling VFE
- Max short HYDROGEL (-200) into a sticky-high HYDROGEL

Every position was wrong, all at maximum size, set in the first 100k ticks of the day.

### And then almost no trades happened until ts 600k

Per-bucket trade counts collapsed mid-day:

| Bucket | HYDROGEL | VFE | V5000 | V5300 |
|---|---|---|---|---|
| 0-100k | 22 | 25 | 99 | 114 |
| 100-200k | 24 | **0** | 43 | 49 |
| 200-300k | 45 | **0** | 20 | 31 |
| 400-500k | 10 | **0** | 5 | 14 |
| 700-800k | 33 | **0** | 56 | 57 |
| 900-1M | 39 | **50** | 75 | 85 |

VFE traded **25 times in the first 100k, then ZERO times for 800k ticks**. Citadel z-score MR never re-fired. Strategy held +200 VFE long through the entire downtrend with no exit logic. When VFE crashed at ts 470-540k, the +200 long got marked down -10,881 and the +200 voucher delta on top got marked down another -64k = **the -75k bleed bucket**.

### The recovery in last 400k ticks

After ts 600k, HYDROGEL dropped below anchor for the first time → MR strategy started covering its short and going long → got the late-day +30k as price reverted to anchor → +9,402 in the final bucket alone. VFE rallied → long inventory paid → final +12,151 in the last bucket.

The whole 80k EOD = **late-day reversion paying back what was bled in the first 600k**, with a small net surplus.

## Root cause (not symptoms)

The strategy is a **first-100k position taker, then a 600k passive holder, then a late-day mean-reverter**. PnL profile:

- First 100k: take max position based on opening-tick distance from anchor.
- Next 500k: hold and bleed if drift continues; barely trade.
- Last 300k: reversion either pays or doesn't.

This is not a robust design. On a day where the opening-tick distance was a real signal of regime (price oscillates around anchor), it makes money. On a day where opening-tick distance was just where the day happened to start before drifting, it bleeds.

## Five design flaws that caused this

### Flaw 1: Position is a step function, not gradient

The strategy enters max position within ~100k ticks because nothing prevents it. `_cap_size` shrinks size as `|pos|/limit` grows but starts from 0 with full speed. Within a few good fills, you're at limit. Then you're stuck.

### Flaw 2: Anchor is constant. Regime is not.

HYDROGEL anchor is hardcoded **9983** based on training-day fits. Day 3 traded at 10000-10040 for 600k ticks straight — a regime shift the anchor doesn't see. Strategy fair gets clipped 30+ ticks below actual mid → strategy aggressively sells → builds short → bleeds.

### Flaw 3: Citadel z-score MR has no time stop

Once Citadel takes a +200 VFE long at z=-2, it holds until z reverses to 0. If z stays at -2 for 800k ticks (because sigma-EMA is recalibrating to a new regime), Citadel holds for 800k ticks. No "exit if z hasn't reverted in N ticks" rule.

### Flaw 4: Per-product limits, no aggregate gross-exposure cap

Each voucher capped at 300, but 8 vouchers all long → total long voucher delta > 600 contracts of underlying-equivalent. Combined with VFE +200, the option book is +800 delta to VFE. A 1-tick VFE drop = -800 ticks PnL. No layer prevents this.

### Flaw 5: No defense against informed flow

Mark 67 buys VFE 165 times across the dataset with 95.8% subsequent-tick positive return. Mark 49 sells with -1.81 to -2.12 edge. The strategy never reads `state.market_trades` to identify these informed events. Every Mark 49 sell that hits your VFE bid is adverse selection.

## What "never happen again" requires

A strategy that works on this day must satisfy ALL five constraints:

### Constraint 1: Position grows slowly, decays fast

In the first 100k ticks, max position should be ~25% of limit. Position only grows above 50% if the regime confirms (e.g., price has been at this level for 100k+ ticks). Position cuts FAST on adverse drift (each 50-tick adverse move reduces target position by 20%).

### Constraint 2: Adaptive anchor / EMA-based fair

HYDROGEL anchor = 50k-tick EMA of mid (regime-adaptive), with the fixed 9983 as a slow drift bias (β=0.001). When regime shifts to 10020, anchor follows within ~50k ticks. No more clipping fair 30 ticks below mid.

### Constraint 3: Time-based stops on directional bets

If Citadel takes +200 VFE long and the position hasn't returned to <100 within 50k ticks, force-exit half the position. Hard time stops prevent infinite-hold during sustained adverse drift.

### Constraint 4: Aggregate Greeks cap

Track portfolio_delta = Σ(voucher_pos × delta_to_VFE) + VFE_pos. Cap |portfolio_delta| at ±50. Hedge any excess with VFE orders. This caps the worst-case bucket loss at ~|delta_cap × max_swing| = 50 × 50 = 2,500, not 75,000.

### Constraint 5: Read market_trades, react to Mark 67 / Mark 49

When Mark 49 sells VFE: pull own VFE bid for next 5 ticks. Suppress Citadel LONG signal for next 20 ticks. When Mark 67 buys: pull own VFE ask, suppress Citadel SHORT signal. This converts known adverse-selection events into defensive flat moves.

## What's NOT the fix

- More knob sweeps on `H_VK_DN_HIGH` etc. — the chassis is structurally wrong, not parameter-wrong.
- A bigger Citadel sigma-EMA half-life — doesn't help with 800k of holding the wrong direction.
- Smile fit alone — fixes voucher fair values but not the inventory-build problem.
- Disabling Citadel — loses the late-day reversion alpha that produced the only positive day.

## What I'm building

A new strategy from scratch, ~500 lines, organized as 4 layers:

1. **Drift-aware fair**: EMA-based fair with regime adaptation. No anchor clipping.
2. **Slow-build / fast-cut sizing**: position target = f(time, regime confidence, drift direction).
3. **Aggregate Greeks layer**: portfolio delta cap with VFE auto-hedge.
4. **Counterparty filter**: Mark 67 / Mark 49 as defensive shrinks and Citadel overrides.

Then layered on top:
- Smile fit for voucher fair values (reduces residuals; necessary for accurate Greeks)
- Time stops on Citadel directional bets

Expected outcome: first 600k ticks produces ~30-50k linear PnL instead of 0. Late-day reversion still adds ~30k. Total day = 60-80k from continuous alpha + reversion, not 80k from reversion offsetting bleed.
