# Table C - absorption-stage stability

`unique` counts seeds whose D_s curve crosses the 0.60 threshold at most once. A non-monotonic curve has no well-posed absorption point and is reported as such rather than forced.

| policy | fault | modal A(f) | modal % | unique / n | distribution |
|---|---|:--:|--:|--:|---|
| P1 | imu_dropout | L7 | 60% | 0/30 | L2a:4, L2b:3, L6:1, L7:18, None:4 |
| P1 | position_bias | L2a | 100% | 30/30 | L2a:30 |
| P1 | position_drift | L2a | 100% | 30/30 | L2a:30 |
| P1 | speed_stuck | L2a | 100% | 30/30 | L2a:30 |
| P1 | speed_bias | L2a | 100% | 0/30 | L2a:30 |
| P1 | lateral_noise | None | 50% | 3/30 | L6:12, L8:3, None:15 |
| P2 | imu_dropout | L7 | 40% | 17/30 | L2a:4, L2b:4, L6:6, L7:12, L8:2, None:2 |
| P2 | position_bias | L2a | 100% | 30/30 | L2a:30 |
| P2 | position_drift | L2a | 100% | 30/30 | L2a:30 |
| P2 | speed_stuck | L2b | 57% | 4/30 | L1:3, L2a:4, L2b:17, L6:3, L7:1, L8:2 |
| P2 | speed_bias | L2a | 40% | 7/30 | L1:6, L2a:12, L2b:10, L8:2 |
| P2 | lateral_noise | L2b | 60% | 6/30 | L2b:18, L6:1, L7:8, None:3 |
| P3 | imu_dropout | L2b | 37% | 0/30 | L2a:4, L2b:11, L6:6, L7:9 |
| P3 | position_bias | L2a | 100% | 30/30 | L2a:30 |
| P3 | position_drift | L2a | 100% | 30/30 | L2a:30 |
| P3 | speed_stuck | L2a | 100% | 8/30 | L2a:30 |
| P3 | speed_bias | L2a | 100% | 0/30 | L2a:30 |
| P3 | lateral_noise | None | 83% | 5/30 | L8:5, None:25 |