# Round 3 — Research Log

Round 3 "Gloves Off" opened 2026-04-24 12:00 CEST. This round starts
the final GOAT phase (R3/R4/R5, PnL reset to zero). We have 48 hours.

## Products

- `HYDROGEL_PACK` — limit 200 (delta-1, wide-spread MM product)
- `VELVETFRUIT_EXTRACT` ("VEV") — limit 200 (delta-1, tight-spread,
  slow drift; underlying of the voucher chain)
- `VEV_{4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500}` —
  limit 300 each; European call vouchers on VELVETFRUIT_EXTRACT.
  7-day TTE from R1 start → TTE = 5 at R3 live final tick.
  Historical data days 0, 1, 2 correspond to TTE = 8, 7, 6.

## §0.2 First-principles sanity numbers (from `data/round3/*.csv`)

Day 1 summary (representative):

| Product              | mid mean | std(day)  | L1 spread | L1 vol ~ | Trades/day | Class |
|---|---|---|---|---|---|---|
| HYDROGEL_PACK        | 9992     | 38 (D1)   | 16        | 12       | 375        | wide-spread stationary MM (§1, ACO-like) |
| VELVETFRUIT_EXTRACT  | 5248     | 15        | 5         | 25       | 450        | tight-spread mild-drift MM |
| VEV_4000             | 1248     | 14.6      | 21        | 11       | 164        | delta-1 ITM (S − 4000) |
| VEV_4500             | 748      | 14.6      | 16        | 9        | 1          | delta-1 ITM (S − 4500) |
| VEV_5000             | 253      | 13.6      | 6         | 11       | 1          | near-ATM ITM |
| VEV_5100             | 165      | 11.9      | 4         | 22       | 1          | near-ATM ITM |
| VEV_5200             | 95       | 8.7       | 3         | 25       | 7          | ATM |
| VEV_5300             | 47       | 5.5       | 2         | 21       | 39         | slightly OTM |
| VEV_5400             | 16       | 2.7       | 1         | 22       | 81         | OTM |
| VEV_5500             | 7        | 1.3       | 1         | 22       | 92         | deeper OTM |
| VEV_6000             | 0.5      | 0.0       | 1         | 22       | 98 (at 0)  | dead OTM |
| VEV_6500             | 0.5      | 0.0       | 1         | 15       | 98 (at 0)  | dead OTM |

Drift: VELVETFRUIT_EXTRACT Δmid per tick mean ≈ +0.002 / tick (≈ +20
per 10 000-tick day), AR(1) ρ(Δm,Δm−1) = −0.17. Modest carry.

HYDROGEL_PACK: mean 9992, median 9999 (bimodal-ish), p5/p95 around
anchor 10000 ± 60. No strong intraday drift; big range.

## §0.1 Generative-process hypotheses (per product)

1. **HYDROGEL_PACK** — story #1 (stationary latent fair + MM noise) with
   wide visible spread. Looks structurally like P3 R2 `RAINFOREST_RESIN`
   or P4 R2 `ACO`, anchored near 10 000, but with bigger excursions
   (std 25-38 vs ACO's 2-5). Expect take-inside-anchor + make-inside-
   touch works; inventory-skew on the anchor.
2. **VELVETFRUIT_EXTRACT** — story #2 (mild deterministic drift + local
   noise). Tight 5-tick spread limits passive-MM headroom. Not much
   drift-carry EV (20 / 10 000 ticks is only ~0.2 SeaShells per qty per
   day). Primary role is as the **options underlying** — spot mid feeds
   BS theo and the basis arb.
3. **VEV chain** — story #5 (deterministic fn of a driver + smooth smile
   residual). Market IV ≈ 0.23 across the liquid strikes 5000–5500 on
   all 3 days — **almost flat smile**. Simpler than P3 R3's quadratic
   polynomial fit.
4. **VEV_4000 / VEV_4500** — degenerate case of story #5: deep-ITM calls
   trade at pure intrinsic (S − K) with basis std < 1 tick. Treat as
   **synthetic clones of the underlying** with limit 300 each (vs 200
   on the true underlying). Total delta-1 position capacity balloons
   from 200 to **200 + 300 + 300 = 800**.
5. **VEV_6000 / VEV_6500** — mid stuck at 0.5, 98 trades/day at
   price = 0. Lottery-ticket regime: any buy at 0 is non-negative EV
   bounded by the hidden liquidation fair value. Deprioritized.

## Key findings (before any code)

1. **Flat IV smile ≈ 0.23** on liquid strikes (5000-5500). Unlike P3 R3
   where the smile curved strongly, here we can fit `IV ≈ const` and
   still be within ~1 % across 3 days. Fit one parameter, update slowly.
2. **Basis trade: S vs VEV_4000 + 4000, std 0.84** (day 1). Mean dev
   +0.016 ticks, min/max ±6. At threshold ±3 (≈ 3.5 σ) we have ~80
   opportunities/day where one side is rich by ≥ 3 ticks. Trade with
   real constraint is position-limit-bound, not signal-bound.
3. **VEV_4000 spread = 21** (ticks) while underlying spread = 5. That's
   **huge MM headroom** on VEV_4000 if we fair-value it to S − 4000.
   Inside-touch quotes at bb+1 / ba-1 give edge = (spread − 2) / 2 ≈
   9.5 ticks per round-trip. Even at 10 trades/day, that's ~95 ticks
   per unit quoted.
4. **HYDROGEL_PACK is P4 R2 ACO-class with wider excursions.** Recipe
   template: `fair = 10000 − k·pos`, inside-touch make, take-through
   when touch crosses the anchor. Size grid {20, 40, 60} to tune.
5. **VELVETFRUIT_EXTRACT tight spread** — post inside-touch with
   size ≤ 10 to avoid adverse selection on the 5-tick spread. Drift
   carry is too small to matter on a 2-day round.

## §7.46 flat-smile option pricing recipe (new learning)

The P4 R3 chain is a **flat-IV-smile** variant of §7.46 (options
family). Concrete steps:

```
sigma_hat = 0.23       # constant fit across strikes 5000-5500
theo(K) = BS_call(S=VEV_mid, K, T=(days_to_expiry)/365, sigma=sigma_hat)
dev(K)  = voucher_mid(K) - theo(K)
```

- Deep ITM strikes (4000, 4500): `theo ≈ S - K + tiny`. Basis arb is a
  pure-intrinsic check; no IV needed.
- Deep OTM (5400+): theo → 0 quickly. A voucher mid of 15-16 on a K
  that BS says is worth ~5 implies the market IV is ABOVE 0.23 — i.e.
  the smile curves up at OTM. Reverify per-day before trading it.
- Dead OTM (6000, 6500): both theo and market are ~0. Lottery posts
  only.

## Per-round levers that move PnL (blank-state recipe targets)

To document as we go:

- [ ] HYDROGEL MM size plateau: {20, 40, 60, 100}
- [ ] HYDROGEL inventory-skew coefficient k
- [ ] HYDROGEL inside-touch depth (+1 vs +2)
- [ ] VEV MM size (small due to tight spread)
- [ ] VEV_4000/4500 synthetic MM size
- [ ] VEV_4000/4500 basis-arb threshold (ticks)
- [ ] Total-delta hedge on/off (aggregate across VEV chain)
- [ ] Sigma-hat value and update cadence

## Session log

### 2026-04-25 — session 8 deeper: HYDROGEL Citadel attempts dead (EMA -122k, static-anchor -167k)

After v26 (511,088 bt) was locked in, tried two variants of porting the
Citadel z-score MR pattern to HYDROGEL_PACK (in addition to VFE).
Both regressed massively:

| Variant | bt | Δ vs v26 |
|---|---|---|
| v26 baseline | 511,088 | 0 |
| HYDROGEL Citadel using long-EMA (1386 HL) of mid | 388,435 | -122,653 |
| HYDROGEL Citadel using STATIC ANCHOR (9983), v28 | 344,245 | -166,843 |

**Why HYDROGEL Citadel doesn't work** (different from VFE Citadel):

HYDROGEL has NO drift — anchored statically at 9983.  The existing
make-side (anchor-clipped fair, post inside-touch with PE=3.5,
TE=0.6, asym INV_SKEW) already captures the inside-anchor reversion
on EVERY mid excursion.  Adding a Citadel take-side with `dev =
mid - 9983` produces THE SAME directional bet as the existing make:
both want to be long when mid<9983 and short when mid>9983.  Two
sleeves bid for the same trades, paying spread cost twice → -167k.

VFE Citadel works because:
1. VFE has POSITIVE DRIFT (+0.002/tick).  The slow EMA tracks the
   drifting fair, so dev = mid - ema captures regime-vs-trend, not
   inside-fair MR.
2. VFE's existing UNDER_MR (Timo P3R3 short window) was a take-side
   sleeve that Citadel REPLACED, not duplicated.
3. VFE has tight 5-tick spread; HYDROGEL has wide 16-tick mode.
   Take-side spread cost is 5x worse on HYDROGEL.

**Generalization**: Citadel-style z-score MR transfers to products that
have:
1. A SLOW-DRIFTING fair (need EMA), OR a quasi-static fair without
   already-existing make-side that captures inside-fair reversion.
