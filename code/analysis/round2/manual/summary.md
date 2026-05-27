# Round 2 Manual Challenge Direction

This report follows only:

- `IMCP2026/documents/round2_info.md`
- `IMCP2026/analysis/round2_manual/rank_bid_framework.md`

The deterministic layer comes from the Round 2 formula sheet. The game-theory layer follows the rank-bid framework's cluster-scan rule.

## Core findings

- If you spend **0% on Speed**, the best split is about **23.1% Research / 76.9% Scale**.
- If you spend **20% on Speed**, the best remaining split is about **19.2% Research / 60.8% Scale**.
- If you spend **30% on Speed**, the best remaining split is about **17.2% Research / 52.8% Scale**.
- The optimal Research/Scale split is stable: roughly **23% Research / 77% Scale of whatever budget remains after Speed**.
- Spending more on Speed lowers your deterministic Research x Scale engine, so Speed only makes sense if it materially improves your rank-based multiplier.

## Symmetric-equilibrium benchmark

- If every team solved `Speed` as a rank contest, the symmetric mixed-strategy support runs from about **0% Speed to 80% Speed**.
- In that benchmark, the **median** outcome is around **70% Speed**, with split **8 / 22 / 70** and multiplier about **0.506**.
- The pure-equilibrium benchmark makes the supported speeds almost **flat in expected value** at roughly **24,234 XIRECs**. That means the actionable edge comes from **cluster avoidance**, not from the deterministic frontier alone.

## Framework Cluster Scan

Following `rank_bid_framework.md`, the field model is split into:

- **dropouts / disengaged** at `0`
- **AI-default bidders** at the single-agent break-even answer
- **nice-number humans** at `(5, 10, 20, 25, 30, 40, 50, 100)`
- **meme / cultural focal points** at `(42, 69, 73)`
- **smooth contest-aware teams** distributed over the equilibrium support

Using only the deterministic frontier from `round2_info.md`, the **AI-default cluster** is taken to be **20% Speed**:

- it is the obvious round-number "balanced" answer
- it keeps most of the `Research x Scale` engine
- from the zero-speed floor case (`m = 0.1`), it only needs about **0.134** to beat `0% Speed`

Under the framework, that contaminates `20` itself. The cheapest rank-arbitrage move is therefore **just past 20**, i.e. `21`.

## Sensitivity Check

Per the framework, I ran three plausible field priors:

- `mostly_nash`
- `heavy_round_numbers`
- `bimodal_dropout_sim`

All three scenarios pick the same best response:

- **Recommended:** **19 / 60 / 21**
- Worst-case regret across the three priors: **0**
- Average regret across the three priors: **0**

Scenario table:

| Scenario | Best split | Achieved m | Expected PnL |
| --- | --- | --- | --- |
| `mostly_nash` | 19 / 60 / 21 | 0.326 | 127,762 |
| `heavy_round_numbers` | 19 / 60 / 21 | 0.404 | 170,289 |
| `bimodal_dropout_sim` | 19 / 60 / 21 | 0.428 | 183,104 |

## Practical Direction

- **Do not submit `19 / 61 / 20`.** The framework marks `20` as the contaminated AI-default cluster.
- **Submit `19 / 60 / 21`.** This is the clean "just past the herd" bid that also survives the 3-prior sensitivity check.
- If you believe the field has already migrated upward and `25` is now the crowded focal point, the next clean jump is **18 / 56 / 26**.
- If you think serious teams will crowd `30`, the next clean jump is **17 / 52 / 31**.

## Robust Candidates

| Research / Scale / Speed | Worst-case regret | Average regret |
| --- | --- | --- |
| 19 / 60 / 21 | 0 | 0 |
| 19 / 59 / 22 | 3,271 | 2,893 |
| 19 / 58 / 23 | 6,531 | 5,776 |
| 18 / 58 / 24 | 9,780 | 8,650 |
| 18 / 57 / 25 | 10,472 | 6,846 |
| 18 / 56 / 26 | 11,242 | 5,197 |

## Useful thresholds

- `0% Speed` product capacity: **742,336**
- `20% Speed` product capacity: **554,360**
- `30% Speed` product capacity: **464,718**
- `50% Speed` product capacity: **296,207**

- To justify **20% Speed** instead of **0% Speed**:
  - if `0% Speed` would only get you multiplier `0.1`, you need about **0.134**
  - if `0% Speed` would get you `0.3`, you need about **0.402**
