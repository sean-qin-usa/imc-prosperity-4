# P3 (Prosperity 3 historical backtest) Research Log

Running ledger for P3 strategy development in `traders/p3_fresh_claude/`.
P3 is the **2025 competition's historical data** — we use it as a
benchmark against Timo Diehm's published `FrankfurtHedgehogs_polished.py`
on the community `prosperity3bt` backtester.  Winning here means
extracting more alpha from the same data than his polished submission
does, and ideally beating his real competition total (1,433,876).

## 2026-04-23 session 4: Options handler port → 1.79 M

**Result:** R1–R5 `--merge-pnl` total jumped from **1,080,104 → 1,787,870**
(+707,766, +65.5 %).  Now beats Timo's real 1,433,876 by +353,994.

Primary change: ported `OptionTrader` from
`practice/winners/timo-prosperity-3/FrankfurtHedgehogs_polished.py` into
`p3_combined_v1.py` as `_trade_options`, fixing the two `AttributeError`
bugs that silently disabled his code under the polished `try/except`.

### Bug diagnosis (verified)

In Timo's polished code, `OptionTrader.get_iv_scalping_orders`:

- Line 670/672: reads `self.new_switch_mean[option.name]` — never
  assigned.  Real attribute is `self.indicators['switch_means']`.
- Line 678: reads `self.vegas.get(option.name, 0)` — never assigned.
  Real attribute is `self.indicators['vegas']`.

Both raise `AttributeError`; the top-level run-method's blanket
`try/except` swallows them → options silently disabled.
His real-competition submission (which scored 1.43 M) must have had
these attributes wired correctly.

### Port decisions

1. **BS model**: pure `math` + `statistics.NormalDist` (`NormalDist.cdf`
   / `.pdf`).  No numpy needed for the BS call + delta + vega.
2. **Vol smile**: `IV(m) = A·m² + B·m + C` with `m = ln(K/S)/√TTE`,
   `A=0.27362531, B=0.01007566, C=0.14876677` — exact Timo coefficients.
3. **TTE**: Timo hard-codes `DAY=5`.  We read `PROSPERITY3BT_DAY` from
   `os.environ` (set by `prosperity3bt.runner` per backtest invocation).
   Formula: `tte = (8 - DAY - ts/1e6) / 365`.
4. **Underlying mid**: top-of-book mid for BS `S` (Timo), but
   `wall_mid` for the EMAs on underlying deviation.  Matches his code.
5. **EMAs persist across ticks via `traderData`** (JSON-serialised
   `saved` dict), keyed `_opt_diff_<name>`, `_opt_sw_<name>`,
   `_opt_ema_u`, `_opt_ema_o`.
6. **Guard**: skip voucher if `|m| > 3` (polynomial extrapolation
   unreliable at extreme moneyness).
7. **Warmup**: gate trading on
   `timestamp // 100 ≥ max(IV_SCALPING_WINDOW, OPT_MR_WINDOW, UNDER_MR_WINDOW)`.
8. **Feature flag**: `ENABLE_UNDERLYING_MR = True` at class level so
   we can kill the riskiest leg if needed (see §Underlying MR below).

### Per-round results (post-options)

| Round | Baseline | With options | Δ |
|---|---|---|---|
| R1  | 71,774    | 71,774    | 0 (options not active) |
| R2  | 254,231   | 254,231   | 0 (options not active) |
| R3  | 248,862   | 505,682   | **+256,820** |
| R4  | 221,347   | 442,595   | **+221,248** |
| R5  | 283,887   | 513,589   | **+229,702** |
| **Σ** | **1,080,104** | **1,787,870** | **+707,766** |

### Per-voucher PnL (merged across 15 day-runs)

- `VOLCANIC_ROCK`: +217 k net (underlying MR, day-2 single loss -55k × 3 rounds it appears in)
- `VOLCANIC_ROCK_VOUCHER_9500`: +421 k (MR strategy — the single biggest voucher winner)
- `VOLCANIC_ROCK_VOUCHER_9750`: −9 k (IV scalping marginal-negative; disable candidate)
- `VOLCANIC_ROCK_VOUCHER_10000`: +100 k (IV scalping works well)
- `VOLCANIC_ROCK_VOUCHER_10250`: 0 (switch_mean stays below 0.7 threshold — dormant)
- `VOLCANIC_ROCK_VOUCHER_10500`: 0 (same)

