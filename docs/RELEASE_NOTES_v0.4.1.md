# v0.4.1 — Execution Safety

## Fixed

- MEXC error 5003 caused by sending preset TP/SL with the entry request.
- Docker pytest imports through `PYTHONPATH=/app`.
- OpenAI exception details leaking into Telegram.

## Changed

- Entry is placed first without TP/SL.
- Actual `positionId`, fill price and volume are read from MEXC.
- TP/SL is placed separately with `/api/v1/private/stoporder/place`.
- Protection prices are recalculated from the actual fill and rounded to `priceUnit`.
- Missing protection triggers an emergency close attempt.

## Safety

This is still a CONFIRM release. AUTO remains unavailable.
Test only with the minimum acceptable notional and no unrelated positions.
