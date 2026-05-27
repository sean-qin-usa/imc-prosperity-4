# Round 2 - “Growing Your Outpost”

Round 2 is the second and final trading round on Intara, and the last opportunity to finish the Intara mission above the `200,000 XIRECs` net PnL threshold.

In Round 2 you continue trading the same two products from Round 1:

- `ASH_COATED_OSMIUM`
- `INTARIAN_PEPPER_ROOT`

The main structural change is that teams can now submit a **Market Access Fee (MAF)** bid to compete for access to **25% more quotes** in the order book. The manual challenge also changes completely: instead of a static auction, you allocate a `50,000 XIRECs` budget across `Research`, `Scale`, and `Speed`.

## Sources

This page consolidates information from:

- the Prosperity wiki / Notion materials mirrored in this repo
- the Round 2 A.R.I.A. uplink transcript provided by the user
- the official Prosperity site content visible in the user-provided screenshot
- public operational docs already mirrored locally, including the round schedule, FAQ, rules, and Python submission docs

Direct automated access to the authenticated `prosperity.imc.com/game` Round 2 pages was not available from the local environment because the available browser profile no longer had valid logged-in credentials. Official-site notes here therefore come from the screenshot, the uplink content, and the mirrored public docs rather than a full live scrape of the in-game UI.

Where a point below is an inference rather than an explicit statement from the source materials, it is labeled as such.

## Round framing

- Round 2 opens on **Friday, April 17, 2026 at 12:00 CEST (UTC+2:00)**.
- Round 2 closes on **Monday, April 20, 2026 at 12:00 CEST (UTC+2:00)**.
- The official schedule notes that this window includes a roughly **3 hour score-calculation period** immediately after Round 1 closes, during which Round 2 may not yet be accessible.
- The storyline and uplink both frame Round 2 as the **final Intara round** and the last chance to clear the mission threshold.

## What carries over from Round 1

- The tradable products remain `ASH_COATED_OSMIUM` and `INTARIAN_PEPPER_ROOT`.
- The position limits remain:
  - `ASH_COATED_OSMIUM`: `80`
  - `INTARIAN_PEPPER_ROOT`: `80`
- You should still refine the Round 1 strategy using the newly disclosed results, leaderboard position, and any downloadable Round 1 result files.

## New algorithmic challenge: “limited Market Access”

The Round 2 algorithmic challenge keeps the same two products but introduces a competition for additional order-book access.

### Core mechanic

- You may define a `bid()` method on `class Trader`.
- The value returned by `bid()` is your team’s **Market Access Fee** bid.
- At the end of the round, only the **top 50% of bids** receive the extra access contract.
- Accepted teams pay their own bid as a **one-time fee**.
- Rejected teams pay nothing.

Example shape:

```python
class Trader:
    def bid(self):
        return 15

    def run(self, state: TradingState):
        ...
```

### What extra access gives you

- Accepted bids unlock **25% more quotes in the order book**.
- These extra quotes are described as fitting naturally inside the same distribution as the already visible market quotes.
- The official explanation implies the added flow is not a separate synthetic market regime; it is additional volume inserted into the same market structure.

### Profit calculation

- If your MAF bid is accepted:
  - `round_2_profit = trading_profit - bid`
- If your MAF bid is rejected:
  - `round_2_profit = trading_profit`

The fee only matters for deciding access and for the final deduction. It does **not** directly alter the matching logic or exchange mechanics during simulation.

### Blind-auction implications

- This is effectively a **blind auction**: you do not see other teams’ bids during the round.
- You only need to finish in the **top 50%**, not necessarily bid the maximum.
- That makes Round 2 partly a game-theory problem, not just a market-making problem.

### Important testing caveats

- During local / public testing, the `bid()` value is **ignored**.
- During testing, the default view is the **base quote set only**, described as roughly `80%` of all generated quotes.
- The source materials state that this visible subset is **slightly randomized for every submission**.
- Teams without full market access do not necessarily miss the exact same quotes every time; the omitted subset can vary across submissions.
- Teams with accepted MAFs get the **full quote set** in the final round processing.

Practical consequence: local testing can help with the base strategy, but it cannot directly tell you whether a specific MAF bid wins or whether the extra 25% access is worth the final fee.

