# Round 2 Workspace

Active round 2 work should live in this folder.

Pointers:

- Running experiment ledger: `RESEARCH_LOG.md`
- Signal-mining addendum: `RESEARCH_LOG_signal_mining_literature_20260423.md`
- Round 3+ DGP playbook: `analysis/ROUND3_AND_LATER_DGP_PLAYBOOK.md`
- Dataset mirror: `IMCP2026/data/round2`
- Static report output: `IMCP2026/analysis/visualizer_report/round2`
- Interactive dashboard: `IMCP2026/analysis/visualizer_report/round2/report_interactive.html`
- Round 2 info doc: `IMCP2026/documents/round2_info.md`
- Round 2 uplink transcript: `IMCP2026/documents/round2_uplink_transcript.md`

Quick rebuild from the repo root:

```bash
python3 analysis/visualizer.py --config analysis/visualizer_config_round2.json
python3 analysis/visualizer_interactive.py --config analysis/visualizer_config_round2.json --output analysis/visualizer_report/round2/report_interactive.html
```

Round-specific reminders:

- Round 2 keeps `ASH_COATED_OSMIUM` and `INTARIAN_PEPPER_ROOT`.
- Round 2 introduces `Trader.bid()` for the Market Access Fee auction.
- Local/public testing ignores `bid()` and uses the reduced base quote set, so fee calibration is partly a blind-auction problem.
- The manual challenge is now the `Research / Scale / Speed` budget-allocation problem.

Current round 2 files:

- `final_strat.py`: clean promoted baseline carried forward from the best validated round 1 core.
- `final_strat_baseline_20260420.py`: frozen copy of the baseline before the recent ACO execution experiments.
- `final_strat_aco_split.py`: small ACO passive split branch (`10 + 9`) that improves local replay without changing fair.
- `final_strat_aco_max80_chunk1.py`: aggressive ACO backtester-optimized branch that posts the full ACO cap as 1-lot child orders. Keep this as a research artifact, not the production default.

Use `RESEARCH_LOG.md` for the chronology, evidence, and exact backtest numbers behind these branches.
