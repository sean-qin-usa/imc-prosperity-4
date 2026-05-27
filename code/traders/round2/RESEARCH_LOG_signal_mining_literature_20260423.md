# Signal Mining Addendum — 2026-04-23

This note is deliberately separate from `RESEARCH_LOG.md` so it can live next to the active round-2 log without clobbering ongoing edits.

Scope:

- validate new round-2 signal measurements with the right targets
- extract only the parts that look portable to rounds 3-5
- map later-round product types to concrete mining methods
- avoid adding elegant-looking trash that does not survive small-sample reality

## What was added to the repo

New analysis scripts:

- `analysis/signal_scan.py`
- `analysis/counterparty_signal_scan.py`
- `analysis/composite_signal_scan.py`
- `analysis/propagation_signal_scan.py`

Current generated outputs:

- `analysis/round2_signal_scan_report.md`
- `analysis/round2_counterparty_signal_report.md`
- `analysis/round2_propagation_report.md`
- `analysis/ROUND3_AND_LATER_DGP_PLAYBOOK.md`

Intended use:

- `signal_scan.py`: single-product LOB / market-making / short-horizon directional scans
- `counterparty_signal_scan.py`: revealed-trader / insider / copy-trade scans once `buyer` / `seller` fields are populated
- `composite_signal_scan.py`: ETF / basket / synthetic-residual scans from a JSON relation spec

The point is to stop re-deriving ad hoc notebooks each round and instead keep a stable scanner set for:

1. single-name microstructure
2. composite spreads and basket residuals
3. informed-flow / named-counterparty detection
4. cross-asset propagation from raw or derived leader series into follower residuals

## Workflow note from strong public writeups

The most useful extra lesson from the Frankfurt Hedgehogs / Timo Diehm writeup is methodological, not just strategic:

- prepare tools first
- infer how the data could have been generated before choosing signals
- choose the backtester based on whether hidden bot interaction matters
- prefer stable parameter plateaus to narrow backtest maxima
- distrust signals that cannot be justified structurally

That is the main reason `analysis/ROUND3_AND_LATER_DGP_PLAYBOOK.md` now exists. It turns the later-round research into a generator-first workflow rather than a pile of signal ideas.

## Round 2: corrected signal measurement

The main measurement trap in round 2 is target choice.

If you regress features on raw unbounded next-tick `Δmid`, rare large jumps swamp otherwise real directional edges. The queue-imbalance literature instead studies:

- direction of the next mid-price move
- direction of the next non-zero mid move
- detrended residual direction for drifting products

That is the right lens for these products too.

### Validated from the corrected scan

Ran `analysis/signal_scan.py` on `data/round2`.

High-confidence results:

- `ASH_COATED_OSMIUM`
  - `imb1` AUC ~= `0.760` against next non-zero mid-move direction
  - `micro_gap` AUC ~= `0.725`
  - `gap_asym` AUC ~= `0.666`
  - `deplete_asym` AUC ~= `0.663`
- `INTARIAN_PEPPER_ROOT`
  - product is detected as strongly drifting, so the right target is detrended residual direction, not raw price direction
  - `imb1` AUC ~= `0.750`
  - `micro_gap` AUC ~= `0.711`
  - `gap_asym` AUC ~= `0.668`
  - `deplete_asym` AUC ~= `0.664`

Immediate take:

- the prior micro-price / imbalance thesis survives
- the next real addition is not deeper static depth by itself, but **liquidity-gap / queue-depletion asymmetry**

### New round-2 insight: gap and depletion asymmetry are real

Feature:

- `gap_asym = (ask2 - ask1) - (bid1 - bid2)`
- `deplete_asym = ask_gap / ask_vol1 - bid_gap / bid_vol1`

Interpretation:

- if the book is thin above the ask and dense below the bid, small buy pressure can jump price upward more easily
- if the opposite holds, downward jumps are easier

This is more portable than a round-specific anchor. It should generalize anywhere there are only a few visible levels and discrete price jumps.

### New round-2 insight: micro-price works much better in thick books

The scan split `micro_gap` by depth regime.

Round 2 result:

- `micro_gap` is still strong overall
- it gets materially better in **thick-book** regimes
- it degrades sharply in **thin-book** regimes

Portable implication:

- do not just use imbalance for direction
- use **imbalance-conditioned sizing**
- in thin books, prefer smaller size or require corroboration from gap/depletion asymmetry

### Things that looked weak or dangerous in round 2

- static 3-level imbalance: weak after the L1 signal is known
- snapshot-level OFI at 100-tick sampling: contrarian / unstable here, likely because event-time structure is too compressed in this dataset
- raw depth magnitude alone: mostly not directional

### Round-2 cross-product propagation sanity check

Ran the new `analysis/propagation_signal_scan.py` on a temporary round-2 spec using:

