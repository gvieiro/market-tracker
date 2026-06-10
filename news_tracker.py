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

def fetch_tone_summary(client, window_minutes=15):
    """Aggregate tone across all English-language articles in the last window_minutes."""
    query = f"""
        WITH parsed AS (
            SELECT
                CAST(SPLIT(V2Tone, ',')[OFFSET(0)] AS FLOAT64) AS tone,
                CAST(SPLIT(V2Tone, ',')[OFFSET(1)] AS FLOAT64) AS positive_tone,
                CAST(SPLIT(V2Tone, ',')[OFFSET(2)] AS FLOAT64) AS negative_tone,
                CAST(SPLIT(V2Tone, ',')[OFFSET(3)] AS FLOAT64) AS polarity
            FROM `gdelt-bq.gdeltv2.gkg_partitioned`
            WHERE _PARTITIONTIME >= TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), DAY)
              AND DATE >= CAST(FORMAT_TIMESTAMP('%Y%m%d%H%M%S',
                    TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {window_minutes} MINUTE)
                  ) AS INT64)
              AND SourceCollectionIdentifier = 1
              AND V2Tone IS NOT NULL
              AND ARRAY_LENGTH(SPLIT(V2Tone, ',')) >= 4
        )
        SELECT
            COUNT(*)        AS article_count,
            AVG(tone)       AS avg_tone,
            AVG(positive_tone) AS avg_positive_tone,
            AVG(negative_tone) AS avg_negative_tone,
            AVG(polarity)   AS avg_polarity
        FROM parsed
    """
    rows = list(client.query(query).result())
    return rows[0] if rows else None

# ── PostgreSQL ────────────────────────────────────────────────────────────────

def connect():
    return psycopg2.connect(DATABASE_URL)

def init_db(conn):
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS news_sentiment (
            id                  SERIAL PRIMARY KEY,
            fetched_at          TEXT    NOT NULL UNIQUE,
            article_count       INTEGER,
            avg_tone            REAL,
            avg_positive_tone   REAL,
            avg_negative_tone   REAL,
            avg_polarity        REAL
        )
    """)
    conn.cursor().execute(
        "CREATE INDEX IF NOT EXISTS idx_sentiment_fetched ON news_sentiment (fetched_at)"
    )
    conn.commit()

def store_sentiment(conn, fetched_at, summary):
    conn.cursor().execute(
        "INSERT INTO news_sentiment "
        "(fetched_at, article_count, avg_tone, avg_positive_tone, avg_negative_tone, avg_polarity) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (
            fetched_at,
            summary.article_count,
            summary.avg_tone,
            summary.avg_positive_tone,
            summary.avg_negative_tone,
            summary.avg_polarity,
        )
    )
    conn.commit()

# ── poll loop ─────────────────────────────────────────────────────────────────

def poll_once(bq, conn):
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"\n── {fetched_at} ──────────────────────────────")

    try:
        summary = fetch_tone_summary(bq)
        if summary and summary.article_count:
            store_sentiment(conn, fetched_at, summary)
            print(f"  Articles        : {summary.article_count:,}")
            print(f"  Avg tone        : {summary.avg_tone:+.3f}")
            print(f"  Avg positive    : {summary.avg_positive_tone:+.3f}")
            print(f"  Avg negative    : {summary.avg_negative_tone:+.3f}")
            print(f"  Avg polarity    : {summary.avg_polarity:+.3f}")
        else:
            print("  No articles found in window.")
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
