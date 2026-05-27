# Signals Playbook — IMC Prosperity 4

Reusable signal-hunting guide accumulated from rounds 1-2 and cross-round
P3 research.  For each new round, work top-to-bottom through this list:
cheap scans first, expensive ones later.  Every signal below has a
measured result in at least one round — the ones that have been dead in
every round so far can be deprioritized.

**Read alongside:**

- `../practice/notes/workflow_guide.md` — HOW to run a round (pre-round
  prep, 30-min/2h/8h checkpoints, adaptation when broken, risk management).
- `../practice/notes/approach_methodology_data_generation.md` — the
  "how was this data generated?" framework.  Use this to pick the right
  signal family before hunting individual signals.
- `../practice/notes/r3plus_strategy_playbook.md` — per-topic
  strategies (options, ETFs, bot-detection).
- `../practice/notes/p3r3_own_analysis_novel_findings.md` — novel
  findings beyond published winners' code.
- `../practice/notes/p4_round1_prior_research_summary.md` — prior
  deep-dive extraction.

## 0 · First-principles reasoning (before any signal hunt)

Non-negotiable: run §0.1 BEFORE §0.2 and §1-7.  If you can't
articulate the generative story you're not ready to build a strategy.

### 0.1 Generative-process hypothesis

Ask: **"how could the Prosperity simulator have generated this
product's price time-series?"**  Plausible stories (full list in
`approach_methodology_data_generation.md` §1):

1. Constant mean + mean-reverting noise → StaticFairMM
2. Linear drift + mean-reverting noise → MM + inventory carry
3. Random walk → skip MM, use as hedge / derivative underlying
4. **Independent constituents + mean-reverting spread** → fixed-threshold
   spread trade, NOT z-score, NO constituent hedge
5. Deterministic fn of a driver → compute fair via formula, trade
   deviations
6. Simulated bot → identify + copy or fade
7. External driver + noise → regress on driver, trade residual

The story directly implies what features matter and which strategies
are theoretically valid.  Validation from our P3 R3 re-architecture:
rebuilding the basket engine on first-principles story #4 moved PnL
from −105 k/day (z-score) to **+52 k/day** (fixed threshold, no hedge).
See `practice/notes/workflow_guide.md` §10 for the delta table.

### 0.2 Data sanity first

Before any signal hunt:

1. Compute per-product per-day **linear drift slope** (OLS of mid vs timestamp).
   In round 2 IPR this was `+0.001 / ts` exactly every day — a deterministic
   core alpha worth ≈ 80 000 / day at position limit 80.
2. Compute per-product **residual sd** around the drift line.  Gives the
   z-score threshold for mean-reversion trades.
3. Compute per-product **mean / stationary anchor** for non-drifting products
   (ACO in r2: flat at 10 000 with sd ≈ 5).

These three numbers drive every subsequent decision (carry target, take
thresholds, passive size, reversion gating).

## 1 · First-order microstructure (always try)

### 1a. L1 book imbalance → next-tick Δmid

- Feature: `(V_bid_1 - V_ask_1) / (V_bid_1 + V_ask_1)`
- Target: `mid_{t+1} - mid_t`
- **R2 result: r ≈ +0.59, R² ≈ 0.34, E[Δ | imb>+0.5] = +3.6 with P(up) = 95 %.**
- **Capture mechanism**: replace `touch_mid = (bid+ask)/2` with
  `micro = (ask·V_bid + bid·V_ask) / (V_bid + V_ask)` as the fair-value
  input everywhere (inventory skew, take thresholds, passive quoting).
  Algebraically `micro - mid = (spread/2)·imbalance`, so no extra feature
  engineering is needed.
- Worth: ~+5-10 k / day / market in r2.

> **CRITICAL CAVEAT (R2 ACO, discovered 2026-04-23):** the +0.59 aggregate
> correlation is almost entirely carried by *walked* states (spread
> 18-19).  At spread = 16 — the 58 % typical regime for ACO — L1
> imbalance ↔ next-Δmid ≈ 0.  Strategies that use pure micro-price as
> fair at normal spreads will be *tracking noise* and regress PnL by
> ≥ 20k / day.  Always spread-gate: fall back to the touch midpoint when
> spread ≤ typical_spread; only enable the micro-price shift when the
> book is walked.  On IPR the regime difference is smaller but the same
> gating still helps.

