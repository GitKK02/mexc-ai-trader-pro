# v1.5.0 — Confluence Engine

This release adds an independent-confirmation layer before live preparation.

## Highlights

- Eight independent checks: trend, momentum, volume, timeframe agreement, entry quality, market guards, BTC context, and portfolio context.
- Configurable minimum confirmations (default 6 of 8).
- Confluence score is included in Decision Engine weighting.
- Signals below the minimum can be held at WAIT instead of reaching LIVE preparation.
- Telegram signal cards show the confirmation count and score.

The engine does not bypass hard risk, macro, volatility, portfolio, or entry guards.
