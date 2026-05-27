# Round 2 Fresh — clean-rebuild experiments

These are **research artifacts**, not the shipped R2 strategy. The shipped R2 strategy lives in [`../round2/final_strat.py`](../round2/final_strat.py).

## Why this folder exists

After R1 closed and before R2 opened, I rebuilt the R1 → R2 strategy from scratch as an exercise — to confirm I could derive the same recipe ([ROUND2_RECIPE.md](../round2/ROUND2_RECIPE.md)) from the data alone, without leaning on the inherited code from the tutorial wrapper. The exercise re-derived the same conclusions:

- ACO is a clipped-anchor MM at 10,000.
- IPR's +0.001/ts drift is a mechanical carry, not a forecast.
- L1 imbalance is non-predictive at typical spread on ACO — spread-gate it.
- MM sizes should be large (~75) at the plateau, not the naive 20.

The strategies here aren't worse than the shipped one — they're slightly differently tuned (somewhat closer to the "from-scratch optimal" before I layered in the R1 microstructure improvements). They're preserved so that a reader can compare the from-scratch rebuild against the ladder-derived ship and see the convergence.

## Files

- **[`fresh_from_scratch.py`](./fresh_from_scratch.py)** — initial clean rebuild from the round-2 info doc.
- **[`fresh_from_scratch_v2.py`](./fresh_from_scratch_v2.py)** — + walked-spread rebound capture.
- **[`fresh_from_scratch_v3.py`](./fresh_from_scratch_v3.py)** — + ACO EOD unwind. The closest of these to the shipped R2 strategy.
- **[`fresh_r1_from_recipe.py`](./fresh_r1_from_recipe.py)** — R1 strategy rebuilt purely from the R1 recipe document, no inherited code.
- **[`R1_RECIPE_NOTE.md`](./R1_RECIPE_NOTE.md)** — notes on the R1 recipe used as the rebuild reference.
- **[`v1.py`](./v1.py), [`v2.py`](./v2.py)** — early-iteration drafts of the rebuild.

If you want to read the shipped R2 strategy, open [`../round2/`](../round2/), not this folder.