### 1b. Walked-spread rebound

- Feature: observed spread > typical MM spread → one side has walked.
- Target: bid / ask rebound next tick.
- **R2 result**: at spread=19 bid rebounds +1.4 (if bid walked) or ask drops
  −1.4 (if ask walked).  Spread 21: ±2.4.
- **Capture mechanism**: on walked states, bias the fair toward the
  non-walked side by `typical_spread/2`, AND post an extra aggressive
  quote inside the spread on the rebound side.
- Worth: ~+3-8 k / day / market.

### 1c. Mid-diff AR(1)

- Compute on detrended mid (subtract linear drift first for drifting products).
- **R2 result**: ≈ −0.49 on both products.
- Already captured by the micro-price trick in 1a (micro-price implicitly
  reverts).  Don't double-count.

## 2 · Leads that were dead in r2 but cheap to re-run

### 2a. Higher-lag ACF (AR(2)..AR(6))

- If AR(1) captures most of the reversion, higher lags should be near 0.
- R2: all |ρ| < 0.03. **Dead.** Re-run anyway in case a new round has
  structured oscillation (e.g. basketed products).

### 2b. L2/L3 extra-depth imbalance

- Feature: `full_depth_imbalance - L1_imbalance`.
- R2: naive r = −0.42 but multicollinear with L1 (joint regression coef
  ≈ −0.05, R² gain = 0.0). **Dead in r2.**
- Still worth a 10-line scan in a new round — in some products hidden
  depth leads the top of book.

### 2c. Cross-product lead/lag correlation

- For products with shared fundamentals (e.g. basket constituents).
- R2 ACO↔IPR: |ρ| ≤ 0.003 at all lags. **Dead.**
- In rounds with derivative / basket structures (common in later
  Prosperity rounds), this flips to being the dominant alpha.

### 2d. Trades-file passive clustering

- All trades happen at best_bid or best_ask (0% in-spread) in r2.
- Our inside-spread fills are simulator-generated via the fill-matcher
  calibration, not from real other-trader orders.
- **Takeaway**: the trades file is useful for *aggressor* classification
  (§3a) but NOT for inferring mid-spread MM density.

### 2e. Time-of-day drift

- Bucket mid deviation by decile.
- R2: scrambled, no structural bias. **Dead.**
- Re-run on new rounds — some rounds have known EOD dynamics.

## 3 · Signals to try proactively in every new round

These I haven't mined in r2 yet (or only shallowly).  Listed by expected EV.

### 3a. Trade-aggressor ratio (high priority)

- Trades file has empty `buyer`/`seller` in r2 but the **price** lets you
  infer: `trade.price == best_ask → buyer aggressor`,
  `trade.price == best_bid → seller aggressor`.
- Feature: rolling-window aggressor imbalance (N trades).
- Expected: leads mid at short horizons; widely used in HFT.
- **Status in r2: not yet tested.**

### 3b. Order-flow intensity / time-between-book-updates

- Feature: number of book changes per N ticks, or time since last top-of-book
  change.
- Expected: burst regimes correlate with directional moves; quiet regimes
  correlate with reversion.
- **Status in r2: not yet tested.**

### 3c. Residual half-life (Ornstein-Uhlenbeck fit)

- Feature: how fast does the (mid − drift_line) residual mean-revert?
- Drives the optimal take threshold and rebalancing cadence.
- **Status in r2: implicit (we use z > 1.2); not explicit-fit.**

### 3d. Preferred-level Markov chain

- Build a transition matrix on top-of-book states `(bid, ask)`.
- Look for asymmetries: states that transition non-uniformly.
- **R2 (partial)**: top-of-book states cluster at 9994/10010 … 9998/10014.
  A spread-21 state predicts big next-tick move (found via §1b), but a full
  state-by-state Markov scan hasn't been done.

### 3e. First-N-tick-of-day / end-of-day anomalies

- First 100-2 000 ticks often have anomalous flow (book warm-up, MAF
  settlement).
- Last 1-5 % often have end-of-day unwind by other traders.
- **Status in r2**: we unwind in last 1 % but haven't checked if *other*
  traders have a pattern there.

### 3f. Fill post-mortem

- After a backtest, tag each of our fills with the signals at fill time
  (imbalance sign, spread regime, inventory, time-of-day) and measure
  PnL over the next 5/10/50 ticks.
