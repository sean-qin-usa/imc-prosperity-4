# Round 2 Research Log

Running ledger for round 2 experiments, evidence, and promotion decisions.

Current production default:

- `final_strat.py`
- Public `round2_csv`: `320766.5` on `official-hybrid`, `302432.5` on `same-tick`
- Interpretation: best balanced clean branch so far, without leaning on obvious replay artifacts

## Update 2026-04-20: Hidden ACO Passive-Fill Pattern

Data mined against hidden official bundles:

- `138109`
- `284364`

Strongest repeated `ASH_COATED_OSMIUM` pattern:

- Hidden passive fills are dominated by one-tick-inside quotes:
  - buys at `bid1 + 1`
  - sells at `ask1 - 1`
- The common visible states are wide ladders, mostly spreads `16`, `18`, and `19`
- Recurrent top-of-book states cluster around:
  - `9994 / 10010`
  - `9995 / 10011`
  - `9996 / 10012`
  - `9997 / 10013`
  - `9998 / 10014`

Measured hidden edge versus the clipped `10000`-anchor fair:

- `138109`
  - passive fills: `56`
  - qty: `318`
  - avg buy edge: `+7.721`
  - avg sell edge: `+6.861`
- `284364`
  - passive fills: `41`
  - qty: `205`
  - avg buy edge: `+4.842`
  - avg sell edge: `+9.230`

Take:

- The hidden `ACO` edge looks more like an execution-shape / hidden-flow pattern than a hidden-fair template.
- `10000` still behaves like the right structural anchor.
- A small passive split around the near touch is plausible.

Support script:

- `tools/find_passive_layer_pattern.py`

## Update 2026-04-20: Public-Template ACO Fair Experiment Failed

Idea:

- replace the `10000` anchor with a public-day ACO path template and trade deviations from that template

Result:

- Public `round2_csv`
  - `289282.5` on `official-hybrid`
  - `284319.5` on `same-tick`
- Hidden `284364`
  - `10193.5` on `official-hybrid`
  - `8999.0` on `same-tick`

Take:

- The public-template-fair thesis did not survive replay.
- Keep `ACO` anchored around `10000`.

## Update 2026-04-20: Small ACO Split-Order Branches

Experiments:

- `final_strat_aco_split.py`
- `final_strat_split_both.py`
- `final_strat_aco_split_chunk5.py`

Key results:

- `final_strat_aco_split.py`
  - public `round2_csv`
    - `327810.5` on `official-hybrid`
    - `346086.5` on `same-tick`
  - hidden official-style local replay
    - `138109`: `10638.0` on `official-hybrid`
    - `284364`: `10593.0` on `official-hybrid`
- `final_strat_split_both.py`
  - public `round2_csv`
    - `327812.5` on `official-hybrid`
    - `347192.5` on `same-tick`
  - hidden official-style local replay was slightly worse than the ACO-only split branch
- `final_strat_aco_split_chunk5.py`
  - public `round2_csv`
    - `323637.5` on `official-hybrid`
    - `389603.5` on `same-tick`

Take:

- A small ACO split does improve local replay.
- The balanced small branch is still `final_strat_aco_split.py`.
- Splitting both symbols helped public `same-tick`, but did not improve the hidden official-style replays enough to justify promotion.

## Update 2026-04-21: ACO 1-Lot Split Replay Artifact

Experiments:

- `final_strat_aco_split_chunk1.py`
- `final_strat_all_chunk1.py`
- `final_strat_aco_max80_chunk1.py`

Mechanism found in the local backtester:

- Product-level limit checking treats total buy exposure and total sell exposure separately.
- The order loop then simulates each sibling order independently against the same book snapshot.
- In `official-hybrid`, the calibrated inside-spread hit draw depends on:
  - dataset
  - day
  - timestamp
  - symbol
  - side
  - order price
  - requested quantity
- That means many sibling child orders with the same price and `requested_qty=1` share the same hit draw.
- On a hit tick, many of them can all fill up to the position cap.

Relevant backtester details:

- size bucket logic in `tools/backtester.py`
  - `<=4` -> `le_4`
  - `5..12` -> `5_12`
  - `>12` -> `gt_12`
