#!/usr/bin/env python3
"""Paper broker for the India options track (NIFTY/BANKNIFTY, long options only).

Mirrors core/ledger.py's discipline: this is the only writer of
journal_in/ledger.jsonl, and every cap in config_in/config.json is enforced
here, not trusted to the strategy layer. A paper BUY fills at the live ask
for the option (crossing the spread), same as a real taker order.

v1 scope, deliberately narrow: long calls/puts only, held to expiry or
closed early with `close`. No spreads, no writing/selling naked options —
that needs margin modeling this track doesn't have yet.

Usage:
  place: python3 core_in/ledger.py place --underlying NIFTY --expiry 2026-10-02 \
           --strike 24500 --option-type CE --lots 1 --est-prob-itm 0.55 \
           --category momentum --edge-class other --rationale "..."
  close: python3 core_in/ledger.py close --id <id>
  status: python3 core_in/ledger.py status
"""
import argparse
import datetime as dt
import json
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import quotes  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEDGER = ROOT / "journal_in" / "ledger.jsonl"
CONFIG = json.loads((ROOT / "config_in" / "config.json").read_text())


def read_ledger():
    """Append-only file; latest row per id wins (same convention as
    core/real.py's real_rows()) — a close/expiry appends a new row for the
    same id rather than mutating the original 'open' one."""
    if not LEDGER.exists():
        return []
    latest, order = {}, []
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rid = row["id"]
        if rid not in latest:
            order.append(rid)
        latest[rid] = row
    return [latest[r] for r in order]


