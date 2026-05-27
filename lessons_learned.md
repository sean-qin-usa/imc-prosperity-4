# Lessons learned

These are the things I'd actually change if I ran IMC Prosperity again, ordered roughly by how much PnL I think they were worth. References to other teams' published writeups are cited explicitly; their work is their work.

## 0. Knowledge wasn't the gap. Game-fundamentals understanding was.

Reading the top teams' published writeups in retrospect — Leo-Hawking, zainy-477, rmtf1111, Deepjot Grewal, Alex Stoeveken — there isn't a technique on their lists that I didn't already know. Black-Scholes on a voucher chain, IV-residual mean reversion, microprice fair value, walked-spread rebound, family-pair-trade overlays, rank-bid manual challenges, generative-process classification — all of that was in my heads-up notes before round 1. I built the [`SIGNALS_PLAYBOOK.md`](./code/SIGNALS_PLAYBOOK.md) precisely to enumerate those approaches up front.

The gap wasn't quant technique. The gap was **understanding the game** at a fundamental level. I understood general market patterns well enough to make stable returns in practice; I didn't think critically enough about how Prosperity's contest structure would penalize that and reward something else.

Specifically, four things I knew in the abstract but didn't internalize until after the fact:

1. **The contest is not a real market.** It's a 3-day-data point estimate against a curated seed, with IMC's proctors picking seeds adversarially to defang AI-assisted EV-maximization (§0b, §0c below).
2. **Backtest-to-live conversion is asymmetric across sleeve classes and is the only number that matters at submission time** (§1, §4 below).
3. **Structural strategy classes that are robust across seeds beat parameter-optimal strategies that are robust within one seed.** I knew this; I didn't ship it (§0d, §3 below).
4. **LARGEST ONE: ZERO TRANSACTION FEES flip which MM strategy class dominates.** Tight high-volume quoting as used by many top competitors is simply real-world unprofitable (and disregarded by me internally when making conscious final ships) but contest-optimal here; I sized for the real world instead of making decisions based on the challenge at hand(§0e below).

The teams that beat me ran the same general playbook I did. They just had a sharper sense of the meta-game and shipped the structurally correct answer even when their local backtest didn't validate it. §0b through §7 are the concrete instances.

## 0b. Variance management beats expected-value maximization on a single realized path

The R4 manual ("Vanilla Just Isn't Exotic Enough", Aether Crystal options) is the cleanest illustration. I priced the contracts as a Black-Scholes problem against the inferred volatility surface and sized to the **EV-optimal** allocation under the long-run distribution. The answer was correct in expectation — the math checked out, the IV fits were reasonable, the implied edge per contract was positive.

It made approximately no PnL on the actual realized path.

IMC seeded the underlying's Brownian motion in a regime where the EV-optimal portfolio's edge sat almost entirely below the realized-path's noise. This is plausibly intentional — a competition designed to be AI-resistant and to simulate "markets don't behave like the long-run distribution on any given day" has every incentive to choose seeds where pure-EV strategies underperform variance-aware ones. The point of the manual challenge, on that reading, isn't to test whether you can solve BS; it's to test whether you size with humility against the variance you can't see.

Concretely, what I'd do differently:

1. **Size by the worst-case across a plausible seed distribution**, not by the EV under the assumed-correct prior. The R3 manual sizing (the `(775, 875)` Bio-Pod bid that beat the textbook-optimal `(751, 836)`) already had this instinct; I should have ported it to the option-sizing problem in R4. (R3 sized for *field-clustering* variance; R4 needed sizing for *underlying-path* variance — same discipline, different source.)
2. **Cap the allocation per leg at a level the realized-path drawdown can absorb**, not at the EV-maximizing level. Greed sizing on a single-seed contest is structurally wrong even when the math is right.
3. **Treat the long-run-optimal answer as the prior, not the answer.** The actual answer is the optimal answer plus a humility discount for the seed-of-the-day risk.

This is the same lesson as the algo-side calibration story (§0): in both cases I had the technique right, and the gap was about understanding that the local/long-run number isn't what's scored.

## 0c. The 3-day-data problem — backtesting on a single curated seed

