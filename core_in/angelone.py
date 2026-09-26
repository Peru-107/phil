#!/usr/bin/env python3
"""Angel One SmartAPI client for the India paper-trading track.

UNTESTED AGAINST THE LIVE API — written from SmartAPI's public documentation
(https://smartapi.angelbroking.com/docs) without a credentialed account to
verify against. Before relying on this for even paper-mode live quotes,
run `python3 core_in/angelone.py doctor` and fix whatever the docs have
since moved.

Auth flow (SmartAPI "Login by password + TOTP"):
  1. POST /rest/auth/angelbroking/user/v1/loginByPassword
     body: {"clientcode", "password", "totp"}
     headers: the X-* headers below, no Authorization yet
     -> {"data": {"jwtToken", "refreshToken", "feedToken"}}
  2. Every subsequent call sends Authorization: Bearer <jwtToken> plus the
     same X-* headers and X-PrivateKey: <api key>.

Required env vars:
  ANGELONE_API_KEY        API key from the SmartAPI app you register
  ANGELONE_CLIENT_CODE    your Angel One client code (login id)
  ANGELONE_PASSWORD       your account PIN/password
  ANGELONE_TOTP_SECRET    the base32 TOTP secret shown when you enable
                          2FA for API access (needs the `pyotp` package)

This file NEVER places a real order unless config_in/config.json has
real_trading_enabled: true — same discipline as core/real.py, just
enforced here instead of by a separate protected file, because this
tree has no CI boundary guard yet (see README_IN.md).
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config_in" / "config.json"
BASE = "https://apiconnect.angelbroking.com"
SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/"
    "OpenAPIScripMaster.json"
)
CACHE = ROOT / "journal_in" / ".scrip_master_cache.json"


def _headers(api_key, jwt=None):
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": "127.0.0.1",
        "X-ClientPublicIP": "127.0.0.1",
        "X-MACAddress": "00:00:00:00:00:00",
        "X-PrivateKey": api_key,
    }
    if jwt:
        h["Authorization"] = f"Bearer {jwt}"
    return h


def _post(path, api_key, jwt, body, timeout=15):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers=_headers(api_key, jwt), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def login():
    """Returns (api_key, jwt_token). Raises SystemExit with a clear message
    on any missing env var or auth failure — never silently falls back."""
    try:
        import pyotp
    except ImportError:
        sys.exit("angelone: `pip install pyotp` first (TOTP generation)")
    api_key = os.environ.get("ANGELONE_API_KEY")
    client_code = os.environ.get("ANGELONE_CLIENT_CODE")
    password = os.environ.get("ANGELONE_PASSWORD")
    totp_secret = os.environ.get("ANGELONE_TOTP_SECRET")
    missing = [n for n, v in [
        ("ANGELONE_API_KEY", api_key), ("ANGELONE_CLIENT_CODE", client_code),
        ("ANGELONE_PASSWORD", password), ("ANGELONE_TOTP_SECRET", totp_secret),
    ] if not v]
    if missing:
        sys.exit(f"angelone: missing env vars {missing}")
    totp = pyotp.TOTP(totp_secret).now()
    resp = _post("/rest/auth/angelbroking/user/v1/loginByPassword", api_key, None,
                 {"clientcode": client_code, "password": password, "totp": totp})
    if not resp.get("status"):
        sys.exit(f"angelone: login failed — {resp.get('message', resp)}")
    return api_key, resp["data"]["jwtToken"]


def scrip_master():
    """Cached instrument master (token/symbol/expiry/strike lookup).
    Refreshed once a day — it is tens of MB and Angel One publishes it once
    per trading day."""
    today = dt.date.today().isoformat()
    if CACHE.exists():
        try:
            meta = json.loads(CACHE.with_suffix(".meta.json").read_text())
            if meta.get("date") == today:
                return json.loads(CACHE.read_text())
        except FileNotFoundError:
            pass
    with urllib.request.urlopen(SCRIP_MASTER_URL, timeout=60) as r:
        data = json.loads(r.read())
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(data))
    CACHE.with_suffix(".meta.json").write_text(json.dumps({"date": today}))
    return data


def find_token(underlying, expiry, strike, option_type):
    """expiry as YYYY-MM-DD; returns (symboltoken, tradingsymbol) or None."""
    exp_fmt = dt.date.fromisoformat(expiry).strftime("%d%b%y").upper()
    want_strike = f"{int(strike * 100):08d}"  # scrip master strikes are paise, zero-padded
    for row in scrip_master():
        if row.get("exch_seg") != "NFO":
            continue
        sym = row.get("symbol", "")
        if not sym.startswith(underlying):
            continue
        if row.get("expiry") != exp_fmt:
            continue
        if row.get("strike") != want_strike:
            continue
        if not sym.endswith(option_type):
            continue
        return row["token"], sym
    return None


class AngelOneQuoteSource:
    def __init__(self):
        self.api_key, self.jwt = login()

    def get_quote(self, underlying, expiry, strike, option_type):
        found = find_token(underlying, expiry, strike, option_type)
        if not found:
            raise RuntimeError(
                f"no instrument found for {underlying} {expiry} {strike}{option_type} "
                f"— check the expiry/strike against the exchange contract list")
        token, tsym = found
        resp = _post("/rest/secure/angelbroking/market/v1/quote", self.api_key, self.jwt,
                     {"mode": "FULL", "exchangeTokens": {"NFO": [token]}})
        if not resp.get("status"):
            raise RuntimeError(f"quote failed: {resp.get('message', resp)}")
        rows = resp["data"]["fetched"]
        if not rows:
            raise RuntimeError(f"no quote data returned for {tsym}")
        row = rows[0]
        depth = row.get("depth", {})
        buys = depth.get("buy", [])
        sells = depth.get("sell", [])
        return {
            "ltp": row.get("ltp"),
            "bid": buys[0]["price"] if buys else None,
            "ask": sells[0]["price"] if sells else None,
            "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def underlying_ltp(self, underlying):
        """VERIFY the index token before trusting this — the scrip master's
        index rows are matched by name substring here, not a hardcoded
        token, but that match has never been run against a live account."""
        name = "NIFTY 50" if underlying == "NIFTY" else "NIFTY BANK"
        for row in scrip_master():
            if row.get("exch_seg") == "NSE" and row.get("name") == name:
                resp = _post("/rest/secure/angelbroking/market/v1/quote",
                             self.api_key, self.jwt,
                             {"mode": "LTP", "exchangeTokens": {"NSE": [row["token"]]}})
                if resp.get("status") and resp["data"]["fetched"]:
                    return resp["data"]["fetched"][0]["ltp"]
        raise RuntimeError(f"could not resolve an index token for {underlying}")


def place_real_order(tradingsymbol, symboltoken, transaction_type, qty, exchange="NFO"):
    """Places a REAL market order. Gated by config_in/config.json's
    real_trading_enabled — never call this directly from a cycle; go through
    core_in/ledger.py so the paper twin and the caps check happen first."""
    cfg = json.loads(CONFIG_PATH.read_text())
    if cfg.get("real_trading_enabled") is not True:
        sys.exit("angelone: real_trading_enabled is not true in config_in/config.json")
    real = cfg.get("real")
    if not isinstance(real, dict):
        sys.exit("angelone: config_in/config.json has no 'real' caps block")
    api_key, jwt = login()
    body = {
        "variety": "NORMAL", "tradingsymbol": tradingsymbol, "symboltoken": symboltoken,
        "transactiontype": transaction_type, "exchange": exchange,
        "ordertype": "MARKET", "producttype": "INTRADAY", "duration": "DAY",
        "quantity": qty,
    }
    resp = _post("/rest/secure/angelbroking/order/v1/placeOrder", api_key, jwt, body)
    print(json.dumps(resp, indent=2))
    return resp


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    args = ap.parse_args()
    if args.cmd == "doctor":
        api_key, jwt = login()
        print(json.dumps({"ok": True, "logged_in": True}, indent=2))


if __name__ == "__main__":
    main()
