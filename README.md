# IMC Prosperity 4 — Writeup

This is the writeup of my IMC Prosperity 4 entry (2026 edition, run April 14–30, 2026), competed solo from day one. The repo covers what I built, what worked, what didn't, and what I'd do differently. Source code lives in [code/](./code) (a snapshot of my working repo); the per-round writeups in this folder cover the reasoning.

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

The biggest miss in that pattern: I knew the contest charged zero transaction fees, but I never stress-tested what that implied for sizing. My MM defaults — wider passive offsets, more conservative inventory skew, smaller post sizes — were carried over implicitly from real-world quant work where every fill costs you the rebate-adjusted bid-ask. Under zero fees those defaults are too tight; the optimal MM is narrower in spread, higher in volume, more aggressive. That single un-audited assumption is the largest piece of leftover PnL in the writeup.

A meta-game observation worth naming explicitly: in retrospect, the late rounds rewarded tight-quote market making more cleanly than the early rounds did, and my arb-style sleeves had less room to generate edge under those conditions. Whether that's deliberate seed design by IMC or natural drift is an empirical question I haven't quantified yet; either way, the read I should have made by round 3 is "the regime has moved against my strategy class — pivot." I treated round-to-round result variance as noise instead of a regime signal. Adding regime-shift monitoring at each round boundary is the cleanest single piece of next-time discipline, and the gap from there to a top finish is on me, not on the contest design.

The full framework, including the cross-round signal-hunting checklist, is in [SIGNALS_PLAYBOOK.md](./code/SIGNALS_PLAYBOOK.md).

## What this writeup is

A record of my own work, with the real backtest numbers, the real ship files, and the real mistakes. Where another team's writeup shaped what I tried, I cite it as theirs (see [lessons_learned.md](./lessons_learned.md) for the comparisons).

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
