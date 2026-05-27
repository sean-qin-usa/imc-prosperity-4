# Prosperity 3 Round 2 — Blank-State Recipe Card

**Goal:** a future Claude reading ONLY this file + `SIGNALS_PLAYBOOK.md`
should ship a strategy that clears **~200 k SeaShells** on the P3 R2
local backtester (`prosperity3bt`) first try, beating Timo Diehm
(Frankfurt Hedgehogs, 2nd place P3) on his own round.

Baseline verified 2026-04-23: `traders/p3_fresh_claude/p3r2_fresh.py`
hit **+201,613** across days −1 / 0 / 1.

**Honest head-to-head (2026-04-23):** running Timo's actual polished
submission (`practice/winners/timo-prosperity-3/FrankfurtHedgehogs_polished.py`)
on the SAME backtester / SAME P3 R2 data gives:

| Product | Timo polished | This recipe v1 | Δ |
|---|---|---|---|
| RAINFOREST_RESIN | ~117,000 | 74,966 | **Timo wins +42k** |
| KELP | ~17,000 | 0 (disabled) | **Timo wins +17k** |
| PICNIC_BASKET1 | 0 (not traded) | 70,348 | we win (he abstained) |
| PICNIC_BASKET2 | 0 (not traded) | 56,299 | we win (he abstained) |
| CROISSANTS / JAMS / DJEMBES / SQUID | 0 / 0 | 0 / 0 | — |
| **Total 3-day** | **133,968** | **201,613** | **+67k** |

**Interpretation** — we out-score Timo only because he chose not to
trade baskets on R2 (his polished basket engine is round-gated to R3+;
the 40-60k/round he reports for baskets is aggregated across R3-R5,
not R2-specific).  On the products he does trade:

- **Timo's Resin MM is 55 % better than ours.**  His "straightforward
  take-under-10k / post-edge-above-10k" anchor MM extracts more per-day
  than our recipe-scaled ACO handler (75 k vs his 117 k).  Likely
  reason: different quote-size tuning, and his liquidity-flatten at
  exactly 10 000 when inventory is skewed.
- **Timo's Kelp works** where ours is disabled.  He uses wall-mid take +
  inside-spread passive + zero-edge flatten when inventory skews.  ~17 k
  free that we're leaving on the table.

So the "we beat Timo by 80-100k" framing earlier in this file was
misleading — we beat his *polished code on R2 data*, not his R2-era
strategy, and only by exploiting an alpha he chose not to take.  The
recipe does produce real +200k in the backtester, but the edge is
almost entirely basket-arb (which is honest alpha) — not superior
MM ability.

Backtest command:

```bash
cd /Users/sean_tsu_/Downloads/prosperity
# need a copy of datamodel.py next to the strategy file
cp practice/winners/timo-prosperity-3/datamodel.py IMCP2026/traders/p3_fresh_claude/
python3 -m prosperity3bt IMCP2026/traders/p3_fresh_claude/<STRATEGY>.py 2
```

---

## 1. Products (P3 R2)

8 products, 3 groups.  Position limits from the backtester:

| Group | Products (limits) | Strategy |
|---|---|---|
| R1 carry-over | RAINFOREST_RESIN (50), KELP (50), SQUID_INK (50) | Resin: static-anchor MM.  Kelp: SKIP in v1 (EMA MM was adverse-selected, −8 to −11 k/day).  Squid: skip (informed-bot; needs Olivia detection). |
| Constituents | CROISSANTS (250), JAMS (350), DJEMBES (60) | Not traded standalone in v1; used as basket legs only. |
| Baskets | PICNIC_BASKET1 (60), PICNIC_BASKET2 (100) | Fixed-threshold spread trade vs synthetic.  NO constituent hedging. |

Basket composition:
- `PICNIC_BASKET1 = 6·CROISSANTS + 3·JAMS + 1·DJEMBES`
- `PICNIC_BASKET2 = 4·CROISSANTS + 2·JAMS`

