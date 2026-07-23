# v1.6.1 — Prediction Engine

Prediction Engine evaluates Opportunity Core WATCH setups before the impulse is released.

## Added

- Prediction Score (0–100)
- Breakout Readiness (0–100)
- False Breakout Risk (0–100)
- Direction and states: COLD, WATCH, READY, INVALIDATED
- Estimated horizon in candles
- Explainable component diagnostics
- Telegram signal-card fields

`READY` is deliberately execution-neutral. It does not place or confirm a live order. The transition from READY to an actionable entry belongs to Trigger Engine v1.6.2.

The displayed scores are model indicators derived from market features, not guaranteed probabilities of profit.
