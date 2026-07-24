# BUG-002 — Position Optimizer Core

Position Optimizer converts the combined quality of a setup into a bounded
multiplier for Smart Risk. It uses Decision, Confluence, Prediction, Trigger,
Entry Optimizer and Market Opportunity scores.

Safety rules:

- Smart Risk hard min/max risk limits remain authoritative.
- Volatility and Macro guards may reduce size and disable scaling up.
- Unconfirmed triggers and non-ENTER_NOW entry states cannot scale above base.
- Chasing or invalid entries receive the defensive minimum multiplier.
