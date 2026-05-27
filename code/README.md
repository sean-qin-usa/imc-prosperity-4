# Code snapshot — IMC Prosperity 4

This is the working-repo state at the end of round 5. The narrative writeup lives at the [repo root](../README.md); this directory is the raw research and trading code.

## Layout

```
code/
├── SIGNALS_PLAYBOOK.md   ← cross-round signal-hunting checklist
├── BACKTESTER.md         ← how to run the local backtester
├── traders/              ← per-round trading strategies (one folder per round)
├── analysis/             ← signal scans, manual-challenge work, visualizer reports
├── tools/                ← backtesters, calibration scripts, run analyzers
└── documents/            ← competition info pages and uplink transcripts
```

## Where to start

- **Picking a round's shipped strategy** — open [`traders/round<N>/README.md`](./traders/). Each one names the shipped file, explains the variant zoo, and links to the recipe.
- **Cross-round signal-hunting framework** — [`SIGNALS_PLAYBOOK.md`](./SIGNALS_PLAYBOOK.md). The §0 generative-process hypothesis step that drove every round.
- **Running the backtester locally** — [`BACKTESTER.md`](./BACKTESTER.md) and the `tools/` scripts.
- **Manual-challenge analyses** — [`analysis/round<N>/manual/`](./analysis/) for each round that had one.

## Notes on the file zoo

You'll see a lot of variants in each `traders/round<N>/` folder — `*_v1.py`, `*_v2.py`, `*_aco_*`, `*_pepper_*`, `*__best_locked.py`, etc. Those are the **experimentation ladder**, not production code. The shipped file for each round is called out in the round's README and re-listed in the top-level [`submissions/`](../submissions/) folder. The variants are preserved (not pruned) because the *progression* — what changed at each step and which deltas survived — is itself the research record.