- `ACO -> IPR`
- `IPR -> ACO`
- `ACO -> IPR residual`
- `IPR residual -> ACO`

Result:

- essentially no meaningful causal propagation
- best lag correlations were around zero
- event-study responses were small and structurally weak

Why this matters:

- the scanner is behaving sensibly on a round where the products should mostly decompose independently
- if round 3 later shows strong constituent -> basket-premium propagation, that will be much more believable

Conclusion:

- keep OFI / MLOFI in the toolkit for richer event-level datasets
- do not force them into low-frequency snapshot data just because the literature likes them

## Literature-backed priors worth carrying forward

### 1. Queue imbalance / micro-price is the default first scan

Sources:

- Gould & Bonart, *Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book*: <https://arxiv.org/abs/1512.03492>
- Stoikov, *The Micro-Price: A High Frequency Estimator of Future Prices*: <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2970694>
- Bonart & Lillo, *A continuous and efficient fundamental price on the discrete order book grid*: <https://arxiv.org/abs/1608.00756>
- Headlands blog, market microstructure signals: <https://blog.headlandstech.com/category/uncategorized/>

Why it matters:

- this is the cleanest short-horizon price estimator available from L1 alone
- it is cheap, explainable, and portable across stationary, drifting, and even component products

Prosperity translation:

- always compute `imb1`, `micro_gap`, and a depth-conditioned version before trying anything fancy

### 2. Order-flow imbalance matters, but only if the data is event-rich enough

Sources:

- Cont, Kukanov, Stoikov, *The Price Impact of Order Book Events*: <https://arxiv.org/abs/1011.6402>
- Xu, Gould, Howison, *Multi-Level Order-Flow Imbalance in a Limit Order Book*: <https://arxiv.org/abs/1907.06230>
- Lipton, Pesavento, Sotiropoulos, *Trade arrival dynamics and quote imbalance in a limit order book*: <https://arxiv.org/abs/1312.0514>

Why it matters:

- OFI is often more robust than raw trade volume
- MLOFI matters once deeper levels and event timing become informative

Prosperity translation:

- use it aggressively only when the round exposes enough message-time structure or when trades are dense
- otherwise use it as a secondary confirmation, not the main alpha

### 3. Price jumps depend on liquidity geometry, not only imbalance

Source:

- Zheng, Moulines, Abergel, *Price Jump Prediction in Limit Order Book*: <https://arxiv.org/abs/1204.1381>

Why it matters:

- jump risk is explained by a mixture of best-level liquidity, gaps, trade sign, and order-event context

Prosperity translation:

- for large-tick / sparse-level products, explicitly mine:
  - gap asymmetry
  - queue depletion risk
  - spread regime
  - whether the signal only matters when level 2 is far away

## Later rounds: product-specific mining map

### ETF / basket / composite products

Core method:

1. compute synthetic fair from constituents
2. model `spread = basket - synthetic`
3. test both:
   - mean reversion in the spread
   - lead/lag between basket and synthetic returns
4. size by hedge capacity, not just z-score

Portable scans:

- spread mean / sd / z-score
- spread AR(1) and half-life
- basket-return vs synthetic-return lead/lag at lags `-k..+k`
- basket-premium differences between two related ETFs when position limits block full hedging

Why this deserves priority:

- multiple public Prosperity winners converged on synthetic spread logic, not on direct directional forecasting

References:

- Eric Liu et al. (`imc-prosperity-2`): basket spread around a hard mean and adaptive z-score logic
  <https://github.com/ericcccsliu/imc-prosperity-2>
- James Cole / Tomas writeup: ETF fair = synthetic basket, signal = spread z-score
  <https://github.com/JamesCole809/IMC-Prosperity-3>
- CMU Physics writeup: basket premiums behaved stationary enough to justify premium-spread trading
  <https://github.com/chrispyroberts/imc-prosperity-3>
- Lerner, ETF-vs-market imbalance causality
  <https://arxiv.org/abs/2204.03760>

Hard rule:

- if position limits stop full hedging, mine the **residual premium difference** between related baskets instead of pretending the direct residual is still clean

### Revealed counterparties / insiders / pattern bots

Core method:

1. align every named trade to the book state
2. treat each trader-side event as a separate signal event
3. measure signed future returns after:
   - trader buys
   - trader sells
   - trader buys from specific counterparty X
   - trader sells to specific counterparty Y
4. rank traders by:
   - signed forward return
   - hit rate
   - persistence horizon
   - cross-product spillover

Portable scans:

- direct copy-trade edge
- regime-only edge: widen/tighten your quotes after informed flow rather than crossing immediately
- constituent-to-basket spillover: if trader is informed in CROISSANTS, check whether that predicts ETF residual too

Why this deserves priority:

- later-round Prosperity data has repeatedly rewarded trader-ID recognition much more than high-complexity statistical models

References:

