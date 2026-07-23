# MEXC AI Trader Pro v1.7.0 — Market Intelligence 2.0

This release upgrades market context into a cross-market opportunity selector.

## Added

- Composite Market Opportunity Score after Opportunity, Prediction and Trigger engines.
- Cross-market ranking and TOP-N selection.
- HOT/WARM/NORMAL market priority.
- Bonuses for READY predictions and confirmed triggers.
- Penalties for invalidated setups, opposite breadth and elevated false-breakout risk.
- Decision Engine hold for setups outside the selected market TOP-N.
- Expanded `/market` report with confidence and best opportunities.

The selector does not guarantee profitable trades. It is intended to prevent the bot from taking every passing setup when stronger alternatives are available.
