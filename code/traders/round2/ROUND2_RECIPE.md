# Round 2 — Blank-State Recipe Card

**Goal:** a future Claude that has NEVER seen this round should be able to
read ONLY this file + `SIGNALS_PLAYBOOK.md` and ship a strategy that
backtests at **≥ 140 k / day** under `local_bundles_profile.json` on its
first try.  Everything non-obvious that took us three sessions to find
is written down here.

Backtester command (canonical — pass calibration or numbers lie):

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/<YOUR_STRAT>.py \
  --dataset round2_csv \
  --fill-model official-hybrid \
  --exchange-calibration tools/calibrations/local_bundles_profile.json \
  --no-plots --run-name <label>
```

Expected PnL benchmarks on `local_bundles_profile.json` (real-data
proxy — expect ~10% optimism vs real submission):

| Strategy sophistication | 3-day total | Per-day |
|---|---|---|
| Pure micro-price MM, size 20, no carry | ~210 k | ~70 k |
| **This recipe** | **~420 k** | **~140 k** |
| Historical `clean_alpha` v10 (best clean) | ~441 k | ~147 k |
| Backtester-artifact branches (do NOT ship) | 500-800 k | — |

---

## 1. Products

Two products.  Position limit **80** on each.

| Product | Generative story | Per-day alpha ceiling |
|---|---|---|
| `ASH_COATED_OSMIUM` (ACO) | stationary ≈ 10 000 + mean-revert noise | ~65 k |
| `INTARIAN_PEPPER_ROOT` (IPR) | linear drift +0.001 / ts + noise | ~80 k |

`POSITION_LIMITS = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}`
on the `Trader` class.

## 2. Data sanity numbers (will come up identical on every round-2 day)

Per-day scan should reproduce:

| Product | drift / 1e6 ts | residual sd | AR(1) mid-diff | mode spread |
|---|---|---|---|---|
| ACO | ≈ 0 (−4 to +20) | ~400 | −0.50 | **16** (≈58% of ticks) |
| IPR | **+984 to +1026** (≡ +0.001/ts) | ~500 | −0.50 | **12-14** |

**L1 imbalance → next-Δmid:**  P(up \| imb>+0.5) = 88-96% on both.
Aggregate r ≈ +0.59 BUT see §4 caveat below.

## 3. The IPR drift is the single biggest alpha (~80 k / day)

- Drift = +0.001 per timestamp = +1000 per 10 000-tick day.
- 80 units × +1000 = **+80 000 / day / market** if you hold the long limit.
- Consequence: optimal IPR strategy is **never flat, never short** during
  the day.  Target = +80 long.  Unwind only in the last 1 % of day.

## 4. ACO: ANCHOR, not pure micro-price

**Critical** — took us a session to realize.

- Pure micro-price fair **sounds** right given the +0.59 imbalance-Δmid
  correlation.  It is wrong for ACO in the common regime.
- **At spread ≤ 16 (the 58 % typical state), L1 imbalance ↔ Δmid ≈ 0**.
  The +0.59 aggregate corr is entirely from walked states (spread 18-19).
- Fair for ACO = clipped anchor at 10 000, i.e. `fair = 10_000 + clip(micro − 10_000, ±4)`.
- Only engage the micro-price shift when spread is non-typical.

For IPR the drift-corrected anchor plays the same role.

## 5. MM size must be LARGE

**Took several sessions to find.**  Naive size 18-22 leaves ~50 k/day on
the floor.

- `ACO_MM_SIZE = 75` (passive quotes one tick inside)
- `ACO_WALKED_EXTRA = 55` (additional quote on walked side, see §7)
- `IPR_PASSIVE_SIZE = 12` primary, `6` secondary (IPR books are thinner;
  size here is per-level in a 2-level stack)

Tuned grid (historical): `(MM=75, walked=55)` sits on a plateau at the
knee of the PnL curve; smaller sizes are strictly worse, larger sizes
give tiny gains but cost drawdown.

## 6. IPR early-accumulation window

During the first **2 000 ticks**, take every ask ≤ benchmark up to
`limit = 80`, at most **20** units per tick.  This gets you to the +80
drift-carry position fast before the book gets expensive.

After ts > 2000, continue taking up to **soft target = 72** (leaves room
for passive top-up); full 80 is the carry target.

## 7. Walked-spread rebound — +10-20 k / day free

When observed spread > typical spread, one side has "walked".  The
walked side snaps back +1.4 to +2.4 on the next tick.

- Detect: `spread > TYPICAL_SPREAD` (16 for ACO, 14 for IPR).
- Which side walked:  `bid_gap = anchor − best_bid`,
  `ask_gap = best_ask − anchor`; the larger gap is the walked side.
- Action: post an EXTRA inside-spread quote on the rebound side at
  `best_bid + 1` or `best_ask − 1`, size `ACO_WALKED_EXTRA = 55` (or
  `IPR_WALKED_EXTRA = 12`).
- Also: shift fair toward the non-walked side by `typical_spread / 2`.

## 8. Inventory skew (ACO only)

`fair_effective = fair − 0.06 * position` so posted quotes drift toward
flattening inventory automatically.  Skew 0.06 × 80 = 4.8 points — a
plausible inside-the-spread move.

## 9. Imbalance size skew

- At `|imb| > 0.30` on both products:
  - boost the favorable-side quote by 1.8 ×
  - shrink the adverse-side quote to 0.2 ×
- Adverse-selection guard; no net directional bet.

## 10. IPR 2-level passive bid

When `spread > 4` and we're below limit:
- Primary bid at `best_bid + 1`, size 12.
- Secondary bid at `best_bid + 2` (still inside `best_ask`), size 6.
- Skip entirely if `imb < −0.30` (book about to drop).
- Skip secondary if total pos would exceed limit.

Two priority slots so we don't get queued out by a single inside quote.

## 11. End-of-day unwind

- Start: `ts ≥ 990_000` (last 1 % of day).
- IPR:  sell into best_bid at most 20 at a time, only if `bb ≥ benchmark − 1`.
  Do NOT flatten earlier — drift is up-only, the longer you carry the
  more you earn.
- ACO: unwind into touch when we have inventory and touch is within
  `1.0` of fair, max 12 qty.

## 12. MAF bid

`def bid(self): return 15_000` — local backtester ignores this, but
real run uses it.  15 k is a mid-range guess for the Round 2 blind
auction (top 50 % wins the 25 % extra quotes).

## 13. Reference strategy file that achieves ~140 k/day

`traders/round2_fresh_claude/fresh_from_scratch_v3.py` (v3 = v2 + ACO EOD unwind; use as default).
Also valid: `fresh_from_scratch_v2.py` (no EOD unwind, PnL within rounding).

Structure:
1. `_book(od, spread_gate)` — returns bid/ask/micro with spread-gated
   fallback to mid.
2. `_walked_fair(bb, ba, micro, anchor, typical, clip)` — returns the
   clipped walked-aware fair.
3. `_trade_aco(od, pos, ts)` — takes, passive MM with inv skew, walked extra.
4. `_trade_ipr(od, pos, ts)` — early window, soft-target takes, 2-level
   passive bid, walked extra, EOD unwind.
5. `run(state)` routes order depths to the two handlers.

## 14. Kill-signals to avoid this round

- Do **NOT** use 1-lot child-order splitting (`final_strat_aco_max80_chunk1`
  hit 785 k local but real replay was 27-30 k).  It is a local-matcher
  artifact — see research log 2026-04-21.
- Do **NOT** quote pure mid-price for ACO (ignores the ~10 000 anchor —
  PnL drifts with noise).
- Do **NOT** quote pure micro-price for ACO at spread ≤ 16 (imbalance is
  non-predictive in that regime).
- Do **NOT** unwind IPR early (kills the drift carry).
- Do **NOT** ship without passing `--exchange-calibration
  tools/calibrations/local_bundles_profile.json` — default official-hybrid
  is +12 % optimistic.

## 14.5 Documented dead-ends (do NOT re-try these on R2 and expect gains)

These were scanned on 2026-04-23 session 3 and rejected on PnL:

- **Tight-spread micro-price gate** (spread ≤ 10 → use micro).
  Signal r = +0.87 is real but costs +2-pt on takes and regresses PnL
  by ~8 k / 3-day.  RESEARCH_LOG 2026-04-23 "Scan E".
- **Conditional imbalance by book depth** (thin vs thick).
  No material asymmetry (r 0.60 vs 0.62).  Dead.
- **L1 absolute-depth direction signal**.
  Only gives a weak volatility-regime hint (U-shape in E\|Δ\|), no
  direction.  Dead for directional trading.
- **First / last N-tick of day anomalies**.
  E[Δmid] and sd flat across the day except for the IPR drift itself.
  Dead.
- **ACO top-of-book Markov transition skew**.
  Largest observed |skew| = 0.085, below the tradable threshold ~0.10.
  Dead.
- **IPR z-score mean-revert trades** on residual.
  Residual half-life 0.1-0.2 ticks (white noise around drift); gating
  z-score trades on noise was shown in a prior session to be PnL-neutral
  or slightly negative.
- **1-lot child-order chunking** (final_strat_aco_max80_chunk1).
  Local-backtester artifact; 785 k local vs 27-30 k real.  Do not ship.

## 15. Minimum viable first-principles order of operations

If a future Claude reads this and wants to re-verify from scratch before
trusting it (sanity check):

1. Load each product's prices_round_2_day_*.csv, compute: OLS drift
   slope, residual sd, spread distribution, AR(1) on mid-diff.
   Should match §2's table.
2. Compute `E[Δmid | imb > +0.5]` and `E[Δmid | imb > +0.5, spread ≤ 16]`.
   The second should be ~0 (§4).
3. Bucket `E[Δmid | spread = s]` for ACO.  Confirm spread 19 and 21 show
   the walked-rebound pattern.
4. Then write the strategy per §3–§12.  Backtest with the
   local-calibration command at the top of this file.
