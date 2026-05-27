# Round 5 Manual - News Trading

## Recommendation

Submit the joint robust allocation:

| Product | Action | Allocation |
| --- | --- | ---: |
| Lava cake | SELL | 27% |
| Ashes of the Phoenix | SELL | 19% |
| Obsidian cutlery | SELL | 14% |
| Thermalite core | BUY | 14% |
| Pyroflex cells | SELL | 13% |
| Magma ink | BUY | 8% |
| Sulfur reactor | BUY | 5% |

Leave `Scoria paste` and `Volcanic incense` empty.

## Mechanics Verified

The live platform identifies the manual challenge as `NEWS_TRADING` and
accepts `NewsTradingRequest` orders with one integer `volume` percentage
per product. Total volume must be at most `100`.

The frontend fee formula is:

```text
investment = round(volume / 100 * 1,000,000)
fee = round(investment^2 / 1,000,000)
```

So a `p%` allocation only has positive expected value if the realized
absolute move is above `p%`.

## Reconciliation

Codex and Claude differed because the optimizer was the same but the
move priors differed:

- Codex's first pass sized directly from article strength and gave more
  weight to `Magma ink`, `Scoria paste`, `Volcanic incense`, and
  `Sulfur reactor`.
- Claude calibrated against Prosperity 3 news-trading archetypes, where
  launch/influencer headlines were often traps and serious safety/PR
  stories moved more.

The current recommendation maximizes the worse expected PnL across both
prior sets. It is effectively Claude's calibrated plan, with 1% shifted
from `Pyroflex cells` to `Magma ink`.

Expected PnL checks:

| Plan | Codex-aggressive priors | Claude-calibrated priors | Worst case |
| --- | ---: | ---: | ---: |
| Original Codex | 270,000 | 100,300 | 100,300 |
| Claude calibrated | 187,500 | 188,000 | 187,500 |
| Joint robust | 189,500 | 187,900 | 187,900 |

## News Read

- `Lava cake`: strongest short. Health authorities launched a review,
  actual lava was confirmed, and immediate sales were halted.
- `Magma ink`: long, but capped. It is the front-page feature, with long
  queues, a limited-edition launch, and merger attention; historical
  launch analogs argue against oversizing it.
- `Pyroflex cells`: short. The cell tax cut is abolished, effectively
  doubling the current levy and slowing upgrades.
- `Sulfur reactor`: small long. Index inclusion should force tracking-fund
  buying after the rebalance, but index-flow effects are usually smaller
  than direct demand or safety shocks.
- `Thermalite core`: long. The forecast points to sharp active-user and
  usage growth.
- `Scoria paste`: skip. The stockpiling call comes from a self-proclaimed
  market medium; this maps better to prior hype traps than to hard demand.
- `Volcanic incense`: skip. The article explicitly frames concentrated
  influencer buying after an extended rally.
- `Ashes of the Phoenix`: short. Public backlash against sourcing is a
  cleaner demand/PR shock than my first pass allowed.
- `Obsidian cutlery`: short. The production halt has some scarcity
  ambiguity, but the contamination and cross-facility warning justify a
  moderate short.