def append(row):
    LEDGER.parent.mkdir(exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(json.dumps(row) + "\n")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def capital_state(entries):
    cash = CONFIG["sim_capital_inr"]
    for e in entries:
        if e["status"] in ("open", "closed", "expired_itm", "expired_otm"):
            cash -= e["premium_paid_inr"]
        if e["status"] in ("closed", "expired_itm"):
            cash += e.get("exit_value_inr", 0.0)
    return cash


def market_open_now():
    hrs = CONFIG["market_hours_ist"]
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    now = dt.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    open_t = dt.datetime.strptime(hrs["open"], "%H:%M").time()
    close_t = dt.datetime.strptime(hrs["close"], "%H:%M").time()
    return open_t <= now.time() <= close_t


def cmd_status(entries):
    open_pos = [e for e in entries if e["status"] == "open"]
    settled = [e for e in entries if e["status"] in
               ("closed", "expired_itm", "expired_otm")]
    pnl = sum(e.get("exit_value_inr", 0.0) - e["premium_paid_inr"] for e in settled)
    print(json.dumps({
        "cash_inr": round(capital_state(entries), 2),
        "open_positions": len(open_pos),
        "settled": len(settled),
        "realized_pnl_inr": round(pnl, 2),
        "open": [{"id": e["id"], "underlying": e["underlying"], "expiry": e["expiry"],
                  "strike": e["strike"], "type": e["option_type"],
                  "entry": e["entry_price"], "est_prob_itm": e["est_prob_itm"]}
                 for e in open_pos],
    }, indent=2))


def cmd_place(args, entries):
    if not market_open_now():
        sys.exit("REJECTED: outside NSE market hours (config_in/config.json market_hours_ist)")
    if args.underlying not in CONFIG["allowed_underlyings"]:
        sys.exit(f"REJECTED: underlying {args.underlying!r} not in {CONFIG['allowed_underlyings']}")
    if args.option_type not in CONFIG["allowed_option_types"]:
        sys.exit(f"REJECTED: option_type {args.option_type!r} not in {CONFIG['allowed_option_types']}")

    today = dt.date.today()
    try:
        expiry_date = dt.date.fromisoformat(args.expiry)
    except ValueError:
        sys.exit("REJECTED: --expiry must be YYYY-MM-DD")
    dte = (expiry_date - today).days
    if not CONFIG["min_days_to_expiry"] <= dte <= CONFIG["max_days_to_expiry"]:
        sys.exit(f"REJECTED: {dte} days to expiry outside "
                 f"[{CONFIG['min_days_to_expiry']}, {CONFIG['max_days_to_expiry']}]")

    open_pos = [e for e in entries if e["status"] == "open"]
    if len(open_pos) >= CONFIG["max_open_positions"]:
        sys.exit(f"REJECTED: max_open_positions ({CONFIG['max_open_positions']}) reached")
    today_str = now_iso()[:10]
    placed_today = sum(1 for e in entries if e["ts"][:10] == today_str)
    if placed_today >= CONFIG["max_new_positions_per_cycle"]:
        sys.exit(f"REJECTED: max_new_positions_per_cycle "
                 f"({CONFIG['max_new_positions_per_cycle']}) reached for today")
    if not 0.0 < args.est_prob_itm < 1.0:
        sys.exit("REJECTED: --est-prob-itm must be in (0,1)")

    lot_size = CONFIG["lot_sizes"].get(args.underlying)
    if not lot_size:
        sys.exit(f"REJECTED: no lot_size configured for {args.underlying}")

    q = quotes.get_quote(args.underlying, args.expiry, args.strike, args.option_type)
    if q["ask"] is None:
        sys.exit("REJECTED: no ask available (cannot fill honestly)")
    premium_paid = round(q["ask"] * lot_size * args.lots, 2)
    if premium_paid > CONFIG["max_premium_per_trade_inr"]:
        sys.exit(f"REJECTED: premium {premium_paid} exceeds "
                 f"max_premium_per_trade_inr {CONFIG['max_premium_per_trade_inr']}")
    if premium_paid > capital_state(entries):
        sys.exit("REJECTED: insufficient sim capital")
    same_underlying_capital = sum(
        e["premium_paid_inr"] for e in open_pos if e["underlying"] == args.underlying)
    if same_underlying_capital + premium_paid > CONFIG["max_capital_per_underlying_inr"]:
        sys.exit(f"REJECTED: max_capital_per_underlying_inr "
                 f"({CONFIG['max_capital_per_underlying_inr']}) exceeded for {args.underlying}")

    entry = {
        "id": uuid.uuid4().hex[:12], "ts": now_iso(),
        "underlying": args.underlying, "expiry": args.expiry, "strike": args.strike,
        "option_type": args.option_type, "lot_size": lot_size, "lots": args.lots,
        "entry_price": q["ask"], "best_bid_at_entry": q["bid"],
        "est_prob_itm": args.est_prob_itm,
        "premium_paid_inr": premium_paid,
        "category": args.category, "edge_class": args.edge_class,
        "rationale": args.rationale, "strategy_rev": args.strategy_rev,
        "status": "open",
    }
    append(entry)
    print(json.dumps({"placed": entry["id"], "filled_at": q["ask"],
                      "premium_paid_inr": premium_paid}, indent=2))


def cmd_close(args, entries):
    match = next((e for e in entries if e["id"] == args.id and e["status"] == "open"), None)
    if not match:
        sys.exit(f"REJECTED: no open position with id {args.id}")
    q = quotes.get_quote(match["underlying"], match["expiry"], match["strike"],
                        match["option_type"])
    if q["bid"] is None:
        sys.exit("REJECTED: no bid available (cannot close honestly)")
    exit_value = round(q["bid"] * match["lot_size"] * match["lots"], 2)
    closed = {**match, "status": "closed", "exit_price": q["bid"],
              "exit_value_inr": exit_value,
              "pnl_inr": round(exit_value - match["premium_paid_inr"], 2),
              "settled_ts": now_iso()}
    append(closed)
    print(json.dumps({"closed": closed["id"], "pnl_inr": closed["pnl_inr"]}, indent=2))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("place")
    p.add_argument("--underlying", required=True)
    p.add_argument("--expiry", required=True, help="YYYY-MM-DD")
    p.add_argument("--strike", type=float, required=True)
    p.add_argument("--option-type", required=True, choices=["CE", "PE"])
    p.add_argument("--lots", type=int, default=1)
    p.add_argument("--est-prob-itm", type=float, required=True,
                   help="your honest probability this finishes in the money by expiry")
    p.add_argument("--category", required=True)
    p.add_argument("--edge-class", required=True,
                   choices=["momentum", "mean-reversion", "event-driven", "other"])
    p.add_argument("--rationale", required=True)
    p.add_argument("--strategy-rev", default="")
    c = sub.add_parser("close")
    c.add_argument("--id", required=True)
    sub.add_parser("status")
    args = ap.parse_args()

    entries = read_ledger()
    if args.cmd == "status":
        cmd_status(entries)
    elif args.cmd == "place":
        cmd_place(args, entries)
    elif args.cmd == "close":
        cmd_close(args, entries)


if __name__ == "__main__":
    main()