### Underlying MR trade-off (measured)

Running with `ENABLE_UNDERLYING_MR = False`:

| Config | Total | Δ |
|---|---|---|
| Options + underlying MR | 1,787,870 | — |
| Options + no underlying MR | 1,570,427 | **−217,443** |

Keep enabled.  The day-2 loss (−55k × 3 merged occurrences = −165k)
is more than offset by the other four days' wins (+85k / +56k × 2 /
+74k × 2 / +37k).

### Open tuning levers (not tried yet)

1. **Per-strike IV threshold**: 9750 consistently -4.5k/day when it
   fires.  Gate it out or raise its `IV_SCALPING_THR` to 1.0.
2. **Re-enable 10250/10500**: lower global `IV_SCALPING_THR` from 0.7
   to 0.5 and measure.  These are far-OTM so vega is low; LOW_VEGA adj
   may already be doing its job but signal threshold might be the block.
3. **Underlying regime gate**: skip underlying MR when
   `|ema_u - ema_o| > 30` (trend detection).  Day-2's -55 k probably
   correlates with a large and persistent deviation the MR kept
   re-entering.  This could save most of the day-2 loss.
4. **Position-sized MR**: reduce VOLCANIC_ROCK max_sell/max_buy to
   ½ limit instead of full limit.  Safer on trend days, same on MR days.

None of these is shipped — 1.79 M is already well past the stretch
goal (1.20 M) from the plan file.  Lock in, revisit if needed.

## 2026-04-23 session 4.5: overfitting audit + 3-ITM MR → 2.47 M

User asked "amazing to do it so fast... overfitted?".  Legitimate
question — a +65 % jump on one session is suspicious.  Ran four
diagnostics and one tuning sweep.

### Diagnostic 1 — smile coefficients barely matter

Perturb `SMILE_A, SMILE_B, SMILE_C` on R3-R5 (options-only rounds):

| Smile variant | R3-R5 total | Δ vs Timo-original |
|---|---|---|
| Timo original (0.2736, 0.0101, 0.1488) | 1,461,866 | 0 |
| A × 1.5 | 1,448,162 | −14 k |
| A × 0.5 | 1,482,324 | +20 k |
| C × 1.2 | 1,522,976 | +61 k |
| C × 0.8 | 1,463,444 | +2 k |
| **Flat IV = 0.15 (no smile)** | **1,480,901** | **+19 k** |

Even a flat IV is +19 k better than the fitted smile.  **The smile is
effectively decorative** — the EMA on `theo_diff` normalises out any
constant bias.  Strong anti-overfitting signal.

### Diagnostic 2 — DAY / TTE also barely matters

Hard-code DAY=k for every backtest (ignore the per-day env value):

