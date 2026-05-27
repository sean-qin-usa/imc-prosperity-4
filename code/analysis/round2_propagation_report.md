# Propagation Signal Report — `/Users/sean_tsu_/Downloads/prosperity/IMCP2026/data/round2`

This report asks a causal question:

- after observing a move in leader series A, does follower series B move in the same direction later?

It is intended for:

- constituent -> basket premium propagation
- underlying -> option residual propagation
- raw product -> derived residual propagation

## `ACO_to_IPR`

- Leader: `ACO`
- Follower: `IPR`
- Overlapping rows: `29900`
- Best causal return lag: leader move into `t` vs follower one-tick return starting `t+2`, corr=`-0.006`
- Leader tail cuts: up >= `+3.500`, down <= `-3.500` with n_up=`3248`, n_down=`3218`
- Follower forward `1`-tick response: signed_mean=`-0.021`, up_mean=`+0.080`, up_hit=`0.377`, down_mean=`+0.123`, down_hit=`0.279`
- Follower forward `3`-tick response: signed_mean=`-0.042`, up_mean=`+0.175`, up_hit=`0.496`, down_mean=`+0.261`, down_hit=`0.281`
- Follower forward `5`-tick response: signed_mean=`-0.041`, up_mean=`+0.370`, up_hit=`0.599`, down_mean=`+0.455`, down_hit=`0.294`

## `IPR_to_ACO`

- Leader: `IPR`
- Follower: `ACO`
- Overlapping rows: `29900`
- Best causal return lag: leader move into `t` vs follower one-tick return starting `t+2`, corr=`-0.006`
- Leader tail cuts: up >= `+3.500`, down <= `-3.000` with n_up=`3080`, n_down=`3360`
- Follower forward `1`-tick response: signed_mean=`+0.018`, up_mean=`-0.004`, up_hit=`0.360`, down_mean=`-0.039`, down_hit=`0.356`
- Follower forward `3`-tick response: signed_mean=`+0.027`, up_mean=`+0.039`, up_hit=`0.403`, down_mean=`-0.017`, down_hit=`0.375`
- Follower forward `5`-tick response: signed_mean=`+0.002`, up_mean=`+0.003`, up_hit=`0.393`, down_mean=`-0.001`, down_hit=`0.399`

## `ACO_to_IPR_resid`

- Leader: `ACO`
- Follower: `IPR_RESID`
- Overlapping rows: `29900`
- Best causal return lag: leader move into `t` vs follower one-tick return starting `t+2`, corr=`-0.006`
- Leader tail cuts: up >= `+3.500`, down <= `-3.500` with n_up=`3248`, n_down=`3218`
- Follower forward `1`-tick response: signed_mean=`-0.021`, up_mean=`-0.020`, up_hit=`0.377`, down_mean=`+0.023`, down_hit=`0.644`
- Follower forward `3`-tick response: signed_mean=`-0.043`, up_mean=`-0.126`, up_hit=`0.496`, down_mean=`-0.040`, down_hit=`0.500`
- Follower forward `5`-tick response: signed_mean=`-0.043`, up_mean=`-0.132`, up_hit=`0.523`, down_mean=`-0.046`, down_hit=`0.469`

## `IPR_resid_to_ACO`

- Leader: `IPR_RESID`
- Follower: `ACO`
- Overlapping rows: `29900`
- Best causal return lag: leader move into `t` vs follower one-tick return starting `t+2`, corr=`-0.006`
- Leader tail cuts: up >= `+3.400`, down <= `-3.100` with n_up=`3076`, n_down=`2991`
- Follower forward `1`-tick response: signed_mean=`-0.001`, up_mean=`-0.001`, up_hit=`0.360`, down_mean=`+0.001`, down_hit=`0.354`
- Follower forward `3`-tick response: signed_mean=`+0.017`, up_mean=`+0.042`, up_hit=`0.403`, down_mean=`+0.008`, down_hit=`0.373`
- Follower forward `5`-tick response: signed_mean=`-0.007`, up_mean=`+0.003`, up_hit=`0.393`, down_mean=`+0.017`, down_hit=`0.396`
