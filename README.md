# Gold Signal App — Backend Core

A weighted signal engine for gold trading that combines **technical price data**,
**macro/fundamental data**, and **news sentiment** into a single composite score,
served over a small FastAPI backend. This is designed to be the "brain" behind
a future mobile app with push alerts.

## Architecture

```
data_sources/
  gold_price.py   -> live/historical gold price + technical indicators (RSI, MAs)
  macro.py         -> real yields, DXY, CPI via FRED (Federal Reserve data)
  news.py           -> headline pull + LLM-based event scoring (bullish/bearish/conviction)

app/
  scoring.py        -> combines technical + macro + news into one weighted score
  main.py            -> FastAPI app exposing /signal endpoint + scheduler stub

config.py            -> API keys and weights (edit this first)
requirements.txt
```

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Get free API keys (all have generous free tiers):
   - **FRED** (macro data): https://fred.stlouisfed.org/docs/api/api_key.html
   - **NewsAPI** (headlines): https://newsapi.org/register
   - **GoldAPI** (spot price): https://www.goldapi.io/
   - **Anthropic API** (news scoring): https://console.anthropic.com/

3. Copy `config.example.py` to `config.py` and fill in your keys.

4. Run the server:
   ```bash
   uvicorn app.main:app --reload
   ```

  Or with the production entrypoint:
  ```bash
  python run_app.py
  ```

5. Hit the signal endpoint:
   ```bash
   curl http://localhost:8000/signal
   ```

   You'll get back something like:
   ```json
   {
     "composite_score": 68.4,
     "direction": "bullish",
     "conviction": "medium",
     "technical_score": 55.0,
     "macro_score": 72.0,
     "news_score": 78.0,
     "top_events": [
       {"headline": "...", "impact": "bullish", "conviction": "high"}
     ]
   }
   ```

## Next steps (not built yet)

- **Scheduler**: wire up APScheduler or a cron job to call `/signal` every 15-30 min
  and push a notification (Firebase Cloud Messaging) when the score crosses a threshold
- **Mobile app**: React Native or Flutter shell that displays the score and receives pushes
- **Backtesting**: before trusting any weighting scheme with real money, run it against
  historical price + news data to see how it would have performed

## Important note

This tool structures information — it does not predict the market. Weights in
`config.py` are a starting point; you should tune and backtest them yourself.
Nothing here is financial advice.

## Deploy Across Servers

Use environment variables for all server deployments so each environment can use its own secrets.

1. Create a runtime env file from `.env.example`:
  ```bash
  cp .env.example .env
  ```

2. Fill `.env` with your production keys and settings.

3. Start the app:
  ```bash
  python run_app.py
  ```

4. Put Nginx in front using `deploy/nginx.conf` (adjust `server_name`).

5. For Linux auto-restart, install `deploy/gold-signal.service`:
  ```bash
  sudo cp deploy/gold-signal.service /etc/systemd/system/gold-signal.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now gold-signal
  ```

6. Validate on each server:
  ```bash
  curl http://127.0.0.1:8001/signal?metal=gold
  curl http://127.0.0.1:8001/manifest.webmanifest
  ```

### One-Command Ubuntu Deploy

From the project root on your Ubuntu server, run:

```bash
bash deploy/setup_ubuntu.sh your-domain.example.com
```

This installs dependencies, configures systemd and Nginx, requests TLS, and runs basic health checks.

### Environment Variable Notes

- These env vars are supported directly by the app: `GOLD_API_KEY`, `FRED_API_KEY`, `NEWS_API_KEY`, `ANTHROPIC_API_KEY`, `NEWS_LOOKBACK_HOURS`, `MAX_HEADLINES_TO_SCORE`.
- `WEIGHTS` supports JSON (for example `{"technical":0.35,"macro":0.30,"news":0.35}`).
- `NEWS_KEYWORDS` supports either JSON array or comma-separated values.
- Environment variables override values from `config.py`.
