# Spec Templates

These JSON files are inputs for the reusable round-analysis scanners:

- `analysis/composite_signal_scan.py`
- `analysis/propagation_signal_scan.py`

Example:

```bash
python3 analysis/composite_signal_scan.py \
  --data-dir data/round3 \
  --spec analysis/spec_templates/round3_picnic_relations.json \
  --output analysis/round3_composite_report.md
```

```bash
python3 analysis/propagation_signal_scan.py \
  --data-dir data/round3 \
  --spec analysis/spec_templates/round3_propagation_relations.json \
  --output analysis/round3_propagation_report.md
```

Interpretation:

- `round3_picnic_relations.json`
  - for basket-vs-synthetic residual scans
  - `target` is the asset you want to explain
  - `components` is the synthetic fair proxy
  - the scanner computes:
    - `spread = target - synthetic`
    - spread stability / half-life
    - short-horizon lead-lag between target and synthetic
    - tail reversion on large spread z-scores
- `round3_propagation_relations.json`
  - for causal propagation scans
  - `series` defines raw or derived time series
  - `tests` asks whether moves in the leader series propagate into the follower series later
  - use this for:
    - constituent -> basket premium
    - underlying -> option residual
    - insider product -> related-product residual

For basket rounds, include:

- direct basket-vs-synthetic relations
- premium-difference relations if there are multiple baskets sharing constituents
- explicit propagation tests in both directions when you want to falsify the “constituents are exogenous” hypothesis
