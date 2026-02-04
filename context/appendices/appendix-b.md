# Appendix B: Dependency Map

```mermaid
graph LR
    S1["Stage 1<br/>Backend"] --> S2["Stage 2<br/>CLI"]
    S1 --> S3["Stage 3<br/>HITL"]
    S2 --> S3
    S3 --> S4["Stage 4<br/>Full Workflow"]
    S4 --> S5["Stage 5<br/>Web Client"]
    S4 --> S6["Stage 6<br/>Deployment"]
    S5 --> S6

    style S1 fill:#1a1a4a,stroke:#6c8aff,color:#e0e0e8
    style S2 fill:#1a3a2e,stroke:#4ade80,color:#e0e0e8
    style S3 fill:#3a2a0a,stroke:#fbbf24,color:#e0e0e8
    style S4 fill:#2a1a4a,stroke:#a78bfa,color:#e0e0e8
    style S5 fill:#0a2a3a,stroke:#22d3ee,color:#e0e0e8
    style S6 fill:#4a1a1a,stroke:#f87171,color:#e0e0e8
```

Stages 5 and 6 are independent of each other — either can be built first. Stage 5 needs Stage 4 for the full graph definition. Stage 6 needs Stage 4 for the worker logic. Both can proceed in parallel once Stage 4 is complete.