## Python submission details that matter in Round 2

- Round 2 is the only round where `Trader.bid()` matters.
- The official Python guide explicitly says it is safe to leave a `bid()` method in every submission:
  - it is used in Round 2
  - it is ignored in the other rounds
- The algorithm format still revolves around the `Trader.run()` method, the `TradingState` input, and the final active upload in the UI.
- If a last-minute upload is not marked `active` before the round closes, the previously active file remains the one that counts.

## Official-site workflow notes

The official site / uplink materials add a few operational details that are easy to miss if you focus only on the challenge formulas:

- While Round 2 is open, you can still navigate back to **Round 1** from the top menu.
- The Round 1 results view includes:
  - an earnings breakdown
  - badges earned
  - a downloadable results file
- After Round 1 processing, the **leaderboard** reflects your Round 1 performance.
- The Round 2 Algorithmic Challenge page includes:
  - a brief describing the MAF mechanic
  - an **Algorithm Status** panel
  - a **Recent Upload** field
  - a **Data Capsule** for historical `ASH_COATED_OSMIUM` / `INTARIAN_PEPPER_ROOT` data
- The Upload & Log flow from earlier rounds still matters: multiple uploads are allowed, but only the final active one at the deadline counts.

## Manual challenge: “Invest & Expand”

The Round 2 manual challenge is no longer an auction. Instead, you allocate a fixed growth budget across three pillars:

- `Research`
- `Scale`
- `Speed`

You choose percentages between `0` and `100` for each pillar, and the total cannot exceed `100`.

### Manual-challenge score

The manual challenge score is:

`PnL = (Research x Scale x Speed) - Budget_Used`

### Pillar definitions

#### Research

- Research represents your trading edge.
- It scales **logarithmically** from `0` to `200,000`.
- Exact formula:

```python
research(x) = 200_000 * np.log(1 + x) / np.log(1 + 100)
```

#### Scale

- Scale represents how broadly your strategy is deployed.
- It scales **linearly** from `0` to `7` as investment goes from `0` to `100`.

#### Speed

- Speed is **rank-based across all players**, not an absolute deterministic function of your own investment alone.
- Highest speed investment gets a `0.9` multiplier.
- Lowest speed investment gets a `0.1` multiplier.
- Everyone else is placed linearly between those endpoints by rank.
- Equal investments share the same rank.

This means the Speed leg is partly a coordination / meta-game problem, similar in spirit to the MAF auction on the algorithmic side.

### Budget-used interpretation

The official description gives a `50,000 XIRECs` budget and asks for percentage allocations. A reasonable inference is:

- if you allocate a total of `T%`, then `Budget_Used = 50,000 * T / 100`
- equivalently, `Budget_Used = 500 * T`

This is an inference from the percentage-based formulation of the challenge, not a separate formula stated verbatim in the mirrored docs.

### Manual-site workflow notes

From the uplink:

- you enter the percentage allocations directly in the **Manual Challenge Overview** window
- you can resubmit as many times as needed before the round ends
- the **last submitted** allocation is the one that gets locked in
- the interface provides immediate feedback for the deterministic parts of the problem, especially `Research` and `Scale`

## Strategy-relevant operational takeaways

- Round 2 has **two separate auction problems** layered on top of the market strategy:
  - the algorithmic `bid()` for extra market access
  - the manual `Speed` allocation, which is rank-based relative to other teams
- The market data itself is still only for `ASH_COATED_OSMIUM` and `INTARIAN_PEPPER_ROOT`, so most Round 1 modeling work can carry forward.
- The new work is deciding:
  - how much extra order-book access is worth in expectation
  - whether your base strategy is robust to missing some quotes
  - how aggressive to be in the manual challenge when one pillar (`Speed`) depends on everyone else

## Operational checklist

- Review the Round 1 results page and download the results bundle if useful.
- Re-run analysis on the Round 2 data capsule for `ASH_COATED_OSMIUM` and `INTARIAN_PEPPER_ROOT`.
- Add or confirm a `bid()` method in the submitted `Trader`.
- Treat MAF calibration as a blind-auction problem, not just a market-simulation problem.
- Confirm the intended file is marked `active` before the deadline.
- Submit and re-check the manual `Research / Scale / Speed` allocation before Round 2 closes.