- jmerle Prosperity 2: named counterparty trades directly drove profitable directional rules in round 5
  <https://github.com/jmerle/imc-prosperity-2>
- Chris Roberts writeup: visualized all bots, found Olivia repeatedly bought lows / sold highs
  <https://github.com/chrispyroberts/imc-prosperity-3>
- AlphaBaguette writeup: used Olivia detection on multiple products and extended the signal from constituent to ETF
  <https://github.com/Sylvain-Topeza/imc-prosperity-3>
- Alpha Animals writeup: tried using insider flow as a regime indicator rather than pure copy-trading, but found it harder to stabilize
  <https://github.com/CarterT27/imc-prosperity-3>

Portable conclusion:

- first test direct copy-trading
- second test quote-skew / regime conditioning
- third test cross-asset propagation
- only after that should you try sophisticated sequence models

### Conversion / dual-venue / foreign-market products

Mining plan:

1. reconstruct implied local fair bid/ask from foreign price plus fees/tariffs
2. test whether a local taker exists at stable edges
3. run fill-adaptive edge search rather than hard-coding one static offset

Winner prior:

- round-2 ORCHIDS-style successes came from understanding the environment and taker mechanics better than from predicting the macro covariates

Reference:

- Eric Liu et al. on ORCHIDS: the big edge came from mechanism understanding plus adaptive edge search, not predictor regressions on sunlight/humidity
  <https://github.com/ericcccsliu/imc-prosperity-2>

Rule:

- whenever the docs expose tariffs, fees, conversions, or external quotes, first mine execution mechanics before macro predictors

### Options / derivative rounds

Core method:

1. fit a simple fair model first: Black-Scholes or competition-specific pricing identity
2. compute residuals at every strike / maturity proxy
3. standardize residuals or IVs into z-scores
4. hedge delta before claiming alpha

Portable scans:

- residual by strike
- IV mean reversion by moneyness
- relative-value scan across strikes
- chain consistency checks instead of only outright cheap/rich flags

Winner prior:

- the winning public writeups that mention options generally ended up using simple fair-value models plus residual standardization and hedging, not high-complexity calibration

Reference:

- AlphaBaguette writeup on voucher pricing / IV z-scores / delta aggregation
  <https://github.com/Sylvain-Topeza/imc-prosperity-3>

## Suggested priority order for future rounds

### Always do first

1. Drift / anchor / residual-sd decomposition per product
2. `imb1`, `micro_gap`, depth regime, spread regime
3. gap / depletion asymmetry if the book has visible level 2
4. if multi-asset: synthetic spread and lead/lag
5. if named counterparties exist: direct event study immediately

### Only do after the above is exhausted

- OFI / MLOFI on event-rich datasets
- change-point or regime segmentation
- options residual clustering
- cross-product spillover between informed trader and related basket

### High risk of becoming trash

- deep learning on three days of sparse competition data
- VPIN as a first-line insider detector
- raw time-of-day pattern mining without day-by-day sign stability
- visually discovered price patterns that do not survive an event study
- aggressive parameter sweeps before the signal definition itself is correct

## About VPIN / toxicity

VPIN-style toxicity measures are worth remembering conceptually, but not as a default first-line competition signal.

Why:

- they are mainly volatility / toxicity indicators, not guaranteed direction signals
- they are sensitive to trade classification choices
- several later critiques argue they need careful benchmarking before trust

References:

- VPIN parameter sensitivity: <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2427086>
- Andersen & Bondarenko critique: <https://metaquantuniverse.com/pdf/VPIN%20%26%20Flash%20Crash.pdf>

Competition guidance:

- use named-trader event studies, signed flow, and book-state changes first
- only add toxicity-style indicators if a later round clearly becomes flow-toxic and volatile

## Practical use

Round-2 scan:

```bash
python3 analysis/signal_scan.py --data-dir data/round2 --output analysis/round2_signal_scan_report.md
```

Later-round insider scan:

```bash
python3 analysis/counterparty_signal_scan.py --data-dir data/round5 --output analysis/round5_counterparty_report.md
```

Later-round ETF / basket scan:

```bash
python3 analysis/composite_signal_scan.py \
  --data-dir data/round3 \
  --spec path/to/relations.json \
  --output analysis/round3_composite_report.md
```

Example relation spec:

```json
{
  "relations": [
    {
      "name": "PICNIC_BASKET1",
      "target": "PICNIC_BASKET1",
      "components": {
        "CROISSANTS": 6,
        "JAMS": 3,
        "DJEMBES": 1
      }
    }
  ]
}
```

## Final take

The durable hierarchy so far is:

1. mechanics and fair-value decomposition
2. queue imbalance / micro-price
3. liquidity-gap asymmetry
4. synthetic residuals for composites
5. named-counterparty event studies

Anything fancier should have to beat those five cleanly before it earns code or strategy surface area.