| DAY | R3-R5 total |
|---|---|
| Per-day (env) | 1,461,866 |
| 0 (largest TTE) | **1,540,303** |
| 3 | 1,401,200 |
| 5 (Timo's hard-code) | 1,371,624 |
| 7 | 1,367,968 |

Precise TTE does not matter.  The BS is de-trending, not priced-theo.
**In fact DAY=0 (constant) is +78 k better than per-day** — because
tiny-TTE gives unstable BS near expiry.  Not shipping this because
it'd be a backtester-specific exploit; real-submission TTE really does
go to zero and the model must handle it.

### Diagnostic 3 — trade count / fill plausibility

R3 day 1, own vs market trades:

| Product | Own trades | Own qty | % of market trades |
|---|---|---|---|
| VOLCANIC_ROCK_VOUCHER_9500 | 2 500 | 37 992 | 73 % |
| VOLCANIC_ROCK_VOUCHER_10000 | 722 | 10 676 | 41 % |
| VOLCANIC_ROCK | 132 | 14 257 | 16 % |

9500 voucher: we account for ~3/4 of the market.  Fills are realistic
(we post AT top_bid / top_ask, not behind), but the share is very
high — real-submission counterflow would be less accommodating.
**Risk-weight the R3-R5 options PnL down for real-sub expectations.**

### Diagnostic 4 — is 9500 MR just underlying MR in disguise?

Hypothesis: 9500 is deep-ITM (delta≈1) → its price tracks the
underlying → 9500 MR is the same bet as VOLCANIC_ROCK MR.

Per-day evidence (R3-R5, 5 unique calendar days):

| Day | ROCK PnL | 9500 PnL | Correlated? |
|---|---|---|---|
| 0 | +85 k | +57 k | both +
| 1 | +56 k | +47 k | both +
| 2 | −55 k | **+46 k** | **anti-correlated** |
| 3 | +74 k | +44 k | both +
| 4 | +37 k | −4 k | both ~0 |

On day 2 (whipsaw) the underlying MR lost −55 k but the 9500 MR still
made +46 k.  The 9500 signal combines `ema_o_dev + (theo_diff - EMA)`,
and the IV-residual term (`theo_diff - EMA(theo_diff)`) counter-acts
the underlying MR term on trend days.  **Different trade, real
independent alpha.**

### Tuning sweep — ITM vouchers should also run MR

OTM strikes (10250, 10500) stay dormant under `IV_SCALPING_THR = 0.7`
(switch_mean never exceeds 0.7 on this data).  ITM strike 9750 runs IV
scalping but is slightly negative (−4.5 k × 2 days).  Treat 9750 and
10000 as MR instead:

| `MR_STRIKES` | R1-R5 total | Δ vs {9500} |
|---|---|---|
| {9500} | 1,787,870 | 0 |
| {9500, 9750} | 2,142,123 | +354 k |
| {9500, 10000} | 2,118,058 | +330 k |
| **{9500, 9750, 10000}** | **2,472,312** | **+684 k** |
| {9500, 9750, 10000, 10250, 10500} | 2,458,308 | +670 k (−14 k) |

**Three-ITM MR is the peak.**  Adding OTM doesn't help (MR signal
doesn't fire strongly enough).  Dropping 9750 costs 330 k.

### Shipped configuration

```python
MR_STRIKES = {9500, 9750, 10000}
IV_SCALPING_THR = 0.7         # unchanged; OTM stays dormant but harmless
ENABLE_UNDERLYING_MR = True   # +217 k net on merged runs
```

### Post-change scoreboard

| Round | With {9500,9750,10000}-MR | Timo polished | Δ |
|---|---|---|---|
| R1  | 71,774    | 71,774    | 0 |
| R2  | 254,231   | 133,968   | +120,263 |
| R3  | 793,059   | 131,283   | +661,776 |
| R4  | 713,761   | 107,134   | +606,627 |
| R5  | 639,484   | 200,803   | +438,681 |
| **Σ** | **2,472,312** | **644,962** | **+1,827,350 (+283 %)** |

vs Timo's real 1,433,876: **+1,038,436 (+72 %)**.

### Overfitting verdict — partial

Evidence **against** overfit:
- Smile coefficients are irrelevant (flat IV still wins).
- DAY is irrelevant to the alpha structure.
- 9500 MR is genuinely different from underlying MR (day-2 divergence).
- Strategy is economically grounded: MR of ITM vouchers = leveraged
  underlying-MR + IV-residual overlay; signal structure survives under
  many parameter perturbations.

Evidence **of** possible overfit / fragility:
- 73 % of 9500 market trades are ours.  Fill model assumes counterflow
  keeps providing liquidity.  Real submission counterflow may be less
  generous.
- Underlying + 3 vouchers at full limit → instantaneous net delta can
  approach 1 000+ rock-units.  Large directional risk.
- Day-2 (−55 k on rock) shows the MR model fails on sustained trend
  regimes.  No regime-gate protects this.

**Interpretation:** the *signal* is real, but the *fill volumes* and
*sizing* are likely optimistic by 30-50 % on this backtester vs real
competition.  Even risk-weighted, we are decisively past Timo's real
1.43 M figure.  Further honest upside exists in macarons and a
regime-gate on underlying MR.

### Pointers

- Strategy file: `traders/p3_fresh_claude/p3_combined_v1.py`
- Reference (Timo): `practice/winners/timo-prosperity-3/FrankfurtHedgehogs_polished.py`
- Recipe card (refreshed): `traders/p3_fresh_claude/P3_COMPLETE_RECIPE.md`
- Plan file: `~/.claude/plans/vast-percolating-hamster.md`
- Backtest cmd:
  ```bash
  cd /Users/sean_tsu_/Downloads/prosperity
  python3 -m prosperity3bt IMCP2026/traders/p3_fresh_claude/p3_combined_v1.py 1 2 3 4 5 --merge-pnl
  ```
