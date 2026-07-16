# v0.8.0 — Dynamic Position Manager

## Added
- SHADOW monitoring of real MEXC positions.
- Current R calculation from entry and active stop-loss.
- Lifecycle actions:
  HOLD, TP1_REVIEW, BREAKEVEN_REVIEW, TRAIL_REVIEW,
  EXIT_REVIEW and PROTECTION_MISSING.
- Change-only notifications with cooldown.
- `/position_advice` command and Telegram button.
- Persistent last-action state.

## Safety
No order is modified automatically in this release.
