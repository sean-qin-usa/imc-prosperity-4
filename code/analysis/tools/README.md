# Analysis tools

Reusable cross-round scanners and visualizer scripts. Per-round outputs live in the round subfolders ([`../round1/`](../round1/), [`../round2/`](../round2/), etc.); this folder is the *engines* that produced those outputs.

## Signal scanners

| Script | What it scans |
|---|---|
| [`signal_scan.py`](./signal_scan.py) | Generic per-product signal-hunt harness. Loops the §1–§7 checks from [`SIGNALS_PLAYBOOK.md`](../../SIGNALS_PLAYBOOK.md) over a product / day. |
| [`composite_signal_scan.py`](./composite_signal_scan.py) | Stacks multiple primitive signals (imbalance, walked-spread, AR(1), etc.) and reports composite-feature correlations with next-tick Δmid. |
| [`counterparty_signal_scan.py`](./counterparty_signal_scan.py) | Per-counterparty event study against forward returns. The engine behind the R4 Mark-67 deep dive. |
| [`informed_flow_scan.py`](./informed_flow_scan.py) | "Informed flow" hypothesis check — does a counterparty's net direction precede next-tick mid moves? |
| [`propagation_signal_scan.py`](./propagation_signal_scan.py) | Cross-product propagation: does an event in product A predict moves in product B? Used in R2 to confirm independence between ACO and IPR. |

## Visualizers

The visualizer scripts produce HTML/PNG reports of the trade and fill data alongside the strategy decisions. Per-round outputs are in [`visualizer_report/`](./visualizer_report/), [`visualizer_report_round1/`](./visualizer_report_round1/), [`visualizer_report_round3/`](./visualizer_report_round3/), [`visualizer_fh_exact_report/`](./visualizer_fh_exact_report/), [`visualizer_fh_plus_report/`](./visualizer_fh_plus_report/).

| Script | Purpose |
|---|---|
| [`visualizer.py`](./visualizer.py) | Static HTML report from a CSV fill log. |
| [`visualizer_interactive.py`](./visualizer_interactive.py) | Interactive Plotly-based version of the same. |
| [`visualizer_fh_clone.py`](./visualizer_fh_clone.py) | Clone of a published top-team visualizer for cross-team output comparison. |
| [`visualizer_fh_exact.py`](./visualizer_fh_exact.py) | Exact-fill-model variant used to test execution assumptions. |
| [`visualizer_fh_plus.py`](./visualizer_fh_plus.py) | `fh_exact` + extra annotations. |

The visualizer config JSONs (`visualizer_config.json`, `visualizer_config_round2.json`) define which products, days, and annotations to render — passed via `--config` to the visualizer scripts.

## Typical invocation

```bash
# Cross-round signal scan
python3 code/analysis/tools/signal_scan.py --round 2 --product ACO --day 0

# Visualizer report
python3 code/analysis/tools/visualizer.py --config code/analysis/tools/visualizer_config.json
python3 code/analysis/tools/visualizer_interactive.py \
  --config code/analysis/tools/visualizer_config_round2.json \
  --output code/analysis/tools/visualizer_report/round2/report_interactive.html
```
