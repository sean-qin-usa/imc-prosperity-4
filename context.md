# Context

A short, honest note on the constraints around this entry. These are context, not excuses — the work is what it is, and the [lessons-learned page](./lessons_learned.md) is where I take responsibility for what I'd change. I include this only because the question of "what was this person actually working with" is reasonable for a reader to ask.

## Limiting factors

- **Finals overlap.** Rounds 1 and 2 (April 14–20) overlapped directly with my finals. I was juggling between submission windows and exams; the R1 manual challenge in particular got the shallow treatment because it landed on the worst day.
- **Solo from day one.** I went into Prosperity 4 as one half of a two-person team, with delegations and . My partner withdrew **before round 1 even opened**, so every shipped algorithm — round 1 onward — was solo. This was fine at first (as I placed higher in phase 1) but once the rounds got shortened to 48 hours and my exam season came to a peak, it grew into a huge intellectual and physical burden. Most visible artifacts: the many versions of backtesters which we planned to work on together/independently, the 100+ versions of `combined_ship_v*.py` in round 3, parallel-experimentation discipline run alone instead of pair-style. In practice, having another mind generate signal and sanity-check conclusions would have been a massive help almost every other top team benefitted from :(
- **Tooling built mid-competition.** The local-to-live calibration harness, the visualizer, the jmerle-style backtester wrapper, and the calibration-aware ablation scripts were all built during the competition itself. Useful in hindsight, expensive in time during.

## What this entry is

A documented record of a real solo run at a 18 k-team algorithmic-trading competition under finals-week constraints. The strategies are honest, the backtest numbers are real, and the mistakes are catalogued.

The point of the writeup is not the placement — it's the reasoning. The bulk of the value to a reader (or a hiring manager) is in the [lessons-learned page](./lessons_learned.md) and the per-round generative-process reads.

## What I'm proud of

In the spirit of an honest reflection, not just a list of what went wrong:

- **Round 3 manual — data-backed priors and simulation.** The Bio-Pod recommendation [`(775, 875)`](./code/analysis/round3_manual/RECOMMENDATION.md) was the result of a six-scenario prior sweep (`avg_b2 ∈ {858, 855, 862, 875, 885, bimodal}`), an integer-grid optimizer over the auction mechanism, and an AI-cluster-aware adjustment for the 55 % of teams who paste an LLM answer at the textbook optimum. The reasoning explicitly outperformed the standalone-EV answer of `(751, 836)`. This is the piece of the competition I'd put in front of a hiring manager first: the answer is one step past the obvious answer, derived from first principles plus a field model, with the sensitivity table to back it.
- **Applying past quant internship knowledge — directly, not theoretically.** The IV-residual MR sleeve in R3 isn't a clever idea — it's a port of the standard ATM-options statistical-arb pattern I'd already implemented on real instruments. The R2 micro-price vs touch-mid spread-regime split is the same idea applied to MM fair-value. The R5 imbalance gate on passive quotes is the same idea applied to adverse selection. The competition rewarded recognizing which standard pattern fit which generative-process story, and I did that consistently round to round.
- **Round 5 market analysis.** Reading 50 product news items and producing a coherent per-product side-bias dict in one sitting — with cross-checks against P3 news-trading archetypes for the manual challenge — is a real piece of work that I think held up. The robust-allocation submission for the news manual (`Lava cake −27, Ashes −19, Obsidian −14, Thermalite +14, Pyroflex −13, Magma +8, Sulfur +5`) is what I'd point at as the most defensible single-submission decision of the competition.
- **Mostly-working strategies in every round.** Every shipped strategy had positive backtest and positive (or at least non-negative) live PnL on every round, on every day, with the exception of the R4 day-3 correlated-drawdown bucket I never fixed. Not the most efficient versions of those strategies — that's what [lessons_learned.md](./lessons_learned.md) is about — but consistently positive expectancy across five very different product universes, solo, under finals pressure. That floor matters separately from how high the ceiling went.

## What's intentionally left out

- Specific final-round placement and per-round leaderboard rank are not in this writeup. They are public on the IMC Prosperity site for anyone who wants them; I'd rather the reader engage with the work than the number.
- The competition produced more code than I'd write into a clean repo from scratch. The `code/` snapshot reflects the working state at the end of round 5, not a curated codebase. The per-round writeups link to the files that mattered.
