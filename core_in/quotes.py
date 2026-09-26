#!/usr/bin/env python3
"""Quote source abstraction for the India paper-trading track.

Two backends, chosen by config_in/config.json -> data_source:
  mock      deterministic synthetic quotes, no network, no broker account
            needed. Use this to exercise ledger/resolve/score end to end
            before you have Angel One credentials.
  angelone  live quotes via core_in/angelone.py (SmartAPI). Needs
            ANGELONE_API_KEY / ANGELONE_CLIENT_CODE / ANGELONE_PASSWORD /
            ANGELONE_TOTP_SECRET in the environment.

A quote is {"ltp": float, "bid": float|None, "ask": float|None, "ts": iso}.
Positions are opened at "ask" (a buy crosses the spread) the same way
core/ledger.py fills against the live CLOB ask — never at ltp or mid. If a
backend cannot report a real bid/ask (mock always can; angelone depends on
depth being available for the strike), the caller must refuse to fill
rather than invent a price.
"""
import datetime as dt
import hashlib
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config_in" / "config.json").read_text())


def option_symbol(underlying, expiry, strike, option_type):
    """Canonical id for a single option leg, e.g. NIFTY|2026-10-02|24500|CE."""
    return f"{underlying}|{expiry}|{strike}|{option_type}"


class MockQuoteSource:
    """Deterministic pseudo-random walk keyed on symbol + current UTC minute.

    Not a model of option pricing — it exists so the rest of the pipeline
    (fill, ledger, resolve, score) can be built and tested before you have a
    broker account. Do not use its numbers as evidence about any strategy.
    """

    def get_quote(self, underlying, expiry, strike, option_type):
        sym = option_symbol(underlying, expiry, strike, option_type)
        minute_bucket = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M")
        h = hashlib.sha256(f"{sym}|{minute_bucket}".encode()).hexdigest()
        base = 20 + (int(h[:6], 16) % 30000) / 1000  # ~20-50 range, deterministic
        spread = max(0.05, base * 0.01)
        return {
            "ltp": round(base, 2),
            "bid": round(base - spread / 2, 2),
            "ask": round(base + spread / 2, 2),
            "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def underlying_ltp(self, underlying):
        h = hashlib.sha256(underlying.encode()).hexdigest()
        base = 20000 + (int(h[:6], 16) % 5000)
        return float(base)


def get_source():
    src = CONFIG.get("data_source", "mock")
    if src == "mock":
        return MockQuoteSource()
    if src == "angelone":
        import angelone  # local import: only needed when this backend is used
        return angelone.AngelOneQuoteSource()
    raise SystemExit(f"unknown data_source {src!r} in config_in/config.json")


def get_quote(underlying, expiry, strike, option_type):
    return get_source().get_quote(underlying, expiry, strike, option_type)
