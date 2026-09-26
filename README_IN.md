# Phil — India options track (v1)

A parallel, paper-first trading track for NIFTY/BANKNIFTY options, built
alongside the original Polymarket engine in this repo. It reuses that
engine's discipline (honest fills against live bid/ask, hard caps checked
by code rather than trusted to the strategy layer, an append-only ledger,
brier-scored calibration) but is entirely separate code: nothing here
touches `core/`, `config/`, or `.github/`, so it can never collide with the
protected Polymarket engine or its CI boundary guard.

## Layout

- `config_in/config.json` — caps (paper capital, max premium per trade,
  max open positions, allowed underlyings, lot sizes, market hours,
  the disabled-by-default `real` block). Plays the role
  `config/protected.json` plays for the other track.
- `core_in/` — the engine: `quotes.py` (data source abstraction),
  `angelone.py` (Angel One SmartAPI client), `ledger.py` (paper broker),
  `resolve.py` (expiry settlement), `score.py` (P&L/calibration report),
  `validate.py` (integrity checks — run it by hand after any edit).
- `strategy_in/` — your playbook and risk policy, meant to be edited as
  positions settle and you learn something.
- `journal_in/` — `ledger.jsonl` (append-only, only `core_in/ledger.py` and
  `core_in/resolve.py` write it), `cycles.log`, `retros/`.
- `CYCLE_IN.md` — the per-cycle procedure. `loop_in.sh` runs it headlessly.

## Getting started (no broker account needed yet)

`config_in/config.json`'s `data_source` starts as `"mock"` — a deterministic
synthetic quote generator with no network calls and no credentials. Use it
to exercise the whole pipeline first:

```
python3 core_in/ledger.py place --underlying NIFTY --expiry 2026-10-09 \
  --strike 25000 --option-type CE --lots 1 --est-prob-itm 0.55 \
  --category test --edge-class other --rationale "pipeline smoke test"
python3 core_in/ledger.py status
python3 core_in/validate.py
```

(`place` only works inside `market_hours_ist` in IST — mock mode still
enforces the same market-hours gate the real thing will.)

## Moving to live quotes (Angel One SmartAPI)

1. Open an Angel One trading + demat account if you don't have one
   (free; standard KYC).
2. Register a SmartAPI app at https://smartapi.angelbroking.com/ — free,
   gives you an API key.
3. Enable TOTP-based 2FA for API login in your Angel One account settings;
   note the base32 secret it shows you once.
4. Install the extra dependency: `pip install pyotp`.
5. Set environment variables: `ANGELONE_API_KEY`, `ANGELONE_CLIENT_CODE`,
   `ANGELONE_PASSWORD`, `ANGELONE_TOTP_SECRET`.
6. `python3 core_in/angelone.py doctor` — confirms login works.
7. Set `config_in/config.json`'s `data_source` to `"angelone"`.

**`core_in/angelone.py` was written from SmartAPI's public docs without a
live account to test against** — endpoint paths, the instrument-master
matching logic, and the index-token lookup for `underlying_ltp` all need
verification against your own account before you trust a single number
from them. Expect to fix small things in there; that's expected, not a
sign the design is wrong.

## Getting to real money — same discipline as the Polymarket track

`config_in/config.json`'s `real_trading_enabled` starts `false`, same
convention as `config/protected.json`. There is no `.github/` CI check
enforcing this here (adding one means touching the operator-owned
`.github/` directory in this repo — do that yourself, or ask for it as a
separate, explicit step). Until you do:

- Run `core_in/validate.py` yourself before trusting any config edit —
  it's the same tripwire `core/validate.py` runs automatically in CI, just
  not wired to run automatically yet in this tree.
- `core_in/angelone.py place_real_order()` refuses to run unless
  `real_trading_enabled` is `true` and the `real` caps block passes
  `validate.py`'s hard ceilings — mirroring `core/real.py`'s gating,
  just enforced by one file instead of a protected config CI checks.
- Don't flip it on until you have real settled paper history (tens of
  positions, not a handful) and have actually read what
  `core_in/score.py` says about calibration and P&L by edge class.

## What's still missing (be honest about scope)

- Only long options — no spreads, no writing/selling, no margin modeling.
- `resolve.py`'s expiry settlement is an approximation (last underlying
  LTP, not NSE's official 30-minute settlement average).
- No CI, no multi-runner lease, no forward-test workflow — this is a
  single-runner v1, not the mature multi-week system the Polymarket track
  has become (see `journal/retros/` there for what that maturity looks
  like in practice).
