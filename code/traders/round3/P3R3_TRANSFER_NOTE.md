# Round 3 — Transfer from P3 R3

User flagged 2026-04-24: Round 3 structure mirrors **Prosperity 3
Round 3** (Volcanic Rock + vouchers). Our P3 port
`traders/p3_fresh_claude/p3_combined_v1.py` handles it. Use it as a
structural starting point, not a verbatim copy, because of four
differences.

## Same structure
- One delta-1 underlying + a chain of European call vouchers
- Vouchers have 1:1 strike mapping to underlying price ladder
- Position limits: underlying higher than each voucher (P3: 400 vs 200;
  P4: 200 vs 300 — note the ratio is inverted here, see below)
- TTE drops one "day" per round; liquidation at hidden fair at end

## Differences to watch

| | **P3 R3** | **P4 R3** |
|---|---|---|
| Underlying | VOLCANIC_ROCK (mid ≈ 10000) | VELVETFRUIT_EXTRACT (mid ≈ 5248) |
| Underlying limit | 400 | **200** |
| Number of voucher strikes | 5 | **10** |
| Voucher limit per strike | 200 | **300** |
| Voucher strikes | {9500,9750,10000,10250,10500} | {4000,4500,5000,5100,5200,5300,5400,5500,6000,6500} |
| IV smile | Fitted quadratic `A m² + B m + C` | **Flat ≈ 0.23** (simpler) |
| ITM strikes (delta≈1) used for MR | {9500,9750,10000} | candidates {5000,5100,5200} (≈ ATM + slight ITM) |
| Deep-ITM delta-1 clones | n/a (deepest moneyness 0.95) | **VEV_4000 + VEV_4500** (moneyness 0.76/0.86, basis std < 1) |
| Side-product | Extra products in P3 only | HYDROGEL_PACK (extra delta-1 MM product, no options exposure) |

## What to port directly from p3_combined_v1

- BS call pricer (`_opt_bs`) — unchanged; discount rate 0 assumed.
- Per-tick TTE: `tte = (tte_days_at_day_start - ts/1e6) / 365`. Historical
  data days 0/1/2 → TTE 8/7/6 days. Live Round 3 starts at TTE 5.
- `_top` / `_walls` book helpers — reusable.
- IV-scalping overlay for OTM (5300, 5400, 5500) — but **first disable**
  since flat-smile removes most residual alpha; re-enable only if we
  can show per-strike residuals mean-revert.
- MR on ITM strikes (`combined = ema_o_dev + iv_dev` signal).

## What's NEW vs P3 (novel alpha hooks here)

1. **Basis arb S ↔ (VEV_4000 + 4000) ↔ (VEV_4500 + 4500)**. Three
   parallel measurements of the same underlying. When their implied S
   diverges by ≥ 3 ticks, arb the rich side. Safer than any voucher
   residual trade. P3 didn't have a viable version of this (deepest
   moneyness 0.95 → too much time value).
2. **Synthetic-underlying MM on VEV_4000 and VEV_4500**. Spread on
   VEV_4000 = 21 (wider than underlying), spread on VEV_4500 = 16. MM
   there is effectively MM'ing the underlying with a 300 position
   limit. Combined delta-1 capacity becomes 200 + 300 + 300 = 800
   (4× the native underlying limit).
3. **HYDROGEL_PACK**: completely separate ACO-class wide-spread MM
   product, not related to the option chain. Stratify as its own
   sleeve.

## Parameter translation

Where P3 `p3_combined_v1` hard-codes things like `SMILE_A, SMILE_B,
SMILE_C` and MR thresholds that were tuned on P3 data, do NOT reuse the
numeric values — fit fresh from round-3 CSVs. The structural code is
reusable; the fitted constants are not.

For MR thresholds specifically: P3 used `UNDER_MR_THR=15` on an
underlying with std ~20. VELVETFRUIT_EXTRACT has σ(Δmid)=1.13 and
day-level std 15. Start threshold exploration in the range 5-15 and
grid-search.
