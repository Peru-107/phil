#!/usr/bin/env python3
"""Scoring & calibration report for the India options paper track.

Mirrors core/score.py's shape: overall P&L/ROI/win-rate, sliced by
category/edge_class/strategy_rev, plus a calibration check. The brier
comparison is narrower here than the Polymarket engine's: it only applies
to positions that ran to expiry (expired_itm/expired_otm), since an early
`close` never gives you a ground-truth "did it finish ITM" answer to score
est_prob_itm against. Early closes still count fully in win-rate/P&L.

Usage: python3 core_in/score.py [--json]
"""
import argparse
import json
import pathlib
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ledger  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETTLED_STATUSES = {"closed", "expired_itm", "expired_otm"}
EXPIRY_STATUSES = {"expired_itm", "expired_otm"}


def pnl_stats(rows):
    n = len(rows)
    wins = sum(1 for r in rows if r["pnl_inr"] > 0)
    pnl = sum(r["pnl_inr"] for r in rows)
    staked = sum(r["premium_paid_inr"] for r in rows)
    out = {"n": n, "wins": wins, "win_rate": round(wins / n, 3),
           "pnl_inr": round(pnl, 2), "roi": round(pnl / staked, 3) if staked else 0}
    expiry_rows = [r for r in rows if r["status"] in EXPIRY_STATUSES]
    if expiry_rows:
        m = len(expiry_rows)
        itm = sum(1 for r in expiry_rows if r["status"] == "expired_itm")
        brier = sum((r["est_prob_itm"] - (1 if r["status"] == "expired_itm" else 0)) ** 2
                    for r in expiry_rows) / m
        out["expiry_settled_n"] = m
        out["itm_rate"] = round(itm / m, 3)
        out["brier"] = round(brier, 4)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    entries = ledger.read_ledger()
    settled = [e for e in entries if e["status"] in SETTLED_STATUSES]
    open_pos = [e for e in entries if e["status"] == "open"]
    if not settled:
        print(json.dumps({"settled": 0, "open": len(open_pos)}))
        return

    report = {"overall": pnl_stats(settled), "open": len(open_pos),
              "by_category": {}, "by_edge_class": {}, "by_strategy_rev": {},
              "calibration": []}
    by_cat, by_class, by_rev = defaultdict(list), defaultdict(list), defaultdict(list)
    for e in settled:
        by_cat[e["category"]].append(e)
        by_class[e.get("edge_class", "unclassified")].append(e)
        by_rev[e.get("strategy_rev") or "unknown"].append(e)
    for cat, rows in sorted(by_cat.items()):
        report["by_category"][cat] = pnl_stats(rows)
    for cls, rows in sorted(by_class.items()):
        report["by_edge_class"][cls] = pnl_stats(rows)
    for rev, rows in sorted(by_rev.items()):
        report["by_strategy_rev"][rev] = pnl_stats(rows)

    buckets = defaultdict(list)
    for e in settled:
        if e["status"] in EXPIRY_STATUSES:
            buckets[min(int(e["est_prob_itm"] * 10), 9)].append(e)
    for b in sorted(buckets):
        rows = buckets[b]
        report["calibration"].append({
            "est_range": f"{b/10:.1f}-{(b+1)/10:.1f}", "n": len(rows),
            "realized_itm": round(
                sum(1 for r in rows if r["status"] == "expired_itm") / len(rows), 3),
        })

    if args.json:
        print(json.dumps(report, indent=2))
        return
    o = report["overall"]
    print(f"settled={o['n']} win_rate={o['win_rate']} pnl=₹{o['pnl_inr']} roi={o['roi']}")
    if "brier" in o:
        print(f"expiry-settled: n={o['expiry_settled_n']} itm_rate={o['itm_rate']} brier={o['brier']}")
    print("\nby category:")
    for cat, s in report["by_category"].items():
        print(f"  {cat:16} n={s['n']:3} win={s['win_rate']:.2f} pnl=₹{s['pnl_inr']:+9.2f}")
    print("\nby edge class:")
    for cls, s in report["by_edge_class"].items():
        print(f"  {cls:16} n={s['n']:3} win={s['win_rate']:.2f} pnl=₹{s['pnl_inr']:+9.2f}")
    print("\ncalibration (expiry-settled, est_prob_itm vs realized):")
    for c in report["calibration"]:
        print(f"  {c['est_range']}: n={c['n']:3} realized_itm={c['realized_itm']:.2f}")


if __name__ == "__main__":
    main()
