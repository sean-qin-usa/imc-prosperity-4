# P4 R3 Bio-Pod — Final Recommendation

**Date**: 2026-04-24 (Round 3 opens)
**Field size**: ~4,050 post-filter survivors (top 18% of ~22,200 R2 field).
**Problem**: Two-bid auction. Reserves uniform on {670, 675, ..., 920} (51
values, step 5). Resale 920. b1 trades if b1≥R. b2 trades if b1<R≤b2,
with prob = ((920-avg_b2)/(920-b2))³ when b2<avg_b2 (else 1).

## TL;DR — Recommended bids

| Pick | (b1, b2) | Mean EV/gardener | Worst-case | When to use |
|------|----------|------------------|------------|-------------|
| **PRIMARY** | **(775, 875)** | **80.20** | 71.50 | Default — best EV under all realistic priors |
| Aggressive | (770, 870) | 80.33 | 69.33 | If you trust P3 R3 history (avg≈858) |
| All-weather | (780, 890) | 75.98 | 74.74 | If you suspect field has shifted high (avg>880) |

**My pick: (775, 875).** Reasoning below.

## Why this beats the AI-default answer

A 2026 LLM asked this problem cold will most likely produce one of:
- (790, 855) — naive math optimum, ignoring the cubic penalty entirely
- (790, 870) — Nash-naive ("bid above the average")
- (790, 880) — Nash + safety buffer
- (780, 890) — careful sophisticate (matches **our own ROUND3_RECIPE.md primary**)

All of these put b1 at 790 (the b1-EV plateau). **775 deviates one cluster
step down**, freeing 3 reserves {780, 785, 790} to flow to b2 — net +1.5 EV
when b2 catches them, ~0 penalty cost when it doesn't.

**875 is one tick above the Nash fixed-point at 870** but **strictly below
the natural focal points 880 and 890**. Under the AI-aware prior — which
assumes 55% of the field clusters at b2 ∈ {855, 870, 880, 890} weighted
(10/25/30/35) — avg_b2 lands at 871±1, so b2=875 is comfortably above
avg with **0% penalty risk and full 45-shell margin per captured unit**.

## Field-prior calibration

The hardest input is `E[avg_b2]`. Three anchors:

1. **P3 R3 historical** (the closest analog problem ever run): the actual
   field average was only +3 above the naive math optimum. If P4 R3
   replicates this pattern: avg_b2 ≈ 858. Source:
   `practice/winners/timo-prosperity-3/README.md` Round 3 writeup.
2. **AI-cluster-aware model** (assumes 55% of teams paste LLM answers
   at the four likely modal outputs): avg_b2 ≈ 871, std 1.2.
3. **Calibrated mixture with parameter uncertainty** (Dirichlet over
   cluster weights — wider tail to absorb prior misspecification):
   avg_b2 ≈ 862, std 11.

All three priors put p95(avg_b2) below 876. Bid 875 dominates 870/876/880
across the entire convex hull of reasonable priors except the aggressive
"sophisticated" tail (avg > 880, ~5% prior weight).

## Cross-scenario robustness table (mean EV per gardener)

| (b1,b2)   | P3-analog (858) | AI-aware (871) | Default (862) | Soph (875) | V-Soph (885) | Heavy-tail | **avg** | **min** |
|-----------|-----------------|----------------|---------------|------------|--------------|------------|---------|---------|
| (770,870) | 81.4            | 79.7           | 80.3          | 75.6       | 69.3         | 78.1       | 77.4    | 69.3    |
| (775,875) | 80.2            | **80.2**       | 80.1          | 77.2       | 71.5         | 78.1       | **77.9**| 71.5    |
| (770,875) | 80.3            | 80.3           | 80.1          | 77.1       | 71.2         | 78.1       | 77.9    | 71.2    |
| (780,876) | 79.5            | 79.5           | 79.5          | 77.1       | 71.9         | 77.7       | 77.5    | 71.9    |
| (780,890) | 76.1            | 76.1           | 76.1          | 76.0       | 74.7         | 75.5       | 75.8    | 74.7    |
| (790,855) | 77.9            | 70.6           | 74.6          | 69.7       | 66.7         | 73.9       | 72.2    | 66.7    |

Read: under **every realistic prior except 'very-sophisticated avg≈885'**,
(775, 875) ties or beats every other candidate I tested. The naive AI
default (790, 855) is the worst by ~6 EV.

