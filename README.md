# Market Tracker

Continuously polls [Finnhub](https://finnhub.io) for real-time market quotes every 5 seconds using parallel API calls, and stores the results in a database. Designed to run unattended on a cloud hosting platform such as [Railway](https://railway.app).

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

## Local setup

1. Clone the repo:
   ```bash
   git clone https://github.com/your-username/market-tracker.git
   cd market-tracker
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Set your Finnhub API key as an environment variable:
   ```bash
   export FINNHUB_API_KEY=your_api_key_here
   ```

4. Run the tracker:
   ```bash
   python3 market_tracker.py
   ```

Press **Ctrl-C** to stop.

### Local database

When running locally without a `DATABASE_URL` environment variable, quotes are stored in a SQLite file (`market_data.db`) in the project directory.

## Deploying to Railway

1. Push this repo to GitHub.
2. Create a new project on [Railway](https://railway.app) and connect your GitHub repo.
3. Add a **PostgreSQL** service to the project. Railway will automatically inject a `DATABASE_URL` environment variable into your app — no manual configuration needed.
4. Add `FINNHUB_API_KEY` as an environment variable in the Railway dashboard under **Variables**.
5. Railway will install dependencies from `requirements.txt` and start the script automatically.

The app detects `DATABASE_URL` at startup and switches to PostgreSQL automatically. Data persists across redeploys and restarts.

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
