# Round 3 Manual Solve From Scratch

This note derives the Round 3 Celestial Gardeners' Guild answer from the official mechanism only:

- [round3_info.md](/Users/sean_tsu_/Downloads/prosperity/IMCP2026/documents/round3_info.md)
- [round3_uplink_transcript.md](/Users/sean_tsu_/Downloads/prosperity/IMCP2026/documents/round3_uplink_transcript.md)
- optional market-color only from [round3_sentiment.md](/Users/sean_tsu_/Downloads/prosperity/IMCP2026/documents/round3_sentiment.md)

It does not rely on the existing `analysis/round3_manual` files.

## Mechanism

- Reserve prices are uniform on the `51`-point grid `{670, 675, ..., 920}`.
- Fills require strict `>` against reserve, so the cheapest way to clear reserve `750` is to bid `751`.
- If `b1 > reserve`, you buy at `b1` and earn `920 - b1`.
- Otherwise, if `b2 > reserve`, the second-bid profit is:
  - `920 - b2` when `b2 > avg_b2`
  - `(920 - b2) * ((920 - avg_b2) / (920 - b2))^3` when `b2 <= avg_b2`
- The penalty applies only to second-bid fills.

Because reserves live on a `5`-point grid, the only meaningful choice is how many reserve levels each bid clears.

If `k` reserve levels are captured, the cheapest integer bid is:

`bid(k) = 666 + 5k`

Examples:

- `k = 17 -> bid = 751`
- `k = 34 -> bid = 836`
- `k = 37 -> bid = 851`

## Low-Mean Optimum

If you can set `b2` at or above the eventual field mean, there is no penalty. Write:

- `k1 =` reserve levels cleared by `b1`
- `k2 =` reserve levels cleared by `b2`
- `b1 = 666 + 5k1`
- `b2 = 666 + 5k2`

Then expected profit per counterparty is:

`EV = [k1 * (254 - 5k1) + (k2 - k1) * (254 - 5k2)] / 51`

For fixed `k2`, the best split is `k1 ~= k2 / 2`, so the first bid should clear about half as many levels as the second bid. Substituting that back in gives an optimum at `k2 ~= 33.87`, hence `k2 = 34` and `k1 = 17`.

That yields the clean theoretical answer:

- `b1 = 751`
- `b2 = 836`

Expected profit per counterparty:

- `84.333333`

For reference, a first-bid-only strategy peaks at `791` or `796` with EV about `63.24`, so the second bid adds substantial value when the field mean is not too high.

## Self-Consistent Bid Levels

There is not a unique symmetric equilibrium. Because the penalty factor equals `1` when `b2 = avg_b2`, every self-consistent `b2` level on the right grid can support a symmetric solution. The best ones are:

| Mean `avg_b2` | Best pair(s) | EV per counterparty |
| --- | --- | --- |
| `836` | `(751, 836)` | `84.333333` |
| `841` | `(751, 841)` or `(756, 841)` | `84.215686` |
| `846` | `(756, 846)` | `84.000000` |
| `851` | `(756, 851)` or `(761, 851)` | `83.588235` |
| `856` | `(761, 856)` | `83.078431` |
| `861` | `(761, 861)` or `(766, 861)` | `82.372549` |
| `866` | `(766, 866)` | `81.568627` |

Higher coordinated second bids are still self-consistent, but they are strictly worse.

## Recommendation

Primary answer from first principles:

- submit `751`
- submit `836`

Reason: it is the highest-EV self-consistent solution and the exact optimum whenever the field mean second bid is at most about `836.1`.

If you believe the crowd will overshoot into the mid-`850`s, a hedge like `761 / 856` is defensible, but that is a crowd-timing adjustment, not the clean theoretical solve.

## Reproduce

Use [solve_biopods.py](/Users/sean_tsu_/Downloads/prosperity/IMCP2026/analysis/round3_manual_from_scratch/solve_biopods.py):

```bash
python3 IMCP2026/analysis/round3_manual_from_scratch/solve_biopods.py
python3 IMCP2026/analysis/round3_manual_from_scratch/solve_biopods.py --mean 851
```