## 2. §0.2 data sanity (reproduce before strategy)

```
RAINFOREST_RESIN  anchor≈10000  rsd≈2.2  AR(1)=-0.50  mode spread 16  imb_r=+0.68
KELP              drifting      rsd≈2-4  AR(1)=-0.48  mode spread 3   imb_r=+0.56
SQUID_INK         drifting      rsd≈17-25 AR(1)≈0     mode spread 3   imb_r≈+0.2
CROISSANTS        drifting      rsd≈7-9   AR(1)=-0.13 mode spread 1   imb_r=+0.33
JAMS              drifting      rsd≈10-16 AR(1)≈0     mode spread 2   imb_r=+0.19
DJEMBES           drifting      rsd≈15-20 AR(1)≈0     mode spread 1   imb_r=+0.20

PB1 − synth:  mean +30 to +70  sd ~85    min -195  max +251
PB2 − synth:  mean -4 to +58   sd ~55    min -120  max +150
Both spreads: persistence(d_t, d_{t+1}) = 0.999 (slow MR, NOT tick-level).
```

Resin is **structurally identical** to P4's ACO. Same anchor-clipped MM
recipe applies. This is the single biggest transfer-learning win.

## 3. Generative-process stories (§0.1)

- **RAINFOREST_RESIN** → story #1 (flat anchor + MR noise).
  Apply ACO-style recipe with limit 50.
- **KELP** → story #2 (slow drift + MR noise). Wants an EMA-fair MM.
  My v1 EMA was adverse-selected; parked for v2.
- **PICNIC_BASKET1/2** → story #4 (independent constituents + MR spread).
  **Fixed-threshold trade, NO hedge.**  Playbook §0.1 story #4 is
  non-negotiable for this structure — z-score sizing and constituent
  hedging both destroy PnL here; the research log from P3 R3 shows
  moving from z-score to fixed-threshold took PnL from −105 k/day to
  +52 k/day.  Same mechanic applies to R2 baskets.

## 4. Production parameters (what hit 201 k)

**Resin (ACO-clone, scaled for limit 50):**

```python
RESIN_FAIR = 10_000
RESIN_FAIR_CLIP = 4.0
RESIN_TYPICAL_SPREAD = 16
RESIN_WALKED_FAIR_CLIP = 6.0
RESIN_INV_SKEW = 0.10          # 0.06 × 80/50 ≈ 0.10
RESIN_MM_SIZE = 40             # ~75 × 50/80
RESIN_WALKED_EXTRA = 25        # ~55 × 50/80
```

Everything else (walked-fair correction, inventory skew, 1-tick penny,
imbalance size-skew) is the same as the P4 R2 recipe.

**Basket thresholds (fixed, no z-score):**

```python
B1_UPPER = +80.0   # short PB1 when PB1 − synth > +80
B1_LOWER = -40.0   # long PB1 when PB1 − synth < -40
B2_UPPER = +80.0   # short PB2 when PB2 − synth > +80
B2_LOWER = -40.0   # long PB2 when PB2 − synth < -40
BASKET_TRADE_SIZE = 15  # per-tick aggression (capped by limit and L1 depth)
```

These were picked by eyeballing the historical distribution (mean +30-70,
sd 55-85; top/bottom 5% ≈ ±80 to ±90).  Widening UPPER reduces trade
count but each trade is bigger; tightening increases churn.

**Basket entry logic** — straight market orders (no passive make):

- `spread > UPPER`: hit best bid (sell basket) up to size.
- `spread < LOWER`: lift best ask (buy basket) up to size.
- Position limit enforced; L1 volume cap respected.

Execution is **intentionally simple** — the spread-trade alpha lives
on the directional bet, not on execution edge.

## 5. Verified PnL contribution

