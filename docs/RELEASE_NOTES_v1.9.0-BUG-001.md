# v1.9.0 BUG-001 — Entry Optimizer Core

Adds a non-executing entry timing layer on top of Entry Intelligence.

## New recommendations

- `ENTER_NOW`
- `WAIT_PULLBACK`
- `WAIT_RETEST`
- `SKIP_CHASE`
- `INVALID`

The optimizer publishes a recommended entry price, entry zone, waiting distance
in ATR and percent, recommendation TTL, score, and explanation. Decision Engine
can enforce waiting recommendations, but this patch does not place limit orders
or modify live execution automatically.