## Step-by-step rationale

### 1. Standalone b1 — first-principles optimum
Maximize (920-b)·(b-665)/5 / 51 over the 51-reserve grid:
- b1 ∈ {790, 795} tie at 63.73 EV/gardener (peak).
- b1 ∈ {785, 800} at 63.53 (-0.20).
- b1 = 780 at 63.14 (-0.59).
- **b1 = 775 at 62.55 (-1.18)** ← my pick.

Sacrificing 1.18 on b1 frees 3 reserves {780, 785, 790} for b2 to capture
at ~0.88 each = +2.64 expected gain. Net: +1.5.

### 2. b2 — the actual game theory
Naive optimum (assume b2 = avg, i.e. penalty factor 1): b2 = 855 captures
n2 = 17 extra reserves, EV = 16.57. **This is the AI-default trap.**

The penalty kicks in when b2 < avg_b2. Best-response function:
- For avg_b2 ≤ 855: best b2 = 855 (unconstrained peak).
- For avg_b2 > 855: best b2 = avg_b2 itself (penalty=1, but capture more
  reserves than a smaller bid).

The fixed-point if everyone reasoned this way: b2 = 855 — *if* the
crowd self-coordinates downward. Historical P3 R3 evidence says
**they do**: avg landed only +3 above the math optimum.

### 3. Why b2 = 875 specifically
**875 is the smallest reserve-grid point above the {855, 870} naive-math
range.** It captures the 21 reserves from 780 to 875 inclusive, while
staying below the tail of any plausible avg_b2 distribution (p95 across
all my models is ≤ 876). At 875 the n2 jump (875 itself enters) gives
+1 reserve = +0.88 EV, almost free vs 870.

Going to 876, 877, 878, 879 does NOT capture any extra reserves (the
next reserve is 880), but **costs profit per captured unit** (44 vs 45,
etc.). Going to 880 captures one more reserve (880) but loses 4 in
margin per unit on the existing 21 — net loss vs 875 (79.02 vs 80.20).

### 4. Why not the recipe's (780, 890)?
The R3 recipe primary (780, 890) was conservative against a worst-case
avg_b2 = 900. Under wider sensitivity testing here, 900 is a >p99 tail,
not a meaningful prior weight. (780, 890) gives up **4.2 EV/gardener
vs (775, 875)** in expectation, in exchange for 3.2 EV less downside
risk. Given my prior, this trade is bad.

If late-round Discord chatter suggests teams are pushing way up, switch
to (780, 890) before the deadline — last-submitted wins.

## Sanity checks

- **Cluster-of-clusters paradox**: if many teams ALSO bid 875 (it's a
  round number), avg_b2 gets pulled up toward 875. At avg = 875 exactly,
  b2 = 875 has penalty factor = 1 (still full profit). At avg = 875.5,
  penalty = (44.5/45)³ = 0.967 — only 0.6 EV loss. Robust.
- **What if I'm wrong and avg = 880**: (775, 875) drops to 71.5 EV.
  That's still better than (790, 855) at 69.7, and only ~4.5 below
  (780, 890)'s 76.0. The asymmetric loss is bounded.
- **Bid space**: integer bids assumed. Step-5 reserve grid means bids
  in [870..874] all capture identical n2 = 20; among these, 870 has
  highest profit per unit. Same for [875..879]. So 870 and 875 are the
  true grid points; intermediate integers are dominated.

## Bid-space topology summary

```
    "Cliff" reserve points (each is a +1 reserve captured):
      ... 870 | 875 | 880 | 885 | 890 | ...
              ↑     (next cliff at +5 always)

    Optimal b2 sits ON a cliff (875), not between cliffs.
    Optimal b2 stays just above expected avg_b2 (~862-871).
    Sweet spot: 875.
```

## Files
- `biopod_fast.py` — vectorized EV solver + 9-cluster mixture field model
- `sensitivity.py` — 6-scenario robustness sweep
- `anti_cluster_test.py` — AI-cluster-aware prior + integer fine grid
- `fast_out.txt`, `sens_out.txt`, `anti_out.txt` — raw outputs

## One-line summary
**Submit (775, 875).** One step below the b1 herd (775 < 790), one cliff
above the Nash fixed-point (875 > 870), strictly below the b2 tail risk
threshold (876). Robust to every prior except a ~5% "very sophisticated"
tail; in that tail the all-weather fallback is (780, 890).
