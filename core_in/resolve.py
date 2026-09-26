#!/usr/bin/env python3
"""Settle open India-track positions whose expiry has passed.

Intrinsic value at expiry, not any post-expiry quote (index options can go
illiquid or stop trading right at the close): max(0, underlying - strike)
for a call, max(0, strike - underlying) for a put, times lot_size * lots.
This is an approximation of NSE's actual settlement price (a 30-minute
weighted average on expiry day) — good enough for a paper track, not
precise enough to bet real money on the difference.

Usage: python3 core_in/resolve.py
"""
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ledger  # noqa: E402
import quotes  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEDGER = ROOT / "journal_in" / "ledger.jsonl"


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    if not LEDGER.exists():
        print(json.dumps({"settled": 0}))
        return
    rows = ledger.read_ledger()  # latest row per id — skips ones already closed early
    today = dt.date.today()
    src = quotes.get_source()
    settled = 0
    for row in rows:
        if row["status"] != "open":
            continue
        if dt.date.fromisoformat(row["expiry"]) >= today:
            continue
        underlying_close = src.underlying_ltp(row["underlying"])
        if row["option_type"] == "CE":
            intrinsic = max(0.0, underlying_close - row["strike"])
        else:
            intrinsic = max(0.0, row["strike"] - underlying_close)
        exit_value = round(intrinsic * row["lot_size"] * row["lots"], 2)
        status = "expired_itm" if intrinsic > 0 else "expired_otm"
        with LEDGER.open("a") as f:
            f.write(json.dumps({
                **row, "status": status, "exit_value_inr": exit_value,
                "pnl_inr": round(exit_value - row["premium_paid_inr"], 2),
                "underlying_close": underlying_close,
                "settled_ts": now_iso(),
            }) + "\n")
        settled += 1
    print(json.dumps({"settled": settled}))


if __name__ == "__main__":
    main()
