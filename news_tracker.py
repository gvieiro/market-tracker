import json
import os
import time
from datetime import datetime, timezone

import psycopg2
from google.cloud import bigquery
from google.oauth2 import service_account

DATABASE_URL  = os.environ["DATABASE_URL"]
GCP_CREDS     = os.environ["GCP_CREDENTIALS"]  # service account JSON as a string (for Railway)
POLL_INTERVAL = 900  # 15 minutes in seconds

# ── BigQuery ──────────────────────────────────────────────────────────────────

def bq_client():
    creds_info = json.loads(GCP_CREDS)
    credentials = service_account.Credentials.from_service_account_info(creds_info)
    return bigquery.Client(project=creds_info["project_id"], credentials=credentials)

def fetch_headlines(client, window_minutes=15):
    """Fetch all English-language articles from the last window_minutes from GDELT."""
    query = f"""
        SELECT
            DATE,
            SourceCommonName,
            Themes,
            V2Tone,
            Persons,
            Organizations
        FROM `gdelt-bq.gdeltv2.gkg_partitioned`
        WHERE _PARTITIONTIME >= TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), DAY)
          AND DATE >= CAST(FORMAT_TIMESTAMP('%Y%m%d%H%M%S',
                TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {window_minutes} MINUTE)
              ) AS INT64)
          AND SourceCollectionIdentifier = 1
        ORDER BY DATE DESC
    """
    return list(client.query(query).result())

# ── PostgreSQL ────────────────────────────────────────────────────────────────

def connect():
    return psycopg2.connect(DATABASE_URL)

def init_db(conn):
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS headlines (
            id              SERIAL PRIMARY KEY,
            fetched_at      TEXT    NOT NULL,
            gdelt_date      BIGINT,
            source          TEXT,
            themes          TEXT,
            tone            REAL,
            positive_tone   REAL,
            negative_tone   REAL,
            polarity        REAL,
            word_count      INTEGER,
            persons         TEXT,
            organizations   TEXT
        )
    """)
    conn.cursor().execute(
        "CREATE INDEX IF NOT EXISTS idx_headlines_fetched ON headlines (fetched_at)"
    )
    conn.cursor().execute(
        "CREATE INDEX IF NOT EXISTS idx_headlines_date ON headlines (gdelt_date)"
    )
    conn.commit()

def parse_tone(v2tone):
    """Parse V2Tone comma-separated string into individual components."""
    if not v2tone:
        return None, None, None, None, None
    try:
        parts = [float(x) for x in v2tone.split(",")]
        tone       = parts[0] if len(parts) > 0 else None
        pos_tone   = parts[1] if len(parts) > 1 else None
        neg_tone   = parts[2] if len(parts) > 2 else None
        polarity   = parts[3] if len(parts) > 3 else None
        word_count = int(parts[6]) if len(parts) > 6 else None
        return tone, pos_tone, neg_tone, polarity, word_count
    except (ValueError, IndexError):
        return None, None, None, None, None

def store_headlines(conn, fetched_at, rows):
    data = []
    for r in rows:
        tone, pos_tone, neg_tone, polarity, word_count = parse_tone(r.V2Tone)
        data.append((
            fetched_at,
            r.DATE,
            r.SourceCommonName,
            r.Themes,
            tone,
            pos_tone,
            neg_tone,
            polarity,
            word_count,
            r.Persons,
            r.Organizations,
        ))
    conn.cursor().executemany(
        "INSERT INTO headlines "
        "(fetched_at, gdelt_date, source, themes, tone, positive_tone, negative_tone, "
        " polarity, word_count, persons, organizations) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        data,
    )
    conn.commit()

# ── poll loop ─────────────────────────────────────────────────────────────────

def poll_once(bq, conn):
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"\n── {fetched_at} ──────────────────────────────")

    try:
        rows = fetch_headlines(bq)
        store_headlines(conn, fetched_at, rows)

        tones = [parse_tone(r.V2Tone)[0] for r in rows if r.V2Tone]
        tones = [t for t in tones if t is not None]
        avg_tone = sum(tones) / len(tones) if tones else 0

        print(f"  Articles fetched : {len(rows):,}")
        print(f"  Avg tone         : {avg_tone:+.3f}")
    except Exception as e:
        print(f"  Error: {e}")

# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    conn = connect()
    init_db(conn)
    bq = bq_client()

    print(f"Backend      : PostgreSQL ({DATABASE_URL.split('@')[-1]})")
    print(f"Poll interval: {POLL_INTERVAL // 60} minutes")
    print("Press Ctrl-C to stop.")

    try:
        while True:
            start = time.monotonic()
            poll_once(bq, conn)
            elapsed = time.monotonic() - start
            time.sleep(max(0, POLL_INTERVAL - elapsed))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        conn.close()
