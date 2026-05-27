# VFE drift carry — 2026-04-25 session 5

## Hypothesis (from session-4 handoff)

VFE has a +0.002/timestamp drift = ~+20 ticks/day on the average drifting day.
v11's VFE handler is pure mean-reversion (cross-spread aggressor on
`ema_o_dev` > / < ±UNDER_MR_THR). Lean target-long (+30 base) and we should
capture roughly +600/day from drift on top of MR.

## Drift verification

Empirical drift per day (mid-price):
| Day | Start | End  | Drift | μ(Δ)/ts | σ(Δ)/ts |
|----:|------:|-----:|------:|--------:|--------:|
| 0   | 5250  | 5244 | -6    | -0.0006 | 1.12    |
| 1   | 5245  | 5266 | +20.5 | +0.0021 | 1.13    |
| 2   | 5268  | 5296 | +28   | +0.0028 | 1.14    |
| avg |       |      | +14.2 |         |         |

Drift S/N over a full day: 20.5 / (sqrt(10000) * 1.13) = **0.18**.
Marginal even in hindsight — the strategy needs many days to realize alpha.

## Day-2 path (matters for carry sizing)

`t=0%:5268  t=25%:5278  t=50%:5246  t=75%:5216  t=100%:5296`

Day 2 dips to 5216 at the 75% mark before rallying +80 to 5296. A static
+30 long takes a 30 × (5268 - 5216) = -1560 mark-to-market drawdown
during the dip. MR signals fire during that dip and force capacity-cap
sells at low prices, locking in losses.

## VFE order book

- L1 spread ≈ 5 ticks (`bb` ≈ best_bid, `ba` ≈ best_ask)
- bid_wall is ~1 tick below best_bid; `bw + 1` ≈ best_bid
- v11 MR aggressor sells at `bw + 1`, buys at `aw - 1` — this is essentially
  an L1-touch crossing aggressor

## Variant A — passive penny-inside layer (combined_ship_v12_carry.py)

Approach: post a passive bid at `bb + 1` (one tick *inside* the L1 spread)
sized to (TARGET_LONG − pos), and ask at `ba − 1` symmetrically.
Skip same-side when MR is firing to avoid self-cross.

Result vs v11 baseline 428,754:

| target | total   | Δ      | day0    | day1    | day2    | vfe0   | vfe1   | vfe2  |
|-------:|--------:|-------:|--------:|--------:|--------:|-------:|-------:|------:|
| 0      | 421,003 | -7,751 | 126,229 | 146,771 | 147,993 | 11,160 |  9,528 | 5,010 |
| 30     | 423,237 | -5,517 | 127,998 | 147,764 | 147,475 | 12,929 | 10,521 | 4,492 |
| 80     | 428,534 |   -220 | 131,557 | 150,044 | 146,933 | 16,488 | 12,802 | 3,950 |

The passive layer **adversely fills**: at `bb + 1` we are one tick inside
the L1 spread, so any market sell that crosses to bb hits us first. We
acquire long right before further drops, and dump it via passive ask
right before further rises. Day-2 VFE PnL is gutted (12,614 → 4,492 at
target=30; → 3,950 at target=80).

The cleaner read: target=0 means the layer always reverts pos to 0, which
is **active churn** that loses 7.7k. Higher target reduces churn (the
deficit is filled and the layer goes idle), so loss shrinks toward zero.
The "drift carry" claim isn't realized — it's just churn-amount tuning.

**Verdict: variant A is bad. Don't ship.**

## Variant B — asymmetric MR cap (combined_ship_v12_carry_b.py)

Approach: cap MR-sell at `(-limit + TARGET_LONG)` instead of `-limit`.
MR-buy still uses full `+limit`. The natural sell→buy MR cycle leaves
position averaging around `+TARGET/2` instead of 0, no extra orders, no
extra spread cost. All carry is "free" — purely from rebalance asymmetry.

Result vs v11 baseline 428,754:

| target | total   | Δ      | day0 vfe | day1 vfe | day2 vfe |
|-------:|--------:|-------:|---------:|---------:|---------:|
| 0      | 428,754 |     +0 |    7,830 |   13,016 |   12,614 |
| 15     | 428,649 |   -105 |    8,006 |   13,126 |   12,224 |
| 30     | 428,565 |   -189 |    8,231 |   13,194 |   11,845 |
| 50     | 428,260 |   -494 |    8,587 |   12,996 |   11,382 |
| 80     | 427,825 |   -929 |    9,147 |   12,594 |   10,790 |
| 120    | 427,769 |   -985 |    9,932 |   12,324 |   10,218 |
| 170    | 425,685 | -3,069 |    8,866 |   12,292 |    9,233 |

Slope ≈ **−6 PnL per unit of TARGET_LONG** at the low end; cliff
above 120 where forced-MR loss compounds with carry drawdown on day 2.

Day-0 and day-1 VFE PnL increase modestly with target (the long bias does
capture some day-1 drift). Day-2 monotonically *decreases* — the dip at
75% of day forces capacity-cap MR sells at low prices that variant B's
restricted -limit + target makes worse, not better.

The trade-off: each MR-sell loses TARGET worth of size at cross-spread alpha
(~5-6 ticks = ~30 PnL per unit). Day 1/2 drift PnL gain at avg pos ≈
TARGET/2 is approximately TARGET × 21 (drift) / 2 = ~+10 per unit.
Net: drift gain (+10/unit) < MR alpha cost (~+15-20/unit). Slightly negative.

**Verdict: variant B is approximately neutral but consistently negative
in this backtest.** The MR sleeve is dominant and any reservation against
its capacity costs more than the carry gains.

## Why drift carry doesn't pay (intuition)

VFE's MR fires often and uses 100% of position capacity each time. The
drift S/N over a full day is ~0.18σ. Reserving N units for carry costs
N × spread_alpha (immediate, every MR cycle), and gains N × 14.2 / 3 over
3 days (averaged across the +20.5/+28/-6 days). Capacity is fungible
between MR alpha and carry, and MR's edge per unit is bigger than drift's.

## Possible escape hatches (untested)

1. **Time-of-day carry**: only enable carry in the last quarter of the day
   when the rally is more likely (day 2 had +80 in last 25%). Risks
   missing day-1 morning drift.

2. **Drift-confirmation gate**: adapt TARGET based on cumulative move
   over last K=2000 ticks; only carry when sign confirmed. Adds lag.
   Low S/N (drift = 0.002/ts vs noise std 1.13/ts) makes this hard.

3. **Carry the OTHER way**: structurally shorten via asymmetric MR-buy
   cap. Bet that drift averages negative across regimes. Day 0 gives
   evidence for this; days 1/2 against.

## Recommendation

**Do not ship a static drift carry on VFE.** The backtest shows a small
but consistent negative slope (-6/unit target on variant B; worse on
variant A). The hypothesis ("+600/day per +30 target") was based on a
pos-holding model that ignores the cost of stealing capacity from the
MR sleeve.

Files retained for later experimentation:
- `combined_ship_v12_carry.py` — variant A (passive penny-inside layer)
- `combined_ship_v12_carry_b.py` — variant B (asymmetric MR cap)

Both default to TARGET_LONG=30 in their headers but the sweep shows 0
is optimal. v11 remains the ship.
