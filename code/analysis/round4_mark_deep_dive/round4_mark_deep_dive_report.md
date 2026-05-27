# Round 4 Mark Counterparty Deep Dive

Data: `data/round4`. Raw trades: `4,281`. Trader-side events: `8,562`.
All per-unit edge and forward-PnL metrics are quantity-weighted. Aggressor share is event-weighted unless explicitly labeled as quantity-weighted.

## Executive Read

- `fwd_2000 = edge_at_fill + mid_move_2000`. This decomposition matters: some Marks look profitable because they captured spread passively, not because they predict the next move.
- `Mark 67` is the cleanest directional flow: almost pure `VELVETFRUIT_EXTRACT` buyer, pays spread, but the mid still moves about `+1.79` per unit in his favor over 2,000 timestamp units.
- `Mark 49` is the cleanest fade: mostly passive `VELVETFRUIT_EXTRACT` seller with positive fill edge, but the subsequent mid move is about `-1.85` from his point of view. After his sells, buy/avoid shorts.
- `Mark 14` and `Mark 01` are passive makers. Their positive `fwd_2000` is mainly fill edge, so they are execution-quality warnings more than chaseable directional signals.
- `Mark 38` and `Mark 55` are liquidity to provide to. They cross spreads aggressively and lose on fill-to-future PnL; take the other side instead of following them.

## Headline Mark Table

| Mark | events | qty | aggr | edge | mid_move_2000 | fwd_2000 | total_fwd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Mark 14 | 2172 | 8718 | 0.0% | +5.72 | -0.09 | +5.63 | +49058 |
| Mark 01 | 1843 | 7428 | 0.0% | +1.34 | +0.01 | +1.35 | +10044 |
| Mark 67 | 165 | 1510 | 99.4% | -0.77 | +1.79 | +1.03 | +1551 |
| Mark 22 | 1584 | 5889 | 90.7% | -0.33 | -0.18 | -0.51 | -3012 |
| Mark 49 | 122 | 1186 | 1.6% | +0.73 | -1.85 | -1.12 | -1328 |
| Mark 55 | 1198 | 6551 | 100.0% | -2.48 | +0.29 | -2.19 | -14330 |
| Mark 38 | 1478 | 5000 | 100.0% | -8.29 | -0.12 | -8.41 | -41983 |

## Directional Versus Execution Edge

Positive `edge_at_fill` means the Mark bought below mid or sold above mid. Positive `mid_move_2000` means the post-fill mid moved in the Mark's direction. Only the latter is directly followable after observing the trade.

| Mark | events | qty | mid_move_2000 | edge_at_fill | fwd_2000 | naive_t |
| --- | --- | --- | --- | --- | --- | --- |
| Mark 49 | 122 | 1186 | -1.85 | +0.73 | -1.12 | -3.1 |
| Mark 67 | 165 | 1510 | +1.79 | -0.77 | +1.03 | +3.2 |
| Mark 55 | 1198 | 6551 | +0.29 | -2.48 | -2.19 | -17.6 |
| Mark 22 | 1584 | 5889 | -0.18 | -0.33 | -0.51 | -9.1 |
| Mark 38 | 1478 | 5000 | -0.12 | -8.29 | -8.41 | -35.8 |
| Mark 14 | 2172 | 8718 | -0.09 | +5.72 | +5.63 | +32.2 |
| Mark 01 | 1843 | 7428 | +0.01 | +1.34 | +1.35 | +19.0 |

## Mark-By-Mark Dossiers

### `Mark 14` — passive informed maker / execution edge collector