- Separates profitable from adverse fills and tells you what rule the
  current strategy is missing.
- **Status: not yet done.** Highest-EV untapped work because it uses
  data we've already generated.

### 3g. Volatility-regime switching

- Split days/segments into high-vol vs low-vol bins by rolling σ of
  mid-diff.
- Re-measure all signals conditional on regime; often the
  imbalance-edge is much stronger in one regime than the other.

### 3h. Signal isolation backtest

- Rather than layering a new signal into the full strategy, run a
  stripped "trade only on signal X, hold Y ticks, flat otherwise"
  and compare its PnL to the baseline.
- Separates "signal is real" from "strategy captures it".  Catches
  cases like the first-pass walked-fair edit that was neutral in the
  full strategy but the signal itself was real (clipping bound).

## 4 · Calibration hygiene (critical)

The local backtester has a calibrated passive-fill model.  The default
`official-hybrid` profile is optimistic.

- **Never ship a number without passing `--exchange-calibration`** to
  something calibrated against a real submission bundle.
- In r2 we have `tools/calibrations/local_bundles_profile.json` built
  from bundles 138109 + 284364.
- Validation protocol: run the real-submitted strategy (`284364.py` or
  equivalent) through the local backtester and compare to
  `real_profit × (full_day_ticks / test_run_ticks)`.  If the ratio is
  > 1.2, the calibration is leaking optimism.
- Apply the observed ratio as a haircut when projecting any new
  strategy's real-world PnL.

## 5 · Fill-matcher exploits vs. honest alpha

The local backtester's size-bucket fill simulation has quirks the real
engine does NOT have.  In r2, posting 80 × (1-lot child orders) at the
same price produced 785 k local but ≈ 20 k on the real-bundle replays.

**Rule**: if PnL scales linearly with requested qty way past the L1
daily volume, you are fitting the fill model, not the market.  Confirm
against real-bundle replay before trusting.

## 5.5 · Kill-signals (stop shipping)

Adopted from TimoDiehm and chrispyroberts P3 writeups.  Any of these =
do NOT ship, even if backtest looks good:

1. **Sharpe > 3** on a short dataset → overfit.  Apply Deflated Sharpe
   (Bailey-LdP 2014) and re-check.
2. **PnL is day-specific** — works on 1/3 days but fails on others →
   regime-fitting; untrustworthy out-of-sample.
3. **Hyperparameter sensitivity**.  If moving a threshold by 10% flips
   PnL sign, it's noise-fitting.  chrispy explicitly didn't ship his
   VR z-score in R5 for this reason.
4. **Feature is a near-synonym of target** (leakage).  Using same-bar
   close to forecast same-bar return.
5. **PnL → 0 with small turnover penalty** → you were harvesting the
   bid-ask spread, not alpha.
6. **Equity curve too smooth** — real alpha is lumpy.
7. **Refuses to degrade under Gaussian noise injection** → overfit.
8. **You can't explain in one sentence why the edge exists.**  Frankfurt
   (R2): *"if you can't explain why a strategy should work from first
   principles, then any 'outperformance' in historical data is probably
   noise."*
9. **Requires ≥ 3 parameters to work.** Simple robust > tuned complex.
10. **You optimized on the website score.**  Frankfurt: *"never optimize
    purely for website score.  Doing so is extremely prone to
    overfitting on simulation-specific randomness."*  Use local
    backtester for tuning; website only for bot-interaction validation.

## 6 · When to use each mining tool

| Question | Tool |
|---|---|
| Does signal X predict next-tick Δmid? | 20-line Python: bucket X, compute E[Δ] per bucket |
| Do two signals add independently? | OLS regression, compare R² with/without |
| Is the edge stable across days? | Per-day re-fit; require same sign on all days |
| Would a strategy capture the edge? | Isolation backtest (§3h) |
| Is the backtester lying about fills? | Real-bundle calibration check (§4) |
| Is the fill pattern pathological? | `tools/calibrate_exchange_model.py` — compare bucket counts |

## 7 · Starting a new round

Recommended order on round kickoff:

1. Write the **generative-process hypothesis** (§0.1) for every new
   product in one paragraph each.  If you can't, keep looking at data.
2. Compute §0.2 sanity numbers (drift, residual sd, anchor, spread
   distribution, AR(1)) for every product.
