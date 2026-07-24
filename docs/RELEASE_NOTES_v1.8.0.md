# v1.8.0 — Learning Data Core

This release creates a local, explainable training dataset without changing
strategy weights automatically.

- Stores ranked signal features in SQLite.
- Links a signal snapshot to the PAPER position opened from it.
- Synchronizes closed PAPER outcomes and net PnL.
- Keeps component dictionaries as JSON for later offline analysis.
- Adds `/learning` and the `🧠 Обучение` menu button.
- Reports sample counts, win/loss statistics and the best sufficiently sampled
  Prediction→Trigger state combination.

The engine intentionally requires at least three closed samples before naming a
best setup. v1.8.0 is data collection, not self-modifying live trading.
