# Round 3 — Blank-State Recipe

**Snapshot**: Round 3 opened 2026-04-24 12:00 CEST. Final PnL resets
to zero for GOAT (R3/R4/R5). 48-hour round.

**Final ship (2026-04-25, session 9 close)**:

> **`traders/round3/combined_ship_v29_mirror.py` → +582,866 bt** (alpha-floor 445,295).
> 427141 chassis + V4000/V4500 Citadel mirror at TARGET=282/282, cap=10.
>
> **Verified live: 442,794** (test_results/442794/) — conversion **0.760×** of bt.
> The +63k bt over v28_warmup65 converted to **+171 live**: V4000/V4500 deep-ITM
> mirror is mostly matching-engine wallpaper (dead-alpha class, like voucher MR
> and synth IMB). Alpha-floor +90k overstated the sleeve's live edge.
>
> ⚠️ **Live conversion correction**: earlier sessions claimed v25 live = 525,560
> (1.057×) — that was a misread of test_results dir names. Actual v25 live =
> **425,560** (0.856×). Citadel-class sleeves UNDER-convert vs jmerle bt; treat
> jmerle as upper bound, not lower bound. See `feedback_citadel_overconverts_live.md`.
>
> Live ladder (file ID = R3 cumulative leaderboard):
>
> | Ship | jmerle bt | Live | Conversion |
> |---|---|---|---|
> | v15 | 443,484 | 417,605 | 0.942× |
> | v25 (Citadel cap=15) | 497,324 | 425,560 | 0.856× |
> | 427141 (v27 chassis port) | 516,679 | 427,141 | 0.827× |
> | v28_warmup65 | 519,679 | 442,623 | 0.852× |
> | **v29_mirror (final)** | **582,866** | **442,794** | **0.760×** |
>
> **Best single-knob win**: WARMUP=65 (+3k bt over v27) converted to +15,482 live
> — single-knob retunes can multiply 5× bt-to-live when they fix a real timing issue.
>
> Lineage:
>   v15 → v23 (asym + carry + hdrift) → v25 (Citadel cap=15)
>   → v26 (v24 + cap=8, 511k bt) → 427141 (chassis port, 516k bt)
>   → v28_warmup65 (519k bt) → **v29_mirror (V4000/V4500 mirror, 582k bt)**
>
> See `RESEARCH_LOG.md` session 8 + 9 close, `feedback_citadel_overconverts_live.md`,
> `reference_round3_v29_mirror_ship.md`, `reference_round3_session9_findings.md`.

- `traders/round3/combined_ship_v23.py` → **+451,331 backtest** (alpha
  floor 280,836).  CONSERVATIVE ship.  Stacks 3 independent additions over v15:
    - v15_hdrift drift-regime CLIP gate (+1,964; +1,130 real alpha)
    - VEV drift carry on V5000-5300, target=300 (+1,594 ME fills)
    - asym INV_SKEW LONG=-0.004 / SHORT=0.014 (+4,289 ME fills, -502 alpha)
  Total v15→v23: +7,847 bt.  Live forecast ~424k.  No `import os`.
- `traders/round3/combined_ship_v22.py` → **+447,042 backtest** (alpha
  floor 281,338).  Conservative ship: v15_hdrift + VEV carry only,
  no asym INV_SKEW.  Strictly monotone-improving alpha floor.
- `traders/round3/combined_ship_v21.py` → +445,078 (v20 + VEV carry,
  before stacking with v15_hdrift).  Superseded by v22/v23.
- `traders/round3/combined_ship_v20.py` → +443,484 (multi-level VFE
  carry + synth V4000/V4500 carry — live-defensive on top of v15).
- `traders/round3/combined_ship_v15.py` → +443,484 / **live 417,605**
  (single biggest live jump in ladder; VFE passive drift carry
  converted at 127% bt-to-live).
- `traders/round3/combined_ship_v14.py` → +429,016 (HYDROGEL retune +
  synth IMB sizing, before VFE drift carry).
- `traders/round3/combined_ship_v12.py` → +429,028 (4-knob HYDROGEL
  joint micro-tune over v11; first session-6 ship).
- `traders/round3/combined_ship_v11.py` → +428,754 / **live +399,113**.
  Prior best ship.
- `traders/round3/combined_ship_v10.py` → +341,808 / live +398,980
  (v11 minus aggressive voucher MR — converts ~1-3% to live anyway).
- `traders/round3/combined_ship_v7.py` → +318,576 (intermediate from
  session 6 before discovering parallel v11).
- `traders/round3/combined_ship_v6.py` → +317,360 (v7 minus TE=0.6).
- `traders/round3/combined_ship_v4.py` → +312,124 / live +395,880.
- `traders/round3/combined_ship_v5.py` → 310,198 (v4 minus VEV_5300).