3. Classify each product into a data-generation story (see
   `practice/notes/approach_methodology_data_generation.md` §1).
4. Run §1a (micro-price test) and §1b (walked-spread test) — reusable
   from prior-round scan scripts.
5. Check for informed bots / archetypes via size-filtered trade plot
   (§3a).
6. Bake drift-carry (if present) + micro-price fair into a minimal
   `baseline.py` with FIXED thresholds.
7. Backtest under real calibration (§4).  If none available, build one
   from the first submission (validation protocol in §4).
8. Ship a **safety-floor** version to the website early (don't wait
   for the "best" one).  You can overwrite later.
9. Only after steps 1-8 does it make sense to go after §3 signals or
   tune aggression / size parameters.  Don't tune on a mis-calibrated
   backtester.

## 7.4 · Cross-round / cross-competition transfer

Strategies transfer across *structurally identical* rounds.  Document
the mapping in both directions so a blank-state Claude can reuse work.

**Verified transfers (2026-04-23):**

- P4 R1 ↔ P4 R2 (same products, same limits, same data structure):
  R2 recipe applies directly.  Fresh strategy from recipe hit
  **+416 k / 3-day on R1** (target 200 k), min single day +132 k
  (target 20 k).
- P4 R2 ACO ↔ P3 R2 RAINFOREST_RESIN (same anchor 10 000, rsd ≈ 2,
  AR(1) = −0.50, mode spread 16, imb_r ≈ +0.68):
  scaled ACO handler (size 40, limit 50) delivers Resin PnL ≈ 75 k / 3-day
  — nearly 2× Timo's reported Resin contribution.
- P4 R2 ACO ↔ P4 R3 HYDROGEL_PACK (same anchor ≈ 10 000 region, mode
  spread 16, stationary with MR). Different: std 25-38 (10× ACO's
  2-5), limit 200 (4× ACO's 50). Rescaled params that worked (2026-04-24):
  `clip=30 (ACO 2.0), inv_skew=0.015 (ACO 0.06), max_post_size=20
  (ACO 19)`. Measured +149 k / 3-day on HYDROGEL alone. NOTE: the
  `ACO_FAIR_ADJUST_CLIP` scales directly with std, not with limit —
  this was the dominant lever; CLIP=20 gave only 112k while CLIP=30
  gave 149k.

**Rule of thumb** — if §0.2 sanity numbers match a known round within
±20%, copy the handler from that round's recipe and rescale size
proportional to position limit.  Do NOT rebuild.

## 7.44 · MR-strategy stop-losses are usually wrong

Mean-reverting strategies (basket arb, ACO anchor MM, ETF spread) are
bets that an extreme move will reverse.  Classic "trim 25 % when we've
moved past 2·threshold adversely" stop-losses **invert the thesis**:
you sell at the extreme right before the reversal.

Measured 2026-04-23 on P3 R2 basket arb: adding a 25 %-trim stop
crashed PnL from +201 k → +57 k on R2 and from +210 k → +49 k on R3 OOS.

**When an MR stop IS legitimate:**

1. Duration-based: spread has been past threshold for 1 000+ ticks
   (not a transient blow-out — a regime shift).
2. Catastrophic-dollar cap: total position MTM loss > X SeaShells on
   one product.  Flattens only in black-swan scenarios.
3. Inventory-skew-on-fair (used in Resin/ACO handlers) — not a stop,
   it just softly reduces aggression when inventory piles up.

Never a simple "spread is extreme → trim".  If the model says "extreme
spread → revert", the rule that exits on extreme is anti-model.

## 7.45 · Basket / ETF arbitrage (P3 R2+ product family)

A whole family of Prosperity rounds have products shaped as a weighted
linear combination of other products (ETF structure):

- P3 R2: PICNIC_BASKET1 = 6 C + 3 J + 1 D ;  PICNIC_BASKET2 = 4 C + 2 J
- P3 R3: same baskets carry over
- likely future rounds: any product whose name includes "BASKET",
  "INDEX", "COMPOSITE", or obvious multi-component name

This maps to §0.1 generative story #4 (independent constituents +
mean-reverting spread).  **Strategy template:**

1. Identify the weights by inspecting the round's `round_info.md` or
   uplink transcript (they are always explicit; no inference needed).
2. Compute `spread_t = basket_mid − Σ w_i · leg_mid`.
3. Measure the historical distribution: mean, sd, min, max, and
   **persistence** (corr of spread_t to spread_{t+1}).