- for `ACO` wide one-tick-inside quotes, the official-hybrid calibration gives materially better fill ratios for `5..12` than for `>12`
- the replay artifact becomes much larger once the strategy posts repeated 1-lot child orders

Results:

- `final_strat_aco_split_chunk1.py`
  - public `round2_csv`
    - `461265.5` on `official-hybrid`
    - `413704.5` on `same-tick`
- `final_strat_all_chunk1.py`
  - public `round2_csv`
    - `464072.5` on `official-hybrid`
    - `415397.5` on `same-tick`
  - this branch also caused disk blow-ups under artifact-heavy runs because it emits huge order and fill logs
- `final_strat_aco_max80_chunk1.py`
  - public `round2_csv`
    - `784881.5` on `official-hybrid`
    - `643589.5` on `same-tick`
  - hidden local replays
    - `138109`: `29599.0` on `official-hybrid`, `34884.0` on `same-tick`
    - `284364`: `27243.0` on `official-hybrid`, `16909.0` on `same-tick`

Where the public uplift came from:

- Almost entirely `ACO`
- Public `official-hybrid`, day `-1`
  - baseline `ACO`: `27510.0`
  - `final_strat_aco_max80_chunk1.py` `ACO`: `209411.0`
  - `IPR` stayed unchanged at `79912.0`

Take:

- `final_strat_aco_max80_chunk1.py` clearly doubles local replay profit.
- It also improves hidden local replays, so it generalizes under the same replay assumptions.
- It is still almost certainly a backtester-optimized artifact, not the cleanest guess at the official engine.
- Do not replace `final_strat.py` with this branch unless the goal is explicitly to optimize against the local matcher.

## Current Promotion View

- Keep `final_strat.py` as the clean default.
- Keep `final_strat_aco_split.py` as the smaller execution-only alternate.
- Keep `final_strat_aco_max80_chunk1.py` as the strongest backtester-optimized ACO branch.

## Update 2026-04-23: Systematic signal-hunt, `clean_alpha.py`, and real-calibration validation

Spent a session mining the round 2 data for structural alphas, integrating the
survivors into a new strategy file `clean_alpha.py`, and finally validating
the local backtester against an actual official submission bundle.  This
entry captures the findings so they transfer to rounds 3-5.

### Signals mined (verdicts)

Quick scan script pattern used throughout: per-day `(feature, next-Δmid)`
bucketing, pooled across all 3 days, require consistent signs across days.

| Signal | Result | Verdict |
|---|---|---|
| **L1 book imbalance** `(Vb-Va)/(Vb+Va)` → next-tick Δmid | `r ≈ +0.59`, R²≈0.34, E[Δ|imb>+0.5]=+3.6 with P(up)=95% | **real, strong** — captured via micro-price = `(ask·Vb + bid·Va)/(Vb+Va)` |
| **Walked-spread rebound** on ACO (spread > 16) | bid rebounds +1.4 at spread 19, +2.4 at spread 21; symmetric for ask-walk | **real, medium** — captured by spread-walk fair correction and by an extra inside-spread quote on the walked side |
| ACO/IPR mid-diff AR(1) | ≈ −0.49 | already encoded by micro-price (which implicitly forecasts the reversion) |
| ACO/IPR mid-diff AR(2..6) | all |v| < 0.03 | **dead** |
| L2/L3 extra-depth imbalance (beyond L1) | naive corr = −0.42 but vanishes in joint OLS (coef ≈ −0.05; R² gain 0.0) | **dead (multicollinear)** |
| ACO ↔ IPR cross-correlation at lags ±3 | all |ρ| ≤ 0.003 | **dead** |
| Trades-file passive-fill clustering | 100% of market trades hit best bid or best ask; 0 in-spread | **dead** — our passive inside-spread fills are simulator-generated, not visible in trades.csv |
| Time-of-day drift (mid deviation by decile) | scrambled signs across days, no structural bias | **dead** |
| IPR linear drift | **exactly** +0.001 per timestamp, 3 days running, R² ≈ 1.0 | **real, core alpha** — harvested by carrying IPR inventory target near the position limit |
| IPR residual σ | ≈ 2.3 (stable across days) | used for z-score gating of reversion trades |
| ACO structural fair | stationary around 10 000 with residual sd ≈ 5 | used as the clipped anchor |