Every round shipped with three days of historical CSVs. My backtesters captured execution logic correctly. They could not tell me what the seed-of-the-day in the live submission would look like, and in a contest where the entire score is one realized path against an adversarially-chosen seed, the seed dominates.

Concretely:

- A 3-day local backtest is a point estimate against a fixed sample. Variance across plausible seeds is not sampled, so a "we beat the prior best by 5 %" backtest delta is statistically meaningless against the live distribution.
- IMC has every incentive to pick seeds that punish strategies clustered around "average market behavior" — that's where most teams' backtests over-fit and where AI-assisted EV-maximization concentrates. The R4 Aether Crystal manual (see §0b) is the cleanest illustration: my Black-Scholes EV-optimal allocation made zero PnL against the seed they actually chose.
- The right response is **structural**. Strategies whose edge is robust *across* seeds — pure carry, anchored mean-reversion, family-pair-trades that neutralize broad factor exposure — beat strategies whose edge depends on the seed-specific noise (most of the variant-laden version ladders I built in R3).

I built ablation ladders as if they sampled the live PnL distribution. They didn't. The strategies that survive seed risk are the ones with the cleanest first-principles generative story, not the ones with the highest local backtest. I knew this conceptually before round 1. I didn't behave like I knew it until after the competition was over.

A separate consequence: stable-returns approaches that work in practice don't necessarily *rank* high in a contest where the scoring is one realized path. Practical trading optimizes for expectation across a distribution of paths; this competition scored you on one. Optimizing for stable returns the way I would on real funds is the wrong objective. Lesson is to model the contest mechanics explicitly, not to assume "good trading" translates to "good contest result."

## 0d. I had the right structural answers and didn't ship them

This is the one that stings most, and it's the practical face of §0–§0c.

For the final three rounds, I quite literally built each of the competition's most optimal strategies, yet shipped the safer, lower-conviction one instead because the first-cut local backtest didn't validate the better one:

- **R5 family-pair-trade overlay** — `traders/round5/ll_pair_*`. Top teams I've since read up on shipped exactly this structure. Family-beta neutralization on a 50-product universe with 10 thematic clusters is *structurally* the dominant approach; its edge shows up as variance reduction, not as a higher first-moment PnL on a single seed. The first-cut backtest is the wrong evaluation tool for a strategy whose advantage is variance reduction. I built it, tested it, rejected it on a backtest delta, and shipped the safer directional ship instead.
- **R4 regime-gated VFE sleeve** — identified the cross-sleeve interaction problem during the round (Mark-67 follow fighting the existing MR sleeve). Designed the unified-with-regime-gate fix. Didn't have the bandwidth or the conviction to ship it under the time pressure (see [`round_4.md`](./round_4.md)).
- **R3 three-way basis arb** — VFE / VEV_4000 / VEV_4500 are three parallel measurements of the same underlying with std < 1 tick. Documented, scoped, never built.

The pattern is the same in every case: I had the right structural instinct, and I chose the safer, locally-validated answer. **The gap is conviction, not insight.** And conviction is what game-fundamentals understanding gives you — knowing that the local backtest isn't the live score, knowing that variance reduction is what beats an adversarial seed, knowing that "first-cut backtest delta" isn't the right rubric for ranking-not-returns contests. The teams that beat me didn't have better ideas. They had the discipline to ship their ideas under contest mechanics I now wish I'd modeled better.

## 0e. No transaction fees changed which strategies dominate — I optimized for the wrong market

Prosperity charges **zero transaction fees** on the algorithmic side. This is not how real markets work, and it changes which strategies are PnL-optimal in a way I didn't internalize until after the rounds closed.

In a real market with maker/taker fees and spread costs, **tight high-frequency / high-volume market-making strategies are usually unprofitable** — every additional fill costs you the rebate-adjusted bid-ask, and you need a real edge per quote to overcome the cost basis. The strategies that survive real-world transaction costs are wider-spread, lower-frequency, more selective MM and structural carry — exactly the shape of what I shipped on rounds 1–3 (clipped-anchor MM, IPR drift carry, HYDROGEL stationary anchor with conservative inventory skew).

