# Trader utilities

Shared scaffolding used across rounds.

## Files

- **[`nothing_trader.py`](./nothing_trader.py)** — A no-op `Trader` class that submits zero orders. Useful as a baseline for replay comparisons — when you want to know what the market does in the absence of your strategy, run this in the backtester and inspect the fill log.