**Session 6 audit findings**:
- P3 session-4.5 winning move (move ITM strikes from IV-scalp to MR)
  REGRESSED in P4 by -25k to -485k across 8 variants.  P4 microstructure
  differs (deep-ITM has 21-tick spread; OTM has vega<1).
- SIGMA sensitivity is high in P4 (peak 0.23, ±0.05 costs 60-70k).
  Different from P3 where smile was decorative.
- CLIP_VOL_K=0.795 contradicts prior memo claim that ">0.3 didn't help
  in combined".  Cliff still at 0.80 (matches `h_only_v15`).

**Earlier ablations against ship_v4 (session 5)**: 11 variants
none-beat-it; most assumed CLIP_VOL_K=0.3 fixed and missed the joint
optimum.

**Live PnL ladder** (test_results/):
- h_only_v8 (HYDROGEL only): 391,745 live (172k backtest → 2.27x)
- combined_ship_v1: 393,037 live (268k backtest)
- combined_ship_v2: 395,505 live (279k backtest)

**KEY INSIGHT**: voucher MR alpha barely converts to live (~1-3% rate).
The HYDROGEL passive sleeves do all the heavy lifting in live (~99%).
Optimize HYDROGEL + passive-make over voucher signal tuning.

**Deltas v4 over v2**: HYDROGEL retune (h_only_v14: anchor 9985→9983,
skew 0.015→0.014, +3.6k); ATM smile-EMA MM on 5400/5500 (+22k);
lottery on V6000/V6500 (+0.9k). +8.7k of the +33k backtest gain is
real alpha (not matching-engine).

**Delta from v1**: ONE line — `combined = ema_o_dev + 2.25 * iv_dev`
(was `1.0 * iv_dev`). Sweep peak at 2.25; backtester +11,347 vs v1.
The IV-residual signal is per-unit ~2x more predictive than the
underlying-EMA deviation. Same threshold, window, strikes, sleeves.

**Prior ship (session 2)**:
`traders/round3/combined_ship_v1.py` → +268,008 / +124,854. Live
+393,037.

Sleeves layered (each independently verified):

1. **HYDROGEL_PACK** (h_only_v8 handler): own-microstructure MM with
   AR(1) lean, vol-adaptive CLIP, anchor 9985. +171,890 alone.
2. **VEV_4000 / VEV_4500** (baseline_v5 synthetic MM): flat σ=0.23 BS
   theo. Spread on V4000 = 21 ticks. +~8k combined.
3. **VEV_5000 / 5100 / 5200 / 5300** (Timo P3R3-style MR): combined
   `ema_o_dev + iv_dev` signal. +~71k.
4. **VELVETFRUIT_EXTRACT underlying MR** (Timo P3R3 port): cross
   spread on |ema_o_dev| > 5. +~19k.

**Prior ship (session 1, kept for reference)**:
`traders/round3/h_only_v8.py` → +171,890 (HYDROGEL alone).
`traders/round3/baseline_v5.py` → +167,930 (HYDROGEL + V4000/V4500
 synthetic MM, no IV-residual sleeves).

## 1. Products and limits

| Product | Limit | Class |
|---|---|---|
| HYDROGEL_PACK | 200 | Stationary MM anchor ≈ 9990, std 25-38, mode spread 16 |
| VELVETFRUIT_EXTRACT | 200 | Underlying ≈ 5248, mild drift, tight 5-spread |
| VEV_4000, VEV_4500 | 300 each | Deep-ITM calls; trade at intrinsic S-K (basis std < 1 tick) |
| VEV_5000, 5100, 5200 | 300 each | Near-ATM calls, delta 0.9-1.0 |
| VEV_5300, 5400, 5500 | 300 each | Slight OTM calls, tight spread (1-2 ticks), active trading |
| VEV_6000, VEV_6500 | 300 each | Dead OTM (mid=0.5, trades at 0). Zero EV in v5 |

## 2. The key non-obvious levers (blank-state critical)

### HYDROGEL_PACK (ACO-class)

```python
H_ANCHOR = 9990.0    # 3-day mean, NOT 10000; crucial
H_CLIP = 30.0        # fair follows touch_mid within ±30 of anchor.
                     # Critical lever: CLIP<20 crashes PnL (~40k loss).
H_INV_SKEW = 0.015   # mild skew, 0.035 was too aggressive (-20% PnL)
H_MAX_POST_SIZE = 20 # plateau 15-30; larger just costs $
H_PENNY_EDGE = 1.5   # insensitive 0.5-3.0
H_PASSIVE_OFFSET = 8.0
H_WIDE_SPREAD = 8
H_TAKE_EDGE = 0.0
H_REDUCE_EDGE = 1.0
```

