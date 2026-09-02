# Table B - primary test: D_L1 vs D_L2a

Wilcoxon signed-rank, two-sided, paired by seed. Holm-Bonferroni across the six faults within each policy. Effect is the median paired difference with a BCa 95% CI.

## Policy P1

| fault | primary | n | W | z | p (raw) | p (Holm) | reject | effect L1-L2a |
|---|:--:|--:|--:|--:|--:|--:|:--:|---|
| imu_dropout | no | 30 | 1 | -4.75 | 2.02e-06 | 9.12e-06 | **yes** | 0.138 [0.105, 0.256] |
| position_bias | **yes** | 30 | 0 | -5.47 | 4.62e-08 | 2.77e-07 | **yes** | 0.500 |
| position_drift | **yes** | 30 | 0 | -4.77 | 1.82e-06 | 9.12e-06 | **yes** | 0.470 [0.467, 0.472] |
| speed_stuck | no | 30 | 0 | -4.77 | 1.83e-06 | 9.12e-06 | **yes** | 0.397 [0.360, 0.418] |
| speed_bias | no | 30 | 0 | -4.77 | 1.83e-06 | 9.12e-06 | **yes** | 0.484 [0.477, 0.488] |
| lateral_noise | no | 30 | 0 | -4.77 | 1.83e-06 | 9.12e-06 | **yes** | 0.019 [0.016, 0.022] |

## Policy P2

| fault | primary | n | W | z | p (raw) | p (Holm) | reject | effect L1-L2a |
|---|:--:|--:|--:|--:|--:|--:|:--:|---|
| imu_dropout | no | 30 | 0 | -4.77 | 1.83e-06 | 9.13e-06 | **yes** | 0.196 [0.102, 0.266] |
| position_bias | **yes** | 30 | 0 | -5.47 | 4.62e-08 | 2.77e-07 | **yes** | 0.500 |
| position_drift | **yes** | 30 | 0 | -4.77 | 1.83e-06 | 9.13e-06 | **yes** | 0.470 [0.466, 0.471] |
| speed_stuck | no | 30 | 105 | -2.61 | 9.00e-03 | 9.00e-03 | **yes** | 0.176 [0.026, 0.245] |
| speed_bias | no | 30 | 24 | -4.28 | 1.88e-05 | 3.77e-05 | **yes** | 0.362 [0.169, 0.398] |
| lateral_noise | no | 30 | 0 | -4.77 | 1.83e-06 | 9.13e-06 | **yes** | 0.044 [0.032, 0.068] |

## Policy P3

| fault | primary | n | W | z | p (raw) | p (Holm) | reject | effect L1-L2a |
|---|:--:|--:|--:|--:|--:|--:|:--:|---|
| imu_dropout | no | 30 | 1 | -4.75 | 2.02e-06 | 9.13e-06 | **yes** | 0.195 [0.166, 0.283] |
| position_bias | **yes** | 30 | 0 | -5.47 | 4.62e-08 | 2.77e-07 | **yes** | 0.500 |
| position_drift | **yes** | 30 | 0 | -4.77 | 1.83e-06 | 9.13e-06 | **yes** | 0.471 [0.469, 0.474] |
| speed_stuck | no | 30 | 0 | -4.77 | 1.83e-06 | 9.13e-06 | **yes** | 0.428 [0.418, 0.432] |
| speed_bias | no | 30 | 0 | -4.77 | 1.83e-06 | 9.13e-06 | **yes** | 0.487 [0.472, 0.491] |
| lateral_noise | no | 30 | 0 | -4.77 | 1.83e-06 | 9.13e-06 | **yes** | 0.019 [0.017, 0.021] |
