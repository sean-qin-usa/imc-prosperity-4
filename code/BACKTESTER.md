# Prosperity Backtester — Setup

## Environment

| Tool   | Version |
|--------|---------|
| Python | 3.12.3  |
| pip    | 24.0    |

## Quickstart

```bash
# 1. Clone / download the project
cd prosperity_backtester

# 2. Create a virtual environment (recommended)
python3.12 -m venv .venv
source .venv/bin/activate        # Mac/Linux
# .venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run (uses synthetic data if no CSV present)
python main.py
```

## Using real Prosperity data

1. Download your round's CSV log from the Prosperity dashboard
2. Place it in this directory
3. Update `CSV_PATH` in `main.py` to match the filename

Expected CSV columns:
```
timestamp, product, bid_price_1, bid_volume_1, ask_price_1, ask_volume_1,
bid_price_2, bid_volume_2, ask_price_2, ask_volume_2,
bid_price_3, bid_volume_3, ask_price_3, ask_volume_3, mid_price
```

## Jmerle-Style Backtester

There is also a separate CLI at `tools/jmerle_backtester.py` for a simpler same-timestamp matcher modeled on the public [`jmerle/imc-prosperity-3-backtester`](https://github.com/jmerle/imc-prosperity-3-backtester).

Examples:

```bash
# One day
python IMCP2026/tools/jmerle_backtester.py IMCP2026/traders/round1/current_strategy.py 1-0

# All days in round 1, merged into one official-style log
python IMCP2026/tools/jmerle_backtester.py IMCP2026/traders/round1/current_strategy.py 1 --merge-pnl

# Use the local round data root explicitly and avoid writing a log file
python IMCP2026/tools/jmerle_backtester.py \
  IMCP2026/traders/round1/kalman_benchmark.py \
  1-0 \
  --data IMCP2026/data \
  --no-out
```

Use `tools/backtester.py` when you want the richer research harness with alternative fill models, CSV summaries, and plots. Use `tools/jmerle_backtester.py` when you want the simpler reference-style same-tick output format.

## Project structure

```
prosperity_backtester/
├── main.py                        # Entry point — runs all 4 steps
├── engine.py                      # Tick replay, order matching, metrics
├── optimizer.py                   # GridSearch + GradientOptimizer
├── prosperity_types.py            # TradingState, OrderDepth, Order (mirrors competition API)
├── strategies/
│   ├── base.py                    # Strategy ABC
│   └── implementations.py        # MarketMaking, MeanReversion, StatArb, IndexArb
├── utils/
│   └── indicators.py              # EMA, KalmanFilter, RollingStats, SpreadZScore
├── requirements.txt
├── .python-version                # For pyenv
└── README.md
```
