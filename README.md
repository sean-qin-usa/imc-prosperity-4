# IMC Prosperity 4 — Writeup

This is the writeup of my IMC Prosperity 4 entry (2026 edition, run April 14–30, 2026), competed solo from day one. The repo covers what I built, what worked, what didn't, and what I'd do differently. Source code lives in [code/](./code) (a snapshot of my working repo); the per-round writeups in this folder cover the reasoning. The piece I'm proudest of is the round-3 manual challenge — the Bio-Pod bid finished world #7. Writeup in [round_3.md](./round_3.md) and [context.md](./context.md).

## Start here

| If you want… | Go to |
|---|---|
| The actual files I submitted, one per round | [`submissions/`](./submissions/) |
| What I built and why, round by round | [`round_1.md`](./round_1.md) → [`round_5.md`](./round_5.md) |
| Background, limiting factors, thoughts | [`context.md`](./context.md) |
| What I'd change for the next competition | [`lessons_learned.md`](./lessons_learned.md) |
| The full code snapshot (raw working repo) | [`code/`](./code/) |

## Quick links

- **[Final submissions per round](./submissions/)** — the exact algorithm file shipped each round, with one-line summaries
- [Round 1 — Tutorial-class MM + intraday path anchor](./round_1.md)
- [Round 2 — Drift-carry, MAF auction, manual budget split](./round_2.md)
- [Round 3 — HYDROGEL anchor MM + VEV voucher chain](./round_3.md)
- [Round 4 — Counterparty signals layered on the R3 chassis](./round_4.md)
- [Round 5 — 50-product sentiment-directional + news manual](./round_5.md)
- [Lessons learned](./lessons_learned.md)
- [Context](./context.md)

## Headline approach

I treated every round as a generative-process problem from first principles, not a tuning exercise. Before hunting for any signal, I'd force myself to answer one question: *how could the simulator have produced this product's time series?* The shortlist of possible stories — stationary anchor, linear drift, random walk, mean-reverting spread, deterministic function of a driver, simulated bot, external driver plus noise — tells you what features matter and which strategies are even valid. Most of my big wins came from getting that question right. Most of my big losses came from skipping it.

The biggest miss in that pattern: I knew the contest charged zero transaction fees, but I never stress-tested what that implied for sizing. My MM defaults — wider passive offsets, more conservative inventory skew, smaller post sizes — were carried over implicitly from real-world quant work where every fill costs you the rebate-adjusted bid-ask. Under zero fees those defaults are too tight; the optimal MM is narrower in spread, higher in volume, more aggressive. That single un-audited assumption is what most hurt my final result. I'm proud of how I performed overall, but it's the one I think about most.

A meta-game point that compounds the same effect, and that I want to call out explicitly: **the contest is designed to recruit market makers, not arb traders.** IMC is a market-making firm — Prosperity is their recruiting funnel for that archetype specifically, and the seed selection bears it out. Rounds 0–2 ran higher-volatility regimes (which is where arb-style sleeves like mine generate edge); rounds 3–5 shifted to lower-volatility seeds (where tight high-volume MM dominates and arb gets ground down by execution noise on thin moves). I assumed the early-round pattern would continue, since higher-vol seeds differentiate candidates more on signal quality. The shift to low vol in the final rounds is a deliberate archetype filter, not round-to-round noise. I should have read it as the contest telling me to pivot to a tighter MM stance by round 3. To be clear: yes, I could have audited that assumption — but "what archetype is this contest selecting for, and what is the seed mix telling me about that" is a meta-game read, not a trading skill. Drawing that distinction *is* part of the lesson.

The full framework, including the cross-round signal-hunting checklist, is in [SIGNALS_PLAYBOOK.md](./code/SIGNALS_PLAYBOOK.md).

## What this writeup is and isn't

This is a record of my own work, with the real backtest numbers, the real ship files, and the real mistakes. Where another team's writeup shaped what I tried, I cite it as theirs (see [lessons_learned.md](./lessons_learned.md) for those comparisons).

I'm not claiming this was the cleanest run. I didn't win, and the [context page](./context.md) and [lessons-learned page](./lessons_learned.md) explain what I'd change. But I'm proud of what I built and excited to do more.

## Repo layout

```
.
├── README.md                 ← you are here
├── round_1.md ... round_5.md ← per-round writeups (reasoning, results, what I'd change)
├── lessons_learned.md        ← what I'd take into Prosperity 5
├── context.md                ← finals overlap, solo-from-day-one, what I'm proud of
├── submissions/              ← the exact algorithm file shipped each round
│   ├── README.md             ← per-round summary table with results & manual submissions
│   └── round_1__*.py … round_5__*.py
└── code/                     ← snapshot of the working repo
    ├── traders/              ← per-round strategy files (full ablation ladder)
    ├── analysis/             ← signal scans, manual-challenge work
    ├── tools/                ← backtesters, calibration scripts
    ├── documents/            ← competition info
    └── SIGNALS_PLAYBOOK.md   ← cross-round signal checklist
```
