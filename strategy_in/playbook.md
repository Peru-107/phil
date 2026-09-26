# India options playbook (v1, no settled history yet)

This is the strategy layer for the India paper-trading track
(`core_in/`, `config_in/config.json`, `CYCLE_IN.md`). It plays the same role
`strategy/playbook.md` plays for the Polymarket track: it is yours to edit,
it must cite evidence from settled positions, and it starts nearly empty
because there is no track record yet.

## Scope (v1)

- Long options only, NIFTY/BANKNIFTY, weekly/monthly expiries within
  `config_in/config.json`'s min/max days-to-expiry window.
- One directional thesis per position: you believe the underlying will move
  enough by expiry that the option finishes in the money. Record that belief
  honestly as `--est-prob-itm` — this is the number `core_in/score.py`
  calibrates against, exactly like the Polymarket track's `est-prob`.
- No spreads, no selling/writing options, no multi-leg structures yet — the
  ledger and caps don't model margin for those.

## Edge classes (for `--edge-class`; score.py splits P&L by this)

- `momentum`: continuation of an existing intraday/multi-day trend.
- `mean-reversion`: a stretched move you expect to partially unwind.
- `event-driven`: a scheduled catalyst (RBI policy, budget, earnings, a
  macro print) with a specific expected direction and size.
- `other`: anything not fitting the above — classify honestly, not
  aspirationally, same rule as the Polymarket track.

## What's still open

Every number in `strategy_in/risk.json` is a placeholder, not a conclusion —
there is no settled position yet to justify any of them. Do not tighten or
loosen `min_edge_pct` without settled evidence citing specific position ids,
the same discipline `strategy/risk.json`'s changelog holds itself to.
