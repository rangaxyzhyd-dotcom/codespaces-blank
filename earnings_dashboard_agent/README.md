# EarningsDashboardAgent

Python 3.11+ earnings research dashboard for NSE/BSE equities. It collects public OHLCV and announcement data, calculates indicators, records raw pulls in SQLite, and renders source-attributed snapshots. Missing estimates, results, guidance, or historical surprises are displayed as `N/A`; the app never fills gaps with invented values.

Scenario categories are screening rules in `config/scenarios.yaml`, not return predictions. LLM output is an evidence-constrained summary, not a financial recommendation or guarantee.

## GitHub Codespaces

1. Open this repository in a Codespace. The dev container installs `requirements.txt` and forwards port 8000.
2. Set `GROQ_API_KEY` (default hosted LLM), and optionally `FINNHUB_API_KEY` and SMTP credentials, as Codespaces secrets or environment variables. Copy `.env.example` to `.env` only for local use; `.env` is ignored by git.
3. Replace the 46 `REPLACE_XX` rows in `config/watchlist.csv` with your remaining companies. The eight specified Priority A names are preconfigured. Columns are `symbol,company,exchange,priority`.
4. Start the server from this directory:

	```bash
	uvicorn dashboard.app:app --host 0.0.0.0 --port 8000
	```

5. Open the forwarded port 8000. The API schema is available at `/docs`; `/api/export.xlsx` downloads one row per configured company.

Without API keys the dashboard still runs. LLM views and optional consensus fields stay `N/A` with the missing provider recorded. Use Codespaces Secrets for credentials on hosted workspaces; never commit secrets.

## Local Run

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
uvicorn dashboard.app:app --host 0.0.0.0 --port 8000
```

The dashboard binds to all interfaces for Codespaces port forwarding. The SQLite database is created at `data/earnings.db` by default; override it with `DATA_DB_PATH`.

## Sources and refresh behavior

- Yahoo Finance via `yfinance`: daily OHLCV, 5-minute intraday bars for session VWAP, and available quarterly income statements.
- NSE/BSE public corporate-announcement endpoints and Yahoo Finance RSS headlines.
- Optional Finnhub earnings endpoint: EPS estimates only. Revenue, EBITDA, PAT consensus, bank-specific values, guidance, or four-quarter history are not inferred when providers do not supply them.
- Groq hosted model is the default LLM provider; Gemini and OpenRouter are selectable, with Ollama as an optional local endpoint. Set `LLM_PROVIDER` and the matching environment key.

Each external payload or provider error is written to SQLite `raw_pulls` with symbol, source, UTC pull timestamp, and payload. Cached requests retain the same provenance; default TTLs are 15 minutes for prices/announcements, 6 hours for EPS, and 24 hours for financial statements and generated views. Rate limiting is global per process. External endpoints can block automated clients, change response formats, or be delayed; errors are logged and surfaced, not silently replaced. No Moneycontrol, Screener, or Trendlyne scraping is enabled because site terms and permissions must be checked before use.

The scheduler polls on weekdays every 15 minutes during 09:15–15:30 Asia/Kolkata and sends a weekday digest at `DIGEST_HOUR_IST` / `DIGEST_MINUTE_IST`. Results announcements detected in the preceding 24 hours trigger alerts when SMTP is configured. Browser data refreshes every 60 seconds; actual source updates follow the scheduler and provider availability. Post-results returns populate only after required daily bars are available.

Technical indicators use daily OHLCV for relative volume, RSI(14), and ADX(14); session VWAP uses available 5-minute intraday bars. Yahoo Finance coverage and units vary by company. Returned statement amounts are shown in source units, not normalized across issuers.

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests mock outbound providers and do not require market-network access or API credentials.