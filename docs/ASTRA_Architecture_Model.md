# ASTRA Architectural Graphical Model

## Overview
ASTRA (**Autonomous Safety, Trust, and Runtime Architecture**) enforces structural separation between an untrusted AI Proposer (**Core-A**) and physical vehicle actuators through a mechanically isolated 9-layer safety governance pipeline (**Core-B**).

---

## 9-Layer Architectural Diagram

```mermaid
graph TD
    subgraph SENSING ["Layer 1: Sensor Sensing & Fusion"]
        GPS["GPS Receiver"]
        IMU["IMU (Inertial Unit)"]
        WHEEL["Wheel Speed Encoders"]
        L1["L1: Redundant Sensing & Median Fusion"]
        GPS --> L1
        IMU --> L1
        WHEEL --> L1
    end

    subgraph ESTIMATION ["Layers 2 & 3: Estimation & Trust"]
        L2["L2: UKF (Unscented Kalman Filter)<br/>State Estimate (x, y, ψ, v)"]
        L3["L3: Trust Index Evaluator<br/>Innovation Noise Covariance"]
        L1 --> L2
        L2 --> L3
    end

    subgraph CORE_A ["CORE-A: Untrusted AI Proposer"]
        L4["L4: Learned PPO Neural Policy<br/>Proposes: (a_prop, δ_prop)"]
        L2 --> L4
    end

    subgraph CORE_B ["CORE-B: Safety Machinery & Checking Layers"]
        L5["L5: Digital Twin Reference Model<br/>Kinematic Bicycle Model"]
        L6["L6: Conformal Prediction Gate<br/>Statistical Non-Conformity Score"]
        L7B["L7b: Physical Gate<br/>Newtonian Jerk & Acceleration Limits"]
        L7A["L7a: Hard Bounds Gate<br/>Deterministic Barrier Functions"]
        L8["L8: Graduated Fail-Safe Engine<br/>NOMINAL → DEGRADED → LIMP → HALT"]
        L9["L9: RCM (Runtime Calibration Manager)<br/>Arbitration & Safe Exploration Envelope"]

        L2 --> L5
        L4 -->|"Proposals (One-Way)"| L6
        L5 --> L6
        L3 --> L6
        L6 -->|"Verdict"| L7B
        L7B -->|"Verdict"| L7A
        L7A --> L8
        L8 --> L9
    end

    subgraph ACTUATORS ["Physical Vehicle Actuators"]
        ACT["Steering & Throttle Actuators"]
        L9 -->|"Command (u_cmd)"| ACT
    end

    classDef coreA fill:#3d1a24,stroke:#f85149,color:#e6edf3;
    classDef coreB fill:#162338,stroke:#58a6ff,color:#e6edf3;
    classDef sense fill:#14221c,stroke:#3fb950,color:#e6edf3;
    class L4 coreA;
    class L5,L6,L7B,L7A,L8,L9 coreB;
    class L1,L2,L3 sense;
```

---

## Key Separation Invariants

1. **One-Way Boundary (Core-A → Core-B):** The AI policy ($L4$) can only issue *proposals*. It has no direct access to actuators.
2. **Deterministic Override:** If any Core-B gate ($L6, L7b, L7a$) issues a `VETO`, $L8$ escalates protection and $L9$ overrides the command to a safe physical baseline.
3. **Uncertified Context Resilience (Tunnel Scenario):** When entering an uncertified domain, $L9$ RCM engages **Bounded Safe Exploration** (restricting speed and steering envelope) rather than halting the vehicle.