4. Pick FIXED thresholds at roughly the 5 %-tail of the distribution
   (e.g. mean ± 1.5 · sd).  **NOT z-score** — if persistence is > 0.99
   (days-long MR) a z-score re-enters inside the natural MR cycle and
   accumulates adverse fills.
5. Trade: cross the basket book when `spread > UPPER` (short) or
   `spread < LOWER` (long).  Size ≈ 15-30 per tick, capped by L1 depth.
6. **Do NOT hedge** with the constituent legs.  Published research
   (P3 R3 re-architecture log) shows hedging destroys PnL in this
   structure — the spread alpha comes from the basket regressing to the
   synthetic, and hedged positions carry the regression cost on both legs.

Evidence on P3 R2: fresh strategy following this template achieved
PB1 +70 k, PB2 +56 k across 3 days, nearly 3× Timo's reported figure.
Entry logic: straight market orders, no passive make — the alpha is
in the directional bet, not in execution edge.

**Dead-end list for basket trades:**

- Z-score sizing on persistent spreads → PnL negative.
- Constituent hedging → PnL destroyed.
- Pair-wise `ETF1 − 1.5·ETF2 − Djembes` spread: Timo used this in P3 R3
  with "dynamic informed adjustment" on Croissants; skip in R2 v1
  (complexity unjustified for the gain vs simpler 2-spread trade).

## 7.46 · Observation-driven directional (P3 R4 macarons pattern)

A Prosperity product may come with a parallel `observations.csv` / 
`ConversionObservation` feed containing exogenous variables (sugarPrice,
sunlightIndex, transport fees, tariffs).  Default first attempt: treat
them as input to the **local import-arb**:
`imp_edge = local_bid − (foreign_ask + transport + import_tariff)`.

**Important kill-signals learned on P3 R4:**

1. **Check arb magnitude first.**  On P3 R4, mean `imp_edge = −$2 to −$4`
   per unit — arb is NEGATIVE.  Don't ship arb code until you've eyeballed
   the distribution.
2. **`prosperity3bt` ignores conversions.**  `runner.py:362` captures
   `conversions` but never uses it.  The import leg can't close locally.
   If a strategy depends on conversions to realize PnL, it will look
   broken in the backtester.  Verify against actual submission framework.
3. **Use the observation AS A FEATURE for the local book directionally.**
   Strong bucket corr (sun<45 → price 750+, sun>55 → price 630) tempts
   a LEVEL rule but level rules enter AFTER the regime has moved.
4. **TREND on the observation wins.**  `feature[t] − feature[t−W] < 0 →
   target +LIMIT` (long if observation is dropping).  W=500 ticks on
   macarons, but tune per product.  Rationale: regime shifts take
   100k+ ticks to complete; the trend signal triggers mid-shift while
   price is still moving, exits when trend reverses.  Local-only
   taker orders — no MM, no conversions.
5. **Day-wildness cost.**  Days with no trend reversal (macarons day 2)
   give a small loss; days with the shift (day 1 & 3) give +25k wins.
   Long-only > symmetric for robustness.

Evidence: P3 R4 went from 122k (no macarons) to 154k (trend engine)
= +32k (+26 %); P3 R5 (shares days 2 & 3) +18k (+19 %).

**Template for any future round with observations:**

- Correlate `obs_feature_t` vs `price_t` (level) and `Δobs_feature_t`
  vs `Δprice_t` (delta).  A high level-corr with near-zero delta-corr
  means the feature captures REGIME, not tick-alpha.
- Build a single rule: `target = +LIMIT if obs_feature_t < obs_feature_{t-W}`.
  Long-only first; add shorts only if day-level variance accepts it.
- Warmup the rolling buffer; warmup_ticks ≥ W.  No trade before buffer full.
- Taker-only.  Market-making an observation-driven directional is
  capturing spread on the wrong side of your own signal.

## 7.455 · Standalone MM on basket constituents — usually a trap

Observed on P3 R2-R5 (2026-04-23): Croissants / Jams / Djembes are
structural BASKET LEGS with tight 1-2 tick spreads.  Standalone MM on
them regresses PnL.

- **Jams**: −22 k / day on trending days (MM adversely selected by drift).
- **Djembes**: 0 fills (spread-1 books → bid_wall+1 = ask_wall → can't
  post inside).