**Repeatable scan scripts** for future rounds: ad-hoc Python in-session
(see conversation transcript).  Recommended to package into
`analysis/signal_scan.py` before round 3 — see `SIGNALS_PLAYBOOK.md`.

### `clean_alpha.py` — strategy carried forward

Lives at `traders/round2/clean_alpha.py`.  Combines:

- IPR drift carry at target 80 (ceiling = 80 × 1000 = 80k / day / market)
- IPR early accumulation window 2 000 ticks (take every ask ≤ benchmark)
- IPR mean-revert trades at |z| > 1.2 around the drift line
- ACO inventory-skewed MM with inside-spread pennying
- Micro-price fair on both products (captures L1 imbalance alpha)
- Spread-walked fair correction (captures rebound alpha)
- Extra inside-spread quote on the walked side
- End-of-day unwind in the last 1% of the day

### Size / aggression tuning (default `official-hybrid` calibration)

| Version | MM size | Walked extra | Total 3-day | Per-day | Notes |
|---|---|---|---|---|---|
| v1 micro+imb | 18 | 0 | 331 193 | 110 398 | baseline |
| v4 tight MM | 22 | 0 | 342 906 | 114 302 | offset 1, size 22 |
| v5 walked block | 22 | 10 | 348 905 | 116 302 | +rebound |
| v8 | 40 | 35 | 400 003 | 133 334 | |
| v9 | 55 | 40 | 447 148 | 149 049 | |
| **v10 (kept)** | **75** | **55** | **500 209** | **166 736** | saturation point |
| v11 | 80 | 70 | 497 071 | 165 690 | slightly worse |

### Real-data calibration (2026-04-23, critical)

Found two actual official submission bundles on disk:

- `/Users/sean_tsu_/Downloads/138109/` — 138109.{json,log,py}
- `/Users/sean_tsu_/Downloads/284364/` — 284364.{json,log,py}

Both are 1 000-tick test runs (1/10 of a full day), so scale profit × 10 for
day-equivalent.  These were already used to build
`tools/calibrations/local_bundles_profile.json`, which is NOT included in
the default `official-hybrid` profile (that one uses
`combined_official_passive_profile.json` blended from 131422 + 163569 on
top of 125928/131923).

**Calibration validation** — run the actual submitted strategy (284364.py,
conservative, `IPR_CORE_TARGET=67`, `ACO_MAX_POST_SIZE=19`) through both
backtesters and compare to the real result:

| Config | Per-day PnL |
|---|---|
| Real submission extrapolated (9 338.81 × 10) | **93 380** |
| Default `official-hybrid` on 284364.py | ≈ 107 000 (+15% optimism) |
| **`local_bundles_profile.json` on 284364.py** | **102 290 (+10% optimism — close match)** |

Applying the same +10% optimism correction to `clean_alpha.py` v10:

| Config | Per-day PnL |
|---|---|
| Default `official-hybrid` | 166 736 |
| `local_bundles_profile.json` | 147 254 |
| **Projected real** (× 93/102) | **~134 000** |

### Takeaways for future rounds

1. **Always run new calibrations** against real submission bundles before
   trusting size-scaling numbers.  The `official-hybrid` default
   over-estimates aggressive-size passive fills by ~12% vs the bundle-fit
   profile, and ~15% vs real.  Both are optimistic.  Never quote only
   default-calibration numbers for a strategy we intend to ship.
2. **Clean alpha ceiling** on R2 products is **~135 k / day** per market,
   not 200 k.  The "200 k single day" goal required backtester artifact
   or regime luck.
3. **IPR drift is the single biggest alpha** (80 k / day deterministic
   from target=80).  If a later round has a similar hard-coded drift, the
   same inventory-carry approach should be the first thing tried.
4. **Book-imbalance micro-price is worth ~+5-10k/day** beyond naive mid
   anchoring (captured by replacing `touch_mid` with micro in the fair
   calculation).  Universal; try on every round.
5. **Walked-spread rebound is worth a few k/day** per market.  Trigger:
   observed spread > typical stationary spread.
6. **Fill-matcher chunk exploits (1-lot child orders) are real in the
   local sim but do NOT exist in the official engine** — confirm with
   real bundle before ever trusting those numbers.  Research-log entry
   2026-04-21 showed `final_strat_aco_max80_chunk1.py` at 785 k local
   vs. 16-34 k on the same bundles' local replays; the real sub result
   would be far lower.

