# IMC Prosperity 4 — Writeup

This repo is a writeup of my entry in **IMC Prosperity 4** (the 2026 edition, run April 14–30 2026), where I placed at rank 101, peak rank 7 (23k+ teams, many of whom dropped out after round 1). It documents what I built, what worked, what didn't, and what I'd do differently. Source code lives in the [code/](./code) tree (a snapshot of the working repo); the per-round writeups in this folder explain the reasoning.

## Start here

| If you want… | Go to |
|---|---|
| The actual files I submitted, one per round | [`submissions/`](./submissions/) |
| What I built and why, round by round | [`round_1.md`](./round_1.md) → [`round_5.md`](./round_5.md) |
| What I'd change — the strongest pitch | [`lessons_learned.md`](./lessons_learned.md) |
| Background and limiting factors | [`context.md`](./context.md) |
| The full code snapshot (raw working repo) | [`code/`](./code/) |

## Start here

| If you want… | Go to |
|---|---|
| The actual files I submitted, one per round | [`submissions/`](./submissions/) |
| What I built and why, round by round | [`round_1.md`](./round_1.md) → [`round_5.md`](./round_5.md) |
| Background, limiting factors, thoughts | [`context.md`](./context.md) |
| What I'd change for the next competition | [`lessons_learned.md`](./lessons_learned.md) |
| The full code snapshot (raw working repo) | [`code/`](./code/) |

## Quick links

- **[Final submissions per round](./submissions/)** — exact algorithm files shipped, with one-line summaries per round
- [Round 1 — Tutorial-class MM + intraday path anchor](./round_1.md)
- [Round 2 — Drift-carry, MAF auction, manual budget split](./round_2.md)
- [Round 3 — HYDROGEL anchor MM + VEV voucher chain](./round_3.md)
- [Round 4 — Counterparty signals layered on the R3 chassis](./round_4.md)
- [Round 5 — 50-product sentiment-directional + news manual](./round_5.md)
- [Lessons learned](./lessons_learned.md)
- [Context](./context.md)

## Headline approach

I tried to take every round seriously as a separate generative-process problem rather than as a tuning exercise. The single most useful habit I built was a forced *§0.1 generative-process hypothesis* step before any signal hunt: "how could the simulator have produced this product's time series?" The shortlist of plausible stories (stationary anchor, linear drift, random walk, mean-reverting spread, deterministic function of a driver, simulated bot, external driver + noise) directly implies what features matter and which strategies are theoretically valid. Most of my big wins came from getting this question right; most of my big losses came from skipping on some of these signals. I will note that I completely failed to consider the lack of trading fees when making the conscious decision on which signal driver to use, which most heavily contributed to my downfall this competition (although I am overall proud of how I performed).

The full version of that framework, with the signal-hunting checklist I accumulated across rounds, lives in [SIGNALS_PLAYBOOK.md](./code/SIGNALS_PLAYBOOK.md) in the code tree.

## What this writeup is and isn't

It's a record of my own work, with the actual backtest numbers, the actual ship files, and the actual mistakes. Where another team's published writeup shaped what I tried, I cite it as theirs — see [lessons_learned.md](./lessons_learned.md) for those comparisons.

I am not claiming this work was the greatest and/or cleanest. Natural, as I did not get rank 1. The [context page](./context.md) covers the limiting factors. The [lessons-learned page](./lessons_learned.md) covers what I'd change. Overall though, I am proud of what I did for this competition and look forward to learning and doing more in the future.

## Repo layout

```
.
├── README.md                 ← you are here
├── round_1.md ... round_5.md ← per-round writeups (reasoning, results, what I'd change)
├── lessons_learned.md        ← what I'd take into Prosperity 5
├── context.md                ← finals overlap, solo-from-day-one, what I'm proud of
├── submissions/              ← the exact algorithm file shipped on each round
│   ├── README.md             ← per-round summary table with results & manual submissions
│   └── round_1__*.py … round_5__*.py
└── code/                     ← snapshot of the working repo
    ├── traders/              ← per-round strategy files (full ablation ladder)
    ├── analysis/             ← signal scans, manual-challenge work
    ├── tools/                ← backtesters, calibration scripts
    ├── documents/            ← competition info
    └── SIGNALS_PLAYBOOK.md   ← cross-round signal checklist
```
