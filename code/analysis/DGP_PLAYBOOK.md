# Round 3 And Later — Data-Generating-Process Playbook

This note is the companion to:

- `traders/round2/RESEARCH_LOG_signal_mining_literature_20260423.md`
- `analysis/signal_scan.py`
- `analysis/composite_signal_scan.py`
- `analysis/propagation_signal_scan.py`
- `analysis/counterparty_signal_scan.py`

The focus here is not “which signal looked best on one backtest”, but:

1. what process could have generated the data,
2. what observables that process should imply,
3. what the lowest-complexity strategy is if the process is true,
4. what evidence would falsify it quickly.

That framing is the most important thing taken from the strong public Prosperity writeups, especially Timo Diehm / Frankfurt Hedgehogs:

- <https://github.com/TimoDiehm/imc-prosperity-3>

Their round-2 basket writeup explicitly asks the right question first:

- how could this market data have been generated?

That is the correct approach. A z-score, OU fit, EMA crossover, or logistic regression only makes sense after the generator hypothesis is coherent.

## Workflow Principles From Strong Writeups

The strongest public Prosperity writeups, especially Frankfurt Hedgehogs, treat workflow as part of the edge.

Core principles worth carrying forward:

- prepare the tooling before the round starts:
  - backtester
  - order-book / trade dashboard
  - quick scan scripts
  - event-study templates
- use visualization to infer latent state before modeling:
  - where are the deep walls?
  - is there a stable “wall mid” or synthetic fair proxy?
  - are fills coming from visible traders or from a hidden acceptance rule?
- pick the backtest environment based on mechanism:
  - bot-interaction / hidden-fill products need official-style or bundle-based validation
  - simple take / quote logic can be screened with the local backtester first
- prefer stable parameter plateaus over narrow maxima
- use fill post-mortems:
  - which fills actually made money 5, 10, or 50 ticks later?
  - which rule is generating adverse selection?
- never trust a website score or one local replay more than the structural story

This is not just “good process hygiene”. It changes which strategies get built.

## Meta-Framework

For every new product family, write down candidate generators before writing code.

### Step 0: instrument the market first

Before testing any alpha:

- plot price, spread, and visible depth through time
- plot trades against the book
- identify whether a latent fair proxy is obvious:
  - fixed anchor
  - drift line
  - wall mid
  - synthetic basket value
  - conversion-implied fair
- note whether the product looks:
  - exogenous
  - derived from another product
  - driven by hidden participants
  - driven by deterministic mechanics like fees or expiry

This step matters because the “correct” feature set is different if the book is a noisy wrapper around a hidden benchmark versus a product with genuine endogenous price discovery.

### Step 1: list generator hypotheses

Examples:

- stationary latent fair plus MM noise
- deterministic intraday drift plus local microstructure noise
- basket = synthetic value + stationary premium process
- option chain = Black-Scholes-like surface + residual smile noise
- local market = external fair +/- fees +/- queue/acceptance mechanics
- named trader follows an extremal or meta-order execution rule

### Step 2: derive testable consequences

Examples:

- if basket premium is stationary, residual should have stable sign-flip pressure and finite half-life
- if constituents are exogenous and basket is derived from them, basket mispricing should not strongly predict constituent moves
- if an insider drives one constituent, that constituent’s flow should lead related basket residuals
- if options come from a smooth IV curve, cross-strike IV should be smooth in moneyness and residuals should be mean reverting
- if fills come from a taker bot with deterministic acceptance logic, one-sided order placement should dominate symmetric market making

### Step 3: choose the cheapest strategy implied by the hypothesis

Examples:

- fixed threshold beats dynamic z-score if the premium is stationary with near-constant variance
- basket-only trading beats full hedge if constituents do not mean-revert back to the basket and hedging only adds cost
- copy-trading beats regime inference when the informed signal is strong and direct

### Step 4: falsify aggressively

Do not ask “does this backtest make money?”

Ask:

- does the sign survive all days?
- does the effect survive costs and limits?
- does it survive when conditioning on obvious confounders?
- does it survive with simple thresholds instead of tuned curves?
- does it still make sense if the simulator is not random but intentionally patterned?