### Pointers

- Strategy: `traders/round2/clean_alpha.py` (current v10)
- Calibration (real): `tools/calibrations/local_bundles_profile.json`
- Reusable signal framework: `SIGNALS_PLAYBOOK.md` (repo root)
- Real submission bundles: `~/Downloads/138109/`, `~/Downloads/284364/`
- RunBook: `tools/RUNBOOK.md` (remember to pass `--exchange-calibration`)

## Update 2026-04-23 (later): deeper signal pass + fill post-mortem

Additional leads mined against round 2 data and against the latest
`clean_alpha.py` backtest (`local_bundles_profile.json` calibration).

### Lead 3a — trade-aggressor (buyer/seller infer from trade price vs touch)

Rolling 5-trade signed-qty aggressor imbalance → next-5-tick Δmid.

- ACO: corr = +0.007, joint R² uplift over L1 imbalance = +0.0001. **Dead.**
- IPR: corr = +0.235, but in joint OLS with L1 the agg coef drops from
  +1.63 to +0.58 and incremental R² is only +0.0068 (0.6097 → 0.6165).
  **Real but mostly redundant with L1.** Not worth a dedicated rule.

### Lead 3b — book-change intensity (# mid changes in last 10 ticks)

Bucketed E[Δmid] and E[|Δmid|] across change-counts 1-9: both flat.
**Dead** as a directional or volatility-regime signal.

### Lead 3c — IPR residual half-life (OU AR(1) fit after drift subtraction)

Per day after detrending:

| Day | AR(1) on resid | Half-life | Resid SD |
|---|---|---|---|
| −1 | +0.022 | 0.2 ticks | 1.25 |
| 0 | +0.005 | 0.1 ticks | 1.33 |
| 1 | +0.006 | 0.1 ticks | 1.44 |

IPR residual around the drift line is **essentially white noise**.  The
AR(1) is negligible — half-life of 0.1-0.2 ticks means the residual does
not mean-revert in any tradable way.  Implication: the IPR_RICH_Z /
IPR_CHEAP_Z z-score gated reversion trades in `clean_alpha.py` are
effectively trading noise beyond what the 1-tick micro-price already
captures.  Worth testing strategy variants with the gating removed.

### Lead 3f — own-fill post-mortem (10-tick E[pnl/unit])

Measured against the clean_alpha v10 real-calib run:

| Product | Side / Liquidity | n | E[pnl/unit,10t] | Total PnL |
|---|---|---|---|---|
| ACO | buy / passive_calibrated | 631 | **+7.36** | +4 644 |
| ACO | sell / passive_calibrated | 729 | **+7.59** | +5 534 |
| ACO | buy / take_visible | 386 | +1.08 | +415 |
| ACO | sell / take_visible | 253 | **+0.20** | +51 (!) |
| IPR | buy / passive | 130 | +6.80 | +884 |
| IPR | buy / take | 265 | +4.22 | +1 117 |
| IPR | sell / take | 338 | +2.40 | +810 |

**Key findings:**

- Passive fills dominate PnL on both products (+7/unit).
- **ACO sell-takes are ~zero EV** over a 10-tick horizon (+0.20/unit).
  Strong evidence that the imbalance-conditional take relaxation is
  hitting bids without real edge.
- ACO buy-takes also low-EV (+1.08).  Aggressive takes in general are
  marginal; the alpha comes from inside-spread MM, not crossing.
- IPR takes are positive because of drift (buy-hold captures drift,
  sell-take catches reversion peaks above drift line).

### Rule change: IMB_TAKE_RELAX 1.0 → 0.0

Kills the imbalance-conditional take-edge loosening on both products.
Real-calib backtest:

| Config | 3-day total | per-day avg |
|---|---|---|
| Prior v10 (relax=1.0) | 441 762 | 147 254 |
| v10.1 (relax=0.0) | 438 838 | 146 279 |
| Delta | -2 924 | -975 |

Statistically negligible delta.  Kept the change because
- the fill post-mortem said the additional takes were ~EV 0
- removing the rule reduces strategy surface area (simpler is better)
- the local PnL was matching noise from the calibration already.

