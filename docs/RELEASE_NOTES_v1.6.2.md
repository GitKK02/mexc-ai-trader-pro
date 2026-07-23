# v1.6.2 — Trigger Engine

This release adds a stateful, execution-neutral Trigger Engine on top of the
Opportunity and Prediction layers.

## Highlights

- Consecutive-observation confirmation to reduce one-candle noise.
- States: `COLD`, `WATCH`, `ARMED`, `TRIGGERED`, `INVALIDATED`.
- Direction-aware momentum activation for LONG and SHORT setups.
- Breakout distance, relative-volume and acceleration confirmations.
- False-breakout and late-entry invalidation.
- Trigger diagnostics in Telegram signal cards.

`TRIGGERED` does not place an order automatically in v1.6.2. It is a verified
input for later execution integration and can be tested before live risk rises.