## Product-Class Generator Hypotheses

### 1. Stationary MM products

Generator:

- hidden fair is approximately constant or slowly moving
- visible book is produced by market makers around that hidden fair
- short-term deviations come from queue imbalance, local trade flow, and occasional queue depletion

What should be true:

- fixed anchor or slowly updated fair works
- micro-price predicts the next price move
- depth asymmetry and queue depletion matter around price jumps

Signals:

- `imb1`
- `micro_gap`
- `gap_asym`
- `deplete_asym`

Strategy form:

- passive market making
- selective takes only when fair discrepancy is real
- size up in thick-book regimes, size down in thin-book regimes

### 2. Deterministically drifting products

Generator:

- fair value has a near-deterministic intraday trend
- short-horizon noise sits around that drift path

What should be true:

- raw price direction is less useful than drift-relative residual direction
- best strategy often carries inventory in the drift direction
- two-sided MM is dangerous because it tends to get short into rising paths or long into falling paths

Signals:

- drift slope
- residual z-score
- microstructure only as timing around the drift path

Strategy form:

- inventory carry
- drift-aware reversion trades
- explicit end-of-day unwind rule unless the payout engine marks to true value at close

### 3. ETF / basket / composite products

Possible generators:

- basket price is built from constituents plus stationary premium noise
- both baskets share a common premium factor because of construction or common participants
- one constituent contains informed flow that propagates into baskets
- basket trades have large spreads, so MM and stat-arb coexist

What should be true if each is the dominant generator:

- basket-vs-synthetic residual stationary:
  - trade basket against synthetic fair or basket outright
- premium-difference stationary:
  - trade basket-premium spread, not each basket independently
- informed constituent leads basket:
  - adjust basket thresholds or copy the constituent into the basket
- wide spreads with weak hedge necessity:
  - MM the basket while waiting for stat-arb or insider entry

### 4. Option chains

Possible generators:

- vouchers are priced from one underlying and a smooth IV smile
- observed prices are Black-Scholes-like with residual mispricing
- chain errors occur more in relative value than in outright direction

What should be true:

- implied vols across strikes should be smooth in moneyness
- residual IV or price errors should mean-revert
- delta-hedged relative value should be cleaner than naked option direction

Signals:

- fitted IV surface residual
- strike-spread monotonicity violations
- chain butterfly / calendar consistency checks

Strategy form:

- fair price from BS or the round-specific model
- trade residuals, not raw option prices
- aggregate and hedge chain delta with underlying

### 5. Conversion / location arbitrage products

Possible generators:

- local price = external quote +/- tariffs, transport, storage, and cap constraints
- execution depends on a taker/acceptance mechanism rather than a random fair-value process

What should be true:

- a narrow band of order prices gets accepted disproportionately
- one-sided quoting at the conversion cap can dominate symmetric making
- exogenous macro variables matter only through the conversion fair, not as free alpha on their own

Signals:

- implied local fair bid/ask from external market
- acceptance probability by price level and recent volume

Strategy form:

- conversion-first arbitrage
- fill-adaptive edge placement
- only add local MM if the remaining spread justifies it

### 6. Revealed or inferable counterparties

Possible generators:

- one trader follows an extremal rule
- one trader meta-orders in one direction for large chunks of the day
- one trader leads across related products

What should be true:

- signed returns after that trader’s trades are asymmetric
- effect persists for some horizon
- cross-product spillovers may exist

Signals:

- direct trader event study
- buyer/seller pair event study
- cross-product post-trade response

Strategy form:

- direct copy-trading first
- regime conditioning second
- cross-asset propagation third

## Round 3 Special Focus: Picnic Baskets

This is the highest-priority later-round structure to prepare for.

Public winner and strong-team writeups converge on a few ideas:

- basket-vs-synthetic spread is the first place to look
  - <https://github.com/JamesCole809/IMC-Prosperity-3>
  - <https://github.com/chrispyroberts/imc-prosperity-3>
  - <https://github.com/Sylvain-Topeza/imc-prosperity-3>