- To justify **30% Speed** instead of **0% Speed**:
  - from baseline `0.1`, you need about **0.160**
  - from baseline `0.3`, you need about **0.479**
- To justify **50% Speed** instead of **0% Speed**:
  - from baseline `0.1`, you need about **0.251**
  - from baseline `0.3`, you need about **0.752**

## Direction

- **Framework-only re-do:** submit **19 / 60 / 21**.
- **If you need the next cluster-jump:** use **18 / 56 / 26** or **17 / 52 / 31**.
- The framework result is about **rank positioning**, not about maximizing a deterministic break-even table entry.

## Candidate Table

Screen order: `Research / Scale / Speed`

| Research | Scale | Speed | Break-even m | PnL @ 0.10 | PnL @ 0.20 | PnL @ 0.30 | PnL @ 0.40 | PnL @ 0.50 | PnL @ 0.55 | PnL @ 0.60 | PnL @ 0.70 | PnL @ 0.80 | PnL @ 0.90 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 23 | 77 | 0 | 0.067 | 24,234 | 98,467 | 172,701 | 246,934 | 321,168 | 358,285 | 395,401 | 469,635 | 543,869 | 618,102 |
| 21 | 69 | 10 | 0.077 | 14,701 | 79,401 | 144,102 | 208,802 | 273,503 | 305,853 | 338,203 | 402,904 | 467,604 | 532,305 |
| 20 | 65 | 15 | 0.083 | 10,033 | 70,066 | 130,099 | 190,132 | 250,164 | 280,181 | 310,197 | 370,230 | 430,263 | 490,296 |
| 20 | 62 | 18 | 0.087 | 7,266 | 64,532 | 121,798 | 179,064 | 236,330 | 264,963 | 293,596 | 350,862 | 408,128 | 465,394 |
| 19 | 62 | 19 | 0.089 | 6,349 | 62,699 | 119,048 | 175,398 | 231,747 | 259,922 | 288,097 | 344,446 | 400,796 | 457,145 |
| 19 | 61 | 20 | 0.090 | 5,436 | 60,872 | 116,308 | 171,744 | 227,180 | 254,898 | 282,616 | 338,052 | 393,488 | 448,924 |
| 19 | 60 | 21 | 0.092 | 4,525 | 59,051 | 113,576 | 168,102 | 222,627 | 249,890 | 277,153 | 331,678 | 386,204 | 440,729 |
| 19 | 59 | 22 | 0.093 | 3,618 | 57,236 | 110,854 | 164,472 | 218,090 | 244,899 | 271,708 | 325,326 | 378,944 | 432,562 |
| 19 | 58 | 23 | 0.095 | 2,714 | 55,427 | 108,141 | 160,854 | 213,568 | 239,924 | 266,281 | 318,995 | 371,708 | 424,422 |
| 18 | 57 | 25 | 0.098 | 914 | 51,828 | 102,742 | 153,656 | 204,570 | 230,027 | 255,484 | 306,398 | 357,312 | 408,226 |
| 18 | 55 | 27 | 0.102 | -873 | 48,255 | 97,382 | 146,509 | 195,637 | 220,200 | 244,764 | 293,891 | 343,018 | 392,146 |
| 17 | 53 | 30 | 0.108 | -3,528 | 42,944 | 89,415 | 135,887 | 182,359 | 205,595 | 228,831 | 275,303 | 321,775 | 368,246 |
| 16 | 49 | 35 | 0.119 | -7,885 | 34,229 | 76,344 | 118,459 | 160,573 | 181,631 | 202,688 | 244,803 | 286,917 | 329,032 |
| 15 | 45 | 40 | 0.132 | -12,151 | 25,698 | 63,546 | 101,395 | 139,244 | 158,168 | 177,093 | 214,941 | 252,790 | 290,639 |
| 13 | 37 | 50 | 0.169 | -20,379 | 9,241 | 38,862 | 68,483 | 98,104 | 112,914 | 127,724 | 157,345 | 186,966 | 216,586 |

## Files

- `frontier.csv`: full optimal frontier by Speed budget
- `key_points.csv`: expanded scenario table with many `PnL @ m=` columns
- `game_theory_table.csv`: integer-speed grid with equilibrium and framework-scenario overlays
- `optimal_split_vs_speed_budget.png`
- `product_and_pnl_vs_speed_budget.png`
- `required_speed_multiplier_vs_speed_budget.png`
- `pnl_surface.png`
- `candidate_pnl_heatmap.png`