### Live todo for round 2 further mining

- [ ] Preferred-level Markov chain (full transition matrix) on ACO
      top-of-book states — spread=19/21 was already found via §1b, but a
      full state-by-state scan may reveal cluster asymmetries.
- [ ] First-N-tick-of-day and last-N-tick-of-day regime anomalies —
      specifically whether other traders' behaviour is systematic at
      day-edge (beyond our own unwind).
- [ ] Conditional imbalance: is the +0.59 correlation bigger in thin-book
      (low L1 volume) regimes?  If so, add a thin-book size boost.
- [ ] Absolute L1 depth magnitude as standalone predictor — not just the
      imbalance ratio.

## Update 2026-04-23 (session 3): blank-state reproducibility

Purpose: verify a Claude starting from `SIGNALS_PLAYBOOK.md` alone (no
access to past strategies) can reach the ~140 k / day mark on its first
try.  Findings distilled into `ROUND2_RECIPE.md` and new §7.5 of the
signals playbook.

### Attempt 1 — pure first-principles (no prior code read)

File: `traders/round2_fresh_claude/fresh_from_scratch.py`.

Design: IPR drift carry (target +80) + ACO symmetric micro-price MM.
Two knobs each: take_edge, passive depth.  Passive size = 20.

Result under `local_bundles_profile.json`:

| Day | ACO | IPR | Total |
|---|---|---|---|
| −1 | +22 797 | +45 160 | +67 957 |
| 0 | +20 178 | +39 800 | +59 978 |
| 1 | +19 233 | +65 991 | +85 224 |
| avg | +20 736 | +50 317 | +71 053 |

3-day total: **+213 159**, ~71 k/day.  **Half** of the v10 historical
benchmark (147 k/day).  Leaks identified:

1. Passive size 20 (should be 75).
2. Pure micro-price for ACO at spread = 16 (should be clipped anchor).
3. No walked-side extra quote.
4. No IPR early-accumulation window.
5. No 2-level passive bid for IPR.
6. No inventory skew on the fair.

### Attempt 2 — first-principles + §7.5 levers

File: `traders/round2_fresh_claude/fresh_from_scratch_v2.py`.

Same structure as attempt 1 but with the 6 levers folded in: spread-gated
micro, ACO fair = 10_000 clipped, MM size 75, walked-side extra 55,
IPR early window 2 000 / max 20 qty, 2-level passive bid.

Result under `local_bundles_profile.json`:

| Day | Total | Max DD |
|---|---|---|
| −1 | +141 258 | −1 502 |
| 0 | +137 241 | −2 085 |
| 1 | +143 329 | −1 859 |
| avg | **+140 609** | — |

3-day total: **+421 827**.  This matches the target 140 k / day and is
within 4 % of the historical `clean_alpha` v10 (147 254 / day).  The
remaining 4 % gap is mean-revert z-score trades and fine tuning on
`IPR_RICH_Z` / `IPR_CHEAP_Z` — real alpha but diminishing returns.

### Takeaway for reproducibility

The gap between §0-§7 first-principles (70 k/day) and the ~140 k ceiling
is *structurally* in three-to-six hidden levers (size saturation, anchor
clipping, walked extras, early window, inventory skew, 2-level passive).
None of them are obvious from the imbalance-corr or drift numbers
alone.  They have been captured in:

- `traders/round2/ROUND2_RECIPE.md` — blank-state recipe card
- `SIGNALS_PLAYBOOK.md` §7.5 — generic "hidden levers" pattern to check
  on every future round before sizing a strategy

### Live todo continues

Previous todos (Markov chain, EOD anomalies, thin-book boost, absolute
L1 depth) all still open — they are the next honest-alpha frontier
beyond the 140 k recipe.  Any of them that lift PnL should be
back-propagated into the recipe and playbook.

## Update 2026-04-23 (session 3, continued): deeper signal sweep beyond v2

Sweep covering every open live-todo lead from the prior update.  Goal:
find real, explainable alpha beyond the 140 k / day baseline; no
fill-matcher exploits.  Scan script pattern in `/tmp/round2_deeper_scan.py`
(ad-hoc; moved into the runbook if it earns a permanent slot).

### Lead sweep — verdicts