- Basket 2 often behaves differently from Basket 1
  - several teams did not keep both in the final strategy
- position limits can make direct full hedging suboptimal
  - cross-basket premium difference can be cleaner than two separate fully hedged books
- informed Croissant flow can spill into basket logic
  - <https://github.com/Sylvain-Topeza/imc-prosperity-3>
  - <https://github.com/TimoDiehm/imc-prosperity-3>

### Round 3 workflow before strategy code

Do these in order:

1. plot:
   - `PB1 - synth1`
   - `PB2 - synth2`
   - `(PB1 - synth1) - (PB2 - synth2)`
   - `PB1 - 1.5 * PB2 - D`
2. measure:
   - mean
   - sd
   - AR(1)
   - zero-crossing rate
   - per-day sign stability
3. test directionality:
   - does basket premium predict basket reversion?
   - does basket premium predict constituent reversion?
   - or are constituents effectively exogenous?
4. test cross-product propagation:
   - do Croissants, Jams, or Djembes returns lead the basket premium?
   - do constituent trade events lead basket moves?
5. compare implementations on matched signals:
   - outright basket
   - fully hedged basket-vs-synthetic
   - half-hedged basket
   - premium-difference spread
6. only after that, choose thresholds

What not to do first:

- do not default to a moving-average crossover on the spread
- do not normalize by rolling volatility unless variance actually regime-shifts
- do not assume full hedging is alpha-positive just because textbooks call it arbitrage

### Hypothesis R3-H1: basket price is synthetic value plus stationary premium noise

Model:

`PB1_t = 6*C_t + 3*J_t + 1*D_t + premium1_t`

`PB2_t = 4*C_t + 2*J_t + premium2_t`

with `premium*_t` mean reverting.

If true:

- residual spread has finite half-life
- basket moves back toward synthetic fair
- constituent response to basket mispricing is weak

Trade:

- sell rich basket, buy cheap basket or synthetic proxy
- if hedging costs and limits are too punitive, trade basket outright on large premium dislocations

Falsify by:

- weak or unstable residual half-life
- constituent returns moving with basket residual in the opposite direction
- premium variance regime-shifting too much for fixed thresholds

### Hypothesis R3-H2: the premium difference is cleaner than either raw premium

Model:

`(premium1_t - premium2_t)` is more stationary than `premium1_t` or `premium2_t` separately.

This is exactly the logic behind Chris Roberts’ writeup emphasis on premium differences under limit pressure:

- <https://github.com/chrispyroberts/imc-prosperity-3>

If true:

- the best signal is a spread between baskets, not two independent z-scores
- constituent hedges can be partial or secondary

Trade:

- long one basket premium, short the other
- use unused limit on one basket for MM if spread edge is wide enough

Falsify by:

- premium-difference residual not more stationary than individual premiums
- position-limit geometry not actually binding the constituent hedge

### Hypothesis R3-H3: one constituent carries informed flow into baskets

Model:

- Croissants or another component gets informed/meta-order flow
- baskets react with lag or through premium threshold shifts

This matches the later public writeups that extended Olivia/Croissant information into Basket 2 or threshold adjustments:

- <https://github.com/Sylvain-Topeza/imc-prosperity-3>
- <https://github.com/TimoDiehm/imc-prosperity-3>

If true:

- constituent order-flow or insider events predict basket residual changes
- basket threshold should be biased, not symmetric

Trade:

- reduce the short-entry threshold when informed flow is bearish
- reduce the long-entry threshold when informed flow is bullish

Falsify by:

- no lead-lag from constituent flow into basket residual
- direct basket spread already dominates the cross-product signal

Practical note:

- if the informed-flow signal is real, use it first to bias thresholds or target inventory
- only later decide whether direct constituent copy-trading adds more EV than just improving basket timing

### Hypothesis R3-H4: basket is the only real alpha; hedge just reduces variance

This is the subtle but important point from Timo Diehm’s round-2 basket writeup:

- if constituents are independently generated and the basket gets a mean-reverting premium shock, then the basket should revert toward synthetic value; the constituents do not need to “come back” with it
- in that case, hedging is risk reduction, not alpha creation

Implication:

- full textbook hedge is not automatically optimal
- with spread costs and tight limits, basket-only trading can have higher expected value than fully hedged stat-arb

Test:

- compare outright basket premium trades vs hedge-neutralized premium trades on matched signals
- include spread and position-limit usage explicitly

### Hypothesis R3-H5: baskets are wide enough to MM while waiting

Chris Roberts’ writeup notes material extra PnL from market making/taking on baskets while waiting for stronger signals:

- <https://github.com/chrispyroberts/imc-prosperity-3>

If true:

- stat-arb should not fully disable passive edge capture
- residual mean-reversion and spread capture can coexist

Trade:

- passive quoting near fair when premium signal is weak
- switch to aggressive/stat-arb mode when the premium crosses threshold

## Round 4+ Generator Templates

### Options

Strong public consensus:

- Black-Scholes-style fair as the baseline
- IV smile fitting or rolling IV estimate
- trade residuals, not naked chain direction

Useful references:

- <https://github.com/TimoDiehm/imc-prosperity-3>
- <https://github.com/Sylvain-Topeza/imc-prosperity-3>
- <https://github.com/CarterT27/imc-prosperity-3>
- Gatheral and Jacquier, arbitrage-free SVI:
  - <https://arxiv.org/abs/1204.0646>
- Hoshisashi, Phelan, Barucca, no-arbitrage IV calibration:
  - <https://arxiv.org/abs/2310.16703>

Recommended tests:

1. fit implied vol by strike / moneyness
2. smooth the surface with the simplest stable model available
3. compute option residual and delta
4. compare:
   - outright option residual
   - cross-strike residual spread
   - delta-hedged residual

Generator-first interpretation:

- if the chain is generated from one smooth smile plus quote noise, cross-strike residuals should dominate raw option direction
- if the underlying itself mean-reverts, a lightweight underlying or deep-ITM hedge can reduce regret, but should not replace the chain-relative signal
- if no-arbitrage violations are persistent, the issue may be stale quotes or sparse strikes rather than true directional alpha

Workflow:

1. convert prices to IV wherever possible
2. inspect smile smoothness in moneyness, not raw strike alone
3. fit the cheapest arbitrage-respecting surface that is stable across days
4. trade residuals back to surface fair
5. use delta / gamma overlays as risk controls, not as an excuse to ignore spreads

### Location arbitrage

Consensus:

- derive local fair from external market and fees first
- acceptance / conversion mechanics matter more than macro prediction

References:

- <https://github.com/Sylvain-Topeza/imc-prosperity-3>
- <https://github.com/ericcccsliu/imc-prosperity-2>
- Timo Diehm / Frankfurt Hedgehogs Macarons section:
  - <https://github.com/TimoDiehm/imc-prosperity-3>

Recommended tests:

1. implied local fair bid/ask from external source
2. realized acceptance probability by quote distance
3. cap utilization vs expected edge

Generator-first interpretation:

- the important hidden variable may not be the macro inputs themselves
- the important hidden variable may be the acceptance frontier of a taker bot or conversion engine

Workflow:

1. reconstruct the fee-adjusted conversion band
2. map fills by quote distance from the external fair
3. infer whether there is a stable price level with abnormal fill probability
4. size to the conversion cap first
5. only then ask whether exogenous features like sunlight or tariffs add incremental timing value

### Trader-ID / insider rounds

Consensus:

- direct copy-trading is often stronger than fancy regime modeling
- daily-extrema or fixed-size meta-order behavior can be inferable even before IDs are revealed

References:

- <https://github.com/TimoDiehm/imc-prosperity-3>
- <https://github.com/chrispyroberts/imc-prosperity-3>
- <https://github.com/jmerle/imc-prosperity-2>
- Taranto et al., propagator / multi-event impact:
  - <https://arxiv.org/abs/1602.02735>
