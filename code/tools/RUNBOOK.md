# Backtester Runbook

This file is a quick command reference for running the local backtester.

## PRE-SHIP CHECKLIST (do not skip)

Before submitting any strategy, confirm all four:

1. **3-day jmerle bt** with `PYTHONHASHSEED=0` reports per-day PnL.
2. **Intra-day drawdown report** auto-prints after the bt. Inspect the worst bucket per day.
3. **No bucket lost more than 30k in any 100k-ts window** (the auto-report flags this with `WARNING:`). If flagged, add an inventory brake / position cap before shipping.
4. **Per-tick rate variance across days < 2×.** Compare `day_pnl / 10000` for each day; if max/min > 2, the strategy has day-specific overfit.

**Why these exist:** R3 day-3 reveal lost -74,894 in a single 100k-ts bucket as VFE swung and every delta-1 voucher marked against position simultaneously. EOD totals on training days 0/1/2 (154k/179k/186k) showed nothing wrong because each day closed positive. The 1k-tick provisional snapshot also showed +44k. Both metrics are blind to mid-day correlated drawdowns. The auto-report would have flagged the day-3 bucket immediately.

**Reanalyze a past bundle or jmerle log:**

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/intraday_drawdown_report.py /path/to/<bundle>.json
python3 tools/intraday_drawdown_report.py /path/to/<jmerle>.log --all-buckets
python3 tools/intraday_drawdown_report.py /path/to/prices.csv --threshold 20000
```



Assumptions:
- Repo root: `/Users/sean_tsu_/Downloads/prosperity/IMCP2026`
- Main backtester: `tools/backtester.py`
- Round 0 strategy files: `traders/round0/*.py`
- Historical data folder: `data/`
- Default run root: `/Users/sean_tsu_/Downloads/prosperity/gen/backtests/`

## Core Commands

Run a strategy against the tutorial CSV bundle:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_try.py --dataset round0_csv
```

Run the current default behavior:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_try.py
```

This now defaults to benchmark-data datasets when present.

Run the same strategy with a label so the folder name is self-describing:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_try.py --dataset round0_csv --run-name fair-reversion-v1
```

Run the archived baseline strategy against the tutorial CSV bundle:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_try_og.py --dataset round0_csv
```

Run a fast no-plot pass for quicker iteration:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_try.py --dataset round0_csv --no-plots
```

## Benchmark Data Day

Run the no-trade benchmark data day from the saved run log:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_nothing.py --dataset 77832 --no-plots
```

Run an active strategy against the same benchmark data day:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_try.py --dataset 77832 --no-plots
```

Run the archived baseline against the benchmark data day:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_try_og.py --dataset 77832 --no-plots
```

## Fill Model Checks

Canonical same-tick matching:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_try.py --dataset 77832 --fill-model same-tick --match-trades all --no-plots
```

Stricter market-trade matching:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_try.py --dataset 77832 --fill-model same-tick --match-trades worse --no-plots
```

No market-trade matching:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_try.py --dataset 77832 --fill-model same-tick --match-trades none --no-plots
```

Older interval-style fill model:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_try.py --dataset 77832 --fill-model interval --queue-alpha 1.0 --no-plots
```

Separate market-trade exposure from fill simulation (hide trades from strategy, still allow tape fills):

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_try.py --dataset 77832 --fill-model same-tick --match-trades all --market-trades none --fill-trades all --no-plots
```

Book-delta fill model (passive fills inferred from book volume changes):

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_try.py --dataset 77832 --fill-model book-delta --book-delta-on-disappear if-through --no-plots
```

Official-style round 1 replay (visible takes + calibrated inside-spread passive fills):

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round1/current_strategy.py --dataset round1_csv --fill-model official-hybrid --no-plots
```

## Compare Two Strategies

Run both strategies on the same dataset:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_try.py --dataset round0_csv --no-plots --run-name current
python3 tools/backtester.py traders/round0/tut_try_og.py --dataset round0_csv --no-plots --run-name baseline
```

Then inspect the run index:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
tail -n 20 ../gen/backtests/index.csv
```

## Official Parity Checks

Compare local backtester output to an official submission log:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/official_compare.py --official-json /tmp/prosperity_submission_84960/86769.json --official-log /tmp/prosperity_submission_84960/86769.log --strategy /tmp/prosperity_submission_84960/86769.py --fill-model same-tick --match-trades all
```

Important:

- Use the actual submission `.log` that came with the official run bundle, not a saved benchmark-data market log under `data/.../benchmark_data_day_0/`.
- A benchmark-data market log usually has `0` `SUBMISSION`-tagged trades and its `activitiesLog` PnL ends at `0.0`.
- `tools/official_compare.py` now prints these diagnostics up front so you can catch mismatched inputs before trusting the replay result.

Replay the official tradeHistory as fills to validate PnL math (should match the official graph if PnL logic is consistent):

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/official_compare.py --official-json /tmp/prosperity_submission_84960/86769.json --official-log /tmp/prosperity_submission_84960/86769.log --strategy /tmp/prosperity_submission_84960/86769.py --replay-official --replay-timing before
```

Exact official graph reconstruction from activitiesLog:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/official_compare.py --official-json /tmp/prosperity_submission_84960/86769.json --official-log /tmp/prosperity_submission_84960/86769.log --strategy /tmp/prosperity_submission_84960/86769.py --replay-activities
```

Generate a reusable official-run review bundle with plots, summary tables, and advice:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/analyze_official_run.py /tmp/prosperity_submission_84960
```

Calibrate a fresh passive-fill profile from an official run bundle:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/calibrate_exchange_model.py --official-log /tmp/prosperity_submission_84960/86769.log --strategy /tmp/prosperity_submission_84960/86769.py --output tools/calibrations/custom_passive_profile.json
```

Aggregate passive-fill calibration across multiple official bundles:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/calibrate_exchange_model.py \
  --bundle-dir /tmp/prosperity_submission_125928 \
  --bundle-dir /tmp/prosperity_submission_131422 \
  --output tools/calibrations/combined_official_passive_profile.json
```

The aggregated calibration now keeps spread-level defaults plus side, size-bucket, and inside-spread-distance buckets.

Blend new official evidence into a prior calibration so sparse buckets do not overfit:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/calibrate_exchange_model.py \
  --bundle-dir /tmp/prosperity_submission_131422 \
  --bundle-dir /tmp/prosperity_submission_163569 \
  --prior-calibration tools/calibrations/round1_official_passive_fills_blended_125928_131923.json \
  --prior-weight 125 \
  --output tools/calibrations/combined_official_passive_profile.json
```

The current default `official-hybrid` profile is the recent-market blend: it layers official bundles `131422` and `163569` on top of `round1_official_passive_fills_blended_125928_131923.json` with `prior-weight=125`.

Use the official-site probe strategy to generate richer fill evidence:

```text
traders/round1/exchange_fill_probe.py
```

That probe alternates quote size and inside-spread distance while keeping inventory near flat, so the resulting bundle can improve the calibration beyond one production strategy's order pattern.

Validate the official-style matcher against that run:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/official_compare.py --official-json /tmp/prosperity_submission_84960/86769.json --official-log /tmp/prosperity_submission_84960/86769.log --strategy /tmp/prosperity_submission_84960/86769.py --fill-model official-hybrid --exchange-calibration tools/calibrations/custom_passive_profile.json
```

Run the same review against a specific `.log` and skip the local replay for speed:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/analyze_official_run.py /tmp/prosperity_submission_84960/86769.log --no-local-compare
```

Run every discovered dataset instead of the benchmark-data default:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/backtester.py traders/round0/tut_try.py --all-datasets
```

## Reports

Default output root:

```text
/Users/sean_tsu_/Downloads/prosperity/gen/backtests
```

Each backtester invocation creates one run folder:

```text
../gen/backtests/<timestamp>__<strategy>__<fill-model>__<match-trades>__<dataset>[__<run-name>]
```

Inside each run folder, the backtester writes:
- `STATUS.txt`
- `run_manifest.json`
- `run_summary.csv`
- one subdirectory per dataset

Inside each dataset subdirectory, it writes:
- `summary.csv`
- `equity_curve.csv`
- `orders.csv`
- `fills.csv`
- `report.html`
- PNG charts when plots are enabled

Convenience pointers:
- `../gen/backtests/latest` points to the most recent backtester invocation when symlinks are available
- `../gen/backtests/LATEST.txt` always contains the absolute path of the most recent run
- `../gen/backtests/index.csv` accumulates per-run summary rows for quick comparisons
- `STATUS.txt` is `running`, `completed`, or `failed`

Open the latest report in Finder or browser if needed:

## Visualizer

Use `analysis/visualizer_interactive.py` as the single supported dashboard.
It generates the interactive Plotly report at `analysis/visualizer_report/.../report_interactive.html`.

Notes:
- `analysis/visualizer.py` is still present for legacy static exports and shared helper functions.
- `analysis/visualizer_fh_clone.py`, `analysis/visualizer_fh_plus.py`, and `analysis/visualizer_fh_exact.py` are compatibility aliases that now resolve to the same unified interactive dashboard.

Config file:
`analysis/visualizer_config.json`

Key config knobs:
- `data_dir`: folder with `prices_*.csv` and `trades_*.csv` (or set to an official `.log`/`.json` file for the interactive visualizer)
- `symbols`: limit to specific products
- `min_trade_qty` / `max_trade_qty`: trade-size filters
- `normalize_by`: normalize mid by `wall_mid` or another series
- `ema_windows`, `impact_horizons`, `rolling_window`: indicator controls
- `indicator_file`: CSV/JSONL with `timestamp` (+ optional `day`, `symbol`) and numeric indicator columns
- `indicator_columns`: which indicator columns to overlay (empty = auto-detect numeric)
- `small_trade_qty` / `big_trade_qty`: thresholds for S/B taker grouping
- `own_trade_tags`: tag(s) to identify your own trades (e.g., `SUBMISSION`)
- `informed_traders`: trader IDs to label as informed
- `backtest_path`: a run directory (e.g. `../gen/backtests/latest`) or dataset folder with `equity_curve.csv`
- `log_file`: CSV/JSONL/plain log to render in the report

### Interactive report

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 analysis/visualizer_interactive.py --config analysis/visualizer_config.json
```

Output:
`analysis/visualizer_report/report_interactive.html`

### One-command rebuild and open

Rebuild and open the unified dashboard from the latest backtest run:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/open_visualizer.py
```

Run a strategy, rebuild the unified dashboard against that fresh run, and open it:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/open_visualizer.py traders/round1/path_anchor_strategy.py --dataset round1_csv
```

Notes:
- The wrapper defaults to your round1 resolved visualizer config when it exists, so it refreshes `analysis/visualizer_report/round1/report_interactive.html`.
- If you only add a new `traders/round*/foo.py` file and rerun the wrapper with no strategy argument, the new strategy name will still appear in the HTML because the dashboard rebuild rescans the `traders/` tree.
- Backtester PNG/report generation is skipped by default for speed; add `--keep-run-plots` if you still want the per-run static outputs.

### Interactive report from an official log

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 analysis/visualizer_interactive.py \
  --config analysis/visualizer_config.json \
  --data-dir /path/to/official_submission.log
```

