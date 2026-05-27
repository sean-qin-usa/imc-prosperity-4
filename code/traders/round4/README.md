# Round 4 — Counterparty signals on the R3 chassis

**Products:** Unchanged from R3 (`HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, `VEV_*` voucher chain). New mechanic: `Trade.buyer` / `Trade.seller` fields now carry named-counterparty IDs.

**Shipped:** [`current_strategy.py`](./current_strategy.py) — seeded from R3 `combined_ship_v31.py` with `TTE_DAYS_LIVE = 4.0` to match the round-4 `VEV_5000` example. **3-day backtest: 440,853** (per-day 175,226 / 184,649 / 80,978).

For the narrative, see [`../../../round_4.md`](../../../round_4.md). For the recipe, see [`ROUND4_RECIPE.md`](./ROUND4_RECIPE.md). The counterparty event-study report lives at [`../../analysis/round4/counterparty_signal_report.md`](../../analysis/round4/counterparty_signal_report.md); the deep-dive event study is in [`../../analysis/round4/mark_deep_dive/`](../../analysis/round4/mark_deep_dive/).

## Approach in one line

The honest question for round 4 was: *does the named-counterparty signal pay enough alpha to justify rewriting any sleeve?* Found one real positive edge (Mark 67 buying VFE), tested overlay, found it fought the existing VFE MR sleeve and regressed PnL ($440,853 → $368,294 on the supplied days), shipped a TTE-only update and accepted the lost Mark-67 alpha. The right fix is a unified VFE sleeve with a regime gate ("if Mark 67 is buying, override the MR exit") — designed, not built.

## Files in this folder

- **[`current_strategy.py`](./current_strategy.py)** — the ship. Seeded from `combined_ship_v31` with the TTE update.
- **[`ROUND4_RECIPE.md`](./ROUND4_RECIPE.md)** — the recipe document, single-source-of-truth for the round.
- **[`STICKY_DIAGNOSIS.md`](./STICKY_DIAGNOSIS.md)** — diagnosis of the day-3 correlated drawdown bucket (`400000-499999`, ~−76 k across 10/12 products). Inherited from R3 chassis; never resolved.
- **[`framework_a.py`](./framework_a.py) … [`framework_h.py`](./framework_h.py)** — eight variant frameworks tested mid-round as candidates for the regime-gated VFE sleeve. None shipped (bandwidth call).
- **[`ship_*.py`](.)** — ship candidates (`ship_a_citadel.py`, `ship_b_marktake.py`, `ship_f_pure_mm.py`, `ship_final.py`, `ship_m_mark_defense.py`, `ship_m_mark_follow_corrected.py`, `ship_r4_v1.py`, `ship_r4_v2_burst.py`, `ship_r4_v2_par10.py`). Final ship is `current_strategy.py`.
- **[`hybrid_v1.py`](./hybrid_v1.py) … [`hybrid_v5.py`](./hybrid_v5.py)** — hybrid TTE + counterparty experiments. All regressed vs the TTE-only update.
- **[`_adaptive_penny_497941.py`](./_adaptive_penny_497941.py)** — adaptive-penny variant; file-ID suffix encodes a live PnL probe.
- **[`cp_pure_v1.py`](./cp_pure_v1.py)** — counterparty-only strategy (no R3 sleeves), used as a control measurement.
- **[`round4_full_candidate.py`](./round4_full_candidate.py)**, **[`rook_e1_from_scratch.py`](./rook_e1_from_scratch.py)** — alternative-architecture probes; neither shipped.
- **[`framework_f_ivscalp.py`](./framework_f_ivscalp.py)** — IV-scalping framework variant, kept for the comparison record.

## What I'd change (summary)

1. Build the regime-gated VFE sleeve — one-evening rewrite.
2. Take the day-3 correlated drawdown seriously — `STICKY_DIAGNOSIS.md` flags it, never identified the common factor.
3. Write up the Aether Crystal solve. Full reasoning in [`../../../round_4.md`](../../../round_4.md).
