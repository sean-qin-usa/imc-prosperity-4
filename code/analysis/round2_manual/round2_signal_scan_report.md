# Signal Scan Report — `data/round2`

This report uses direction-style targets rather than raw unbounded `Δmid`.
That matches the queue-imbalance literature more closely and avoids large-jump outliers swamping otherwise real signals.

## `ASH_COATED_OSMIUM`

- Target: `next_nonzero_dir`
- Reason: stationary product -> next non-zero mid move direction
- Day trend summary: median r²=`0.006`, slope range=`-0.0007` .. `+0.0002`

### Feature Table

| Feature | AUC | Corr | Top bucket aligned-rate | Bottom bucket aligned-rate | n |
| --- | ---: | ---: | ---: | ---: | ---: |
| `imb1` | `0.763` | `+0.471` | `0.599` | `0.600` | `29853` |
| `micro_gap` | `0.726` | `+0.441` | `0.581` | `0.581` | `27617` |
| `gap_asym` | `0.667` | `+0.321` | `0.635` | `0.630` | `12753` |
| `deplete_asym` | `0.665` | `+0.284` | `0.666` | `0.660` | `12753` |
| `depth3_imb` | `0.500` | `+0.143` | `0.559` | `0.566` | `29853` |
| `l1_depth` | `0.499` | `+0.000` | `0.501` | `0.497` | `29853` |
| `spread` | `0.497` | `-0.022` | `0.500` | `0.499` | `27617` |
| `ofi1_norm` | `0.370` | `-0.195` | `0.371` | `0.365` | `29853` |

### Regime Splits

- `all`: `micro_gap` auc=`0.726`, tail-hit=`0.902`, n=`27617`
- `thin`: `micro_gap` auc=`0.619`, tail-hit=`0.129`, n=`13507`
- `thick`: `micro_gap` auc=`0.805`, tail-hit=`0.891`, n=`14110`
- `wide_spread`: `micro_gap` auc=`0.887`, tail-hit=`0.884`, n=`7783`

### Incremental Tests

- Base linear-probability R² with `micro_gap`: `0.1943`
- Add `imb1` on matched rows: uplift=`+0.0039`, n=`27617`
- Add `gap_asym` on matched rows: uplift=`+0.0422`, n=`12753`
- Add `deplete_asym` on matched rows: uplift=`+0.0142`, n=`12753`
- Add `depth3_imb` on matched rows: uplift=`+0.0000`, n=`27617`
- Add `l1_depth` on matched rows: uplift=`+0.0001`, n=`27617`
- Add `ofi1_norm` on matched rows: uplift=`+0.0072`, n=`27617`

### Common Book States

- `9986/10005`: n=`134`, p_up=`0.724`, avg_micro=`1.612`, avg_imb=`0.170`
- `9987/10005`: n=`145`, p_up=`0.697`, avg_micro=`1.302`, avg_imb=`0.145`
- `9985/10003`: n=`95`, p_up=`0.642`, avg_micro=`1.290`, avg_imb=`0.143`
- `9986/10004`: n=`122`, p_up=`0.639`, avg_micro=`1.037`, avg_imb=`0.115`
- `9987/10006`: n=`162`, p_up=`0.630`, avg_micro=`0.710`, avg_imb=`0.075`
- `9990/10009`: n=`328`, p_up=`0.625`, avg_micro=`0.854`, avg_imb=`0.090`
- `9985/10004`: n=`107`, p_up=`0.617`, avg_micro=`1.024`, avg_imb=`0.108`
- `9991/10010`: n=`397`, p_up=`0.602`, avg_micro=`0.571`, avg_imb=`0.060`
- `9991/10009`: n=`318`, p_up=`0.588`, avg_micro=`0.500`, avg_imb=`0.056`
- `9988/10006`: n=`178`, p_up=`0.579`, avg_micro=`0.319`, avg_imb=`0.035`

## `INTARIAN_PEPPER_ROOT`

- Target: `resid_sign_1`
- Reason: drifting product -> detrended residual direction
- Day trend summary: median r²=`1.000`, slope range=`+0.1000` .. `+0.1000`

### Feature Table

| Feature | AUC | Corr | Top bucket aligned-rate | Bottom bucket aligned-rate | n |
| --- | ---: | ---: | ---: | ---: | ---: |
| `imb1` | `0.751` | `+0.444` | `0.435` | `0.740` | `29903` |
| `micro_gap` | `0.710` | `+0.404` | `0.409` | `0.729` | `27678` |
| `gap_asym` | `0.668` | `+0.276` | `0.354` | `0.747` | `12470` |
| `deplete_asym` | `0.666` | `+0.227` | `0.354` | `0.747` | `12470` |
| `spread` | `0.546` | `+0.020` | `0.448` | `0.670` | `27678` |
| `l1_depth` | `0.530` | `+0.044` | `0.451` | `0.628` | `29903` |
| `depth3_imb` | `0.494` | `+0.130` | `0.452` | `0.648` | `29903` |
| `ofi1_norm` | `0.369` | `-0.198` | `0.286` | `0.404` | `29903` |

### Regime Splits

- `all`: `micro_gap` auc=`0.710`, tail-hit=`0.876`, n=`27678`
- `thin`: `micro_gap` auc=`0.549`, tail-hit=`0.056`, n=`15695`
- `thick`: `micro_gap` auc=`0.837`, tail-hit=`0.882`, n=`11983`
- `wide_spread`: `micro_gap` auc=`0.840`, tail-hit=`0.880`, n=`11081`

### Incremental Tests

- Base linear-probability R² with `micro_gap`: `0.1632`
- Add `imb1` on matched rows: uplift=`+0.0141`, n=`27678`
- Add `gap_asym` on matched rows: uplift=`+0.0527`, n=`12470`
- Add `deplete_asym` on matched rows: uplift=`+0.0278`, n=`12470`
- Add `depth3_imb` on matched rows: uplift=`+0.0011`, n=`27678`
- Add `l1_depth` on matched rows: uplift=`+0.0078`, n=`27678`
- Add `ofi1_norm` on matched rows: uplift=`+0.0039`, n=`27678`