- **Croissants**: per-product PnL shows +13-25 k/day on R5 but total
  stays unchanged — appears offset by basket-leg accounting at
  aggregate.

**Rule**: if a product is a constituent of a basket you're already
trading, DON'T add a standalone MM unless the constituent has a
genuinely separate alpha (e.g. informed-trader signal).  The basket
trade already monetizes the constituent's mispricing.

## 7.46 · Options / voucher family (P3 R3+)

Five call-option vouchers at distinct strikes over one underlying
(e.g. Volcanic Rock).  Structure that carries forward to any future
round with an "INDEX / UNDERLYING + VOUCHERS" pattern.

**Unverified templates** — not yet PnL-positive in our backtests, but
structurally correct.  Flag as OPEN WORK; revisit before shipping any
round involving options.

1. Intrinsic lower bound: call option value ≥ max(0, S − K).  Any
   voucher ask below its intrinsic is an immediate arb — LIFT.
2. Black-Scholes theoretical value with a rolling IV estimate.  Trade
   deviations.  Timo's approach uses a 20-period EMA of IV and buys
   when market IV < EMA by 0.5 σ.
3. Pure voucher MM at 1 tick inside touch.  Doesn't fill much on tight
   books (spread = 1 is typical) — quote size has to be small to avoid
   adverse selection from an informed counterparty.

**Position limits**: 200 per voucher, 400 for underlying.  Large vs
Resin/Kelp — but vouchers are LEVERAGED (delta < 1) so dollar risk
is similar.

**Pitfalls observed (2026-04-23)**:

- Wall-mid-anchored MM on volcanic rock LOST money (wall_mid is a wide
  midpoint that wanders too much on a volatile underlying).  Use
  top-of-book mid instead.
- Naive size-limit/4 voucher quotes produced zero fills on P3 R3
  backtester — too passive.  Needs aggressive inside-touch posts.

### 7.46.1 · Flat-smile options chain (P4 R3 pattern, 2026-04-24)

A second round-3 variant from P4 observed 2026-04-24: 10-strike
voucher chain on a delta-1 underlying with a near-FLAT IV smile
(σ ≈ 0.23 across liquid strikes), not the quadratic smile P3 R3 had.

**Key first-principles observations on this pattern:**

1. **Deep-ITM calls are synthetic-underlying clones.** For strikes with
   moneyness ≤ 0.86 (e.g. K=4000 and K=4500 on underlying S≈5248),
   market price ≈ S - K exactly, basis std < 1 tick. This is leverage
   — underlying limit is 200, each voucher limit is 300. Total
   delta-1 capacity balloons to 200 + 300 + 300 = 800 (4×).
2. **ATM strikes have wide-enough spreads (3-6) to MM** but flat-σ BS
   theo is systematically biased enough (~0.005 off real) to make
   take-side trades adversely selected. Losing -10k/day per ATM strike
   when you use `BS(σ=const)` as fair for take.
3. **OTM strikes have 1-2 tick spreads** — too tight for pure MM;
   need IV-MR-residual overlay to trade signal.
4. **Underlying itself may still be unprofitable.** The P4 R3
   VELVETFRUIT_EXTRACT is -EV on every take/make config tried. Its
   role is **reference feed for voucher pricing**, not a trading
   product. Don't assume "this is the underlying, of course we MM it."

**Strategy template for flat-smile voucher chains:**

```
Tier 1 (safe, immediate):
  1. MM the wide-spread delta-1 clones at fair = S - K
     (no IV needed — pure intrinsic for moneyness < 0.9).
  2. ACO-class MM on the side delta-1 product if present.
Tier 2 (IV-residual, needs port of p3_combined):
  3. IV-residual MR on ATM strikes using EMA(theo_diff).
     σ frozen at the data-fit flat value.
  4. IV scalping on OTM strikes.
Tier 3 (delta-management):
  5. Aggregate delta hedge: sum all deltas, hedge via underlying.
```

**Measured P4 R3 session-1 result:** Tier-1-only (HYDROGEL + VEV_4000
+ VEV_4500) = +167 930 / 3-day, all days strongly positive
(60k / 54k / 52k). Extending MM to ATM (v4) dropped this to 135k due
to IV bias.