Notes:
- The interactive report loads Plotly from a CDN, so it needs internet when you open the HTML.

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
open ../gen/backtests/latest/round0_csv/report.html
```

Inspect the latest run metadata:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
cat ../gen/backtests/latest/run_manifest.json
```

Regenerate plots and `report.html` for the latest no-plot run:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/plot_run.py
```

Regenerate plots for a specific run folder:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/plot_run.py ../gen/backtests/20260412_223603__77832__same-tick__all__77832__data_layout_smoke
```

Regenerate plots for just one dataset inside a run:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/plot_run.py ../gen/backtests/latest --dataset round0_csv
```

## Useful One-Liners

Syntax-check the backtester:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 -m py_compile tools/backtester.py
```

Syntax-check the plot script:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 -m py_compile tools/plot_run.py
```

Syntax-check a strategy:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 -m py_compile traders/round0/tut_try.py
```

List discovered strategy files:

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
find traders/round0 -maxdepth 1 -name '*.py' | sort
```

## Current Defaults

- `--fill-model same-tick`
- `--match-trades all`
- default input root is `data/` and directory discovery is recursive
- default dataset selection prefers benchmark-data runs when present
- plots enabled unless `--no-plots` is passed
- runs saved under `../gen/backtests`
- strategy files are expected to define `Trader`

## Notes

- `round0_csv` means the combined CSV dataset discovered from `data/round0/prices_round_0_day_-2.csv`, `data/round0/prices_round_0_day_-1.csv`, `data/round0/trades_round_0_day_-2.csv`, and `data/round0/trades_round_0_day_-1.csv`.
- `77832` is the saved benchmark-data run-log dataset from `data/round0/benchmark_data_day_0/77832.log`.
- You can usually omit `--input` entirely because the backtester now scans nested directories under `data/`.
- If you omit `--dataset`, the backtester now prefers benchmark-data datasets by default. Use `--all-datasets` to run everything it discovers.
- If we discuss a new strategy file later, replace the strategy path in the commands above and keep the rest the same.
- If you want a memorable folder name, pass `--run-name some-label`.
