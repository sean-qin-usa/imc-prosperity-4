# Round 2 Manual "Invest & Expand" — POSTMORTEM

## ANSWER (submit this if re-solving Round 2)

- **Optimal pick: `R=15, S=43, V=42`** (or continuous `14.7 / 43.3 / 42`)
- **Safer fallback: `R=23, S=77, V=0`** — only if already above 200k qualification threshold and you want a guaranteed floor (~+24k worst case, ~+321k at μ=0.5)
- **Do NOT submit V=15–25 range.** That's the AI-default trap (see `rank_bid_framework.md` next to this file). Around 6–8% of the 22,200-team field landed there because LLMs converge on it from break-even math. Being tied with them destroys the rank you paid for.

Expected PnL at 15/43/42: ~225k. Expected PnL at the AI-default 20/65/15: ~90k. Expected PnL at 23/77/0: ~45k at worst (μ=0.13, tied with the dropout pile), ~321k if ties resolve to midpoint μ=0.5.

If re-solving a *similar* problem in a later round (post-filter), remember: V=42 itself becomes the crowded bid next time — shift to V=44–46 or consider an under-crowded zone like V=30–35.

---

## Problem
Round 2 manual "Invest & Expand": allocate percentages R + S + V ≤ 100 (Research / Scale / Speed). PnL = Research(R) · Scale(S) · Speed(V) − 500(R+S+V). Speed multiplier is rank-based across all players, 0.1 (lowest V) to 0.9 (highest V).

## Field size
- Total Round 2 field: **~22,200 teams**
- Qualified past the 200k threshold for Round 3: **~4,050 teams (18.2%)**
- Elimination was primarily on trading PnL, not manual PnL — manual strategy choice is only weakly correlated with survival

## Field distribution (observed, 2026-04-22, histogram)
Shape percentages (bar heights scaled to ~22.2k total):
- V=0: huge spike, ~1,500 teams (dropouts + bank-the-floor players)
- Nice-number spikes at V = 5, 10, 15, 20, 25, 30, 40
- V=20 was anomalously large (~970 teams) — likely AI-default contamination
- Secondary mode V=35–45, peak ~V=37–40 (V=40 spike ~780 teams)
- Tail dies off fast past V=50
- Mean ≈ 26.6, median ≈ 27, mode = 0
(My earlier histogram-read had total ~6k; the shape and ratios were right but absolute counts were ~3.5x too low. Rank-percentile analysis is unaffected.)

## Default AI answer (first-pass from Claude, ChatGPT Pro, likely Gemini)
- "Balanced / aggressive hedge": V=15–22, typically R=19-20, S=61-65, V=20
- Comes from break-even math: required μ vs. deterministic-optimum V=0 path
- Wrong because it doesn't model field clustering

## Actual optimum
- V=41–43 (plateau, 42 is the midpoint / representative cite)
- Optimal R,S at V=42: R ≈ 14.7, S ≈ 43.3
- One step past the V=37–40 simulator cluster, before product decay dominates

## Safer-play fallback
- 23 / 77 / 0 — accepts the rank floor, banks the full deterministic product (742,336). Floor PnL ≈ 24k at μ=0.13, ~321k at μ=0.5. This is what "L" ultimately did on Discord despite simulating the 41–43 optimum, because they were already at 182k and wanted a guarantee.

## Cluster breakdown (rescaled to 22.2k field)
| Cluster | Estimated size | Share | Driver |
|---------|----------------|-------|--------|
| Dropouts at V=0 | ~1,000 | 4.5% | Disengaged / didn't submit / auto-zero |
| Rational floor at V=0 | ~500 | 2.3% | "Bank the guarantee" reasoning |
| AI-default at V=15–22 | ~1,500 | 6.7% | LLM break-even recommendations |
| Nice-number humans | ~4,000 | 18% | Anchors at 10, 20, 25, 30, 40, 50 |
| Simulator cluster V=37–45 | ~3,000 | 13.5% | Monte Carlo converges here |
| Mid-range guessers V=5–35 | ~10,000 | 45% | Smooth dist fill-in |
| Tail V>50 | ~1,500 | 6.8% | Over-aggressive / long-shot |
| Very high V>80 | ~300 | 1.4% | Trolls / nothing-to-lose |

## Implications for Round 3+ (filtered field of ~4,050)
- The filter is on **trading PnL**, not manual strategy. So manual-strategy sophistication survives roughly proportionally, except:
  - V=0 dropouts are disproportionately eliminated (they're often also dropouts at trading) — dropout cluster shrinks ~3–4x
  - "Did the work" simulator cluster survives disproportionately — it grows in share
  - Nice-number humans are weakly filtered (correlated with unsophisticated trading) — shrinks ~2x in share
- Expected Round 3+ post-filter cluster shares:
  - V=0 pile: drops from ~7% to ~2–3%
  - AI-default V=20 cluster: ~6–8% (AI use is skill-uncorrelated)
  - Nice-number clusters: ~10% combined
  - Simulator cluster: grows from 13% to ~25–30%
  - Remaining 50–60%: "did some thinking" mid-range bidders
- The Round 3 simulator cluster will have absorbed the Round 2 lesson → it now centers on V=41–43 itself, not V=37–40. This means **V=42 becomes the crowded bid in any post-R2 similar problem**. Winning move shifts to "one step past the new R3 cluster" = V=44–46, or the under-crowded zone ~V=30–35 if all sophisticates moved up together.

## Files in repo
- [IMCP2026/analysis/round2_manual/summary.md](../../../../Downloads/prosperity/IMCP2026/analysis/round2_manual/summary.md) — deterministic frontier
- [IMCP2026/analysis/round2_manual/frontier.csv](../../../../Downloads/prosperity/IMCP2026/analysis/round2_manual/frontier.csv) — full optimal R,S by V
- [IMCP2026/documents/round2_info.md](../../../../Downloads/prosperity/IMCP2026/documents/round2_info.md) — problem statement