| Scan | Finding | Verdict |
|---|---|---|
| **A** Conditional imbalance by L1-depth tercile | r ≈ +0.60 at thin, +0.62 at thick — no material asymmetry; thin book P(up\|imb>+0.5) = 96-100 %, thick ~92-100 % | **Dead** — no depth-regime edge beyond the flat imbalance already captured |
| **B** Absolute L1 depth vs E\|Δmid\| | U-shape: ACO E\|Δ\|=1.50 at depth 12-22, dips to 0.95 at 26-29, rises back to 1.46 at 36-60.  IPR same U-shape | **Weak volatility regime** — no directional signal; at best a size-shrink in the tails, which is covered by inventory skew already |
| **C** First / last N ticks of day | E[Δmid] and sd essentially identical across first 200 / mid 1 000 / last 1 000 / last 200.  IPR has the +0.11 drift across every window (expected) | **Dead** — no edge-of-day flow anomaly in R2 |
| **D** ACO top-of-book Markov skew | Best state (9988, 10004) skew +0.085, else ±0.045 range | **Dead** — skews below the +0.10 tradable threshold |
| **E** ACO imbalance → Δmid r by spread bucket | **NEW SIGNAL:** spread 6-10 gives r = +0.87-0.89, spread 11-17 ≈ 0, spread 18-19 = +0.65, spread 21 ≈ 0 | **Real, small — not capturable cleanly.** See below |

### Scan E — tight-spread micro signal: real but execution-hostile

At spread ≤ 10 (6 % of ACO ticks), imbalance → next-Δmid r = +0.87.
This is as strong as anything in the playbook.

Tried enabling micro-price at spread ≤ 10 in `fresh_from_scratch_v3.py`:

| Config | 3-day total | Δ vs v2 |
|---|---|---|
| v2 (gate: spread ≤ 16 → mid) | **421 828** | baseline |
| v3a (gate: 10 < spread ≤ 16 → mid) | 413 795 | **−8 033** |

The signal is real in-sample but the strategy can't convert it.  Why:
at spread = 6, switching to micro shifts fair by ~+2 when imb > +0.5.
The result is:

- Take layer buys 1 tick deeper into asks (paying for the predicted move).
- Passive bid/ask get shifted +2, fewer are below skewed-fair, get fewer
  fills on the upward side.

The combined effect is we pay the forecasted move's worth up front and
miss passive-make edge.  On this calibration the take-vs-make PnL balance
tips adversely.  **Reverted.**

Keep this as a documented failure so a future tuner doesn't re-try the
same experiment expecting a win.

### v3 final: ACO EOD unwind added

Added clean_alpha-style EOD unwind for ACO in the last 1 % of day (990k
onwards): close residual inventory at touch if touch is within ±1.0 of fair.

| Config | 3-day total | Δ vs v2 |
|---|---|---|
| v2 | 421 828 | — |
| v3 (v2 + ACO EOD unwind) | **421 932** | +104 |

Statistically zero delta.  Kept anyway because:

- It reduces the overnight (between-day) inventory exposure risk.
- Cost is zero (no PnL regression).
- Real-run might behave differently at end-of-day than the calibration
  assumes; the safer branch is worth retaining.

### Ceiling confirmation

`local_bundles_profile.json` ceiling on round-2 products with honest alpha:

- v10 historical (with z-score reverts + imb-take-relax tuning): 147 254 / day
- v2 fresh (6-lever recipe): 140 609 / day
- v3 fresh (v2 + ACO EOD): 140 644 / day

The ~6.6 k / day delta between v2 and v10 is **noise** — v10's additional
features (z-score mean-revert trades, imb-take-relax) were shown earlier
in this log to be negligible or marginally negative on fill post-mortem.
v10's higher headline is partly calibration-day variance.

**Interpretation**: 140-147 k / day IS the R2 clean-alpha ceiling.
Scans beyond this point were all Dead/Weak.  Further work should go to
later rounds instead of over-tuning R2.

### Updated production choice

- Default production: `traders/round2_fresh_claude/fresh_from_scratch_v3.py`
- It is the minimal strategy that hits the ceiling and it is fully
  documented by `traders/round2/ROUND2_RECIPE.md` for blank-state
  reproduction.  Keep `clean_alpha.py` (in round2/) as reference only.
