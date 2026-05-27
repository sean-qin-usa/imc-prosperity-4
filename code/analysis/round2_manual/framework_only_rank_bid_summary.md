# Round 2 Manual — Rank-Bid Framework Only

**Source constraint:** this note uses only
`IMCP2026/analysis/round2_manual/rank_bid_framework.md`.

That framework is enough to choose the **rank-contest leg** (`Speed`),
but it is **not** enough to derive a unique full `Research / Scale / Speed`
allocation, because it does not contain the underlying deterministic payout
formula.

## What The Framework Says

The framework gives one invariant:

- **Do not submit the break-even / AI-default answer.**
- **Bid just past the last herd that is not you.**

It also says to expect clusters at:

- `0`
- round numbers like `5, 10, 20, 25, 30, 40, 50, 100`
- meme numbers like `42, 69, 73`
- whatever a mainstream LLM or simple break-even solver converges to

## Framework-Only Read

Without using any round-specific payoff math, the most plausible crowded
"default serious answer" bucket is the **balanced round number zone**:

- first candidate cluster: `20`
- next candidate cluster: `25`
- next candidate cluster: `30`

Applying the framework literally:

- if the herd is at `20`, submit **`21`**
- if the herd has already migrated to `25`, submit **`26`**
- if the serious-teams herd is at `30`, submit **`31`**

## Monte Carlo Correction

I subsequently ran an actual **framework-only Monte Carlo** on the **rank
leg alone**:

- opponent field sampled from the framework mixture components
- three priors:
  - `mostly_nash`
  - `heavy_round_numbers`
  - `bimodal_dropout_sim`
- compared candidate clean jump points `20, 21, 25, 26, 30, 31`

What that Monte Carlo shows:

- `21` clearly beats `20` on expected percentile because it escapes the
  contaminated cluster
- but `26` also beats `21`
- and `31` also beats `26`

So, using **`rank_bid_framework.md` only**, there is **no unique optimal
Speed number**. The framework identifies the **clean jump points**, but
choosing between them requires the deterministic payoff curve that lives
outside the framework file.

## Recommendation

The honest framework-only answer is therefore:

- **primary clean jump:** `21`
- **next clean jumps:** `26`, then `31`

This is a **ladder**, not a fully solved optimum.

## Fallback Ladder

Use this only if you believe the crowding has shifted upward:

| Suspected crowded cluster | Framework move |
| --- | --- |
| `20` | **`21`** |
| `25` | **`26`** |
| `30` | **`31`** |

## What To Avoid

Framework-only, I would avoid submitting these exact `Speed` values unless
you have a very specific reason:

- `20`
- `25`
- `30`
- `40`
- `50`
- `42`
- `69`
- `73`

## Bottom Line

- **Framework-only result:** the clean jump ladder is `21 -> 26 -> 31`
- **What the framework alone cannot do:** choose uniquely among those
- **What this note does not claim:** a full `Research / Scale / Speed` split
