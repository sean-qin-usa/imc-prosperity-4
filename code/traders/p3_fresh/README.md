# P3 Fresh — Prior-year (Prosperity 3) reference port

Used as **scaffolding** for the R3 voucher-chain work. Structurally, IMC Prosperity 4 Round 3 is the same problem as Prosperity 3 Round 3 — one delta-1 underlying + a voucher chain. The structural code (Black-Scholes theo, IV-EMA tracking, ATM mean-reversion, ITM synth-MM) is transferable. **The fitted numeric values are not** — smile coefficients, thresholds, and EMA windows have to be refit on the P4 data.

For the explicit mapping from P3 R3 code → P4 R3 code, see [`../round3/P3R3_TRANSFER_NOTE.md`](../round3/P3R3_TRANSFER_NOTE.md).

## Files

- **[`p3_combined_v1.py`](./p3_combined_v1.py)** — the full P3-style multi-sleeve strategy. Contains the BS-theo + IV-EMA + ITM-MR machinery that was lifted into the P4 R3 ladder.
- **[`p3r2_fresh.py`](./p3r2_fresh.py) … [`p3r2_fresh_v5.py`](./p3r2_fresh_v5.py)** — P3 Round 2-style fresh rebuilds, used for technique practice before the P4 R3 work began.
- **[`P3R2_RECIPE.md`](./P3R2_RECIPE.md)** — recipe for the P3 R2 problem.
- **[`P3_COMPLETE_RECIPE.md`](./P3_COMPLETE_RECIPE.md)** — full P3 retrospective notes used as a heads-up before P4 opened.
- **[`RESEARCH_LOG.md`](./RESEARCH_LOG.md)** — log of the P3 rebuild work, dated before P4's start.
- **[`datamodel.py`](./datamodel.py)** — copy of the competition's `Order`/`OrderDepth`/`TradingState` data model, used as a local stub.

## Why this folder exists

P3 R3 was the publicly-published prior year. Writeups and code from top P3 teams (notably Timo Diehm's solution) were studied before P4 opened to build intuition on the option-chain structure. This folder is the cleaned-up port of that prior-year work — useful as a reference but **not used directly** in any shipped P4 strategy. The actual P4 R3 ship pulls *patterns* from here and refits the numbers.