In Prosperity's zero-fee regime, those constraints disappear. The optimal MM strategy is to **quote as tightly as possible and turn over as much volume as possible**, because every fill is pure spread capture with no cost basis. That's exactly what the top teams' shipped algorithms did. Their R1/R2 PnLs aren't higher because their fair-value models are smarter; they're higher because they spam tighter quotes at higher volume in a regime where there's no penalty for it.

My strategies were tuned implicitly for a real-world fee structure — wider passive offsets, larger inventory skew, smaller post sizes than were strictly optimal. The result:

- **Lower contest PnL** — confirmed across the R1–R3 backtest-to-live conversion checks.
- **Strategies that would actually work on a real exchange** — which is not what the contest scored.

This is a third specific instance of the §0 meta-lesson ("game-fundamentals understanding was the gap"). I optimized for stable, real-world-deployable trading and got penalized for it in a contest that explicitly rewards the opposite. The right move was to **explicitly model the cost structure of the contest as the starting point** and let the constraints (or lack of them) inform the strategy class — not to default to "what would I run on a real exchange" and hope the contest mechanics aligned.

If I'd internalized this on day one, the R1 ACO/IPR sizes would have been larger and the passive offsets tighter; the R3 HYDROGEL MM would have run at the top of its size plateau (or above it) rather than the conservative middle; and the R5 directional ship would have leaned harder into the take side instead of the imbalance-gated passive quoting. Most of those changes are visible in the backtests as a 10–20 % PnL improvement that I left on the floor because I was sizing for a world where every fill cost something.

## 1. Local backtester PnL is not live PnL — and the gap is asymmetric across sleeve classes

The single most expensive theme of my five rounds was misreading the backtest-to-live conversion ratio. Concretely:

- **HYDROGEL passive-make sleeves** converted at ≈ 1.0× (sometimes > 1.0× from my misread on early sessions).
- **Voucher mean-reversion alpha** converted at **~1–3 %** to live.
- **Citadel-class deep-ITM mirror sleeves** under-converted vs jmerle backtest by 0.76–0.86× — the *opposite direction* from what I assumed for the first two sessions of R3.

The right discipline is to (a) build the conversion calibration *during the tutorial round*, not mid-competition; (b) cap optimization time on any sleeve once its conversion ratio is known to be < 5 %, since the local backtest is no longer scoring the right thing; and (c) treat the jmerle backtester as an *upper bound* on live, not as ground truth.

Reference points from other teams that handled this better than I did:

- **Leo-Hawking** ([repo](https://github.com/Leo-Hawking/IMC-Prosperity-4-Review)) — explicit per-round calibration discussion and a clear separation of "local replay" vs "production" PnL columns.
- **rmtf1111** ([repo](https://github.com/rmtf1111/imc-prosperity-4)) — kept the strategy intentionally simpler than my zoo of `combined_ship_v*` versions; less to over-fit to a local matcher.

## 2. Generative-process hypothesis before signal hunting, every time

The §0.1 rule I wrote into [`SIGNALS_PLAYBOOK.md`](./code/SIGNALS_PLAYBOOK.md) — *articulate the generative story before building a strategy* — paid off every time I followed it and bit me every time I didn't.

The cleanest illustration is R2's IPR drift: a constant +0.001 / ts is +1000 / day, which at limit 80 is +80 k / day of pure mechanical carry. Treating IPR as a "path-anchor forecast" in R1 left half that carry on the floor. Treating it as a deterministic-driver class in R2 (story #5 in the playbook) made the strategy obvious.

The opposite-direction example is R3's voucher chain. The micro-price-imbalance signal had +0.59 aggregate correlation, but the generative-process check (§1a + spread regime split) revealed the signal was concentrated entirely in walked-book states. A strategy that uses micro as fair *at typical spreads* is fitting to noise. Same lesson, opposite framing.

This is also where the top-team writeups were most useful as comparison:

- **zainy-477** ([repo](https://github.com/zainy-477/imc-prosperity-4)) — short, principled per-round notes that read like generative-process hypotheses checked one by one. The thing I want to look more like next year.
- **Deepjot Grewal** ([LinkedIn](https://www.linkedin.com/posts/deepjot-grewal_imcprosperity-algorithmictrading-trading-ugcPost-7459488385015914497-yQJB)) — explicit framing of voucher rounds as "options on a delta-1" rather than as a free-standing strike chain.
- **Alex Stoeveken** ([LinkedIn](https://www.linkedin.com/posts/alex-stoeveken_imc-prosperity4-quant-share-7459944204320849920-gyJ7)) — short post but useful framing on the R5 sentiment round as a "size by conviction × move-magnitude prior" problem rather than a directional-MM problem.

## 3. Strategy structure beats parameter tuning on a multi-product universe

R5 was the clearest case. I shipped a 50-product directional MM with imbalance-gated passive quotes. The right structure was almost certainly a **family-pair-trade overlay** that neutralizes thematic-family beta (e.g. PANEL_2X4 vs PANEL_2X2 controls for the panel-supply-glut narrative exactly). I had the pair-trade variants (`ll_pair_*`) — they didn't beat the directional ship on local backtests, but in retrospect that's almost certainly a calibration issue (sizing constants tuned for the single-product regime), not a strategy issue. I shipped the inferior structure because the superior structure needed a calibration pass I didn't run.

The discipline is: when a strategy class is structurally dominant on the universe shape, calibrate it; don't reject it on first-cut backtests against a less-structural baseline.

## 4. Conversion-check between shipping versions

The R3 v25 → 427141 → v28_warmup65 → v29_mirror progression added 86 k of backtest and 17 k of live (mostly from v28's warmup-65 retune). The mirror layer (v29 over v28) added 63 k backtest and 171 live. I shipped v29 anyway because each step beat the previous on backtest, and I wasn't running a conversion-check at each shipping decision.

The rule going forward: when the conversion ratio of a sleeve drops materially between two consecutive ships, *that sleeve is dead-alpha class* and the marginal backtest improvement should be ignored. This is the same lesson as §1 but at the per-version, per-sleeve granularity.

## 5. Cross-sleeve interaction is real and expensive

R4's Mark-67 follow on VFE was a positive signal that *hurt* the strategy because the existing VFE mean-reversion sleeve was already long the same trades. The signal was right; the overlay was wrong. The correct fix is to unify competing sleeves under a regime gate, not to layer them.

I noticed this in R4 but didn't have time to fix it. Same pattern probably hit me in R3 between the HYDROGEL passive sleeve and the IV-residual MR — I never measured the cross-trade overlap because the per-sleeve backtests looked clean.

For next year: budget a half-session per round for **cross-sleeve interaction tests** — pairwise PnL with one sleeve disabled, check that the sum-of-parts matches the whole.

## 6. Manual challenges are EV problems against a field-cluster prior, not optimization problems

The deterministic optima for the R2 budget split and the R3 Bio-Pod bids are well-defined. They are also approximately what every AI-assisted team will submit, which means they sit in the contaminated-cluster region of the rank-distribution. The actual best response is "one step past the obvious answer" — R2's `19 / 60 / 21` instead of `19 / 61 / 20`, R3's `(775, 875)` instead of the textbook-optimum `(751, 836)`.

The framework I used (rank-bid cluster scan with AI-default contamination) worked for R2 and R3. R5's news manual needed a different framework — sized conviction against a move-magnitude prior. I should keep both as templates.

## 7. Operationally — finish each round before chasing the next session's gain

A meta-lesson, not a quant one. The 100+ versions of `combined_ship_v*.py` in R3 are an artifact of session-on-session backtest chasing without a hard stop on "diminishing returns vs live." If I'd capped R3 at v15 + a 6-hour validation pass, I'd have shipped within 1 % of v29's live PnL and freed up a full day for R4's regime-gated VFE sleeve. The discipline that's missing is "this is the ship file; the next 48 hours are about validating it, not improving it."

## What I'd take into Prosperity 5

Concisely:

1. Calibration harness before round 1. Conversion ratios for every sleeve class.
2. Forced §0.1 generative-process hypothesis on every product in every round. Written down before any signal-hunting code is run.
3. Hard ship cutoff per round at the 50 %-time mark. Remaining time is validation only.
4. Cross-sleeve interaction test in the validation pass.
5. For multi-product rounds, structurally dominant approaches get a dedicated calibration pass even if they lose first-cut.
6. For manual challenges, the deterministic optimum is the *prior*, not the answer. Add the field-cluster step.