- Lillo, order flow and price formation:
  - <https://arxiv.org/abs/2105.00521>
- Maitrier, Loeper, Bouchaud, reconstructing metaorders from public data:
  - <https://arxiv.org/abs/2503.18199>
- Goliath and Gebbie, metaorder identification from public data:
  - <https://arxiv.org/abs/2602.19590>

Recommended tests:

1. event study by trader and side
2. event study by trader-pair
3. event study on related products after an informed constituent trade

Generator-first interpretation:

- many “insider” patterns are just order-splitting or extremal bots seen through partial observability
- the right hidden state is often:
  - estimated trader inventory
  - current meta-order direction
  - whether the trader is early, late, or done

Workflow:

1. estimate signed trader inventory over the day
2. measure post-trade drift and decay horizons
3. test whether direct copy-trading beats quote-skew conditioning
4. test whether the signal transfers across linked products
5. if multiple traders interact, move to a simple trader graph before any ML

Tooling note:

- `analysis/propagation_signal_scan.py` is the default reusable scanner for these questions
- it handles raw and derived series, so it can test:
  - constituent -> basket premium
  - underlying -> option residual
  - informed product -> related spread or residual

## Additional Literature That Changes The Workflow

- Lerner, ETF-vs-market imbalance causality:
  - <https://arxiv.org/abs/2204.03760>
  - implication: ETF flow can transmit pressure, so basket-vs-component lead-lag should be tested explicitly, not assumed away
- Petajisto, ETF inefficiencies:
  - <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2000336>
  - implication: ETF premiums can mean-revert even when creation/redemption exists, so stationarity of the premium is a valid first hypothesis
- Pan and Zeng, ETF arbitrage under liquidity mismatch:
  - <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2895478>
  - implication: when hedging assets are less liquid or balance-sheet constrained, mispricing can persist longer and full hedging can be inferior
- Marshall, Nguyen, Visaltanachoti, ETF arbitrage intraday evidence:
  - <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1709599>
  - implication: basket dislocations are most interesting when the path into convergence is constrained, not frictionless
- Taranto et al. and Lillo:
  - <https://arxiv.org/abs/1602.02735>
  - <https://arxiv.org/abs/2105.00521>
  - implication: persistent order flow is compatible with diffusive prices, so later-round “insider” data should be treated as hidden meta-orders first, clairvoyance second
- Benzaquen, Mastromatteo, Eisler, Bouchaud, cross-impact of order flow imbalance:
  - <https://arxiv.org/abs/2112.13213>
  - implication: cross-asset propagation can be real even when same-asset logic looks weak, so linked-product event studies should be routine

## Thoughts On Claude’s Generated Round-2 Files

Files:

- `traders/round2_fresh_claude/claude_v1.py`
- `traders/round2_fresh_claude/claude_v2.py`
- `traders/round2/clean_alpha.py`
- `traders/round2/strat_284364.py`

### `claude_v1.py`

Good:

- correctly splits ASH as stationary and PEPPER as trending at the descriptive level
- code is clean and simple
- ASH logic is directionally fine as a first-pass baseline

Bad:

- the PEPPER implementation still treats the drifting product like a two-sided market-making problem
- this is a mismatch between the stated generator and the executed strategy

Local backtests:

- same-tick 3-day total: `-152419.5`
- official-hybrid with `local_bundles_profile.json`: `-84209.0`

Why it loses:

- it ends materially short PEPPER on the strongest up-drift days
- official-style replay day-end positions:
  - day `-1`: `PEPPER = -29`
  - day `0`: `PEPPER = -67`
  - day `1`: `PEPPER = -1`

Interpretation:

- this is exactly what happens when the true generator is “drift + local noise” but the strategy behaves as “local fair + symmetric reversion”

### `claude_v2.py`

Good:

- fixes the core generator mismatch from `v1`
- moves PEPPER from symmetric MM to directional target inventory
- the architecture now matches the data story: ASH = stationary edge-capture, PEPPER = carry/trend

Local backtests:

- same-tick 3-day total: `246805.0`
- official-hybrid with `local_bundles_profile.json`: `249867.0`

