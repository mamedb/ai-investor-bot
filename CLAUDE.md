# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

**FastAPI backend:**
```bash
# Load env vars then start (OPENAI_API_KEY required for sentiment)
set -a && source .env && set +a
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

**Authentication env vars** (add to `.env`):
```
LOGIN_USERNAME=admin      # default: admin
LOGIN_PASSWORD=password   # default: password
SECRET_KEY=your-secret    # default: change-me-in-production
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

There is no requirements.txt, Dockerfile, or Makefile — dependencies (FastAPI, uvicorn, yfinance, pandas, python-telegram-bot, python-multipart, itsdangerous, openai) must be installed manually.

## Architecture

This is a multi-factor stock analysis system with three independent scoring pillars feeding a decision engine.

### Data Flow

1. **Single data fetch** — `services/data_service.py:get_stock_data()` fetches yfinance data once per request and returns a shared dict passed to all analysis modules.

2. **Asset type detection** — `app/main.py` reads `info.quoteType` after fetch:
   - `STOCK` → `fundamental_analysis.py`
   - `ETF` → `etf_analysis.py`
   - `CRYPTOCURRENCY` → `crypto_analysis.py`
   - Bare crypto symbols (e.g. `SOL`) are auto-retried as `SOL-USD` if the initial fetch returns no data.

3. **Three independent pillars** — each receives the shared data dict and returns `{score, breakdown, summary}`:
   - `services/technical_analysis.py` — RSI, SMA200 trend, 52-week position (score 0–5)
   - `services/fundamental_analysis.py` — revenue growth, EPS, P/E vs sector, debt, margin, FCF (score 0–8)
   - `services/etf_analysis.py` — expense ratio, AUM, 1Y/5Y return, dividend yield (score 0–8)
   - `services/crypto_analysis.py` — market cap, 1Y return, liquidity, supply health, 30d volatility (score 0–8)
   - `services/sentiment_analysis.py` — OpenAI GPT: news sentiment, analyst outlook, macro context (score 0–5)

4. **Decision synthesis** — `services/decision_engine.py:decide()` applies:
   - **Veto conditions** (hard stops checked first — e.g., negative FCF + declining EPS blocks any buy; skipped for ETF and CRYPTO)
   - **Gate logic** (`GATES` dict, e.g., `STRONG_BUY` requires tech≥4, fund≥6, sent≥3, total≥13)
   - **Flags** — warning signals appended to the output (asset-type-aware: stocks, ETFs, and crypto each have specific flags)
   - **Confidence** — HIGH/MEDIUM/LOW based on pillar agreement

5. **Output** — `app/main.py` returns JSON with `decision`, `score`, `confidence`, `reason`, `flags`, `pillar_scores`.

### Key Design Principles

- **Fundamentals can veto technicals, but not vice versa** — veto logic runs before gate logic.
- **Scoring contracts** — every analysis module returns a consistent `{score, breakdown}` dict; the fundamental slot is swappable (stock/ETF/crypto) without touching the decision engine.
- **FCF/EPS veto is stocks-only** — skipped when `is_etf=True` or `is_crypto=True` on the fundamental result.
- The decision engine accepts both legacy string sentiment and the new dict structure (backward compatibility).

### Configuration

All configuration is in-code (no config files):
- Gate thresholds: `decision_engine.py` → `GATES` dict
- Veto rules: `decision_engine.py` → `VETO_CONDITIONS`
- Sector P/E benchmarks: `fundamental_analysis.py` → `SECTOR_PE` dict (~25 sectors)

### UI

- Web GUI: `static/index.html` served at `GET /` by FastAPI
- Login page: `static/login.html` served at `GET /login`
- Portfolio Forecaster: `static/portfolio.html` served at `GET /portfolio`
- Dropdown has two optgroups: **Top 20 Stocks by Market Cap** and **Popular Crypto** (BTC-USD, ETH-USD, SOL-USD, etc.)
- The Fundamental card adapts its label and rows based on `asset_type` (Stock / ETF / Crypto)
- Telegram: `tg_bot.py` calls `/analyze/{ticker}` and formats results with emojis/markdown in Russian
- UI-facing text and flag labels are in English
- Nav bar on both pages links between Asset Analysis (`/`) and Portfolio Forecaster (`/portfolio`)

### Portfolio Forecaster

`services/portfolio_service.py` + `GET /portfolio` + `POST /portfolio/calculate`

Inputs: investment type (monthly / one-time), amount, hold period (months), risk level (conservative / moderate / aggressive).

**Universe analyzed** (18 assets, fetched in parallel via `ThreadPoolExecutor`):
- ETF: SPY, QQQ, VTI, AGG, GLD
- Stock: AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA, JPM, LLY, BRK-B
- Crypto: BTC-USD, ETH-USD, SOL-USD

**Risk profiles** (category weight → min score to qualify):

| Risk | ETF | Stock | Crypto | Min score | Annual return (projection) |
|------|-----|-------|--------|-----------|---------------------------|
| Conservative | 65% | 35% | 0% | 10/18 | 7% |
| Moderate | 35% | 55% | 10% | 7/18 | 10% |
| Aggressive | 15% | 55% | 30% | 4/18 | 15% |

Within each category, assets are weighted proportionally to their analysis score. If no asset clears the min-score threshold, the top-3 by score are used as a fallback.

**Projection** uses two formulas depending on investment type:
- **Monthly DCA**: `FV = PMT × ((1+r)^n − 1) / r × (1+r)` (annuity due)
- **One-Time**: `FV = PV × (1+r)^n` (compound growth of lump sum); projection anchors at month 0

`r = annual_rate / 12`, `n = months`. OpenAI returns `expected_annual_return_pct`; fallback rates are 7/10/15% per risk level.

**Output JSON**: `{ allocations[], projection[], summary{} }` — rendered as doughnut pie chart, allocation table with decision badges, and a line chart showing portfolio value vs. invested over time.

### Authentication

Session-based login protects all routes (`/`, `/analyze/{ticker}`, `/history`, `/portfolio`, `/portfolio/calculate`).

- `GET /login` — login page; redirects to `/` if already authenticated
- `POST /login` — validates credentials from `LOGIN_USERNAME` / `LOGIN_PASSWORD` env vars; sets signed session cookie via `SessionMiddleware` (requires `itsdangerous`)
- `GET /logout` — clears session, redirects to `/login`
- Unauthenticated requests to protected routes redirect to `/login` (HTTP 303)
- Requires `python-multipart` installed for form handling