- Footprint: `2,172` events and `8,718` units, mostly `HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, and `VEV_4000`; `0%` aggressor share.
- Economics: `edge_at_fill=+5.72`, `mid_move_2000=-0.09`, `fwd_2000=+5.63`. The profit is almost entirely spread/fill edge, not post-trade drift.
- Product read: strongest on wide-spread `HYDROGEL_PACK` and `VEV_4000`; still positive but smaller on `VELVETFRUIT_EXTRACT`.
- Action: do not cross into this Mark. If our live fills often print against `Mark 14`, our execution layer is likely donating edge. It is not a clean after-the-fact chase signal because the edge has already been captured at their fill price.

### `Mark 01` — passive maker, mild edge, voucher pair specialist

- Footprint: `1,843` events and `7,428` units; `0%` aggressor share. Most volume is `VELVETFRUIT_EXTRACT` plus recurring `Mark 01 -> Mark 22` voucher prints.
- Economics: `edge_at_fill=+1.34`, `mid_move_2000=+0.01`, `fwd_2000=+1.35`.
- Product read: `VELVETFRUIT_EXTRACT` edge is stronger than the voucher edge, but the voucher flow is mostly mechanical spread capture in low-value strikes.
- Action: respect as a maker and avoid taking bad prices into them. Do not spend position budget following the voucher prints unless another model already wants that exposure.

### `Mark 67` — true VFE informed taker

- Footprint: `165` events and `1,510` units, all `VELVETFRUIT_EXTRACT` buys; `99.4%` event aggressor share.
- Economics: pays spread (`edge_at_fill=-0.77`), but future mid move is strong (`mid_move_2000=+1.79`), leaving `fwd_2000=+1.03`.
- Stability: positive on every day; strongest late-session in this sample. The effect is real but thin relative to spread, so late chasing can erase it.
- Action: use as long bias, short veto, and voucher-delta fair shift. Prefer passive or at-touch participation; blind extra market-taking is only justified when the rest of the VFE stack agrees.

### `Mark 49` — passive but mistimed VFE trader / fade candidate

- Footprint: `122` events and `1,186` units, almost entirely `VELVETFRUIT_EXTRACT` sells; only `1.6%` event aggressor share.
- Economics: earns fill edge (`edge_at_fill=+0.73`), then loses it and more (`mid_move_2000=-1.85`, `fwd_2000=-1.12`).
- Stability: negative `fwd_2000` on all three days and across short/medium horizons. Large `11+` unit prints remain negative.
- Action: fade, especially after sells. In practice this means allow/add VFE long skew and suppress shorts after `Mark 49` seller prints.

### `Mark 55` — pure VFE noise taker

- Footprint: `1,198` events and `6,551` units, all `VELVETFRUIT_EXTRACT`; exactly `100%` aggressor share with balanced buy/sell count.
- Economics: `edge_at_fill=-2.48`, `mid_move_2000=+0.29`, `fwd_2000=-2.19`. Direction is mildly favorable but far too small to pay the spread.
- Action: provide liquidity to `Mark 55`; do not follow. Their trades are useful as fill opportunities, not as price-discovery signals.

### `Mark 38` — strongest spread-paying noise flow

- Footprint: `1,478` events and `5,000` units, concentrated in `HYDROGEL_PACK` and `VEV_4000`; exactly `100%` aggressor share.
- Economics: worst fill-to-future result in the tape: `edge_at_fill=-8.29`, `mid_move_2000=-0.12`, `fwd_2000=-8.41`.
- Pair read: `Mark 14` is usually the other side and captures the transfer. This is a liquidity-provision edge, not a directional forecast.
- Action: quote confidently into `Mark 38` flow on `HYDROGEL_PACK`/`VEV_4000` when inventory allows; avoid joining their side.

### `Mark 22` — mostly noise taker / mechanical seller

- Footprint: `1,584` events and `5,889` units; `90.7%` event aggressor share and heavily seller-skewed.
- Economics: `edge_at_fill=-0.33`, `mid_move_2000=-0.18`, `fwd_2000=-0.51`.
- Product read: many voucher sells are paired mechanically with `Mark 01`; `VELVETFRUIT_EXTRACT` behavior is weakly negative from Mark 22's perspective but not as clean as `Mark 49`.
- Action: generally provide, but avoid overfitting. Use as a secondary liquidity/noise tag rather than a primary directional signal.

## Product-Level Mark Behavior

| product | mark | events | qty | aggr | edge | mid_move | fwd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HYDROGEL_PACK | Mark 14 | 1003 | 4022 | 0.0% | +7.96 | +0.25 | +8.20 |
| HYDROGEL_PACK | Mark 22 | 19 | 74 | 0.0% | +3.85 | -3.49 | +0.36 |
| HYDROGEL_PACK | Mark 38 | 1022 | 4096 | 100.0% | -7.88 | -0.18 | -8.06 |
| VELVETFRUIT_EXTRACT | Mark 01 | 504 | 2792 | 0.0% | +2.63 | -0.01 | +2.62 |
| VELVETFRUIT_EXTRACT | Mark 14 | 647 | 3524 | 0.0% | +2.44 | -0.44 | +1.99 |
| VELVETFRUIT_EXTRACT | Mark 67 | 165 | 1510 | 99.4% | -0.77 | +1.79 | +1.03 |
| VELVETFRUIT_EXTRACT | Mark 22 | 126 | 843 | 13.5% | +0.69 | -0.96 | -0.28 |
| VELVETFRUIT_EXTRACT | Mark 49 | 122 | 1186 | 1.6% | +0.73 | -1.85 | -1.12 |
| VELVETFRUIT_EXTRACT | Mark 55 | 1198 | 6551 | 100.0% | -2.48 | +0.29 | -2.19 |
| VEV_4000 | Mark 14 | 439 | 870 | 0.0% | +10.41 | -0.18 | +10.23 |
| VEV_4000 | Mark 38 | 442 | 876 | 100.0% | -10.38 | +0.18 | -10.19 |
| VEV_5200 | Mark 01 | 11 | 34 | 0.0% | +1.00 | +1.21 | +2.21 |
| VEV_5200 | Mark 14 | 33 | 122 | 0.0% | +1.00 | +0.05 | +1.05 |
| VEV_5200 | Mark 22 | 47 | 162 | 93.6% | -0.94 | -0.21 | -1.14 |
| VEV_5300 | Mark 01 | 132 | 439 | 0.0% | +0.91 | -0.08 | +0.83 |
| VEV_5300 | Mark 14 | 30 | 105 | 0.0% | +0.76 | -0.18 | +0.58 |
| VEV_5300 | Mark 22 | 164 | 548 | 98.2% | -0.87 | +0.10 | -0.77 |
| VEV_5400 | Mark 01 | 263 | 911 | 0.0% | +0.60 | +0.07 | +0.67 |
| VEV_5400 | Mark 14 | 13 | 48 | 0.0% | +0.45 | -0.33 | +0.11 |
| VEV_5400 | Mark 22 | 276 | 959 | 99.6% | -0.59 | -0.05 | -0.64 |
| VEV_5500 | Mark 01 | 299 | 1042 | 0.0% | +0.53 | +0.03 | +0.55 |
| VEV_5500 | Mark 22 | 306 | 1069 | 100.0% | -0.52 | -0.01 | -0.54 |
| VEV_6000 | Mark 01 | 317 | 1105 | 0.0% | +0.50 | +0.00 | +0.50 |
| VEV_6000 | Mark 22 | 317 | 1105 | 100.0% | -0.50 | +0.00 | -0.50 |
| VEV_6500 | Mark 01 | 317 | 1105 | 0.0% | +0.50 | +0.00 | +0.50 |
| VEV_6500 | Mark 22 | 317 | 1105 | 100.0% | -0.50 | +0.00 | -0.50 |

## Buyer/Seller Pair Transfers

Buyer perspective. Seller's `fwd_2000` transfer is the negative of buyer total, up to end-of-day missing horizons.

| product | buyer->seller | events | qty | buyer_aggr | buyer_edge | buyer_mid_move | buyer_fwd | buyer_total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HYDROGEL_PACK | Mark 14 -> Mark 38 | 496 | 1989 | 0.0% | +7.98 | +0.01 | +7.99 | +15900 |
| VEV_4000 | Mark 14 -> Mark 38 | 232 | 458 | 0.0% | +10.47 | -0.21 | +10.26 | +4700 |
| VELVETFRUIT_EXTRACT | Mark 14 -> Mark 55 | 316 | 1761 | 0.0% | +2.42 | -0.27 | +2.15 | +3794 |
| VELVETFRUIT_EXTRACT | Mark 01 -> Mark 55 | 260 | 1417 | 0.0% | +2.59 | +0.06 | +2.65 | +3752 |
| VELVETFRUIT_EXTRACT | Mark 67 -> Mark 49 | 89 | 963 | 100.0% | -0.64 | +1.64 | +1.01 | +970 |
| VEV_5400 | Mark 01 -> Mark 22 | 263 | 911 | 0.0% | +0.60 | +0.07 | +0.67 | +610 |
| VEV_5500 | Mark 01 -> Mark 22 | 299 | 1042 | 0.0% | +0.53 | +0.03 | +0.55 | +577 |
| VELVETFRUIT_EXTRACT | Mark 67 -> Mark 22 | 75 | 546 | 100.0% | -1.00 | +2.05 | +1.05 | +573 |
| VEV_6000 | Mark 01 -> Mark 22 | 317 | 1105 | 0.0% | +0.50 | +0.00 | +0.50 | +552 |
| VEV_6500 | Mark 01 -> Mark 22 | 317 | 1105 | 0.0% | +0.50 | +0.00 | +0.50 | +552 |
| VEV_5300 | Mark 01 -> Mark 22 | 132 | 439 | 0.0% | +0.91 | -0.08 | +0.83 | +364 |
| VELVETFRUIT_EXTRACT | Mark 22 -> Mark 55 | 18 | 92 | 0.0% | +1.58 | +0.26 | +1.84 | +170 |
| VELVETFRUIT_EXTRACT | Mark 55 -> Mark 49 | 9 | 54 | 100.0% | -0.64 | +3.09 | +2.45 | +132 |
| VEV_5200 | Mark 14 -> Mark 22 | 33 | 122 | 0.0% | +1.00 | +0.05 | +1.05 | +128 |
| VEV_5200 | Mark 01 -> Mark 22 | 11 | 34 | 0.0% | +1.00 | +1.21 | +2.21 | +75 |
| VEV_5300 | Mark 14 -> Mark 22 | 30 | 105 | 0.0% | +0.76 | -0.18 | +0.58 | +60 |
| VELVETFRUIT_EXTRACT | Mark 55 -> Mark 22 | 14 | 62 | 100.0% | -1.09 | +1.88 | +0.79 | +49 |
| VEV_5400 | Mark 14 -> Mark 22 | 13 | 48 | 0.0% | +0.45 | -0.33 | +0.11 | +6 |
| HYDROGEL_PACK | Mark 22 -> Mark 38 | 11 | 42 | 0.0% | +4.07 | -4.48 | -0.40 | -17 |
| HYDROGEL_PACK | Mark 38 -> Mark 22 | 8 | 32 | 100.0% | -3.56 | +2.19 | -1.38 | -44 |
| VELVETFRUIT_EXTRACT | Mark 49 -> Mark 22 | 12 | 89 | 8.3% | +1.50 | -2.35 | -0.85 | -76 |
| VELVETFRUIT_EXTRACT | Mark 55 -> Mark 14 | 331 | 1763 | 100.0% | -2.46 | +0.62 | -1.83 | -3234 |
| VELVETFRUIT_EXTRACT | Mark 55 -> Mark 01 | 244 | 1375 | 100.0% | -2.67 | +0.08 | -2.59 | -3562 |
| VEV_4000 | Mark 38 -> Mark 14 | 207 | 412 | 100.0% | -10.35 | +0.14 | -10.20 | -4142 |
| HYDROGEL_PACK | Mark 38 -> Mark 14 | 507 | 2033 | 100.0% | -7.93 | -0.48 | -8.41 | -17096 |

## Horizon Curve: Fill-To-Future PnL

Columns are timestamp units after the trade. Values include fill edge, so passive makers stay positive even when future mid movement is flat.

| mark | 100 | 200 | 500 | 1000 | 2000 | 5000 | 10000 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Mark 14 | +5.75 | +5.76 | +5.71 | +5.63 | +5.63 | +5.71 | +5.39 |
| Mark 01 | +1.42 | +1.40 | +1.39 | +1.45 | +1.35 | +1.39 | +1.21 |
| Mark 67 | +1.24 | +1.21 | +1.19 | +1.44 | +1.03 | +1.16 | +0.84 |
| Mark 22 | -0.54 | -0.53 | -0.52 | -0.51 | -0.51 | -0.63 | -0.39 |
| Mark 49 | -1.18 | -1.17 | -1.14 | -1.43 | -1.12 | -1.00 | -1.27 |
| Mark 55 | -2.45 | -2.44 | -2.41 | -2.42 | -2.19 | -2.02 | -1.60 |
| Mark 38 | -8.37 | -8.39 | -8.34 | -8.28 | -8.41 | -8.73 | -8.59 |

## Day Stability

| mark | day | events | qty | edge | mid_move | fwd |
| --- | --- | --- | --- | --- | --- | --- |
| Mark 01 | 1 | 550 | 2261 | +1.36 | +0.25 | +1.61 |
| Mark 01 | 2 | 573 | 2414 | +1.45 | -0.21 | +1.23 |
| Mark 01 | 3 | 720 | 2753 | +1.24 | +0.00 | +1.24 |
| Mark 14 | 1 | 764 | 3012 | +5.97 | +0.13 | +6.10 |
| Mark 14 | 2 | 668 | 2736 | +5.57 | -0.06 | +5.50 |
| Mark 14 | 3 | 740 | 2970 | +5.61 | -0.34 | +5.27 |
| Mark 22 | 1 | 474 | 1806 | -0.28 | -0.25 | -0.53 |
| Mark 22 | 2 | 471 | 1804 | -0.28 | -0.28 | -0.56 |
| Mark 22 | 3 | 639 | 2279 | -0.40 | -0.06 | -0.45 |
| Mark 38 | 1 | 544 | 1823 | -8.35 | -0.59 | -8.93 |
| Mark 38 | 2 | 439 | 1500 | -8.29 | -0.06 | -8.34 |
| Mark 38 | 3 | 495 | 1677 | -8.22 | +0.32 | -7.90 |
| Mark 49 | 1 | 40 | 380 | +0.70 | -1.96 | -1.26 |
| Mark 49 | 2 | 43 | 440 | +0.71 | -1.49 | -0.79 |
| Mark 49 | 3 | 39 | 366 | +0.78 | -2.15 | -1.38 |
| Mark 55 | 1 | 384 | 2109 | -2.46 | +0.11 | -2.35 |
| Mark 55 | 2 | 411 | 2289 | -2.48 | +0.46 | -2.02 |
| Mark 55 | 3 | 403 | 2153 | -2.49 | +0.29 | -2.21 |
| Mark 67 | 1 | 58 | 519 | -0.79 | +2.05 | +1.26 |
| Mark 67 | 2 | 61 | 567 | -0.77 | +1.55 | +0.79 |
| Mark 67 | 3 | 46 | 424 | -0.74 | +1.80 | +1.06 |

## Timing And Size Diagnostics

- Session-bin summary: `analysis/round4_mark_deep_dive/mark_time_bin_summary.csv`
- Quantity-bin summary: `analysis/round4_mark_deep_dive/mark_size_bin_summary.csv`
- The generated CSVs are the source of truth for slices too wide to keep readable in this markdown file.

## Trading Implications

- Use `Mark 67` as a VFE directional follow/short-veto signal, but do not overpay. His 2,000-unit markout from mid is only about two ticks, so an extra spread crossing can erase the edge.
- Use `Mark 49` sells as a VFE fade/long-permission signal. The signal is stronger as a quote-skew or short-veto than as a blind market order.
- Use `Mark 38` and `Mark 55` for liquidity provision. Their losses are mostly spread paid, so the practical edge is making markets against them, not forecasting a large drift after they trade.
- Treat `Mark 14` and `Mark 01` as makers to respect. If our strategy is repeatedly trading into them, the strategy is probably donating execution edge.
- Ignore most voucher Mark IDs as standalone alpha. The recurring `Mark 01`/`Mark 22` voucher flow is mechanical, often in near-zero vouchers, and has weak forward information.

## Output Files

- `analysis/round4_mark_deep_dive/events.csv`
- `analysis/round4_mark_deep_dive/mark_summary.csv`
- `analysis/round4_mark_deep_dive/mark_product_summary.csv`
- `analysis/round4_mark_deep_dive/mark_day_summary.csv`
- `analysis/round4_mark_deep_dive/mark_side_summary.csv`
- `analysis/round4_mark_deep_dive/mark_horizon_summary.csv`
- `analysis/round4_mark_deep_dive/pair_summary.csv`
- `analysis/round4_mark_deep_dive/mark_time_bin_summary.csv`
- `analysis/round4_mark_deep_dive/mark_size_bin_summary.csv`
