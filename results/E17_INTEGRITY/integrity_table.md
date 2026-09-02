| Fault | Severity | Intended channel | Reaches L1? | Reaches estimator? | Reaches downstream? | Ground-truth bypass? | Verdict |
|---|---|---|:--:|:--:|:--:|:--:|:--:|
| `imu_dropout` | suppress IMU | `frame-level (IMU)` | **yes** | **yes** | **yes** | no | VALID |
| `position_bias` | 1.0 m | `y` | **NO** | **NO** | **NO** | **YES** | **INVALID** |
| `position_drift` | 2.0 m final | `y` | **NO** | **NO** | **NO** | **YES** | **INVALID** |
| `speed_stuck` | hold | `v` | **yes** | **yes** | **yes** | no | VALID |
| `speed_bias` | 3.0 m/s | `v` | **yes** | **yes** | **yes** | no | VALID |
| `lateral_noise` | sigma x25 | `a` | **yes** | **yes** | **yes** | no | VALID |