2. Tight spread on the take side (so cross cost doesn't dominate alpha).
3. NO COMPETING SLEEVE on the same MR signal.

P4 R3 has VFE matching all 3.  HYDROGEL fails (1) (existing make-side
captures it) and (2) (wide spread).  Documented in
`feedback_hydrogel_citadel_dead.md`.

#### Other dead-ends this push (rejected)

- **Citadel + drift carry stack on VFE**: -1k to -2k bt regression at
  every (LOW_Z, target) combination.  When |z|<1, post passive long
  bid; when |z|>2, Citadel takes.  Conflicts because Citadel is
  already accumulating long when z<-2; drift carry buys at intermediate
  z range but doesn't add edge.
- **HYDROGEL queue-join layer at bb (size 5-30)**: -12 to -15k bt.
  Adverse selection on wall walks.
- **EOD VFE flat (last 100/200/500 ticks)**: -1 to -5k.  Drift wants
  to hold to end-of-day.
- **CARRY_BID_SIZE / lottery / synth-carry sizing sweeps**: bt-invariant.
- **ATM-EMA / IV_SCALPING_THR sweeps on v26 chassis**: all within ±1k of v26.

#### Final session-8 state

| Ship | bt | alpha floor | live | Status |
|---|---|---|---|---|
| v15 | 443,484 | 280,208 | 417,605 | Pre-Citadel ladder peak |
| v23 | 451,331 | 280,836 | TBD | Pre-Citadel + asym/carry/hdrift |
| v25 (parallel) | 497,324 | 341,134 | **525,560** | Citadel cap=15 (1.057x conversion confirmed) |
| **v26 (this Claude)** | **511,088** | **354,898** | **~540k forecast** | Citadel cap=8 |

v26 is the verified-reproducible peak.  v27 in the file system claims
516k via HYDROGEL Citadel but actually runs at ~344k now (likely an
in-flight refactor that broke the chassis).

### 2026-04-25 — session 8 close: ship_v26 = v24 + cap=8 (511,088 bt, expected ~540k live)

User shared v25 live result: **525,560** (vs bt 497,324 = **1.057x bt-to-live
conversion** for the Citadel sleeve).  This SETTLES the live-conversion
risk question — Citadel converts cleanly, not just matching-engine
artifact.  v25 jumped +107,955 live over v15's 417,605.

Re-swept VFE_MAX_TAKE_PER_TICK on my v24 chassis (508,770 bt baseline):

| cap | bt | Δ |
|---|---|---|
| 5  | 505,144 | -3,626 |
| 6  | 508,464 | -306 |
| 7  | 510,358 | +1,588 |
| **8**  | **511,088** | **+2,318** ← peak |
| 9  | 510,909 | +2,139 |
| 10 | 510,307 | +1,537 |
| 12 | 509,663 | +893 |
| 15 | 509,293 | +523 |
| 18-25 | 508,742-936 | ±200 noise |
| 80 (default) | 508,770 | 0 |

Joint sweep at cap=8 (all dad.py defaults peak):
- Z_ENTER 1.80→502k, 1.85→504k, 1.95→504k, **2.00→511k**, 2.05→497k cliff
- EMA_ALPHA 4e-4→487k, **4.5e-4→511.2k** (+70 noise), 5e-4→511k, 6e-4→507k
- WARMUP 300→510k, 400→508k, **500→511k**, 600→509k, 800→499k

Lock at cap=8, Z=2.0, alpha=5e-4, warmup=500.

**v26 = 511,088 bt, alpha floor 354,898, no `import os`.**
+2,318 over v24, +59,757 over v23, +13,764 over v25.
Live forecast at 1.057x: **~540,200** (+14.6k over v25's 525,560).

#### Why cap=8 wins

The slower per-tick rebalancing means Citadel takes ~25 ticks to
accumulate ±200 (vs ~3 ticks at cap=80).  This:
1. Reduces whipsaw fills near z-crossings (where direction can flip)
2. Spreads the take across more book depth (better avg fill price)
3. Allows the slow EMA more time to confirm the regime side

Alpha-floor moves +2,318 (matches bt move) — entirely real alpha, not
matching-engine.  Both gain mechanisms (better fills + cleaner regime
confirmation) are live-applicable.

### 2026-04-25 — session 8 v24: Citadel z-score VFE MR onto v23 chassis (508,770, +57,439 over v23)

`dad.py` (parallel work) showed a Citadel-style bipolar long-EMA z-score
MR on VFE adds +34,345 bt over v11 chassis (485,676).  Ported onto v23
(which has v15_hdrift drift-gate, VEV carry, asym INV_SKEW, etc).

| Stack | bt | alpha floor | Δ vs v23 |
|---|---|---|---|
| v23 (no Citadel) | 451,331 | 280,836 | — |
| dad.py (Citadel only, v11) | 485,676 | 337,360 | +34,345 bt |
| **v24 = v23 + Citadel** | **508,770** | **352,580** | **+57,439 / +71,744 ALPHA** |

Citadel is **real alpha** — alpha floor jumped +71,744 over v23, the
biggest single real-alpha addition in the entire round.  The slow
ema/sigma EMAs identify clean MR regimes that the short-window
UNDER_MR (Timo's port) missed.

#### Mechanism (port from `dad.py:460-530`)

```
ema_long  = (1-α) · ema + α · mid          α=0.0005, HL ≈ 1386 ticks
sigma_var = (1-α') · sigma_var + α' · dev² α'=0.0005, floor=1.0
z = (mid - ema_long) / sigma

After warmup of 500 ticks:
  z ≥ 2.0  → side = -1 (target = -LIMIT)
  z ≤ -2.0 → side = +1 (target = +LIMIT)
  else: keep last side (sticky regime)

target = side · LIMIT (200)
take aggressively toward target, up to 80 units / tick
```

Replaces v23's UNDER_MR (`|ema_o_dev| > 6 cross-take`) AND drift carry
(passive long bias when MR silent).  Both subsumed.

#### Citadel param sweeps on v24 chassis (peaks at dad.py defaults)

| Knob | Peak | Other points |
|---|---|---|
| VFE_Z_ENTER | **2.0** → 508k | 1.75=495k, 2.25=451k cliff |
| VFE_EMA_ALPHA | **5e-4** → 508k | 1e-4=442k, 1e-3=504k smooth |
| VFE_MAX_TAKE | 60 → 509k (+113 noise) | 80 default; 40+ saturate |
| VFE_WARMUP | **500** → 508k | 200=494k, 1000=492k |
| VFE_SIGMA_FLOOR | **1.0** → 508k | 0.5/2.0=494k, 5.0=495k |

Joint sweeps (z × alpha) all under-perform the dad.py corner.  Lock
at defaults.

#### Live risk

dad.py was tagged "highest live-conversion RISK" of any ship —
Citadel is a directional take, no precedent in the live ladder.
v24 stacks Citadel on v23's passive-make sleeves (HYDROGEL converts
2.27x, VEV/VFE carry 1.0-1.27x), so the make-side at least is
live-defensive.  Live forecast:
  - Best case (Citadel converts ~1.0x): ~470k live
  - Worst case (~0.5x): ~430k live
  - Either way: ~+10-50k over v15 live (417,605).

Ship: `combined_ship_v24.py`, no `import os`.

### 2026-04-25 — session 8 final: ship_v23 = stack v15_hdrift + VEV carry + asym INV_SKEW (451,331, +7,847 over v15)

Cumulative session-8 push, three independent additions stacked on top
of v15 (443,484 bt / 417,605 live).  Each tested for additive behavior;
all three are.

| Stage | bt | bt floor | gain | mechanism |
|---|---|---|---|---|
| v15 | 443,484 | 280,208 | — | baseline |
| v15_hdrift (parallel) | 445,448 | 281,338 | +1,964 | drift-regime CLIP gate (real alpha +1,130) |
| v22 = + VEV carry | 447,042 | 281,338 | +1,594 | passive-make matching-engine fills |
| **v23 = + asym INV_SKEW** | **451,331** | 280,836 | +4,289 | passive-make matching-engine + slight alpha loss |
| Total v15 → v23 | | | **+7,847** | |

#### v23 add: asymmetric pos-conditional H_INV_SKEW

Port from h_only_v22's main lever (asym CLIP_VOL_K), but in combined
chassis the asym CLIP regressed -21k.  However, h_only_v22's separate
asym INV_SKEW direction DOES transfer:

```python
H_INV_SKEW_LONG  = -0.004    # was 0.014 symmetric
H_INV_SKEW_SHORT = +0.014    # unchanged
```

Joint sweep around the optimum:

| LONG | SHORT | bt |
|---|---|---|
| 0.014 (sym, v22) | 0.014 | 447,042 |
| -0.004 | 0.014 | **451,331** |
| -0.005 | 0.014 | 450,983 |
| -0.003 | 0.014 | 451,219 |
| -0.010 | 0.014 | 450,917 |
| -0.020 | 0.014 | 451,072 |
| ≤ -0.018 (other) | 0.014 | 360k-389k cliff |

Smooth peak at LONG=-0.004; cliff at LONG ≤ -0.018 (param-discontinuity
where asks jump fully out of fill range).  SHORT=0.014 is the sharp
peak; ±0.002 costs 5-10k.

The "no-skew when long" pattern means: when long, fair shifts UP
slightly (skew=fair+0.004*pos), making bid prices higher (more
aggressive buy fills) AND ask prices higher (sell at better prices
when filled).  The bt gain is mostly matching-engine fills; alpha
floor goes DOWN by -502 (small real-alpha cost).

#### Trade-off note

v23 alpha floor is 280,836 (v22's 281,338, -502).  That's tiny vs
the +4,289 bt and at HYDROGEL's 2.27x → 1.0x conversion mix, the
live gain is still strongly positive, but ship v22 if you want
strict alpha-floor monotone improvement.

#### Mid-session ship: combined_ship_v21.py

`v21` was the intermediate (v20 + VEV carry, before stacking with
v15_hdrift).  See ship file for details — superseded by v22/v23.

#### Other tests this push (rejected)

- HYDROGEL queue-join layer at bb (size 5-30): -12 to -15k bt.  Adverse
  selection on wall walks; same as h_only_v15 layer-2 dead-list.
- EOD VFE flat (last 100/200/500 ticks): -1 to -5k.  Drift wants to hold.
- VEV CARRY_TARGET sweep: 300 cap is peak; 50→+943, 100→+1,079, 200→+1,222.
- Subset VEV strikes (only 5000-5100 / 5000-5200): partial / -409.
- Multi-level VEV carry (bb + bb-1): bt-invariant (queue priority only).
- VFE persist-during-MR carry: -47k.  Carry buys conflict with MR sells.
- h_only_v22 chassis full port (TE=0.3 PE=4 AR1=0.20 + asym CLIP):
  -17k regress.  Combined chassis prefers v22's TE=0.6 PE=3.5 AR1=0.25.
- Asym CLIP_VOL_K alone (without TE/PE/AR1 changes): -21k regress.
- CARRY_BID_SIZE / lottery / synth-carry sizing sweeps: bt-invariant.

Ship: `combined_ship_v23.py`.  No `import os`.
Live forecast: ~424k (v15 417,605 + ~6.5k for the cumulative bt-to-live
conversion of HYDROGEL retune + VEV carry passive-make + drift-gate
real alpha).

### 2026-04-25 — session 8: ship_v21 = v20 + VEV drift carry on V5000-5300 (445,078, +1,594)

After v15/v17/v20 (parallel-track) ported VFE drift carry and converted at
**127% live** (v15 +14k bt → +18k live), the obvious next move was to
extend the same passive-make-on-delta-1 mechanism to the voucher MR
strikes V5000-5300 (delta 0.4-0.95, all follow VFE drift).

**Mechanism:** voucher MR loop posts an aggressive sell/buy when
`|combined| > OPT_MR_THR=6.3`.  The else-branch was previously empty.
v21 adds a passive carry bid stack at `bb` (size 30) and `bb-1` (size 20)
in the else-branch, accumulating up to position 300 long per strike.

#### VEV_CARRY_TARGET sweep (on top of v20, 443,484 bt)

| target | bt | Δ |
|---|---|---|
| 0 (v20) | 443,484 | 0 |
| 50 | 444,427 | +943 |
| 100 | 444,563 | +1,079 |
| 150 | 444,686 | +1,202 |
| 200 | 444,706 | +1,222 |
| 250 | 444,766 | +1,282 |
| 275 | 445,047 | +1,563 |
| **300** (cap) | **445,078** | **+1,594** |

Smooth ramp; capped at position limit (300).  Subset 5000-5100 only:
+0 (no help), 5000-5200 only: +409.  All four strikes needed.

#### Tests rejected this session

- **HYDROGEL queue-join layer** (post tiny size at bb / ba): -12 to -15k
  bt across sizes {5, 10, 15, 20, 30}.  Adverse selection on wall walks
  — same mechanism as h_only_v15's layer-2 dead-list.
- **EOD VFE flat** (last 100 / 200 / 500 ticks unwind): -1 to -5k bt.
  Drift wants to hold; unwinding loses the accumulated drift gain.
- **Persist-during-MR carry**: -47k bt.  Carry buys conflict with MR
  sells.  Confirms session-7 lesson "don't tune away the deviations
  that make the strategy work."
- **Multi-level VFE / synth carry**: bt-invariant; v20 already has them.
- **Lottery / synth carry sizing sweeps**: bt-invariant.
- **CARRY_BID_SIZE sweep on VFE**: bt-invariant (matcher fills full
  posted size regardless of size knob).

#### Alpha floor stays flat

Match-trades-none on v20 = 280,208; v21 = 280,208.  Entire +1,594 is
matching-engine fill, just like v15's VFE drift carry add.  Same live
conversion mechanism expected → ~1.0-1.3x → ~+2k live.

Ship: `combined_ship_v21.py`, no `import os`.

### 2026-04-25 — session 7: walked-rebound dead on HYDROGEL (5 R3 directions, parallel agents)

User dispatched 5 directions (1 walked-rebound port, 2 VFE drift carry, 3
V4000/V4500 imb sizing, 4 R2 day-1 deep dive, 5 HYDROGEL day-1 regime).

**Direction 3 (V4000/V4500 imbalance sizing): DEAD.** Ported clean_alpha
`IMB_FAVORABLE_BOOST/IMB_ADVERSE_SHRINK` onto the synth-MM block. Signal
IS real:
- VEV_4000: corr(L1_imb, Δmid_next) = **+0.483** (n=29,997)
- VEV_4500: corr = +0.401
- |imb| > 0.3 fires on 1.6% of ticks (book is super-deep / dominant MM)

But **synth-MM is volume-bound, not size-bound**: VEV_4000 trades only
940 lots over 3 days (1.5% of ticks); VEV_4500 trades 1 lot total. Our
12-lot post is already deeper than any single market trade; sizing skew
has no fill pathway. Sweep over `IMB_STRONG ∈ {0.2..0.6}` × `BOOST ∈
{1.5, 2.0, 2.5}` × `SHRINK ∈ {0.3, 0.5, 0.7}`: every config 318,576.
Even `TAKE_ADVERSE_EXTRA=100` (kills all takes when adverse) → 318,576.

The clean_alpha sizing trick is correct on flow-rich symbols (HYDROGEL,
ACO_ROCKET) where 940 vol/3day translates to thousands of takes — but
zero traction on the synth strikes' near-empty trade tape. Same
architectural lesson as Direction 1: **alpha without counterparty
volume = no fills.** Variant `combined_ship_v7_imbsz.py` shipped at
parity (318,576), null-result reference.

**Direction 2 (VFE drift carry): DEAD.** Hypothesis was VFE has
+0.002/ts drift = +20 ticks/day; lean target-long +30 to capture
~+600/day on top of MR. Reality: drift is +1.4e-5/ts ≈ +14 ticks/day
average (day 0 = -6, day 1 = +20.5, day 2 = +28). The per-day estimate
was right but AR(1)(Δmid) = -0.15 — strong mean reversion. Variant
`combined_ship_v7_drift.py` with `VFE_LONG_BIAS ∈ {15, 30, 50, 80}`:

| bias | total | vs 318,576 |
|---|---|---|
| 0 | 318,576 | 0 |
| 15 | 287,740 | -30,836 |
| 30 | 288,670 | -29,906 |
| 50 | 289,962 | -28,614 |
| 80 | 291,779 | -26,797 |

VFE per-day flips +4k→-5k for any bias>0. Forced longs eat the 5-tick
spread on entry and AR(1) reversion punishes momentum-aligned trades.
The symmetric MR already extracts what little drift exists. Don't ship.
File kept at parity (bias=0) as null-result reference.

**Direction 4 (R2 day-1 / ASH_COATED_OSMIUM): R2-only learnings.** ASH
spread-walked-rebound DOES fill (5% conversion vs HYDROGEL's 0%) — the
R2 `clean_alpha.py` ACO walked-rebound (size=55) is undersized vs the
80-cap and could be raised. Stronger insight: ASH's `ACO_FAIR_CLIP=4.0`
≈ 1σ for a σ=3.9 product is too wide; tightening to 0.4σ (~1.5-2.0)
would harvest the strong AR(1)=-0.49 lag-1 reversal (after Δmid≥+2
next Δmid mean = -1.5 across all 3 days, n≈1000/day each). HYDROGEL has
weaker AR(1) (-0.12) and much wider mid range (170 vs ASH's ~15) so
direct CLIP-tightening transfer is dubious — but the principle "CLIP
scales with σ" remains.

**Direction 5 (HYDROGEL day-1 regime shift): DEAD.** Hypothesis was day 1
underperforms (53,884) because it has wider mid range (170 vs 60) so
fair gets stuck near anchor; a slow-EMA anchor shift would track the
drift. Probe found a clean detector: slow-EMA(touch_mid - H_ANCHOR) at
α=1/2000 — day 0 max=18.6, day 1 max=36.4 (>20 in 55% of ticks),
day 2 max=28.8. So the regime IS distinct.

But the fix monotonically regresses every day INCLUDING day 1:

| α | day 0 | day 1 | day 2 | total | Δ |
|---|---|---|---|---|---|
| 0 (=v16) | 63,544 | 53,884 | 64,247 | 181,675 | 0 |
| 5e-5 | 63,231 | 52,379 | 60,210 | 175,820 | -5,855 |
| 1e-4 | 60,801 | 49,356 | 58,749 | 168,906 | -12,769 |
| 5e-4 | 53,115 | 41,468 | 41,406 | 135,989 | -45,686 |

**Why (post-hoc):** HYDROGEL is a strong mean-reverter. The strategy
harvests reversion against a STATIC anchor. Day 1's "drift to 10079"
is not a regime to chase — it's the deviation we eventually profit
from when it reverts (day 1 closes at 9979, back at anchor). Shifting
anchor with price cancels the reversion edge. **The static-anchor pin
is the feature, not the bug.** Day 1 underperformance is the COST of
holding inventory through the wider excursions, paid for by larger
end-of-day fades.

`h_only_v18.py` left at α=0 (= v16 behavior) as null-result reference.
Do NOT chase per-regime CLIP/anchor adjustments — generalizes to: don't
tune away the deviations that make the strategy work.

**Direction 1 (walked-rebound on HYDROGEL): DEAD.** Built
`h_only_v17_walkedrebound.py` mirroring `clean_alpha.py` ACO logic
(spread > TYPICAL trigger, boost ASK size to 60 at ba-1 when ASK walks).
Backtest: 63,544 / 53,884 / 64,247 = **181,675 — IDENTICAL to v16**.

The mark-to-mid alpha is real:
| day | ASK-walks | mean edge ((ba-1) − next_mid) | positive-edge share |
|---|---|---|---|
| 0 | 100 | +8.10 | 100% |
| 1 | 165 | +7.37 | 100% |
| 2 | 127 | +7.67 | 100% |

But the **fills don't materialize**. Across all 392 walks, 97-99% have
ZERO trade volume in the next 3 ticks at price ≥ ba-1. The matching
engine has no counterparty for the rebound: the wall snaps back via
order-book snapshot change, not via aggressive buy flow. Our quote at
ba-1 sits at the new touch but no one trades against it.

**Why this differs from clean_alpha (R2 ACO).** ACO had counterparty
flow at the rebound price; HYDROGEL doesn't. Spread > 16 fires only on
spread = 17 (just one tick wider than typical), which suggests it's the
BOT briefly retracting one tick rather than aggressive flow walking the
book. Different microstructure → no fill mechanism.

Dead-list: do NOT port walked-rebound to HYDROGEL. Save for products
where the walked-trigger correlates with active flow.

**Session 7 final synthesis (5/5 directions explored):**

| # | Direction | Outcome | Δ vs v7 baseline 318,576 |
|---|---|---|---|
| 1 | Walked-rebound on HYDROGEL | DEAD (0 counterparty flow) | 0 |
| 2 | VFE drift carry (long bias) | DEAD (AR(1) reversion bites) | -27k to -31k |
| 3 | V4000/V4500 imb sizing | DEAD (volume-bound) | 0 |
| 4 | R2 ASH_COATED_OSMIUM dive | R2-only learning, no R3 transfer | n/a |
| 5 | HYDROGEL day-1 regime shift | DEAD (static anchor IS the feature) | -6k to -57k |

All 5 hypotheses fully falsified. Two new memory entries saved:
`feedback_mark_to_mid_needs_counterparty.md` and
`feedback_static_anchor_is_the_feature.md`. Directions 1 and 3 share a
deep lesson — **passive quote alpha needs counterparty volume to
monetize** (mark-to-mid edge ≠ fills). Direction 5 teaches the dual
lesson — **don't tune away the deviations that drive the strategy** on
mean-reverting stationary-anchor MM products.

Files left on disk as null-result references (do not ship):
- `traders/round3/h_only_v17_walkedrebound.py` (= v16 PnL)
- `traders/round3/h_only_v18.py` (anchor-shift α=0)
- `traders/round3/combined_ship_v7_drift.py` (VFE bias=0)
- `traders/round3/combined_ship_v7_imbsz.py` (= ship_v7 PnL)

(Note: ship has since advanced to v11/v12 in parallel sessions per the
"session 6 late" entry below; this synthesis is over the v7-baseline
search the user kicked off, all five branches independently dead.)

### 2026-04-25 — session 6 late: ship_v12 = v11 + 4-knob HYDROGEL micro-tune (429,028, +274)

Picked up after parallel sessions 4-7 had pushed the combined ship to
v11 (428,754 bt / 399,113 live).  Re-tested my session-6 v7 HYDROGEL
deltas against v11's chassis (which already had h_only_v16 retunes:
CLIP=0.76, DH=150, PE=3, TE=0.5, AR1=0.17 + voucher MR retune to
WIN=44/THR=6.3 + VS_INV_SKEW=0).

**Single-knob diffs vs v11 — ALL hurt:**
- CLIP=0.795: -2,243
- PE=3.5: -56
- TE=0.6: -2,311
- AR1=0.25: -393

**4-knob joint = +274.** Joint optimum exists at the corner of the
parameter surface.  This kind of result is exactly why Lesson 6 in
`reference_round3_p4_recipe.md` got rewritten — single-knob sweeps at
fixed others can hide the true peak.

Final v12 settings (vs v11):

| Knob | v11 | v12 |
|---|---|---|
| CLIP_VOL_K | 0.76 | **0.795** |
| H_PENNY_EDGE | 3.0 | **3.5** |
| H_TAKE_EDGE | 0.5 | **0.6** |
| AR1_BETA | 0.17 | **0.25** |

3-day bt: **429,028** (vs v11 428,754, Δ +274).  Per-day:
123,533 / 150,168 / 155,327.

#### Other tests this late-session (rejected)

- DMID_HISTORY=100 with v12 chassis: +22 (not worth defaulting away
  from v11's 150 for noise).
- DMID_HISTORY=200: +208 over v11 baseline but -66 vs v12 — v12 wins.
- CLIP=0.80 with v12 retune: -2,857 (v11/v12 cliff at 0.80 still holds).
- UNDER_MR_THR=5 (revert from v11's 6): -23,251 cliff.  Confirms v11's
  finding that UNDER=6 matches OPT_MR_WINDOW=44.
- Apply my v7 knobs single-knob over v11: each one regresses, only
  joint helps.

#### Recap of the cumulative session-6 work (in order)

1. **MR-strike expansion (P3 transfer):** all 8 variants regressed
   -25k to -485k.  Wide V4000 spread (~21 ticks) + low-vega OTM break
   the P3 ITM-to-MR move.  See `feedback_p3_to_p4_transfer_caveats.md`.
2. **SIGMA sensitivity audit (P3-style):** P4 SIGMA peaks sharp at 0.23
   ± 0.05 → -60k.  P4 uses SIGMA in 3 load-bearing places (synth-MM,
   ATM-EMA, BS theo for MR); P3 only used it for residual EMA.
3. **CLIP_VOL_K joint with DH:** prior memo claim "CLIP > 0.3 didn't
   help in combined" was wrong — at fixed DH=20 yes, but joint with
   DH=50 we got CLIP=0.795 → +4.7k bt.  Found ship_v6 (317,360 from
   ship_v4 baseline).
4. **h_only_v16 transfer to combined:** parallel work with TE=0.5,
   DH=150 ports cleanly.  ship_v7 found at 318,576.
5. **Discovered parallel ship_v11 at 428,754:** much further than v7.
   v11 had VS_INV_SKEW=0, voucher MR retune (+87k bt though only +1-3%
   live), HYDROGEL h_only_v16 base.
6. **Joint-retune v7 deltas onto v11 chassis:** +274 → ship_v12.

Live forecast for v12: ~+620 over v11 live (HYDROGEL converts 2.27x;
the +274 is purely HYDROGEL gain).  v11 was 399,113 → v12 ~399,700.

`combined_ship_v12.py` ships clean (no `import os`).

### 2026-04-25 — session 6: P3 transfer audit + HYDROGEL chassis retune (combined_ship_v6, 317,360)

User asked to "beat Timo this way for prosp round 3 (in P4)" — i.e.
re-apply the P3 session-4.5 winning move (move ITM voucher strikes
from IV-scalp to MR for +684k bt).

**Result:** P3 strike-bucket insight DOES NOT TRANSFER to P4 R3.
Every variant regressed.  Surprise insight came from re-sweeping
HYDROGEL chassis: **CLIP_VOL_K from 0.3 → 0.795** is +4.1k bt and was
incorrectly listed as dead in the prior-session memo.

#### Diagnostic 1 — MR strike expansion (the P3 move): all variants regress

Tested 8 variants of `MR_STRIKES` against ship_v4 baseline (312,124):

| MR strikes added | bt | Δ |
|---|---|---|
| ship_v4 baseline {5000-5300} | 312,124 | 0 |
| + 4500 | 152,612 | -159,512 |
| + 4000 | 30,205 | -281,919 |
| + 5400 | 286,708 | -25,416 |
| + 5500 | 293,842 | -18,282 |
| + 5400 + 5500 (drop ATM-EMA) | 268,425 | -43,699 |
| + 4500 + 5400 + 5500 | 108,912 | -203,212 |
| + 4000 + 4500 + 5400 + 5500 (all) | -173,008 | -485,132 |
| no 5300, + 5400 + 5500 | 266,499 | -45,625 |

**Why P3's win doesn't transfer:**
- P4 R3 deep-ITM (V4000) has spread ~21 ticks; aggressive market-take
  posting (`bid_wall+1` / `ask_wall-1`) walks the book at huge cost.
  P3 vouchers had tighter spreads.
- P4 OTM strikes (5400/5500) have vega < 1 in this regime; the iv_dev
  signal is noise-dominated when vega is small.
- P3 ATM strikes (10000) had clean vega ~5 and spread ~2-4.

**Lesson for the playbook:** MR-on-ITM transfers when (a) the strike
chain has tight spreads and (b) ATM has non-trivial vega.  P4 R3
fails (a) on deep ITM and (b) on OTM.

#### Diagnostic 2 — SIGMA sensitivity (P3-style audit)

P3 session-4.5 showed `SMILE_A/B/C` were decorative (flat IV gave +19k
over fitted).  Test on P4:

| SIGMA | bt 3-day |
|---|---|
| 0.10 | 213,668 |
| 0.18 | 292,551 |
| **0.23 (baseline)** | **312,124** |
| 0.28 | 244,964 |
| 0.40 | 89,296 |

Sharp peak at 0.23, ±0.05 perturbation costs 60-70k.  **Different from
P3** because P4 uses SIGMA in three live-load-bearing places: synth-MM
on V4000/V4500, ATM-EMA on V5400/V5500, and BS theo for the MR
iv_dev signal.  P3's sigma only entered the IV-residual EMA which
absorbed any constant bias.

#### Diagnostic 3 — HYDROGEL chassis re-sweep at fixed voucher config

The prior-session memo asserted "CLIP_VOL_K > 0.3 didn't help in
combined".  Verified false — the test was likely done holding
DMID_HISTORY=20 fixed, masking the joint optimum.

| CLIP_VOL_K (with DH=50, PE=3) | bt |
|---|---|
| 0.30 (baseline) | 312,124 |
| 0.40 | 313,096 |
| 0.50 | 313,924 |
| 0.60 | 314,624 |
| 0.70 | 315,782 |
| 0.75 | 316,222 |
| 0.78 | 316,992 |
| 0.79 | 317,070 |
| **0.795** | **317,154** |
| 0.798 | 317,154 |
| 0.80 | 287,680 ← cliff |
| 0.85 | 287,922 |

Cliff at 0.80 matches `h_only_v15` warning.  Adding `AR1_BETA` sweep on
top: 0.18 (baseline) 317,154 → 0.20 317,220 → 0.22 317,248 →
**0.25 317,360** → 0.27 316,678 → 0.30 316,386.

#### Other knobs probed (no further alpha)

- iv_dev weight at new HYDROGEL config: 1.5=305k, 2.0=316k,
  **2.25=317.4k**, 2.5=311k, 3.0=302k.  Weight unchanged from session 3.
- H_PENNY_EDGE 2.5/3.5/4 within 200 of 3.0 (insensitive plateau).
- H_INV_SKEW=0.013 craters (-25k); 0.015 mild loss; 0.014 peak.
- H_MAX_POST_SIZE=19 craters (-35k), 17/18 plateau.
- H_CLIP=31 / 35 both regress; 33 confirmed peak.
- H_ANCHOR=9982 / 9984 both regress; 9983 confirmed peak.
- DMID_HISTORY=40 -1k; 50 peak; 60 craters (-25k); 70 craters.

#### Shipping decision (early v6 → upgraded v7)

After porting four h_only_v15 knobs to combined (above), checked the
even-newer `h_only_v16` (181,675 standalone) which adds:

  DMID_HISTORY    50 → 150  (plateau 100-200)
  H_PENNY_EDGE    3.0 → 3.5 (plateau 3.0-4.0)
  H_TAKE_EDGE     0.0 → 0.6 (NEW lever; cuts marginal noise crosses)
  (H_REDUCE_EDGE must stay 0 once TE>0; RE+TE>0 leaks -5k bt)

Joint sweep at peak combined config:

| TE  | DH  | bt |
|-----|-----|----|
| 0.0 (v4 baseline) | 20 | 312,124 |
| 0.0 | 50 | 317,360 (v6) |
| 0.5 | 150 | 318,342 |
| **0.6** | **150** | **318,576** |
| 0.65 | 150 | 315,938 (cliff) |
| 0.6 | 150 | + RE=0.5 → 313,444 (-5k regression confirmed) |

`combined_ship_v7.py` — final ship this session:

```python
CLIP_VOL_K   = 0.795   # was 0.3
DMID_HISTORY = 150     # was 20
H_PENNY_EDGE = 3.5     # was 2.0
AR1_BETA     = 0.25    # was 0.18
H_TAKE_EDGE  = 0.6     # was 0.0
H_REDUCE_EDGE = 0.0    # confirmed must stay 0
```

3-day bt: **318,576** (83,839 / 124,878 / 109,860), Δ +6,452 vs ship_v4.

**Live forecast:** entirely HYDROGEL gain.  At 2.27x conversion rate
the +6,452 bt → +14,650 live → ship_v4 live 395,880 → ship_v7 ~410,500
live.  Worth shipping.

No `import os` (passes upload validator).

`combined_ship_v6.py` (intermediate) kept on disk as the +5,236 ship
without TE, in case TE=0.6 turns out to behave differently in real
submission than the backtester predicts.

### 2026-04-24 — orientation session

- Read R3 briefing, uplink, schedule. R3 runs 04-24 12:00 → 04-26 12:00.
- Computed §0.2 sanity + IV fit. Key numbers above.
- Classified each product (H1-H5 above).
- Next step: ship baseline v1 (HYDROGEL MM + VELVETFRUIT MM only) and
  verify backtester runs on round-3 data before adding options logic.

### 2026-04-24 — session 1: baseline + Bio-Pod manual

PnL ladder — see `ROUND3_RECIPE.md` §7 for the full table. Core
progression:

| Version | Total (3-day) | Key change |
|---|---|---|
| v1 naive MM | -158k | VELVETFRUIT inside-touch bleed |
| v2 ACO-clone | +33k | HYDROGEL fixed but VELVETFRUIT still -EV |
| v3 HYDROGEL peak + V4000/V4500 | +158k | First real alpha |
| v4 all strikes 4000-5500 | +135k | ATM BS take bleeds (flat-σ bias) |
| **v5 (ship)** = {4000, 4500} only | **+168k** | Safety floor, all 3 days positive |

HYDROGEL grid-search peak (plateau):
`anchor=9990 clip=30 inv_skew=0.015 size=20 penny_edge=1.5`. CLIP is
the critical lever — going from 20 to 30 added +40k. Inv_skew is the
next most important — {0.010, 0.015, 0.020} win; 0.035 collapses PnL.

VELVETFRUIT_EXTRACT is -EV on every take threshold / clip combo we
tried. Leave alone in v5. Role: underlying-mid reference for voucher
pricing only.

VEV_4000 vs VEV_4500: VEV_4000 ships ~13k total (MM + take), VEV_4500
ships ~5k (almost entirely take). The wider spread on V_4000 (21 vs
V_4500's 16) gives MM fills; V_4500 MM doesn't fill on this data.

Manual Bio-Pod: primary recommendation (b1, b2) = **(780, 890)** per
rank-bid framework. EV/gardener ≈ 76 at avg_b2 ≤ 890. Reasoning in
`ROUND3_RECIPE.md` §4. "One step past herd" applied: step below the
b1=790 AI cluster, step above the b2=880-885 AI cluster.

Next session priorities:
- IV-residual MR overlay for strikes 5000-5500 (port Timo's EMA_diff
  logic from `traders/p3_fresh_claude/p3_combined_v1.py:404-441`).
- 3-way basis arb (S, V_4000+4000, V_4500+4500) — std < 1 tick.
- Delta hedge aggregate voucher position via underlying.
- Lottery posts at 0 for V_6000/V_6500 (low-priority).

### 2026-04-24 — smile-quadratic + VFE-hedge probe (dead end)

Built `smile_quadratic_hedged_v1.py` on top of v5. Added: per-strike
market-IV EMA persisted across day rollovers via traderData, quadratic
smile fit `iv_fair(k) = a + b*k + c*k²` (k = log(K/S)), curve-IV BS
fair + passive two-sided MM inside touch, aggregate net-delta hedge
into VFE when |net_delta| > 25. Strikes 5000-5500 as the MM universe.

3-day jmerle backtest (`--match-trades none` alpha test):

| Strategy                           | Day 0 | Day 1 | Day 2 | Total  |
|------------------------------------|------:|------:|------:|-------:|
| `baseline_v5` (ship)               | 1072  | 15782 | 22793 | **39646** |
| `fundamental_consensus_hedged`     | 2035  | 10908 | 17030 | 29973  |
| `smile_quadratic_hedged_v1` (new)  | -611  | 11206 | 16769 | 27364  |

`--match-trades all` (optimistic): v5 168031, smile 156958.

Failure modes:

1. **Smile sleeve ships zero fills on strikes 5000-5500 in `match-none`**
   even with a probe variant (MIN_EDGE=0.5, MIN_SPREAD=1, hedge off).
   Inside-touch passive quotes sit too close to mid on spread=1-6
   ticks; bot flow doesn't cross. Same structural failure as v15's
   per-strike residual EMA (+66 PnL live).
2. **VFE hedge is pure tax** — costs 4.5-6k/day in match-none, since
   V_4000/V_4500 are deep-ITM (delta≈1) synthetic spot clones. Hedging
   their delta through VFE just burns the 5-tick spot spread for no
   variance-reduction benefit. The hedge fires on every non-trivial
   voucher position and can't be rescued by parameter tuning.
3. **Quadratic smile fit itself is mechanically sound** (smoke-tested
   BS inversion roundtrips to 1e-4, fit returns stable coefs) — the
   problem is downstream: there's no fill mechanism on ATM strikes
   that this round's spreads support.

File kept at `smile_quadratic_hedged_v1.py` for reference. Do NOT
ship. To revisit: the idea only works if you switch from passive MM
to take-side (cross when curve-IV says quote is rich by ≥ X ticks),
and even then needs to survive adverse selection — the same wall v7
hit.

### 2026-04-25 — session 5: post-live-data exploration (combined_ship_v5, 310k)

User submitted ship_v4 → live **+395,880** (+375 over ship_v2 live).
Live-vs-backtest ratios so far:

| Ship | bt 3-day | live | ratio |
|---|---:|---:|---:|
| h_only_v8 alone | 171,890 | 391,745 | 2.27x |
| ship_v1 | 268,008 | 393,037 | 1.47x |
| 393333 (parallel scalp) | 213,927 | 393,333 | 1.84x |
| ship_v2 | 279,355 | 395,505 | 1.42x |
| ship_v4 | 312,124 | 395,880 | **1.27x** |

**The bt-to-live ratio drops every time we add voucher-side complexity.**
Each marginal voucher addition adds ~1-22% of its bt gain to live.
HYDROGEL converts at 2.27x — adding more voucher backtester alpha
doesn't unlock more live PnL because the marginal alpha doesn't exist
in live data.

**11 ablations vs ship_v4 — none beats it on backtest**:

| Variant | Spec | bt total |
|---|---|---:|
| **v4 (ship)** | base | **312,124** |
| v71 | drop VEV_5300 strike | 310,198 (-1,926) |
| v67 | OPT_MR_THR=6 (less voucher) | 289,330 (-22,794) |
| v70 | MR strikes={5100,5200} only | 293,493 (-18,631) |
| v68/v69 | VS_MAX_POST_SIZE=80/120 | 312,124 (no change, capacity-bound) |
| v65 | H_MAX_POST_SIZE=40 | 249,380 (-62,744) |
| v66 | H_MAX_POST_SIZE=60 | 224,710 (-87,414) |
| v61 | voucher MR fully off | 242,165 (-69,959) |
| v62 | HYDROGEL deeper passive layer | 198,950 (-113,174) |

Tried and rejected:
- **Layer-2 deeper passive HYDROGEL** (skew−13 / skew+13 quotes at
  size 30): -113k bt. Adverse selection — deeper quotes get filled
  exactly when fair has shifted unfavorably. Backtester's `--match-
  trades none` showed +0 bt impact (no fills), so the loss is from
  same-tick trade-print fills at adverse prices. Either way, dead.
- **Bigger HYDROGEL post size (40, 60)**: -63k / -87k bt. Same
  adverse-selection mechanism on the primary make layer.
- **Bigger V_4000 synth MM size (80, 120)**: identical to v4
  (capacity-bound — V_4000 daily fill volume already saturated at 40).

Per-strike contribution analysis (v4 backtest delta): VEV_5000 = 17k,
5100 = 28k (biggest), 5200 = 24k, 5300 = 1.9k.

**Decision: ship combined_ship_v5.py** (= ship_v4 minus VEV_5300 from
MR_STRIKES). -1,926 backtest, but reduces voucher position variance
with negligible expected live loss (5300's contribution at 1-22%
conversion = $20-450 live). Conservative choice given live noise
exceeds this delta.

**Key learning to bake into recipe**: stop tuning voucher backtester
alpha. Each percent extracted in backtest converts to <0.3% in live.
The 1.27x ratio at ship_v4 is plateauing — optimization should pivot
to either (a) HYDROGEL passive-fill modeling improvements that
preserve backtest, or (b) accept ship_v4/v5 as the local max.

Tried but didn't help backtest (skipped from ship): drift handler
from baseline_v17, VFE-momentum overlay from baseline_v18, L3_BETA
from h_only_v9 (-19k standalone), CLIP_VOL_K > 0.3, AR1_BETA tweaks.

Ship file: `traders/round3/combined_ship_v5.py`.
3-day backtest: +310,198 (83,364 / 119,466 / 107,368).
Alpha floor: +142,938 (vs v4 +144,856; -1.3% — within noise).

### 2026-04-25 — session 4: cross-track integration (combined_ship_v4, 312k)

User flagged: parallel work has been happening on alternate tracks
(`baseline_v15..v19.py`, `h_only_v9..v14.py`) and several have been
submitted live. Asked to compare and integrate.

**Live PnL ladder** (from `test_results/<pnl>/<pnl>.{py,json,log}`):

| File | Strategy | Live PnL |
|---|---|---|
| 391745.py | h_only_v8 (HYDROGEL alone) | 391,745 |
| 393037.py | combined_ship_v1 | 393,037 |
| 393333.py | parallel Timo IV-scalp (THR=0.03) | 393,333 |
| 395505.py | combined_ship_v2 (iv_dev weight 2.25) | 395,505 |

**KEY LEARNING**: voucher alpha generalizes BADLY to live.
- HYDROGEL alone: 391k live, 172k backtest → 2.27x lift.
- ship_v1's voucher machinery: +96k backtest, +1,292 live (1.3% rate!).
- ship_v2's iv_dev tune: +11k backtest, +2,468 live (22%).

The Timo IV-residual MR I built captures backtester alpha that doesn't
exist in real markets. HYDROGEL passive MM does the heavy lifting in
live (~99% of total). Future optimization should prioritize HYDROGEL
and passive-make sleeves over voucher MR signal tuning.

**Head-to-head backtest of all candidates**:

| Strategy | Backtest 3-day |
|---|---|
| h_only_v8 | 171,890 |
| h_only_v9 (+L3_BETA) | 152,499 (-19k vs v8 — DOES NOT HELP) |
| h_only_v14 (anchor/skew retune) | 175,497 (+3,607 vs v8) |
| baseline_v17 (drift+ATM+lottery+capflat) | 200,406 |
| baseline_v18 (+VFE-mom HYDROGEL) | 202,278 |
| baseline_v19 (+L3_BETA HYDROGEL) | 205,996 |
| combined_ship_v1 | 268,008 |
| combined_ship_v2 | 279,355 |
| combined_ship_v3 (=v2+h_only_v14) | 282,962 |
| **combined_ship_v4 (=v3+ATM+lottery)** | **312,124 (+29,162)** |

Three findings during integration:
1. **h_only_v14 retune is real** (+3.6k) and ports clean to ship_v3.
2. **L3_BETA imbalance signal LOSES money** in standalone backtest
   (-19k vs v8). Despite the parallel agent's R²=0.79 statistical
   evidence at narrow spread, the integrated PnL is worse. Don't ship.
3. **ATM smile-EMA on 5400/5500 is GOLD**. baseline_v17's per-strike
   contributions: V5400 +5,377 / V5500 +2,183 (day 2). My MR signal
   was bad on those strikes (vega<1). The smile-EMA's slow
   `ATM_RESIDUAL_ALPHA = 1/5000` learns the smile bias and then
   passively MMs at fair. Adding to ship_v3 → +29,162 backtest, +8,708
   alpha-only (so most of it is real, not matching-engine).

**Why ATM smile-EMA wins where Timo MR fails on 5400/5500**:
- Timo MR fires at |combined|>5; on OTM strikes with vega<1, residual
  scale is small, so the threshold is rarely hit (or fires on noise).
- Smile-EMA centers per-strike fair value over 5000-tick window, then
  MMs at that fair. No threshold needed; MM captures spread on every
  fill. Works because the smile bias is approximately stationary.

Combined v4 = v3 + ATM smile-EMA + lottery (no L3_BETA, no drift
handler, no VFE-mom overlay — those didn't help in backtest).

**Ship: `traders/round3/combined_ship_v4.py`**.
3-day backtest: +312,124 (81,027 / 123,658 / 107,440).
Alpha floor: +144,856.

Live extrapolation: ATM/lottery sleeves are passive-make so should
benefit from the same matching-engine boost as HYDROGEL. Expected
~400-405k live (vs 395,505 for ship_v2). Voucher MR portion still
~1-3% real conversion to live, so the +29k backtest probably yields
+5-10k live, dominated by the smile-EMA passive sleeves.

### 2026-04-25 — session 3: signal-weight discovery (combined_ship_v2, 279k)

User submitted ship_v1 to live and got **393,037** (vs 268k backtest →
+125k gap, attributable to passive-fill modeling in the backtester
matching engine). Asked to deep-dive on improvements.

**Forensics first** (`/tmp/r3_forensics.py`): per-day per-strike IV
fits, basis stds, V6000/V6500 prints, combined-MR signal histograms.

Key findings:
1. **Sigma is ~0.243, not 0.23** (true mean across 5000-5300 strikes,
   drifts 0.241 → 0.244 day 0 → day 2). Not flat-flat — V_5400 IV is
   consistently ~0.229 (~"lower wing"). But iv_dev EMA centers it.
2. **|combined| signal p99 ≈ 6.5** across all strikes/days — confirms
   THR=5 catches the 5%-tail. THR=4 fires top 10% (mostly noise).
3. **Lottery V6000/V6500: dead.** Mid stuck at 0.5, max liquidation EV
   ~50 SS. Not worth coding.
4. **3-way basis arb: dead.** V4000+4000 vs S std=0.83, max ±7 ticks,
   but round-trip cost ~4 ticks. Edge < cost.

Iterations and what bit:
1. **Chunked MR** (size scales with |signal|-threshold): wash at THR=5.
   Lower threshold still blew up — signal genuinely has no alpha < 5.
2. **HYDROGEL post-size sweep**: 18 still peak in backtester.
   60 collapses (-54k). Live > backtest gap is matching-engine
   modeling, not our post sizes.
3. **Layer-2 passive close** (flatten passive when signal reverts):
   marginal +228 at MR_CLOSE_THR=2; not worth shipping.
4. **THEO_NORM_WINDOW sweep**: 20 confirmed peak (5/10/50 worse).
5. **Chunked VFE MR**: wash. Lower UNDER_MR_THR still loses.

**THE BREAKTHROUGH — signal weight sweep**:

Decomposed `combined = ema_o_dev + 1.0 * iv_dev` and tested ablations:

| Variant | Total |
|---|---|
| ship_v1 (1.0 weight) | 268,008 |
| ema_o_dev only | 261,980 |
| iv_dev only | 209,396 |
| weight 1.5 | 267,578 |
| **weight 2.0** | **278,620 (+10,612)** |
| weight 2.25 | **279,355 (+11,347 — peak)** |
| weight 2.5 | 272,890 |
| weight 3.0 | 264,358 |
| weight 4.0 | 230,958 |
| 0.5*ema_o + 2*iv_dev | 210,446 |

iv_dev is per-unit ~2x more predictive than ema_o_dev. Both still
needed (pure iv_dev = 209k, pure ema_o_dev = 262k). Peak at 2.25.

THR re-sweep at weight 2.25: 4 → -25k (cliff), 5 → 279k, 6 → 257k.
Strike re-sweep at weight 2.25: +5400 → 274k, -5300 → 274k. Set
{5000-5300} unchanged. Layer-2 close at weight 2.25: +/-83 wash.

Why iv_dev is more predictive: it captures voucher-specific residual
mean-reversion that the underlying-EMA misses (per-strike quote
staleness, smile shifts, cross-strike noise). ema_o_dev adds a useful
underlying-momentum prior on top, but the right relative weight is
~2.25:1 in favor of iv_dev.

**Match-trades none (alpha-only) sanity check**:
- ship_v1: 124,854
- combined_ship_v2: 136,148 → +11,294

The +11k gain is REAL (not matching-engine artifact); both modes
agree to within 0.5%.

**Ship: `traders/round3/combined_ship_v2.py`**.
3-day backtest: +279,355 (75,352 / 108,346 / 95,657).

Backtest command:
```
python3 tools/jmerle_backtester.py traders/round3/combined_ship_v2.py 3 --merge-pnl --no-out
```

Live extrapolation: ship_v1 backtest 268k → live 393k (+47%). Same
multiplier on v2 backtest 279k → ~410k. But variance is high.

### 2026-04-24 — session 2: Timo P3R3 voucher port (combined_ship_v1, 268k)

User asked to follow Timo Diehm's P3 R3 process verbatim — clone the
options handler from `p3_fresh_claude/p3_combined_v1.py:296-477`, refit
constants for P4R3, layer on top of the locked-in h_only_v8 HYDROGEL
sleeve. Smile is flat (σ=0.23) so SMILE_A/B/C are replaced with a
single constant; residual EMA still centers per-strike bias.

Layered architecture (each component independently validated):

1. HYDROGEL_PACK: h_only_v8 handler (frozen — 171,890 alone).
2. VEV_4000 / VEV_4500: baseline_v5 synthetic-underlying MM (frozen).
3. Strikes 5000-5300: Timo-P3R3 MR on (ema_o_dev + iv_dev).
4. VELVETFRUIT_EXTRACT underlying MR (Timo's `ENABLE_UNDERLYING_MR`).

PnL ladder (3-day, match-trades all):

| Version | Spec | Total | Δ vs h_only |
|---|---|---|---|
| h_only_v8 (prior ship) | HYDROGEL only | 171,890 | — |
| combined_v1 | + 4000/4500 synth MM + MR{5000,5100,5200} + scalp{5300-5500} | 240,655 | +68,765 |
| combined_v2 | MR{5000-5500} (scalp moved to MR) | 239,346 | +67,456 |
| combined_v3 | MR{5000-5300} only | 249,179 | +77,289 |
| combined_v4 | v3 + OPT_MR_THR=3 | -542,390 | (broken — noise) |
| combined_v5 | v3 + OPT_MR_THR=7 | 247,929 | +76,039 |
| combined_v6 | v3 + OPT_MR_THR=4 | -66,264 | (broken) |
| combined_v7 | v3 + OPT_MR_THR=6 | 234,806 | +62,916 |
| **combined_v8 (ship)** | v3 + underlying MR (UNDER_MR_THR=5) | **268,008** | **+96,118** |
| combined_v9 | v8 + UNDER_MR_THR=3 | 174,943 | +3,053 |
| combined_v10 | v8 + UNDER_MR_THR=7 | 254,186 | +82,296 |
| combined_v11 | v8 + UNDER_MR_THR=10 (no fires) | 249,179 | +77,289 |
| combined_v12 | v8 + UNDER_MR_THR=4 | 251,090 | +79,200 |
| combined_v13 | v8 + UNDER_MR_THR=6 | 254,528 | +82,638 |
| combined_v14 | v8 + OPT_MR_WINDOW=20 | 221,908 | +50,018 |
| combined_v15 | v8 + OPT_MR_WINDOW=50 | -410 | (broken) |
| combined_v16 | v8 + OPT_MR_WINDOW=25 | 242,379 | +70,489 |
| combined_v17 | v8 + OPT_MR_WINDOW=40 | 116,888 | -55,002 |

Per-strike PnL contribution (combined_v8 day 2 example):
- HYDROGEL: 57,634
- VFE underlying MR: 4,146 (day total - voucher total - HYDROGEL)
- VEV_4000: 5,039 (synth MM)
- VEV_4500: 2,795 (synth MM)
- VEV_5000: 5,490 (Timo MR)
- VEV_5100: 10,297 (Timo MR — biggest single voucher contributor)
- VEV_5200: 5,689 (Timo MR)
- VEV_5300: 1,465 (Timo MR)

Match-trades none (alpha-only floor): +124,854 vs baseline +37,656
→ +87,198 alpha. So ~95k of the +96k all-mode lift is robust alpha,
the rest is matching-engine optimism.

Why this beats the smile_quadratic_hedged_v1 dead end (-12k vs v5):
that strategy posted PASSIVE inside-touch quotes on ATM strikes, which
sit too close to mid on tight 1-6 tick books and don't fill. Timo's
MR/scalping CROSSES the touch when residual signal fires — it's a
take-side strategy, not a make-side. The signal `combined = ema_o_dev
+ iv_dev` only fires on rare large deviations (~5+ ticks), and on
those events crossing the spread is +EV.

What we left on the table:
- IV scalping on OTM 5300/5400/5500: 0 fills on this data. Worth
  re-checking if real-submission spreads widen. Logic still in code,
  bucket SCALP_STRIKES is empty.
- VEV_6000/VEV_6500 lottery posts at price 0: untouched.
- Per-strike per-day SIGMA refit: not attempted; flat 0.23 works.
- Aggregate delta hedge across vouchers: previous v7 dead end says
  -EV. Not retried.

Ship file: `traders/round3/combined_ship_v1.py`. Backtest command:

```
python3 tools/jmerle_backtester.py traders/round3/combined_ship_v1.py 3 --merge-pnl --no-out
```

Expected: day 0 = 72,648; day 1 = 102,805; day 2 = 92,555; total 268,008.

### 2026-04-24 — HYDROGEL-only deep dive (v6 → v8)

User asked "are you 100 % sure HYDROGEL has NO covariates with VEV /
VEV strikes / volume / spread / time-of-day, even lagged?" Three
covariate-hunt passes (`covariate_hunt.py`, `_v2.py`, `_v3.py`):

| Test | Result |
|---|---|
| Δmid(H)~Δmid(X) at lag ±5, all 9 cross-products | best \|R\|=0.03, signs flip across days |
| pooled OLS with day-FE | all \|t\| ≤ 1.26 |
| partial corr controlling own-imbalance + AR(1) | best \|t\| = 3.24 day 2 only, doesn't replicate |
| **OOS R² of 36-feature OLS, train 2 days / test 3rd** | **NEGATIVE for all 3 rotations** (-0.0033, -0.0024, -0.0020) |
| sign-only IC X→H at K∈{1,5,20} | best \|z\|=1.34 |
| basket Σsign(ΔX) | HR=0.50, \|z\|≤1.21 |
| signed trade flow | one z=-3.10 day 1 only, doesn't replicate |
| hour-of-day diurnal | per-bucket means ~10⁻² ticks, no consistent shape |
| block returns K=50/200/500 | sign-flip across days → spurious common-trend |
| regime-gated (spread>16) | nothing significant |

**Verdict — HYDROGEL is statistically independent of every other
product. No usable cross-product covariate.**

Built `h_only_v8.py` from own-microstructure only:
- spread-gated micro-price (TYPICAL_SPREAD=16, fall back to touch_mid
  at typical regime where own-imb has zero predictive z, see
  `imb_regime.py`)
- AR(1) lean (β = 0.18; cliff at β≤0.13)
- volatility-adaptive CLIP (CLIP_VOL_K = 0.3, std over last 20 ΔH)
- shifted anchor 9985 (true mean is 9990; -5 biases inventory toward
  shorts and pairs with reduce_edge=0 to capture mean-reversion)

3-day backtest (HYDROGEL ONLY): **171,890** (61,791 / 52,465 / 57,634).
- vs v5 HYDROGEL-only baseline (149,355) → **+22,535 (+15.1 %)**
- vs v5 ship total HYDROGEL+VEV (168,031) → **+3,859** (HYDROGEL alone now
  beats the v5 ship even with VEV alpha included)

PnL ladder for HYDROGEL alone:

| Version | params | 3-day total |
|---|---|---|
| v5 baseline | a=9990, c=30, ar=0, rd=1.0, sz=20 | 149,355 |
| v6 (+ micro-gate, AR1=0.13, layer2 noop) | a=9990, c=30, ar=0.13, rd=1.0 | 150,512 |
| v7 combo (rd=0, ar=0.15) | a=9990, c=30, ar=0.15, rd=0.0 | 154,656 |
| v7 + anchor=9985 + clip=33 | a=9985, c=33 | 168,493 |
| v7 + (+pn=4.0, ar=0.18) | + tweaks | 168,784 |
| v7 + size=18, CLIP_VOL_K=0.3 | full v8 | **171,890** |

See `HYDROGEL_ONLY_RECIPE.md` for full param table + ablation
breakdown + don't-list. Ship file: `traders/round3/h_only_v8.py`.

### 2026-04-24 — Timo P3 R3 method ported (timo_clone_FINAL.py)

User asked: "follow the same process Timo Diehm did for P3 R3, do round 3
here. should be very similar; clone for these assets then improve, beat
Timo no shortcuts."

Method (from Timo's `FrankfurtHedgehogs_r3.py` + README):
  1. Per-strike: theo = BS_call(S, K, T, sigma_smile)
  2. diff = mid - theo;  mdiff = EMA(diff, win=20)
  3. residual = diff - mdiff  (smile-bias-corrected)
  4. switch_mean = EMA(|residual|, win=100)  ← regime gate
  5. score (sell) = best_bid - theo - mdiff   ← already nets cross-spread cost
  6. score (buy)  = best_ask - theo - mdiff
  7. If switch_mean > THR_SW: trade-side at touch when |score| ≥ THR_OPEN

Adaptations to P4 R3:
  - Smile is FLAT (sigma=0.23 across 5000-5500), no quadratic fit. EMA
    absorbs any residual bias automatically.
  - Residual std ~0.4 vs Timo's P3 ~0.7 → switch_mean THR=0.7 dead;
    removed gate.
  - SCALP_THR_OPEN swept from 0.50 → 0.03 (peak); plateau [0.01, 0.05].
  - OTM strikes 5400+ have POSITIVE 1-lag AC (momentum, not MR); excluded.
  - K=5200/5300 net-flat to slightly negative in jmerle (mark-to-mid +
    but position carry -); excluded from scalp universe.

Sleeve composition (final):
  - HYDROGEL_PACK: h_only_v8 verbatim (171,890 standalone)
  - VEV_4000/4500: synthetic-underlying MM, baseline_v5 logic (+13k)
  - VEV_5000/5100: Timo IV-scalp at THR=0.03 (+28-29k combined)
  - Everything else: untraded (verified -EV)

3-day backtest progression:
  v1 (THR=0.5, K=5000-5300):    198,652
  v2 (THR=0.3, K=5000,5100):    206,698
  v3 + sw_gate=0.15:            203,271 (gate hurts)
  THR sweep peak (THR=0.03):    213,927  <-- SHIPPED
  Δ vs baseline_v5 168,031:     +45,896 (+27.3%)

Per-day breakdown of timo_clone_FINAL:
  Day 0: 64,807   (IV-scalp slightly negative; EMA warmup)
  Day 1: 66,241   (IV-scalp +6.8k)
  Day 2: 82,879   (IV-scalp +17.4k; HYDROGEL strong)

Tested-and-rejected (all -EV at every parameter tested):
  - VFE EMA-MR with take-side: -60k/day (alpha 0.12/tick < spread 2.5)
  - OTM (K=5400+) momentum chase: -150 to -19k per THR setting
  - Basis arb (S vs vouchers): -250 to -12k per THR (2-leg spread cost)
  - K=4000/4500 IV-scalp on top of synth: 0 fills (residual std ≈ 0)
  - switch_mean gate at any THR > 0: hurts PnL (suppresses good trades)
  - Per-strike alpha sweep (mark-to-mid, 1-tick hold): K=5000/5100
    +200-300/strike/day; K=5200/5300 +50-80/day mark-to-mid but jmerle
    realises -300 to -700 due to position carry through reverting EMA.

Ship file: `traders/round3/timo_clone_FINAL.py`.
Reproduce: `python3 tools/jmerle_backtester.py traders/round3/timo_clone_FINAL.py 3 --merge-pnl --no-out`

## Update 2026-04-25 (session 5): R2 day -1 → R3 transfer audit (direction #4)

Goal: investigate the R2 day -1 96k vs leaderboard top 154k gap and find
patterns that transfer to R3 / HYDROGEL.

### R2 baseline reproduction (local_bundles_profile.json calibration)

| Strategy | day -1 | day 0 | day 1 | 3-day |
|---|---|---|---|---|
| `fresh_from_scratch_v3` (recipe ship) | 141,258 | 137,229 | 143,445 | 421,932 |
| `clean_alpha` v10 (full kitchen-sink) | 144,546 | 145,238 | 154,484 | 444,268 |
| Δ (clean_alpha − v3) | +3,288 | +8,009 | +11,039 | +22,336 |

Per-day per-product (fresh_v3 → clean_alpha):
- day -1 ACO 64,747 → 63,394 (−1.4k); IPR 76,510 → 81,152 (**+4.6k**).
- day 0  ACO 65,213 → 65,014 (flat);  IPR 72,016 → 80,224 (**+8.2k**).
- day 1  ACO 63,872 → 69,182 (+5.3k); IPR 79,573 → 85,302 (**+5.7k**).

The day -1 +3k delta is **entirely IPR z-score MR**, not ACO microstructure.

### Where the 96k vs 154k gap actually came from

`fresh_from_scratch_v3` projects 134k/day real (140k local × 0.96
conversion per ROUND2_RECIPE.md). Our shipped `284364.py` was
**conservative**: ACO_MAX_POST_SIZE=19 (vs recipe 75), IPR_CORE_TARGET=67
(vs recipe 80), MAF_BID=9000 (vs recipe 15000). That conservatism is
the dominant 38k of the 58k gap. The remaining ~20k = clean_alpha
deltas above + tuning noise + leaderboard top's MAF bid.

### R2 alphas not in our R3 ship — transfer audit

| R2 lever (clean_alpha v10) | Already on R3 ship_v11? | Transfers? |
|---|---|---|
| `ACO_REDUCE_EDGE = 1.0` (extra take when reducing inventory) | No (H_REDUCE_EDGE=0) | **No** — explicitly tested in v16 recipe: RE=0.5 → −2.8k; RE=1.0 → −8.9k. With H_TAKE_EDGE=0.5 already, RE>0 means covering at *worse* than fair. Rejected. |
| IPR z-score MR (`RICH_Z=1.2 / CHEAP_Z=−1.2`) around drift line | No | **No** for HYDROGEL (no fixed drift; AR1_BETA=0.17 already absorbs MR). **Yes** for VFE — that's session-4 direction #2 (drift carry), already on the work list. |
| 2-level passive ladder (primary at bid+1, secondary at bid+2) | No | **No** — tested 3 variants below. |
| `IMB_FAVORABLE_BOOST=1.8 / IMB_ADVERSE_SHRINK=0.2` on quote sizing | No (HYDROGEL); No (synth-MM) | Direction #3, in flight elsewhere. |
| Walked-side EXTRA quote (rebound) | No | Direction #1, in flight elsewhere. |
| EOD unwind | No (HYDROGEL) | Marginal on backtest (R2 added +104). Skipped. |

### 2-level passive ladder on HYDROGEL — three variants, all regress

Tried porting clean_alpha's `IPR_PASSIVE_SIZE=12 / IPR_PASSIVE_SECOND_SIZE=6`
priority-ladder onto HYDROGEL's penny-MM block in combined_ship_v11.

| Variant | Description | 3-day total | Δ vs v11 |
|---|---|---|---|
| v11 baseline | single quote at bid+1 / ask−1, size 18 | **428,754** | — |
| ladderA | split 18 → 12 primary + 6 secondary 1 tick CLOSER to fair | 409,593 | **−19,161** |
| ladderB | unchanged primary 18 + extra 6 one tick AWAY from fair (deeper) | 428,754 | 0 (extra never fired — would land at `bb`, not inside spread) |
| ladderC | unchanged primary 18 + extra 6 one tick CLOSER to fair (in addition) | 386,518 | **−42,236** |

Why it fails on HYDROGEL but worked on IPR:
- IPR books are thin (L1 vol ~25), single inside-quote is queue-able-out
  → 2nd slot worth real queue priority.
- HYDROGEL spread is 16 with deep books; primary at bb+1 already gets
  most of the available passive flow. Adding inner slots means filling
  at *closer to fair* prices (worse edge) without earning meaningfully
  more queue priority — the size cliff at H_MAX_POST_SIZE≥20 may also
  be biting here (ladderC's 18+6=24 per side likely shifts the fill-rate
  bucket adversely).

### Conclusion (direction #4)

Day -1 has the lowest variance regime (ACO sd 387 vs 469 on day 1; IPR
sd 505 vs 612 on day 1). No unique day-1-only signal was found beyond
the cross-day clean_alpha deltas. The 96k vs 154k gap is dominated by
**conservative shipping in R2**, not missing alpha — and the R2 alphas
clean_alpha *did* extract do not transfer to HYDROGEL on R3 (every
candidate was either already tested-rejected, structurally-not-applicable,
or empirically regressed).

The session-4 voucher MR / VS_INV_SKEW / HYDROGEL retune work in v11 is
nearer the local ceiling than the R2 fresh_v3 ship was. The remaining
upside on R3 is more likely in the user's directions #1 (walked rebound),
#2 (VFE drift carry — direct IPR-pattern transfer), #3 (imbalance
quote-sizing on synth-MM), and #5 (HYDROGEL day-1 vol-regime gating)
than in further R2 → HYDROGEL transplants.

---

## Session 5 (2026-04-25) — Direction #3: Imbalance-aware sizing on synth-MM

Goal: port clean_alpha's `IMB_FAVORABLE_BOOST=1.8 / IMB_ADVERSE_SHRINK=0.2`
to V4000/V4500 synth-MM. User hypothesized this could close the day-0 synth gap
(VEV_4000=2,802 / VEV_4500=−286 vs day-2 14,482 / 12,760 in v11).

### Imbalance signal verification (R3 days 0-2 prices CSV)

| Product | |imb_L1|>0.30 fires | next-tick Δmid (positive) | (negative) | hit-rate |
|---|---|---|---|---|
| VEV_4000 | 484 / 30,000 ticks (1.6%) | +5.49 | −5.05 | 99% / 100% |
| VEV_4500 | 423 / 30,000 ticks (1.4%) | +4.12 | −3.76 | 99% / 100% |

Signal is **only** present in tight-spread regime:
- VEV_4000 typical spread = 21; |imb|>0.3 events all at spread 9-12
- VEV_4500 typical spread = 16; |imb|>0.3 events all at spread 7-9

In wide-spread regime (98% of ticks) bots pad both sides symmetrically
and L1 imbalance is essentially 0. Threshold sweep 0.05–0.30 shows
all events catch the same +5/−5 cohort — signal is binary (zero or strong).

### Variants tried — net regression

| File | Mechanism | 3-day backtest | Δ vs v11 (428,754) |
|---|---|---|---|
| `combined_ship_v13.py` | sizing only (BOOST=1.8, SHRINK=0.2) | 428,742 | **−12** |
| v13b (deleted) | + fair-shift +0.5 ticks | 418,182 | −10,572 |
| v13b (deleted) | + fair-shift +1.0 | 409,942 | −18,812 |
| v13b (deleted) | + fair-shift +1.5 | 409,173 | −19,581 |
| v13b (deleted) | + fair-shift +2.0 | 408,615 | −20,139 |
| v13b (deleted) | + fair-shift +3.0 | 408,649 | −20,105 |
| v13c (deleted) | sizing + adverse-take guard | 428,742 | −12 (guard never fires) |
| v13d (deleted) | sizing BOOST=7.5/SHRINK=0 | 428,750 | −4 |

### Why backtest doesn't move

1. **Synth fills are delta-driven, not own-microstructure.** Take loop
   (`ap <= fair`) fires when VFE moves and voucher lags. In tight-spread
   regime where imb fires, the typical book has ap > fair so take loop
   doesn't engage (and adverse-take guard never bites).

2. **Phantom-trade flow is thin.** V4500 had ZERO trades on day 0,
   V4000 had 351 vol total. Passive bb+1/ba-1 posts inside the spread
   require phantom trades at ≤ our price to fill — there are none in
   the imb-firing regime.

3. **Fair-shift overshoots.** Leaning fair by +shift when imb>0.3 makes
   the take loop cross the spread aggressively. Day 0 gets a small lift
   (+344..+1,170) but days 1-2 lose 8-13k from fills the +5 next-tick
   move can't fully recoup in this fill model.

### Decision: ship v13 (sizing-only port)

Net backtest delta is −12 PnL (noise floor). v13 is structurally
defensive: it shrinks the side that imbalance pushes against and only
fires in tight-spread regime where the signal is real (>99% hit rate).
The signal exists in the data even if backtest can't capture it; live
adverse-selection events on synth should be at least as strong, and
the live fill simulator may reflect them more faithfully than the
recorded-trade replay used in backtest. This is a "defensible no-harm,
maybe converts live" change.

`combined_ship_v13.py` total 428,742 (122,899 / 150,246 / 155,597).

## Update 2026-04-25 (session 9): exotic-signal hunt + v15_hdrift_aggr (445,498 bt)

Mandate from session-8 close: "explore fundamentally new alpha categories
— temporal patterns, basket signals, IPR-style deterministic drift on R3
products we haven't profiled, order-book-shape signals." Goal: a
+100k breakthrough beyond v15 (443,484).

### Signals SCANNED (data/round3/*.csv; partial-corr controls applied)

| Category | Finding | Verdict |
|---|---|---|
| **VFE aggressor flow** (signed-qty from `state.market_trades`) | corr(K=1, next_dmid)=+0.28/+0.22/+0.34; E[Δ\|AGG≥+5]=+0.55, E[\|AGG≤-5]=-0.18 | **REAL — partial-converts (+50 bt; +360 bundle-cal in some runs, 0 in others — bundle 1k-tick window is too sparse)** |
| **HYDROGEL deep-book (L2+L3) imbalance** | β = −19 to −22, R²_alone=0.11 across 3 days, OPPOSITE sign from L1 (+0.30); ΔR² over L1 = +0.022 | **REAL but UNMONETIZABLE** — fair-shift (-2k to -10k), size-shrink (-1.2k to -2.2k); matcher cap dominates |
| **VEV_4000 deep-book + L1 joint** | R²_alone (L1) 0.23, (L23) 0.24, joint 0.24 | Marginal incremental (+0.008) — synth-MM fair-shift already tested-rejected per memory |
| **Vertical spreads (V5000-V5500 chain)** | ALL pairs AR(1)(diff) = -0.34 to -0.47, sd 1.5-4.6 | **REAL MR but signal < spread cost** — V5300-V5400 sd 3.14, 1σ-edge 1.4 vs round-trip 3.5 ticks |
| **Butterflies (V_K - 2·V_{K+1} + V_{K+2})** | AR(1)(diff) = -0.42 to -0.49 across all centroids/days | Same — 3-leg cost > edge |
| **VEV_4000 + 4000 ↔ VFE basis** | mean ≈ 0, sd 0.83, AR(1)(diff)=-0.50 | Already in memory: round-trip ≥4 > available edge |
| **Trade-size-conditional aggressor** (qty buckets 4-/5-7/8-10/11+) | huge_11+ BUY: E[Δ]=+1.6/+2.2/+2.0; large_8-10 BUY: +0.74/+0.74/+0.90 | **REAL but cross-take still net negative** (huge: 2.0 < 2.5 half-spread) |
| **VEV_4000 ↔ VFE lead-lag** | contemporaneous corr=+0.59; V4000→VFE lag-1=-0.015; VFE_imb→V4000 lag-1=+0.08 (weak) | Voucher-stock lead-lag is **dead** (contemporaneous only) |
| **Voucher cross-leads V_5500→V_5400, V_5400→V_5300** | lag-1 = +0.27 to +0.50 same-tick; lag-2,3 = noise | Same-tick coupling only — no exploitable lead |
| **Time-of-day buckets** | flat across 10 buckets/day for HYDROGEL/VFE/V4000/V5300-5500 | **DEAD** (no morning/afternoon asymmetry) |
| **Trader IDs** | buyer/seller fields all empty in R3 historical CSVs | **N/A** (anonymized) |

### What shipped — `combined_ship_v15_hdrift_aggr.py` (445,498)

Combines two orthogonal session-9 wins:

1. **HYDROGEL drift-regime gate** (already in `combined_ship_v15_hdrift.py`):
   200-tick mid-range gate widens CLIP_VOL_K when range>53. Per-day
   improvements +629/+660/+676 over v15.
2. **VFE aggressor SHRINK overlay** (NEW): in the drift-carry MR-silent
   branch, when signed-aggressor sum from this tick's `market_trades`
   ≤ -3 (strong seller flow), shrink the bb passive-bid size by 0.3
   to avoid loading inventory at a falling mid.

3-day jmerle bt:

| Variant | Total | Day 0 | Day 1 | Day 2 |
|---|---|---|---|---|
| v15 (session-8 ship) | 443,484 | 136,310 | 156,750 | 150,423 |
| v15_aggr (NEW) | 443,534 (+50) | 136,315 | 156,760 | 150,458 |
| v15_hdrift | 445,448 (+1,964) | 136,944 | 157,410 | 151,094 |
| **v15_hdrift_aggr (NEW SHIP)** | **445,498 (+2,014)** | 136,944 | 157,420 | 151,134 |

Bundle-cal on bundle 399113 (most-recent v11/v15-class submission):
- v15: 41,435.5 (cal_minus_official −360.3)
- v15_hdrift / v15_hdrift_aggr: 41,989.5 (+193.7) — full-day jmerle
  delta (+50) doesn't show in 1k-tick bundle window (aggressor fires
  too sparsely there).

### Aggressor lever knob sweep (recorded for future reuse)

`VFE_AGGR_THR` × `VFE_AGGR_BID_SHRINK` (with INSIDE=0, BOOST=1.0):
- THR=3, SHRINK=0.3 → 443,534 (peak)
- THR=5, SHRINK=0.3 → 443,532
- THR=8, SHRINK=0.3 → 443,492
- SHRINK=0.0 → 432,354 (-11k, full bid skip too aggressive)
- SHRINK=0.5 → 443,496 (+12)
- BOOST sweep: BOOST 1.0/1.5/2.0 all → 443,484 unchanged.
  **Matcher fill-cap binds**: enlarging quote size doesn't add fills.
- INSIDE=1 (post bb+1 on buyer flow) → 432,354 (-11k, queue-position
  loss — confirms `feedback_vfe_drift_carry_negative.md`).

### Knobs tested and REJECTED (don't redo)

- `H_DEEP_K` fair-shift via L23 imbalance: 0→443,534, 0.5→442,920,
  1.0→440,944, 8.0→433,214. **Monotonic loss.**
- `H_DEEP_THR/SHRINK` size-shrink via L23 imbalance: 0.2/0.0→441,334;
  0.3+ never fires. Signal real, not monetizable here (already absorbed
  by AR1+inv-skew chassis + matcher fill cap).

### Conclusion (session 9)

The +100k breakthrough is NOT in the deeper-statistics signal pile.
Every additional R3 signal scanned — single-strike, vertical, butterfly,
basis, time-of-day, lead-lag, deep-book, trade-size — is either too
small (sub-spread-cost), already absorbed by the existing chassis, or
unmonetizable due to the local matcher's L1 fill cap.

The VFE aggressor flow is the single new MONETIZED lever (+50 jmerle).
It's tiny in backtest but should convert better live where queue
dynamics and adverse-selection matter more (matcher cap shouldn't bind
there). Kept in the ship as live-defensive insurance.

The remaining +100k almost certainly requires either:
- Joint multi-product factor model (PCA on the full 12-product Δmid
  covariance, trade the leading factor)
- A completely different chassis (active-take with optimal-execution
  sizing rather than passive-make)
- Live-only signals invisible to jmerle (queue-position micro-arbs,
  post-fill momentum)

**Ship: `traders/round3/combined_ship_v15_hdrift_aggr.py`** (445,498 bt).
Reproduce: `python3 tools/jmerle_backtester.py traders/round3/combined_ship_v15_hdrift_aggr.py 3 --merge-pnl --no-out`

---

## Session 9 deep-research (separate run, parity hunt)

Goal: hunt fundamentally new alpha categories — drift on unprofiled R3
products, time-of-day patterns, basket signals.

### Per-product drift hunt (R3 days 0/1/2)

Linear regression of mid vs ts (β per kt timestamps):

| Product | day-0 β | day-1 β | day-2 β | Notes |
|---|---|---|---|---|
| HYDROGEL_PACK | +0.031 | +0.084 | +0.051 | Anchored; static-anchor IS the feature |
| VELVETFRUIT_EXTRACT | +0.014 | +0.008 | -0.007 | Already captured by drift carry |
| VEV_4000/4500 | same as VFE | … | … | Delta-1 ITM, drift captured by VFE-anchored fair |
| VEV_5400 | -0.0035 | -0.0027 | -0.0038 | Theta — already in BS_theo |
| VEV_5500 | +0.0006 | -0.0019 | -0.0026 | Theta — already in BS_theo |
| VEV_6000/6500 | 0 | 0 | 0 | Lottery, mid=0.5 all day |

**No unprofiled products with capturable drift.**  Theta on V5400/5500
is real but already in BS_theo (the ATM_RESIDUAL_ALPHA EMA tracks any
residual).

### Trade counterparty flow

`trades_round_3_day_*.csv` has buyer/seller fields **empty across all
9k+ trades**. R3 data is fully anonymized; no patsy-following alpha.

### Voucher pair-spread arbitrage

| Pair | mean | sd | range |
|---|---|---|---|
| **V4000 - V4500** | **500.00** | **0.41** | **[498.5, 501.5]** |
| V5000 - V5100 | 88.22 | 3.00 | [81, 96] |
| V5100 - V5200 | 71.26 | 3.62 | [58.5, 83.5] |
| V5200 - V5300 | 48.79 | 3.75 | [36, 62.5] |
| V5300 - V5400 | 30.81 | 3.51 | [20, 39.5] |
| V5400 - V5500 | 9.31 | 1.89 | [4, 15.5] |
| V4500 - VFE | -4499.99 | 0.76 | [-4506, -4494.5] |

V4000-V4500 is **near-perfectly stationary at 500.00** with sd=0.41
across 30k ticks. Mean-reversion is sharp and verified:

| dev = (V4000 - V4500) - 500 | n | next-tick ΔV4000 | ΔV4500 | ΔVFE | Δdev |
|---|---|---|---|---|---|
| -1.5 | 137 | +5.75 | +4.22 | +0.23 | +1.53 |
| -1.0 | 147 | +5.22 | +4.18 | -0.23 | +1.03 |
| -0.5 | 8233 | +0.26 | -0.24 | +0.20 | +0.50 |
|  0.0 | 12928 | -0.02 | -0.01 | -0.01 | -0.01 |
| +0.5 | 8283 | -0.25 | +0.24 | -0.19 | -0.49 |
| +1.0 | 126 | -4.91 | -3.85 | +0.13 | -1.06 |
| +1.5 | 139 | -5.26 | -3.75 | -0.07 | -1.50 |

VFE doesn't move — both legs revert toward parity. V4000 leads (5x V4500's
move).  Strong mean-reversion signal: 99% hit rate, magnitude +5/-5.

### v22_parity test variants — ALL REGRESS

Built `combined_ship_v22_parity.py` on the v22 chassis (447,042 bt).

**Variant 1 — Replace BS fair with parity (V4500_mid + 500):**
- WEIGHT=0.5 → 412,214 (-34,828)
- Kills the BS-VFE-vs-voucher lead-lag alpha that drives existing
  take-fills. Strikes had only +3,039/+0/+3,334/-34/+2,437/+0 vs baseline
  +2,802/-286/+8,228/+5,619/+14,482/+12,760.

**Variant 2 — Add fair-bias = -kappa * dev (keep BS):**
| KAPPA | total | Δ vs v22 |
|---|---|---|
| 0.0 | 447,042 | (baseline) |
| 0.1 | 445,604 | -1,438 |
| 0.3 | 445,604 | -1,438 |
| 0.5 | 424,489 | -22,553 |
| 1.0 | 416,646 | -30,396 |
| 2.0 | 415,407 | -31,635 |
| 3.0 | 415,224 | -31,818 |
| 5.0 | 428,042 | -19,000 |

ALL kappa > 0 regress. Reason: take-side cross costs (~10 ticks) > basis
revert magnitude (~5 ticks). Same pattern as the flow-burst /
skew-residual unmonetizable signals.

**Variant 3 — Post-only sizing bias (no fair shift):**
- BOOST 1.5/2.0/3.0 + SHRINK 1.0: 447,042 (no-op — boost cap-bound by L1)
- BOOST any + SHRINK 0.5: 447,024 (-18 noise)
- BOOST any + SHRINK 0.0: 444,649 (-2,393 — adverse cuts off real fills)

**Conclusion:** V4000-V4500=500 parity is real and tight, but synth-MM is
already saturating the alpha through BS theo with VFE underlying. The
basis revert magnitude (+5 ticks) is below the cross-the-book half-spread
(~10 ticks for V4000), so take-side capture is -EV. Post-side capture is
already at fill ceiling.  This is the same family of "real signal, no
monetization in this fill model" findings as the flow-burst and
skew-residual notes.

`combined_ship_v22_parity.py` removed; flagship remains v22-class
(v15_hdrift_aggr).

### Time-of-day pattern check

VFE per-50k-bin Δmid across days shows some highly aligned bins (e.g.,
ts 200-250 averages +20.2 across all 3 days; ts 350-400 averages -14;
ts 630-640 has t=-15.8 with sd=2.7). But:

- The drift-carry sleeve already maintains 200 long throughout the
  day, capturing average per-day drift.
- Adding a time-conditional target boost requires going > position
  limit (200) to add at troughs, which is impossible.
- Reducing target during dump-bins to "save" PnL would conflict with
  carry's slow-accumulation mechanic.
- 3-day OOS is too small to validate ts-conditional bot schedule —
  could be coincidence at sd=2.7.

Not coded as a strategy; the existing carry already extracts most of
the systematic VFE drift.

## Update 2026-04-25 (session 9, late): v27 Citadel mirror on V4000/V4500 (+65k bt)

**Headline**: combined_ship_v27.py = **576,528 bt** (3-day jmerle), alpha
floor **428,676** — beats v26 by **+65,440 bt** and **+73,778 alpha-floor**.
Live forecast at the v25-observed 1.057× ratio: **~609,150**, +83k over
v26's forecast 540k.

### Why it works — voucher delta-1 mirroring

V4000 and V4500 are deep ITM with delta = 1.000 at S=5250, T=5/365,
σ=0.23. Their basis to VFE has mean=0.01 ± 0.83 ticks across all 3
days — they track VFE 1:1. So the SAME `vfe_side` flag set by the
existing Citadel VFE MR translates directly to short/long positions
on V4000 and V4500. Total ±760 underlying-units (vs v26's ±200) → 3.8×
directional bet sharing one signal.

### Sweep results (cap=10, Z=2.0, EMA=5e-4 fixed)

V4000_TARGET / V4500_TARGET / total:
- 100/200 → 526,028
- 200/200 → 544,918
- 250/250 → 563,734
- 270/280 → 575,170
- **280/280 → 576,528** ← peak
- 285/285 → 573,667
- 290/290 → 537,236 (cliff)

Cap sweep at 280/280: 4→532k / 6→558k / 8→572k / **10→576,528** /
12→573k / 15→563k.

### Cliffs (do NOT cross)
- TARGET ≥ 290: synth-MM bid/ask blocked at LIMIT margin → -60k+
- TARGET ≤ 100: too small to capture move
- cap ≤ 6: slow rebalance misses Z-cross peaks
- cap ≥ 15: fast rebalance whipsaws on local Z noise

### Per-product attribution (3-day match-trades all)

| Product | v26 | v27 | Δ |
|---|---|---|---|
| HYDROGEL | 188,202 | 188,202 | 0 |
| VFE | 107,684 | 107,684 | 0 |
| V4000 | 39,579 | 38,070 | -1,509 |
| **V4500** | 18,093 | **70,976** | **+52,883** |

V4500 dominates the gain — historically 0 trades. With Citadel mirror
at ±280 against visible book volume (8.9/side, sp=16), the directional
bet accumulates +53k over 3 days.

### Citadel-HYDROGEL — REJECTED (don't redo)
Target ∈ {10, 20, 30, 50, 75, 100, 200} all regress -167k to -202k.
The static-anchor MM (145k of matching-engine wallpaper) needs near-zero
inventory to keep posting both sides; directional layer kills it.
Confirms `feedback_static_anchor_is_the_feature.md`.

### Bundle-cal note
Bundle 399113 (1k-tick window) too short for 500-tick warmup +
multi-Z-crossing development. v27 cal_minus_official = -108 vs v26 +499
→ INCONCLUSIVE on 1k bundle. Trust 3-day jmerle bt per
`feedback_citadel_overconverts_live.md`.

### Live forecast

| Strategy | bt | alpha-floor | Live (1.057× bt) |
|---|---|---|---|
| v25 (shipped) | 497,324 | 341,134 | 525,560 actual |
| v26 (forecast) | 511,088 | 354,898 | ~540,200 forecast |
| **v27 (this ship)** | **576,528** | **428,676** | **~609,150 forecast** |

Sample-path risk: 3-day VFE drift was -6/+20.5/+28. V4000/V4500 inherit
1:1. Conservative fallback: v25 (verified live 525,560) or v26.

Ship: `traders/round3/combined_ship_v27.py`.
Reproduce: `python3 tools/jmerle_backtester.py traders/round3/combined_ship_v27.py 3 --merge-pnl --no-out`

## Update 2026-04-25 (session 9 final): v28 = 427141 chassis + V4000/V4500 mirror (582,120 bt)

After realizing the repo had a v27 collision (memory pointed at 427141.py
as the actual shipped v27 = 516,679 bt), I stacked the V4000/V4500
Citadel mirror on the 427141 chassis. Result is the new high-water
mark.

| Ship | jmerle bt | alpha-floor | bundle-cal (427141) | live (1.057×) |
|---|---|---|---|---|
| v25 (verified) | 497,324 | 341,134 | 37,076 (-5,572) | **525,560 actual** |
| v26 (forecast) | 511,088 | 354,898 | 41,371 (-1,277) | ~540,200 |
| 427141.py / "v27" (forecast) | 516,679 | 370,768 | n/a | ~546,200 |
| repo v27 (mirror on v26) | 576,528 | 428,676 | 40,844 (-1,804) | ~609,150 |
| **v28 (mirror on 427141 chassis)** | **582,120** | **444,546** | **43,028 (+380)** | **~615,300** |

The bundle-cal +380 (cal_minus_official) for v28 is the BEST in the
ladder (v25 was -5,572) — bundle-cal accurately predicts a v25-class
submission's official PnL on this strategy. Combined with the +1.057×
live-conversion observation from v25, v28 forecast is **~615k live**.

### v28 stack vs v26

| Component | bt Δ | floor Δ |
|---|---|---|
| 427141 chassis (HYDROGEL retune) | +5,591 | +15,870 |
| V4000/V4500 Citadel mirror | +65,440 | +73,778 |
| **v28 stack** | **+71,032** | **+89,648** |

The two changes stack cleanly because:
- 427141 chassis is HYDROGEL-only (better take-edge / vk_dn / asym skew)
- Mirror is V4000/V4500-only (Citadel directional layer)
- Independent product books; no interaction.

### Why mirror works
V4000 and V4500 both have BS delta = 1.000 at S=5250, T=5/365, σ=0.23.
Their basis to VFE has mean ≈ 0, sd 0.83 across all 3 days — they
track VFE 1:1. Same `vfe_side` flag from VFE Citadel triggers parallel
take. Effective directional exposure: ±200 (VFE) + ±280 (V4000) +
±280 (V4500) = ±760 underlying-units → 3.8× the v26 directional bet.

V4500 dominates the gain (+53k) — historically had 0 trades, 18k MM
PnL. Citadel mirror at ±280 against visible book volume (8.9 / side,
sp=16) accumulates large directional PnL.

### Tuned config (locked)
```
ENABLE_CITADEL_V4000_MR = True
V4000_CITADEL_TARGET    = 280   # cliff at 290 (LIMIT margin)
V4000_MAX_TAKE_PER_TICK = 10    # plateau 8-12, cliff at ≤6 / ≥15
ENABLE_CITADEL_V4500_MR = True
V4500_CITADEL_TARGET    = 280
V4500_MAX_TAKE_PER_TICK = 10
```

### What I REJECTED in this session (don't redo)

- **Citadel-HYDROGEL** (long-EMA z-score directional layer on HYDROGEL):
  every TARGET ∈ {10, 20, 30, 50, 75, 100, 200} regressed -167k to -202k.
  The static-anchor MM (145k matching-engine wallpaper) and directional
  layer compete for inventory. Confirms `feedback_static_anchor_is_the_feature.md`.
- **Finer VFE_Z_ENTER / VFE_EMA_ALPHA sweeps**: peaks unchanged at
  Z=2.0, ALPHA=5e-4. Sharp cliffs both sides.
- **Citadel mirror at TARGET ≥ 290** (full LIMIT): synth-MM blocked → -45k+.

### Sample-path risk
3-day VFE drift was -6/+20.5/+28 (net +43). V4000/V4500 inherit 1:1.
The alpha-floor jump (+90k) is robust to drift patterns since it's
take-side directional alpha; the matching-engine half scales with
underlying volatility but not drift sign.

### Conservative fallbacks
- repo's combined_ship_v27.py (mirror-only on v26 chassis): 576,528 bt
- 427141.py (chassis-only, shipped): 516,679 bt
- v25: 497,324 bt, 525,560 verified live (empirical floor)

**Ship: `traders/round3/combined_ship_v29_mirror.py`** (582,866 bt — see addendum below).
Reproduce: `PYTHONHASHSEED=0 python3 tools/jmerle_backtester.py traders/round3/combined_ship_v29_mirror.py 3 --merge-pnl --no-out`

### Addendum (post v28-naming-collision)

Renamed v28 → `combined_ship_v29_mirror.py` to avoid colliding with the
parallel agent's `combined_ship_v28_warmup65.py` (519,679 bt).

A finer V4000/V4500 target sweep on the same chassis revealed:
- 282/282 → 582,866 (plateau peak; the locked config)
- 287/288 → 594,344 (cliff-edge spike, sample-path fragile)
- 289/+ → -33k cliff (synth-MM blocked at LIMIT margin)

Picked 282/282 (plateau, robust to ±2 deviation) over the cliff-edge
spike since live regime may shift the cliff position.

### Final ladder (PYTHONHASHSEED=0, --merge-pnl)

| Ship | jmerle bt | alpha-floor | bundle-cal (427141) | live forecast |
|---|---|---|---|---|
| v25 (verified) | 497,324 | 341,134 | 37,076 | 525,560 actual |
| v26 | 511,088 | 354,898 | 41,371 | ~540k |
| 427141 (v27 shipped) | 516,679 | 370,768 | n/a (source) | live TBD |
| v28_warmup65 (parallel) | 519,679 | 373,768 | **45,275 (+2,626)** | bundle-cal best |
| v29_v4mirror (parallel) | 579,596 | 442,070 | 43,016 (+367) | jmerle peer |
| **v29_mirror.py (my ship)** | **582,866** | **445,295** | **43,014 (+365)** | **~616k @ 1.057×** |

Bundle-cal vs jmerle disagree on which is best for live:
- jmerle ratio (v25: 525,560/497,324 = **1.057×**) → v29_mirror best
- Bundle-cal × 10 × ~1.42 → v28_warmup65 best
The two ships are orthogonal in concept (warmup is *when* Citadel
fires; mirror is *which products* take the directional bet). I tested
combining them in v30: regressed jmerle to 564k AND bundle-cal to
35,870 (-6,778). They don't stack.

Final pick: v29_mirror.py — trust the v25-verified jmerle conversion
ratio. If a future submission shows v28_warmup65 over-converts beyond
1.057×, switch.

### Mirror config (locked in v29_mirror.py)
```
ENABLE_CITADEL_V4000_MR = True
V4000_CITADEL_TARGET    = 282   # plateau peak; cliff at 289
V4000_MAX_TAKE_PER_TICK = 10    # plateau 8-12
ENABLE_CITADEL_V4500_MR = True
V4500_CITADEL_TARGET    = 282
V4500_MAX_TAKE_PER_TICK = 10
```

### Memory updates
- New: `reference_round3_v28_v4000_v4500_mirror.md` (now points to
  `combined_ship_v29_mirror.py` — the v28 file was renamed).
- v28 reference still valid for the discovery; ship file is v29_mirror.
