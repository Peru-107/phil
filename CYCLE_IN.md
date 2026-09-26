# India Options Trading Cycle Procedure (v1)

Paper-trading cycle for the India track (NIFTY/BANKNIFTY long options).
Follow this procedure once per invocation, then stop. This track is new —
unlike CYCLE.md, there is no settled history, no CI boundary guard, and no
multi-runner lease yet. Treat this file itself as provisional: it will
need real edits once the first few cycles show what's missing.

## Hard rules

- Only `core_in/ledger.py` writes `journal_in/ledger.jsonl`; only
  `core_in/resolve.py` and `core_in/ledger.py close` settle positions.
  Never hand-edit the ledger.
- Every `--est-prob-itm` you record must be your honest belief, formed
  before you look at the premium, not fit to justify a trade you already
  wanted to make.
- Every position needs an edge-class classified honestly (see
  `strategy_in/playbook.md`).
- Nothing places outside NSE market hours — `core_in/ledger.py place`
  enforces this itself, but do not attempt to work around a rejection.

## Procedure

0. **Market check**: if it isn't a weekday within
   `config_in/config.json`'s `market_hours_ist` window, skip straight to
   step 1 (settle) and step 7 (log) — there is nothing to research or place
   outside trading hours.

1. **Settle**: `python3 core_in/resolve.py` — settles any position whose
   expiry has passed, using intrinsic value at expiry (an approximation;
   see the docstring in resolve.py).

2. **Score**: `python3 core_in/score.py` — read win rate, P&L, ROI, and
   (for expiry-settled positions) the calibration/brier numbers.

3. **Retro** (only if new positions settled since the last retro): write
   `journal_in/retros/RETRO-<UTCdate-HHMM>.md`:
   - For each settled position: was the direction wrong, the entry timing
     bad, or normal variance? Check the original rationale.
   - Concrete lessons → edit `strategy_in/playbook.md` or
     `strategy_in/risk.json` to encode them. No speculative rewrites
     without settled evidence.
   - Commit: `git add -A && git commit -m "retro: <one-line lesson>"`.

4. **Scan & research**: pick NIFTY/BANKNIFTY setups worth a directional
   view — technical levels, an upcoming scheduled catalyst (RBI policy,
   budget, a macro print), or an index-level dislocation. Research with
   whatever data/tools you have; form your estimate before looking at the
   option's premium.

5. **Place**: for each candidate clearing `strategy_in/risk.json`'s
   `min_edge_pct` (respecting `max_positions_per_category_per_cycle`):
   `python3 core_in/ledger.py place --underlying NIFTY --expiry <YYYY-MM-DD> \
     --strike <N> --option-type CE|PE --lots <N> --est-prob-itm <p> \
     --category <cat> --edge-class <momentum|mean-reversion|event-driven|other> \
     --rationale "<evidence, level, catalyst>" \
     --strategy-rev $(git rev-parse --short HEAD)`
   Respect rejections — they are `config_in/config.json` cap enforcement,
   not errors to fix.

6. **Log**: append one line to `journal_in/cycles.log`:
   `<UTC ISO> cycle done: settled N, placed M, cash ₹X` (from
   `core_in/ledger.py status`).

7. **Commit**: `git add -A && git commit -m "cycle_in: <UTCdate-HHMM> placed M settled N"`

8. **Push** (if there's an `origin` remote and you're set up to push):
   `git push origin main`. If rejected, `git pull --rebase origin main`
   and retry. Never hand-resolve a ledger conflict — if the rebase
   conflicts on `journal_in/ledger.jsonl`, abort and re-run from step 1.