See `IMCP2026/traders/round3/ROUND3_RECIPE.md` for the lever table
and `P3R3_TRANSFER_NOTE.md` for the diff vs P3 R3.

### 7.46.2 · Rank-bid auction with per-bid penalty (P4 R3 Bio-Pod)

A rank-bid auction variant with a **second-bid penalty tied to the
global mean of second bids**:

- reserves uniform on a k-spaced grid [low, high]
- submit two bids (b1, b2)
- b1 ≥ reserve → profit fair - b1
- b2 ≥ reserve and b2 > avg_b2 → profit fair - b2
- b2 ≥ reserve and b2 ≤ avg_b2 → penalty factor
  `((fair - avg_b2) / (fair - b2))^3` on profit (or probability)

**Optimization structure:**

1. **Standalone b1 optimum is flat** — with uniform reserves, multiple
   b1 values within {low + k, …, (low+fair)/2} give same EV. On P4 R3
   Bio-Pod: {785, 790, 795, 800} all tie at 63.7/gardener.
2. **Fixed-point b2*** is where the Nash-ish equilibrium lands: where
   everyone best-responds to everyone else's b2. On P4 R3 Bio-Pod,
   b2* = 870 with b1=790 (both at mid of plateaus).
3. **Winner bids one step past the Nash cluster.** "Just past the
   herd that isn't you." On Bio-Pod: (780, 890) is the robust pick —
   below the b1 plateau centre and above the b2 Nash by one step of k.

**Decision framework** (how to pick from robust / aggressive / safe):
- Aggressive: peak at the Nash b2 (77.7/gardener if crowd is at/below
  Nash avg).
- Robust: one step past the Nash → ~76/gardener, protects against
  avg_b2 drifting up.
- All-weather: set b2 to max-in-grid minus one step (e.g. 900 on a
  920 fair). Zero avg-dependence, ~72/gardener. Use as fallback when
  late-round sentiment suggests the avg is unusually high.

Pick the robust option by default; shift to all-weather if Discord or
post-Round-1 chatter suggests bid inflation. Last-submitted pair wins,
so iterate during the round.

## 7.47 · Conversion arbitrage (P3 R4 Macarons pattern)

A product that has a parallel "conversion exchange" with:

- `bidPrice` (what the external exchange pays you to sell there)
- `askPrice` (what you pay to buy there)
- `transportFees`, `importTariff`, `exportTariff`

Effective prices:

- `ex_ask = askPrice + importTariff + transportFees` (our cost to buy via conversion)
- `ex_bid = bidPrice − exportTariff − transportFees` (our revenue selling via conversion)

**The arbitrage**: if local market offers a better price than the
conversion equivalent, trade local and flatten through conversion.

- SHORT arb: local_bid > ex_ask → sell local, buy via conversion
- LONG arb: local_ask < ex_bid → buy local, sell via conversion

**Conversion limit** (P3): 10 units per tick.  Round this is the
binding constraint.

**Historical claim (Timo)**: 80-100 k / round from Macarons alone on
P3 R4; theoretical optimum 130-160 k if the hidden taker-bot edge is
fully exploited.

**Our status**: naive implementation lost ~10 k / day.  Likely cause:
using `local_sell_price` = rounded conv.bidPrice as a POST price
rather than crossing market bids directly, and not gating on
`short_arbitrage >= 0` before posting.  Fix pending.

## 7.5 · Non-obvious levers that cost us 2+ sessions to find (R2)

A blank-state Claude given SIGNALS_PLAYBOOK.md + three days of R2 data
will naturally produce a **~70 k / day** strategy (measured 2026-04-23).
The gap to the **~140 k / day** ceiling is filled by levers that are
not in the §0-§7 signal table.  Write these down on every round:

1. **MM quote size saturates at ~75**, not ~20.  A naive-size MM caps
   the make-side PnL at half of what's available.  Grid-search size in
   round numbers {15, 30, 50, 75, 100} — the plateau is between 55-80
   on R2 per the historical log (2026-04-20).  Smaller sizes don't fill
   when the book rebounds; larger sizes don't produce more fills and
   just increase adverse-selection risk.

2. **Aggressive early-accumulation window** for any drift-carry product.
   In R2 IPR: first 2 000 of 10 000 ticks, take every ask ≤ benchmark
   up to full limit 80 at 20 qty/tick.  Without this the long inventory
   lags the drift by thousands of ticks and loses ~10 k / day.

