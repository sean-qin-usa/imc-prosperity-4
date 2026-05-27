# Round 4 Recipe

## Current Ship File

`IMCP2026/traders/round4/current_strategy.py` is seeded from Round 3
`combined_ship_v31.py`.

The only active Round 4 logic change is:

- `TTE_DAYS_LIVE = 4.0`, matching the official Round 4 `VEV_5000`
  example.

No direct counterparty-follow logic is active in the ship file.

## Counterparty Result

The local scan in `IMCP2026/analysis/round4_counterparty_signal_report.md`
found that `Mark 67` buying `VELVETFRUIT_EXTRACT` has the cleanest
positive event-study edge. A direct follow overlay was tested and
rejected:

- TTE-only ship: `440,853`
- TTE + Mark 67 direct follow: `368,294`

Reason: the overlay fought the existing VFE mean-reversion sleeve and
reduced VFE PnL on all three supplied days.

## Local Backtest

Command:

```bash
PYTHONHASHSEED=0 python3 IMCP2026/tools/jmerle_backtester.py \
  IMCP2026/traders/round4/current_strategy.py \
  4 \
  --data IMCP2026/data \
  --no-out
```

Results:

| Day | PnL |
| --- | ---: |
| `4-1` | `175,226` |
| `4-2` | `184,649` |
| `4-3` | `80,978` |
| **Total** | **`440,853`** |

Residual risk:

- The backtester flags one correlated drawdown bucket on day 3,
  `400000-499999`, with about `-76k` PnL across `10/12` products.
- This is inherited from the Round 3 chassis and is not caused by the
  Round 4 TTE update.
