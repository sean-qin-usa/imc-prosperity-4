# Lessons learned

These are the things I'd actually change if I ran IMC Prosperity again, ordered roughly by how much PnL I think they were worth. References to other teams' published writeups are cited explicitly; their work is their work.

## 0. Knowledge wasn't the gap. Execution and calibration were.

Reading the top teams' published writeups in retrospect — Leo-Hawking, zainy-477, rmtf1111, Deepjot Grewal, Alex Stoeveken — there isn't a technique on their lists that I didn't already know. Black-Scholes on a voucher chain, IV-residual mean reversion, microprice fair value, walked-spread rebound, family-pair-trade overlays, rank-bid manual challenges, generative-process classification — all of that was in my heads-up notes before round 1. I built the [`SIGNALS_PLAYBOOK.md`](./code/SIGNALS_PLAYBOOK.md) precisely to enumerate those approaches up front.

The gap was not knowledge. The gap was *backtesting calibration discipline* — knowing which sleeve's local PnL would survive contact with the live exchange, building the conversion calibration before I needed it, capping ablation time once a sleeve's conversion ratio dropped below the threshold of "this is real alpha." Items §1 and §4 below are the concrete instances; this section is the meta-lesson that ties them together. The teams that beat me ran the same playbook I did — they just had cleaner backtest-to-live machinery and shipped earlier.

The other side of this lesson, separately, is round 4's manual challenge.

## 0b. Variance management beats expected-value maximization on a single realized path

The R4 manual ("Vanilla Just Isn't Exotic Enough", Aether Crystal options) is the cleanest illustration. I priced the contracts as a Black-Scholes problem against the inferred volatility surface and sized to the **EV-optimal** allocation under the long-run distribution. The answer was correct in expectation — the math checked out, the IV fits were reasonable, the implied edge per contract was positive.

It made approximately no PnL on the actual realized path.

IMC seeded the underlying's Brownian motion in a regime where the EV-optimal portfolio's edge sat almost entirely below the realized-path's noise. This is plausibly intentional — a competition designed to be AI-resistant and to simulate "markets don't behave like the long-run distribution on any given day" has every incentive to choose seeds where pure-EV strategies underperform variance-aware ones. The point of the manual challenge, on that reading, isn't to test whether you can solve BS; it's to test whether you size with humility against the variance you can't see.

Concretely, what I'd do differently:

1. **Size by the worst-case across a plausible seed distribution**, not by the EV under the assumed-correct prior. The R3 manual sizing (the `(775, 875)` Bio-Pod bid that beat the textbook-optimal `(751, 836)`) already had this instinct; I should have ported it to the option-sizing problem in R4. (R3 sized for *field-clustering* variance; R4 needed sizing for *underlying-path* variance — same discipline, different source.)
2. **Cap the allocation per leg at a level the realized-path drawdown can absorb**, not at the EV-maximizing level. Greed sizing on a single-seed contest is structurally wrong even when the math is right.
3. **Treat the long-run-optimal answer as the prior, not the answer.** The actual answer is the optimal answer plus a humility discount for the seed-of-the-day risk.

This is the same lesson as the algo-side calibration story (§0): in both cases I had the technique right, and the gap was about understanding that the local/long-run number isn't what's scored.

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
