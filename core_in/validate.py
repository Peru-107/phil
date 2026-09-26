#!/usr/bin/env python3
"""Integrity tripwires for the India paper-trading track. Offline, no network.

Not wired into CI yet (adding a workflow means touching .github/, which is
operator-owned in this repo — see README_IN.md). Run it by hand after any
strategy_in/ or config_in/ edit, the same way core/validate.py is meant to
be read, not just trusted.

Usage: python3 core_in/validate.py
"""
import json
import pathlib
import py_compile
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

LEDGER_REQUIRED = {
    "id", "ts", "underlying", "expiry", "strike", "option_type", "lot_size",
    "lots", "entry_price", "premium_paid_inr", "est_prob_itm", "status",
}
LEDGER_STATUSES = {"open", "closed", "expired_itm", "expired_otm"}
SETTLED_STATUSES = {"closed", "expired_itm", "expired_otm"}

# Raising these requires a deliberate edit here, not a config_in/config.json
# bump talked into a cycle — same intent as core/validate.py's hard ceilings.
HARD_CEILINGS = {
    "max_premium_per_trade_inr": 5000.0,
    "max_open_positions": 20,
    "max_capital_per_underlying_inr": 15000.0,
}
REAL_HARD_CEILINGS = {
    "max_premium_per_trade_inr": 1000.0,
    "max_open_positions": 5,
    "daily_capital_cap_inr": 2000.0,
}

errors = []


def err(msg):
    errors.append(msg)


def load_json(relpath):
    path = ROOT / relpath
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        err(f"{relpath}: missing")
    except json.JSONDecodeError as e:
        err(f"{relpath}: invalid JSON — {e}")
    return None


config = load_json("config_in/config.json")
if config:
    for field, ceiling in HARD_CEILINGS.items():
        v = config.get(field)
        if not isinstance(v, (int, float)) or v <= 0:
            err(f"config_in/config.json: {field} missing or not a positive number")
        elif v > ceiling:
            err(f"config_in/config.json: {field} = {v} exceeds hard ceiling {ceiling}")

    if config.get("real_trading_enabled") not in (True, False):
        err("config_in/config.json: real_trading_enabled must be a boolean")
    if config.get("real_trading_enabled") is True:
        real = config.get("real")
        if not isinstance(real, dict):
            err("config_in/config.json: real_trading_enabled is true but the "
                "'real' caps block is missing")
        else:
            for field, ceiling in REAL_HARD_CEILINGS.items():
                v = real.get(field)
                if not isinstance(v, (int, float)) or v <= 0:
                    err(f"config_in/config.json: real.{field} missing or not "
                        f"a positive number")
                elif v > ceiling:
                    err(f"config_in/config.json: real.{field} = {v} exceeds "
                        f"hard ceiling {ceiling}")

    lot_sizes = config.get("lot_sizes")
    if not isinstance(lot_sizes, dict) or not lot_sizes:
        err("config_in/config.json: lot_sizes missing or empty")
    for u in config.get("allowed_underlyings", []):
        if u not in (lot_sizes or {}):
            err(f"config_in/config.json: allowed_underlyings has {u!r} but "
                f"lot_sizes has no entry for it")

risk = load_json("strategy_in/risk.json")
if risk and config:
    if not isinstance(risk.get("min_edge_pct"), (int, float)):
        err("strategy_in/risk.json: min_edge_pct missing or not numeric")

ledger_path = ROOT / "journal_in" / "ledger.jsonl"
if ledger_path.exists() and config:
    for lineno, line in enumerate(ledger_path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            err(f"journal_in/ledger.jsonl:{lineno}: invalid JSON — {e}")
            continue
        missing = LEDGER_REQUIRED - row.keys()
        if missing:
            err(f"journal_in/ledger.jsonl:{lineno}: missing fields {sorted(missing)}")
            continue
        if row["status"] not in LEDGER_STATUSES:
            err(f"journal_in/ledger.jsonl:{lineno}: unknown status {row['status']!r}")
        if row["status"] in SETTLED_STATUSES and not (
                "pnl_inr" in row and "settled_ts" in row):
            err(f"journal_in/ledger.jsonl:{lineno}: settled row lacks pnl_inr/settled_ts")
        if row["premium_paid_inr"] > config["max_premium_per_trade_inr"]:
            err(f"journal_in/ledger.jsonl:{lineno}: premium_paid_inr "
                f"{row['premium_paid_inr']} exceeds max_premium_per_trade_inr "
                f"{config['max_premium_per_trade_inr']}")
        if not 0 < row["est_prob_itm"] < 1:
            err(f"journal_in/ledger.jsonl:{lineno}: est_prob_itm "
                f"{row['est_prob_itm']} outside (0, 1)")

for pyfile in sorted((ROOT / "core_in").glob("*.py")) + \
        sorted((ROOT / "strategy_in").rglob("*.py")):
    try:
        py_compile.compile(str(pyfile), doraise=True)
    except py_compile.PyCompileError as e:
        err(f"{pyfile.relative_to(ROOT)}: does not compile — {e.msg}")

if errors:
    print(f"FAIL — {len(errors)} integrity error(s):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print("OK — config, risk policy, and ledger all sane")
