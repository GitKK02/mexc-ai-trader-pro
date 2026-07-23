# v1.6.0 — Opportunity Core

This release introduces an execution-neutral early-move detection layer.

## Added

- `OpportunityEngine` with Energy and Opportunity scores.
- Stages: `COLD`, `BUILDING`, `CHARGED`, `RELEASED`.
- `WATCH` state for setups that are forming but have not triggered.
- In-memory `HeatQueue` with `HOT`, `WARM`, and `COLD` priorities.
- ATR, EMA and range compression diagnostics.
- Volume-building and VWAP-balance diagnostics.
- Telegram signal-card visibility for Energy, Opportunity, stage and heat.

## Safety

Opportunity Core cannot submit an order. `WATCH` is observational only. Entry
activation remains the responsibility of Decision/Execution and the future
Trigger Engine.
