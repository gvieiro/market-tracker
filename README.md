# Market Tracker

Continuously polls [Finnhub](https://finnhub.io) for real-time market quotes every 15 seconds and stores the results in a PostgreSQL database. Designed to run unattended on [Railway](https://railway.app).

## Tracked symbols

| Symbol | Represents |
|--------|------------|
| SPY | S&P 500 (via SPDR S&P 500 ETF) |
| QQQ | NASDAQ-100 (via Invesco QQQ ETF) |
| GLD | Gold (via SPDR Gold Trust ETF) |
| BINANCE:BTCUSDT | Bitcoin (USD) |

> **Note:** Finnhub's free tier does not support direct index quotes for ^GSPC or ^IXIC, so ETF proxies are used for the S&P 500, NASDAQ-100, and Gold. Bitcoin is queried directly from Binance via Finnhub's crypto endpoint.

## Requirements

- Python 3.8+
- A free [Finnhub](https://finnhub.io) account and API key
- A PostgreSQL database (provided automatically by Railway)

## Deploying to Railway

1. Push this repo to GitHub.
2. Create a new project on [Railway](https://railway.app) and connect your GitHub repo.
3. Add a **PostgreSQL** service to the project. Railway will automatically inject a `DATABASE_URL` environment variable into your app — no manual configuration needed.
4. Add `FINNHUB_API_KEY` as an environment variable in the Railway dashboard under **Variables**.
5. Set the start command to `python market_tracker.py`.
6. Railway will install dependencies from `requirements.txt` and start the script automatically.

Data persists across redeploys and restarts.

## Database schema

```sql
CREATE TABLE quotes (
    id          SERIAL PRIMARY KEY,
    queried_at  TEXT    NOT NULL,  -- UTC timestamp (ISO 8601)
    symbol      TEXT    NOT NULL,
    price       REAL,              -- current / last traded price
    change      REAL,              -- change from previous close
    change_pct  REAL,              -- change % from previous close
    high        REAL,              -- day high
    low         REAL,              -- day low
    open        REAL,              -- day open
    prev_close  REAL,              -- previous close
    trade_ts    INTEGER            -- Unix timestamp of last trade
);
```

## License

MIT