**Plateau**: size ∈ {15-30}, skew ∈ {0.010-0.020}, CLIP ∈ {28-30}.
All grid cells in this 3x3 region give 145-150k 3-day.

### VEV_4000 / VEV_4500 (synthetic-underlying MM)

```python
VOUCHER_STRIKES = {"VEV_4000": 4000, "VEV_4500": 4500}
SIGMA = 0.23          # flat smile, valid across strikes 5000-5500
VS_TAKE_EDGE = 0.0    # 0 is the peak; increasing to 0.5 → -6k PnL
VS_INV_SKEW = 0.005
VS_MAX_POST_SIZE = 40
VS_PENNY_EDGE = 1.0
VS_WIDE_SPREAD = 3
```

Note: fair = BS theo with σ=0.23. For deep-ITM (4000/4500) this is
essentially `S - K + tiny_time_value`. MM gets 5-13k per voucher
across 3 days. Most of V4500's PnL comes from take side.

### Do NOT (verified bad)

1. **VELVETFRUIT_EXTRACT take-only**: -EV on every threshold (v_te ∈
   {0.5, 1, 1.5, 2, 3}). Best non-trading config = 0. Leave alone.
2. **VELVETFRUIT MM inside-touch**: -60k/day. Tight 5-spread means
   any inside-touch quote gets adverse-selected.
3. **Flat-IV MM on ATM strikes (5000-5300)**: -25k/day on day 2. σ=0.23
   is ~0.005 off market IV, enough to pull the take side into adverse
   fills. Need proper IV-residual logic before touching.
4. **Anchor 10000 for HYDROGEL**: mean is 9990, not 10000. 10 ticks
   matters on a 16-spread book.
5. **High HYDROGEL inv_skew (0.035+)**: aggressive skew crashes PnL
   from 149k to 32k. Use 0.010-0.020.

### Timo P3R3-port — IV-residual MR (NEW in session 2)

```python
# Module-level constants (mirror Timo verbatim)
THR_OPEN, THR_CLOSE = 0.5, 0.0
LOW_VEGA_THR_ADJ = 0.5
THEO_NORM_WINDOW = 20      # EMA window for theo_diff itself
IV_SCALPING_WINDOW = 100   # EMA window for |theo_diff - mean|
IV_SCALPING_THR = 0.7      # scalp regime gate
OPT_MR_WINDOW = 30         # EMA window for underlying mid (peak — sensitive)
OPT_MR_THR = 5             # peak — sensitive

# class Trader
ENABLE_UNDERLYING_MR = True
UNDER_MR_THR = 5           # peak

SCALP_STRIKES = {}                                    # OTM scalp didn't fire
MR_STRIKES = {"VEV_5000": 5000, "VEV_5100": 5100,
              "VEV_5200": 5200, "VEV_5300": 5300}
```

**Threshold sensitivity** (do NOT casually retune):

- `OPT_MR_THR`: 3→-542k, 4→-66k, **5→+249k**, 6→235k, 7→248k.
- `UNDER_MR_THR`: 3→175k, 4→251k, **5→268k**, 6→255k, 7→254k, 10→249k.
- `OPT_MR_WINDOW`: 20→222k, 25→242k, **30→268k**, 40→117k, 50→-410.

The MR signal alpha lives in rare large deviations (~5+ ticks). Trading
the small ones is noise — that's why thr=3-4 blows up.

## 3. Reproduction command

```bash
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026

# Current ship (combined v8 → ship_v1):
python3 tools/jmerle_backtester.py traders/round3/combined_ship_v1.py 3 --merge-pnl --no-out
# Expected: day 0 = 72,648; day 1 = 102,805; day 2 = 92,555; total 268,008.

# Prior ship (HYDROGEL only):
python3 tools/jmerle_backtester.py traders/round3/h_only_v8.py 3 --merge-pnl --no-out
# Expected: day 0 = 61,791; day 1 = 52,465; day 2 = 57,634; total 171,890.

# Original session-1 baseline (HYDROGEL + synthetic ITM MM):
python3 tools/jmerle_backtester.py traders/round3/baseline_v5.py 3 --merge-pnl --no-out
# Expected: day 0 = 61,499; day 1 = 54,438; day 2 = 52,094; total 168,031.
```

## 4. Manual Challenge — Ornamental Bio-Pod bids

Reserves uniform on {670, 675, ..., 920} — 51 values, step 5. Fair
sale 920. Two-bid auction.

### Rules recap

- If b1 ≥ reserve: trade at b1 (profit 920 - b1).
- If b1 < reserve ≤ b2:
  - If b2 > avg_b2 (global mean of 2nd bids): trade at b2 (profit 920 - b2)
  - Else: penalty factor `((920 - avg_b2) / (920 - b2))^3`

