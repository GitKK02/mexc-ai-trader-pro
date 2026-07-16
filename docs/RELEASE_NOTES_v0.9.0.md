# v0.9.0 — Confirmed Position Actions

## Added
- Confirmed breakeven stop-loss movement.
- Existing TP preservation.
- Atomic TP/SL planned-order price modification.
- Price-unit rounding and side validation.
- Double Telegram confirmation.
- Post-change MEXC verification.
- Persistent position-action audit log.

## Safety
No automatic action is enabled. Breakeven movement requires an active
position, an existing stop, sufficient R, and explicit confirmation.