Important nuance:

- most of the PnL is PEPPER carry marked at the end, not realized intraday trading gains
- official-style 3-day split:
  - total PnL: `249867.0`
  - realized PnL: `66322.8`
  - unrealized PnL: `183544.2`
- day-end PEPPER position is `+80` on all three days

Interpretation:

- `v2` proves the regime classification is right
- but it still under-monetizes round 2 relative to the stronger branch because it lacks:
  - explicit deterministic drift anchor
  - better timing around the drift line
  - stronger ACO microstructure alpha
  - explicit close/unwind logic if the final marking rule changes in a future round

Bottom line:

- `v1` is a useful negative example: correct description, wrong executable generator model
- `v2` is a useful positive example: once the generator assumption matches reality, a simple strategy can outperform much fancier but structurally wrong code
- that lesson should carry directly into round 3 baskets and later rounds

### `clean_alpha.py`

This is materially closer to the research standard implied by the strongest writeups.

Why:

- it decomposes round 2 into explicit generator sleeves:
  - deterministic IPR drift carry
  - residual timing around that drift line
  - ACO stationary MM
  - micro-price and walked-spread rebound as microstructure overlays
- it is calibrated against real bundle evidence instead of only trusting the default local fill model
- it contains fill post-mortem feedback, which is exactly the workflow strong teams describe

What I like:

- the strategy is explainable from first principles
- the dominant alpha sources are separate and testable
- it treats simulator calibration as a research object, not a given

What I do not fully buy:

- the IPR residual mean-reversion sleeve looks weaker than the drift carry and timing sleeves
- the later half-life test in the round-2 log suggests much of that residual component is near-white noise

Interpretation:

- `clean_alpha.py` is the closest local example of the approach we should export to round 3 and later:
  - infer generator
  - isolate sleeves
  - keep only justified complexity

### `strat_284364.py`

This looks like a safer, more compact production compromise.

Why:

- it still respects the main generator split:
  - ACO anchored near a stationary fair
  - IPR anchored to a deterministic drift path
- it reduces surface area relative to more aggressive branches
- the IPR core-band logic is a practical way to say:
  - carry the drift
  - trim only when path-relative richness is real

Weakness relative to the stronger research branch:

- it uses touch-mid style benchmarking more than the richer micro-price / liquidity-geometry view
- it is more execution-pragmatic than signal-rich, which is good for robustness but can leave microstructure EV on the table

Interpretation:

- if `claude_v2.py` is the first structurally correct draft, `strat_284364.py` is closer to the kind of restrained production implementation that survives official evaluation
- it is less ambitious than `clean_alpha.py`, but much more mature than `claude_v1.py`

## Workspace References Worth Reading Carefully

Local conceptual references already present in this workspace:

- `traders/round0/clones/fh_clone.py`
- `traders/round0/clones/aa_clone.py`

Use them as idea banks, not as trusted production code.

Why:

- they encode the right motifs:
  - basket premium trading
  - insider/counterparty following
  - option chain residuals
- but at least one local clone has clear implementation errors in the ETF block, so the conceptual structure is more valuable than the exact code

## Practical Next Actions When Round 3 Data Arrives

1. Run `analysis/composite_signal_scan.py` with the round-3 relation spec template in `analysis/spec_templates/round3_picnic_relations.json`.
2. Run `analysis/propagation_signal_scan.py` with `analysis/spec_templates/round3_propagation_relations.json`.
3. Test basket-vs-synthetic and premium-difference hypotheses separately.
4. Check whether outright basket trades beat fully hedged trades once costs and limits are included.
5. Scan constituent-to-basket lead/lag and propagation before adding any cross-product bias rule.
6. Build a quick dashboard view before tuning anything:
   - price
   - premium
   - trades
   - depth
   - inferred informed-flow markers
7. Use the backtester appropriate to the mechanism:
   - if the edge is pure spread crossing / simple quotes, local first
   - if fills depend on hidden bot mechanics, validate with official-style evidence
8. Only after those steps should you tune thresholds or add z-score normalization.
