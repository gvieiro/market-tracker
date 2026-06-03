import os
import time
from datetime import datetime, timezone

import psycopg2
import requests

API_KEY        = os.environ["FINNHUB_API_KEY"]
DATABASE_URL   = os.environ["DATABASE_URL"]
POLL_INTERVAL  = 15    # seconds between polls
CALL_SPACING   = 1     # seconds between individual API calls within a poll (avoids burst limits)
MAX_BACKOFF    = 120   # seconds — cap on exponential backoff after rate limit errors
BACKOFF_RESET  = 3     # number of consecutive clean polls before backoff resets to POLL_INTERVAL

# Finnhub free tier does not support CFD index quotes (^GSPC, ^IXIC).
# ETF proxies are used instead. Gold spot requires a paid forex plan; GLD ETF is used.
SYMBOLS = {
    "SPY":             "S&P 500 (via SPY ETF)",
    "QQQ":             "NASDAQ-100 (via QQQ ETF)",
    "GLD":             "Gold (via GLD ETF)",
    "BINANCE:BTCUSDT": "Bitcoin (USD)",
}

# ── database ──────────────────────────────────────────────────────────────────

def connect():
    return psycopg2.connect(DATABASE_URL)

def init_db(conn):
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS quotes (
            id          SERIAL PRIMARY KEY,
            queried_at  TEXT    NOT NULL,
            symbol      TEXT    NOT NULL,
            price       REAL,
            change      REAL,
            change_pct  REAL,
            high        REAL,
            low         REAL,
            open        REAL,
            prev_close  REAL,
            trade_ts    INTEGER
        )
    """)
    conn.cursor().execute(
        "CREATE INDEX IF NOT EXISTS idx_symbol_time ON quotes (symbol, queried_at)"
    )
    conn.commit()

def store_quotes(conn, queried_at, results):
    rows = [
        (
            queried_at,
            symbol,
            data.get("c"),
            data.get("d"),
            data.get("dp"),
            data.get("h"),
            data.get("l"),
            data.get("o"),
            data.get("pc"),
            data.get("t"),
        )
        for symbol, data in results.items()
    ]
    conn.cursor().executemany(
        "INSERT INTO quotes "
        "(queried_at, symbol, price, change, change_pct, high, low, open, prev_close, trade_ts) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        rows,
    )
    conn.commit()

# ── Finnhub ───────────────────────────────────────────────────────────────────

class RateLimitError(Exception):
    pass

def fetch_quote(symbol):
    response = requests.get(
        "https://finnhub.io/api/v1/quote",
        params={"symbol": symbol, "token": API_KEY},
        timeout=10,
    )
    if response.status_code == 429:
        raise RateLimitError("429 Too Many Requests")
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return symbol, data

# ── display ───────────────────────────────────────────────────────────────────

def print_quotes(queried_at, results):
    print(f"\n── {queried_at} ──────────────────────────────")
    for symbol, label in SYMBOLS.items():
        data = results.get(symbol)
        if data is None:
            print(f"  {label}: error")
            continue
        price  = data.get("c") or 0
        change = data.get("d") or 0
        pct    = data.get("dp") or 0
        print(f"  {label:<30}  {price:>12,.2f}  {change:>+10,.2f}  ({pct:>+7.2f}%)")

# ── poll loop ─────────────────────────────────────────────────────────────────

def poll_once(conn):
    """Fetch all quotes sequentially and store results. Returns True if rate limited."""
    queried_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results, errors = {}, {}
    rate_limited = False

    for i, symbol in enumerate(SYMBOLS):
        if i > 0:
            time.sleep(CALL_SPACING)
        try:
            sym, data = fetch_quote(symbol)
            results[sym] = data
        except RateLimitError:
            rate_limited = True
        except Exception as e:
            errors[symbol] = str(e)

    if results:
        store_quotes(conn, queried_at, results)
    print_quotes(queried_at, results)
    for sym, err in errors.items():
        print(f"  Error fetching {sym}: {err}")

    return rate_limited

# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    conn = connect()
    init_db(conn)

    print(f"Backend      : PostgreSQL ({DATABASE_URL.split('@')[-1]})")
    print(f"Poll interval: {POLL_INTERVAL}s with {CALL_SPACING}s between calls")
    print("Press Ctrl-C to stop.")

    backoff      = POLL_INTERVAL
    clean_streak = 0
    try:
        while True:
            start = time.monotonic()
            rate_limited = poll_once(conn)
            elapsed = time.monotonic() - start

            if rate_limited:
                clean_streak = 0
                backoff = min(backoff * 2, MAX_BACKOFF)
                print(f"  Rate limited — backing off for {backoff}s")
                time.sleep(backoff)
            else:
                clean_streak += 1
                if clean_streak >= BACKOFF_RESET:
                    backoff = POLL_INTERVAL
                time.sleep(max(0, POLL_INTERVAL - elapsed))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        conn.close()
