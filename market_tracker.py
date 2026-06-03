import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

API_KEY       = os.environ["FINNHUB_API_KEY"]
DATABASE_URL  = os.environ.get("DATABASE_URL")  # set by Railway; absent = use SQLite
DB_FILE       = "market_data.db"
POLL_INTERVAL = 5  # seconds

# Finnhub free tier does not support CFD index quotes (^GSPC, ^IXIC).
# ETF proxies are used instead. Gold spot requires a paid forex plan; GLD ETF is used.
SYMBOLS = {
    "SPY":             "S&P 500 (via SPY ETF)",
    "QQQ":             "NASDAQ-100 (via QQQ ETF)",
    "GLD":             "Gold (via GLD ETF)",
    "BINANCE:BTCUSDT": "Bitcoin (USD)",
}

# ── database helpers ──────────────────────────────────────────────────────────

def connect():
    """Return (conn, placeholder) for whichever DB backend is available."""
    if DATABASE_URL:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        return conn, "%s"          # psycopg2 uses %s placeholders
    conn = sqlite3.connect(DB_FILE)
    return conn, "?"               # sqlite3 uses ? placeholders

def init_db(conn, ph):
    conn.cursor().execute(f"""
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

def store_quotes(conn, ph, queried_at, results):
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
    sql = (
        f"INSERT INTO quotes "
        f"(queried_at, symbol, price, change, change_pct, high, low, open, prev_close, trade_ts) "
        f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})"
    )
    cur = conn.cursor()
    cur.executemany(sql, rows)
    conn.commit()

# ── Finnhub ───────────────────────────────────────────────────────────────────

def fetch_quote(symbol):
    response = requests.get(
        "https://finnhub.io/api/v1/quote",
        params={"symbol": symbol, "token": API_KEY},
        timeout=10,
    )
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

def poll_once(conn, ph):
    queried_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results, errors = {}, {}

    with ThreadPoolExecutor(max_workers=len(SYMBOLS)) as pool:
        futures = {pool.submit(fetch_quote, sym): sym for sym in SYMBOLS}
        for future in as_completed(futures):
            sym = futures[future]
            try:
                symbol, data = future.result()
                results[symbol] = data
            except Exception as e:
                errors[sym] = str(e)

    if results:
        store_quotes(conn, ph, queried_at, results)
    print_quotes(queried_at, results)
    for sym, err in errors.items():
        print(f"  Error fetching {sym}: {err}")

# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    conn, ph = connect()
    init_db(conn, ph)

    backend = f"PostgreSQL ({DATABASE_URL.split('@')[-1]})" if DATABASE_URL else f"SQLite ({DB_FILE})"
    print(f"Backend : {backend}")
    print("Press Ctrl-C to stop.")

    try:
        while True:
            start = time.monotonic()
            poll_once(conn, ph)
            elapsed = time.monotonic() - start
            time.sleep(max(0, POLL_INTERVAL - elapsed))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        conn.close()