| Product | Day −1 | Day 0 | Day 1 | 3-day total |
|---|---|---|---|---|
| RAINFOREST_RESIN | 25,089 | 26,863 | 23,014 | **74,966** |
| PICNIC_BASKET1 | 15,450 | 17,466 | 37,432 | **70,348** |
| PICNIC_BASKET2 | 22,476 | −9,832 | 43,655 | **56,299** |
| KELP / SQUID / C/J/D | 0 | 0 | 0 | 0 |
| **Daily total** | **63,015** | **34,497** | **104,101** | **201,613** |

Timo reference (approx): Resin 39 k + Baskets 40-60 k + Croissants 20 k
+ Kelp ~25 k = **120-145 k / round**.  We beat this with 4 of 8 products
un-traded, leaving substantial upside in Kelp, Croissants, and
informed-bot-aware Squid.

## 6. Known gaps (what a v2 should add)

1. **Kelp fix** — EMA MM was adverse-selected.  Symptom: chasing anchor
   at tight spread (mode 3) crosses into the informed-trader flow.
   Try: slower EMA (α = 0.02), plus "don't post when |mid − EMA| > clip"
   guard.  Upside: +10 to +30 k / round.
2. **Croissants standalone** — Timo's 20 k / round comes from tracking
   the informed trader "Olivia" on Croissants.  Without her detection,
   skip.  With her detection (size-filtered trade scan), can add ≥ 20 k.
3. **Squid Ink** — same Olivia pattern on the previous round's product.
   Needs a size-filtered trade aggressor scan.  Skip until that's
   built.

## 7. Kill-signals (do NOT ship)

- Constituent hedging on baskets.  P3 R3 research-log 2026-04-20 shows
  hedging destroys PnL in this structure.
- Z-score sizing on basket spread.  Persistence is 0.999 (days-long MR),
  so z-score re-entry is too fast and accumulates losses inside the
  natural MR cycle.
- Kelp pure-micro MM with default α.  Loses money in local backtest.
- **Rolling-center thresholds** (v2 failure, 2026-04-23): replacing
  hardcoded `+80 / −40` with `EMA_center ± K` degraded PnL by 20 %
  on R2 and introduced a −50k cliff at K ≤ 40.  The EMA center chases
  our own trades and erases the real distribution-skew signal.
  Hardcoded thresholds are correct for this round.
- **"Trim on adverse move" stop-loss** (v3 failure, 2026-04-23): trimming
  25 % when spread runs past 2·K destroyed PnL (−71% on R2, −77% on
  R3 OOS).  Mean-revert strategies can't use trim-on-adverse stops —
  the thesis IS that the move will reverse; selling into it realises
  loss before the reversal.  A legitimate stop for MR would key off
  **duration of extreme** (e.g., 1 000+ ticks past threshold) or a
  catastrophic-dollar cap, not just the spread level.

## 7.5 Sensitivity test summary (measured 2026-04-23)

v1 parameter sweep on R2 baseline (201,613) and R3 OOS (209,847):

| Perturbation | R2 Δ | R3 OOS Δ |
|---|---|---|
| B1_UPPER ±25 | +8% / −4% | +5% / −10% |
| B1_LOWER ±20 | +4% / −7% | — |
| B2_UPPER ±25 | +7% / −10% | −6% (up only tested) |
| B2_LOWER ±20 | −10% / +5% | +3% (down only tested) |

All within ±10 %.  **Flat plateau, not a noise peak** per playbook §8.
Tighter thresholds (B1U=60, B2U=60) gave +8% on both R2 and R3 — minor
upside but the baseline is already robust.

## 8. Min-viable reproduction checklist

1. Run `analysis/fresh_scan_p3r2.py` and confirm the §0.2 table above.
2. Compute per-day basket − synthetic spread, confirm the mean / sd
   ranges above.
3. Write strategy with: Resin MM (recipe-scaled), both basket
   fixed-threshold trades, everything else skipped.
4. Backtest: `python3 -m prosperity3bt <file> 2`.
5. Expect ~200 k total on 3 days, >= 30 k per day.  If below, debug the
   basket entry logic first (most PnL sensitivity there).
