# Analysis

Signal scans, manual-challenge analyses, visualizer reports, prior-year reference research.

## Layout

```
analysis/
├── tools/           ← cross-round scanners and visualizer scripts
├── round1/          ← per-round signal scans, summaries, reports
├── round2/
│   └── manual/      ← R2 Research / Scale / Speed manual analysis
├── round3/
│   ├── manual/      ← R3 Bio-Pod six-scenario prior sweep
│   ├── manual_from_scratch/  ← clean first-principles R3 manual solve
│   ├── voucher_empirical/    ← VEV chain empirical findings
│   └── DGP_PLAYBOOK.md       ← cross-round generative-process playbook (R3+)
├── round4/
│   ├── counterparty_signal_report.md
│   ├── mark_deep_dive/       ← Mark-67 VFE deep-dive event study
│   └── mark_deep_dive.py
├── round5/
│   └── manual/      ← R5 news-trading allocation analysis
├── p3_priors/       ← prior-year (P3) research used as priors for P4
├── notebooks/       ← exploratory Jupyter notebooks
└── spec_templates/  ← templates for repeatable analyses
```

## Where to find specific analyses

| Round | Manual-challenge analysis | Algo-side reports |
|---|---|---|
| 1 | (not deep-dived — finals week) | [`round1/signal_scan_summary.json`](./round1/signal_scan_summary.json), [`round1/strategy_backtest_summary.csv`](./round1/strategy_backtest_summary.csv) |
| 2 | [`round2/manual/summary.md`](./round2/manual/summary.md) — Research/Scale/Speed (submitted `19/60/21`) | [`round2/counterparty_signal_report.md`](./round2/counterparty_signal_report.md), [`round2/propagation_report.md`](./round2/propagation_report.md), [`round2/signal_scan_report.md`](./round2/signal_scan_report.md) |
| 3 | [`round3/manual/RECOMMENDATION.md`](./round3/manual/RECOMMENDATION.md) — Bio-Pod (submitted `(775, 875)`, world #7 with `(771, 861)`) | [`round3/voucher_empirical/`](./round3/voucher_empirical/) |
| 4 | (Aether Crystal — submitted on paper, no write-up; see [`../../round_4.md`](../../round_4.md)) | [`round4/counterparty_signal_report.md`](./round4/counterparty_signal_report.md), [`round4/mark_deep_dive/`](./round4/mark_deep_dive/) |
| 5 | [`round5/manual/README.md`](./round5/manual/README.md) — News Trading allocation | (no separate algo report) |

## Subfolders

- **[`tools/`](./tools/)** — reusable cross-round scanners and visualizer scripts. See [`tools/README.md`](./tools/README.md).
- **[`p3_priors/`](./p3_priors/)** — prior-year (Prosperity 3) research used to seed P4 priors. See [`p3_priors/README.md`](./p3_priors/README.md).
- **[`DGP_PLAYBOOK.md`](./DGP_PLAYBOOK.md)** — the "data-generating-process" playbook started after R2 and applied R3 onward.
