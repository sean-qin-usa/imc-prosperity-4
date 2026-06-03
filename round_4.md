# Round 4 — Counterparty signals layered on the R3 chassis

**Products:** Algorithmic products unchanged from R3 (`HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, the `VEV_*` voucher chain). The new mechanic is that **historical trade data now exposes named counterparties** in `Trade.buyer` and `Trade.seller`. Manual challenge is the **Aether Crystal** option-pricing problem (independent of the algo).

**Final ship:** [`traders/round4/current_strategy.py`](./code/traders/round4/current_strategy.py), seeded from R3 `combined_ship_v31.py`, with one active change: `TTE_DAYS_LIVE = 4.0` to match the round-4 `VEV_5000` example.

## Approach

The R4 setup is a continuation of R3 with an information disclosure. The honest question for the algo side was: **does the named-counterparty signal pay enough alpha to justify rewriting any sleeve?** I ran the obvious analyses, found one real positive event-study edge, and then found that overlaying it hurt the existing VFE sleeve. I shipped a TTE-only update.

## Counterparty event study

Full report in [`analysis/round4/counterparty_signal_report.md`](./code/analysis/round4/counterparty_signal_report.md). The cleanest positive edge:

- **Mark 67 buying VFE** has a positive forward return across the deep-dive horizons (`analysis/round4/mark_deep_dive/`).
- Other named counterparties (Mark 0–66, 68+) showed nothing consistent at the size, side, time-bucket, or product cuts I ran.

## Why I didn't ship the Mark-67 follow

Direct overlay test, three-day backtest:

| Ship | 3-day PnL |
|---|---:|
| TTE-only (R3 chassis + TTE update) | **440,853** |
| TTE + Mark 67 direct follow on VFE | 368,294 |

The overlay fought the existing VFE mean-reversion sleeve and reduced VFE PnL on all three supplied days. Mark 67's buys are a real positive signal *as forecast*, but they cluster in the same regimes where the MR sleeve was already long. Adding the follow doubled exposure into trades the MR already had on, then exited late when the MR sleeve unwound.

The right fix is structural — reformulate VFE as a single sleeve with a regime gate ("if Mark 67 is buying, override the MR exit") rather than two competing signals. I didn't have the bandwidth to design and validate that mid-round, so I shipped the TTE-only update and accepted the lost Mark-67 alpha.

## Backtest results (TTE-only ship)

```
PYTHONHASHSEED=0 python3 IMCP2026/tools/jmerle_backtester.py \
  IMCP2026/traders/round4/current_strategy.py 4 \
  --data IMCP2026/data --no-out
```

| Day | PnL |
|---|---:|
| `4-1` | 175,226 |
| `4-2` | 184,649 |
| `4-3` | 80,978 |
| **Total** | **440,853** |

Residual risk: the backtester flags one correlated drawdown bucket on day 3 (`400000-499999`, ~−76 k across 10/12 products). This is inherited from the R3 chassis, not caused by the TTE update. I noted but did not address it — same bandwidth call as the Mark-67 fix.

## Manual challenge — "Vanilla Just Isn't Exotic Enough" (Aether Crystal)

This is a sealed option-pricing exercise on a new instrument set with the underlying (Aether Crystal) and a set of vanilla call contracts. I solved it as a straight Black-Scholes pricing problem against the implied surface from the order book, computed the EV-optimal allocation under the inferred volatility, and submitted that.

The math was right. The submission was wrong.

The realized path put the EV-optimal portfolio's edge inside the noise band — contracts that should have paid off under the long-run distribution paid nothing on the actual realized path. The submission made approximately zero PnL on a problem where the EV-optimal answer had double-digit-percent edge in expectation. That's the failure mode of EV-sizing on a single-seed contest: the math is right in expectation; the score is one draw. The variance-management lesson is written up at length in [lessons_learned.md §0b](./lessons_learned.md). Short version: I should have capped per-leg allocation at the level the realized-path drawdown could absorb, not at the EV-maximizing level. The R3 manual instinct (`(775, 875)` beating textbook-optimal `(751, 836)` via cluster-aware sizing) was the right discipline applied to field-clustering variance. R4 needed the same discipline applied to underlying-path variance and I didn't make the jump.

The post-hoc absence of an `analysis/round4_manual/` file is itself part of the lesson — I treated the math as the answer and moved on, instead of writing the per-strike EV table and the worst-case-allocation sensitivity I needed.

## What I'd change

1. **Build the regime-gated VFE sleeve.** The Mark-67 overlay loss isn't because the signal is bad — it's because two sleeves were betting on overlapping moves and the exit logic conflicted. A unified sleeve is a one-evening rewrite I should have made time for.
2. **Take the day-3 correlated drawdown seriously.** A −76 k cluster across 10/12 products is a portfolio-level signal that the strategy is over-exposed to some common factor in that window. I never identified what.
3. **Write up the Aether Crystal solve.** The fact that I have no `analysis/round4_manual/` file is itself a process failure — at minimum a 5-minute summary of the BS inputs and the chosen quantities would have made it possible to verify the answer later.
