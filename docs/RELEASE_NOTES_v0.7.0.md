# v0.7.0 — AI Decision Engine

## Added

- Deterministic final-decision layer.
- Component scores for scanner, timeframes, momentum and portfolio.
- Market-regime and BTC-context adjustments.
- Advisory OpenAI bonus or penalty.
- Actions: ENTER, CONFIRM, WAIT and REJECT.
- Confidence labels.
- `/decisions` command.
- LIVE preparation blocked for WAIT and REJECT signals.

## Safety

ENTER is only a classification in this release. It does not enable AUTO.
Every real order still requires the existing CONFIRM workflow.
