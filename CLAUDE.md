# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

**FastAPI backend:**
```bash
# Load env vars then start (OPENAI_API_KEY required for sentiment)
set -a && source .env && set +a
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Telegram bot** (requires environment variables):
```bash
export TELEGRAM_BOT_TOKEN="your-token"
export API_URL="http://127.0.0.1:8000/analyze/"
python tg_bot.py
```

**Manual testing:**
```bash
curl http://localhost:8000/analyze/AAPL
```

There is no requirements.txt, Dockerfile, or Makefile — dependencies (FastAPI, uvicorn, yfinance, pandas, python-telegram-bot) must be installed manually.

## Architecture

This is a multi-factor stock analysis system with three independent scoring pillars feeding a decision engine.

### Data Flow

1. **Single data fetch** — `services/data_service.py:get_stock_data()` fetches yfinance data once per request and returns a shared dict passed to all analysis modules.

2. **Three independent pillars** — each receives the shared data dict and returns `{score, breakdown, summary}`:
   - `services/technical_analysis.py` — RSI, SMA200 trend, 52-week position (score 0–5)
   - `services/fundamental_analysis.py` — revenue growth, EPS, P/E vs sector, debt, margin, FCF (score 0–8)
   - `services/sentiment_analysis.py` — analyst ratings, insider trades, institutional holdings (score 0–5)

3. **Decision synthesis** — `services/decision_engine.py:decide()` applies:
   - **Veto conditions** (hard stops checked first — e.g., negative FCF + declining EPS blocks any buy)
   - **Gate logic** (`GATES` dict, e.g., `STRONG_BUY` requires tech≥4, fund≥6, sent≥3, total≥13)
   - **Flags** — warning signals appended to the output
   - **Confidence** — HIGH/MEDIUM/LOW based on pillar agreement

4. **Output** — `app/main.py` returns JSON with `decision`, `score`, `confidence`, `reason`, `flags`, `pillar_scores`.

### Key Design Principles

- **Fundamentals can veto technicals, but not vice versa** — veto logic runs before gate logic.
- **Scoring contracts** — every analysis module returns a consistent `{score, breakdown}` dict; adding a new pillar means wiring it into `decision_engine.decide()`.
- The decision engine accepts both legacy string sentiment and the new dict structure (backward compatibility).

### Configuration

All configuration is in-code (no config files):
- Gate thresholds: `decision_engine.py` → `GATES` dict
- Veto rules: `decision_engine.py` → `VETO_CONDITIONS`
- Sector P/E benchmarks: `fundamental_analysis.py` → `SECTOR_PE` dict (~25 sectors)

### UI

- Web GUI: `static/index.html` served at `GET /` by FastAPI
- Telegram: `tg_bot.py` calls `/analyze/{ticker}` and formats results with emojis/markdown in Russian
- UI-facing text and flag labels are in Russian