3. **Walked-side extra quote**.  On every walked-spread tick, post
   *additional* size-55 / size-12 quote at `bb+1` or `ba-1` (not just
   the normal MM quote).  Worth ~+20 k / day.

4. **2-level passive bid** (or ask).  When spread > 4, post at bid+1
   size 12 AND bid+2 size 6.  You keep two priority slots, survive
   queue rearrangements.

5. **Inventory skew on the fair**.  `fair_effective = fair − k * pos`
   with k ≈ 0.06 at position limit 80.  Auto-flattens without a
   separate "reduce" logic branch.

6. **Kill exchange-cleverness**.  Any strategy whose PnL scales
   super-linearly with quote-splitting or 1-lot child orders is
   fitting the local matcher.  Confirm against real-bundle replay (§4)
   before trusting; historical examples (R2 `_max80_chunk1`) showed
   785 k local vs 27-30 k real.

7. **Fair-adjust CLIP on stationary-MM products scales with the
   product's std, not its limit.** On P4 R3 HYDROGEL (std 25-38),
   CLIP=30 shipped +149 k/3-day while CLIP=20 gave only 112 k and
   CLIP=15 gave 99 k — a 1.5× cliff in one parameter. The P4 R2 ACO
   ACO_FAIR_ADJUST_CLIP=2.0 was sized for std 2-5; reusing it for a
   10× std product would bleed 30 % of PnL. **Rule**: set CLIP ≈ 1 ×
   per-day residual std (or 0.8-1.2× as a plateau). Measure std BEFORE
   scaling recipe parameters across rounds.

8. **ATM option MM with a flat-σ BS fair is a trap.** On P4 R3 (σ_fit
   ≈ 0.23 across strikes), using BS(S, K, T, σ=0.23) as fair for
   take-side on ATM strikes (5000-5300) lost 10-13 k per strike per
   day (-25 k/day on day 2 alone). The ~0.005 σ bias between the fit
   and true market σ is enough to pull take into adverse fills. **Rule**:
   option fair should be a time-varying residual (EMA of theo-diff)
   or a mid-relative signal, NOT a flat-σ analytic fair.

Record each round's values for these levers at the top of the
round's `RESEARCH_LOG.md`, next to the §0.2 sanity numbers.

## 8 · Parameter-selection discipline

From TimoDiehm workflow (validated on our P3 R3 replays):

- **Two parameters max** per strategy.  More → overfitting risk.
- Grid-search with **round-number steps** (10, 50, 100) — fine grids
  find noise cells.
- Pick a **flat plateau**, NOT the peak, on the PnL heatmap.  A
  3x3-cell region where PnL is within ±10% of the max is a keeper;
  a single bright cell with zeros around it is noise.
- **Re-optimize each round** on the newest concatenated data.
- **If hyperparameter sensitivity is high, SKIP**.  See §5.5 kill #3.
- If you've iterated > 10 times on parameters, STOP.  Go back to §0.1
  and question the generative hypothesis.

## 9 · Adaptation protocol (when something breaks mid-round)

Fault-class triage:

1. **Infrastructure**: strategy crashed, logs empty, submission didn't
   parse.  chrispy R3 was Jasper-visualizer OOM.  Fix: strip
   heavyweight imports; run the submission file through a memory
   profile.
2. **Model**: fair-value formula giving wrong sign / magnitude.
   chrispy R3 quadratic IV smile overshot by huge margin.  Fix:
   replace with simpler more-robust model (rolling mean).
3. **Execution cost**: strategy filling at adverse prices / slippage
   eating alpha.  Fix: tighten triggers, raise min-edge, or stop
   hedging if hedge-leg slippage is measurable.

Don't rewrite the whole round.  Frankfurt on R5: *"for Kelp we left
our Kelp trading alone."*  Change only the module that broke.

## 10 · Risk-management checklist per strategy

- [ ] Explicit 95 % VaR estimate (from resid sd × √horizon × position)
- [ ] VaR compared to current lead / session budget
- [ ] Position cap set such that hedge is always feasible, if hedging
- [ ] Fallback branch: what happens if main model returns bad size?
- [ ] Hybrid framing: any strategy = λ·(full hedge) + (1−λ)·(no hedge).
      Pick λ explicitly, document why.
- [ ] Acceptable per-day max-loss stop (flatten at −X / product)