### First-principles solution

Standalone b1 optimum: **EV(b1) peaks at 63.7 per gardener on the
plateau {785, 790, 795, 800}**. The break-even-math answer is here.
Per rank-bid framework this is the **AI-default cluster — avoid**.

Fixed-point b2 (assuming everyone plays b1=790): **b2* = 870**. Sophisticates
who run Monte Carlo will cluster near b2 ∈ {870, 880, 885}.

### Recommendation hierarchy (UPDATED 2026-04-24 after MC sensitivity sweep)

Full analysis: `analysis/round3_manual/RECOMMENDATION.md`. Six-scenario
prior sweep (avg_b2 ∈ {858, 855, 862, 875, 885, bimodal}), integer grid
sweep, AI-cluster-aware prior (55% of teams paste an LLM answer at
{855, 870, 880, 890}). Prior median for avg_b2 is 862-871 across all
realistic models.

| Pick | Bids | Expected EV/gardener | Worst-case | When to use |
|---|---|---|---|---|
| **PRIMARY** | **(775, 875)** | **80.20** | 71.5 | Default — best EV under all realistic priors |
| Aggressive | (770, 870) | 80.33 | 69.3 | If you trust P3 R3 history (avg≈858) |
| All-weather | (780, 890) | 76.08 | 74.7 | If late chatter says field shifted high (avg>880) |

**Default recommendation: (775, 875).** Reasoning:
1. **b1=775**: one step below the AI/sim cluster at 790. Sacrifices 1.18
   EV on b1 side, frees 3 reserves {780, 785, 790} to flow to b2 side.
2. **b2=875**: sits on a reserve "cliff" (the next reserve up is 880),
   capturing 21 of 26 b2-eligible reserves. Above all plausible avg_b2
   p95 thresholds (≤876 across every prior tested). Below the natural
   AI-buffer cluster at 880.
3. **Decisive evidence**: P3 R3 actual avg was only +3 above naive math
   optimum — supports avg_b2 ~858-871, NOT 880+. Bidding 875 captures
   the +1 reserve at 875 with zero penalty risk in 95%+ of prior mass.

Fallback to (780, 890) ONLY if Discord/leaderboard signals avg_b2 > 880.
Last-submitted pair wins — can iterate. Don't fall for (790, 855)
naive-math AI default — it's the worst at -10 EV/gardener.

## 5. Pending work (next session)

1. **IV-residual MR on ATM strikes** — port Timo's
   `_opt_diff` EMA + `iv_scalping` logic from
   `p3_combined_v1.py:404-441`, refit threshold on round-3 data. Needed
   to extract PnL from strikes 5000-5500 without eating
   flat-sigma-bias losses.
2. **3-way basis arb**: S, (VEV_4000 + 4000), (VEV_4500 + 4500). Three
   parallel measurements of the same underlying with std < 1 tick.
   Any 3-tick divergence is tradeable.
3. **Aggregate delta hedge**: once multi-strike voucher exposure is
   live, sum up delta and hedge via VELVETFRUIT_EXTRACT.
4. **VEV_6000 / VEV_6500 lottery bid**: post passive buys at 0. Never
   pays, but non-negative if liquidation fair > 0. Zero capital at
   risk; only worth doing after the bigger items.

## 6. Cross-round transfer

This round is structurally **Prosperity-3 Round 3** (single delta-1
underlying + voucher chain). The P3 port at
`traders/p3_fresh_claude/p3_combined_v1.py` has the full BS-theo +
IV-EMA + ITM-MR machinery. When porting: **do NOT reuse the fitted
numeric values (SMILE_A/B/C, thresholds)** — fit fresh. The structural
code is transferable; the numbers aren't. See
`P3R3_TRANSFER_NOTE.md` in this folder for the exact mapping.

## 7. Session PnL ladder

| Version | Spec | Total 3-day | Notes |
|---|---|---|---|
| v1 | naive MM, both products | -158,259 | Reference floor. Inside-touch on VELVETFRUIT bled -60k/day. |
| v2 | HYDROGEL ACO-clone, VELVETFRUIT take-only | +33,636 | VELVETFRUIT take still -EV |
| v2 (HYDROGEL alone) | disable VELVETFRUIT | +21,724 | Isolated HYDROGEL at v2 params |
| v3 | HYDROGEL peak + VEV_4000/4500 synth | +158,110 | First real alpha above baseline |
| v3 (VS_TAKE=0) | VS_TAKE_EDGE=0.0 | +167,988 | Drops take threshold |
| v4 | Extend MM to all strikes 4000-5500 | +135,122 | ATM strikes bleed — regresses |
| **v5 (ship)** | Pare back to {4000, 4500} | **+167,930** | Safety floor, all 3 days strong positive |
