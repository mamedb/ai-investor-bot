# AI Investor

Multi-factor stock, ETF, and crypto analysis system with a web UI, Telegram bot, price alerts, and PostgreSQL history tracking.

## Features

- **Three-pillar scoring** — Technical (0–5) + Fundamental/ETF/Crypto (0–8) + AI Sentiment (0–5) = 18 points max
- **Decision engine** — STRONG BUY / BUY / HOLD / AVOID with veto conditions and confidence level
- **Web GUI** — dark-theme dashboard with analysis results, search history, and portfolio tools
- **Asset support** — Stocks, ETFs, and Crypto (auto-detected by quote type)
- **Portfolio Forecaster** — monthly DCA or one-time investment projections across 18 assets
- **My Portfolio** — live P&L tracking, history chart, and 10-year AI forecast
- **Price & Signal Alerts** — Telegram notifications when price or score thresholds are hit
- **Telegram bot** — Russian-language formatted analysis results
- **PostgreSQL history** — every search persisted with all 40+ indicator columns

---

## Architecture

```
GET /analyze/{ticker}
       │
       ▼
data_service.py          ← single yfinance fetch (shared dict)
       │
       ├── technical_analysis.py   → score 0–5  (RSI, SMA200, 52w range)
       ├── fundamental_analysis.py → score 0–8  (revenue, EPS, P/E, D/E, margin, FCF)
       │   ├── etf_analysis.py     → score 0–8  (expense ratio, AUM, returns, yield)
       │   └── crypto_analysis.py  → score 0–8  (market cap, return, liquidity, volatility)
       └── sentiment_analysis.py   → score 0–5  (OpenAI GPT: news, analyst, macro)
                │
                ▼
        decision_engine.py         → STRONG_BUY / BUY / HOLD / AVOID
                │
                ▼
        db_service.py              → INSERT into PostgreSQL search_history
```

### Decision Logic

1. **Veto conditions** (checked first — override everything):
   - Fundamental score < 2/8
   - Downtrend + fundamental score < 4
   - Negative FCF **and** negative EPS simultaneously (stocks only)

2. **Gate thresholds**:

   | Decision    | Tech ≥ | Fund ≥ | Sent ≥ | Total ≥ |
   |-------------|--------|--------|--------|---------|
   | STRONG BUY  | 4      | 6      | 3      | 13      |
   | BUY         | 2      | 4      | 2      | 8       |
   | HOLD        | 1      | 2      | 1      | 4       |
   | AVOID       | —      | —      | —      | —       |

3. **Confidence**: HIGH (all 3 pillars agree) / MEDIUM (2 agree) / LOW (mixed)

---

## Services

### `technical_analysis.py`
| Indicator | Description | Max |
|---|---|---|
| Weekly RSI (14) | Oversold <35 | 2 |
| SMA 200 | Price vs 200-day MA | 2 |
| 52-week position | Near low vs near high | 1 |

### `fundamental_analysis.py` (stocks)
| Criterion | Max |
|---|---|
| Revenue growth YoY | 2 |
| EPS trend (3-year) | 2 |
| P/E vs sector median | 1 |
| Debt/Equity ratio | 1 |
| Profit margin | 1 |
| Free cash flow | 1 |

### `etf_analysis.py`
| Criterion | Max |
|---|---|
| Expense ratio | 2 |
| AUM (fund size) | 2 |
| 1-year return | 2 |
| Dividend yield | 1 |
| 5-year avg return | 1 |

### `crypto_analysis.py`
| Criterion | Max |
|---|---|
| Market cap | 2 |
| 1-year return | 2 |
| Liquidity | 2 |
| Supply health | 1 |
| 30-day volatility | 1 |

### `sentiment_analysis.py`
Uses OpenAI GPT (`gpt-4o-mini` by default) to score:
| Sub-score | Max |
|---|---|
| News sentiment | 2 |
| Analyst outlook | 2 |
| Macro context | 1 |

Falls back to neutral (2/5) if `OPENAI_API_KEY` is not set.

### `alert_service.py`
Background asyncio loop started at app startup:
- **Price alerts** — checked every 30 minutes using `yfinance.fast_info` (lightweight)
- **Score alerts** — checked every 6 hours using the full analysis pipeline
- One-shot: alerts deactivate after firing to prevent repeat notifications
- Delivers to all Telegram chat IDs registered via `/start`

---

## Database

**PostgreSQL** — database `aiinvestor`, user `aiinvestor`

### Tables

**`search_history`** — every `/analyze/{ticker}` result (40+ columns)
| Group | Columns |
|---|---|
| Meta | `id`, `ticker`, `searched_at`, `asset_type` |
| Decision | `recommendation`, `total_score`, `confidence`, `reason`, `flags[]` |
| Pillar scores | `tech_score`, `fund_score`, `sent_score` |
| Technical | `tech_rsi`, `tech_signal`, `tech_trend`, `tech_sma200`, `tech_price`, `tech_week52_*` |
| Fundamental | `fund_grade`, `fund_sector`, `fund_name`, per-criterion scores + values |
| Sentiment | `sent_label`, `sent_news_score`, `sent_analyst_score`, `sent_macro_score`, `sent_summary` |

**`portfolio_holdings`** — My Portfolio real holdings (ticker, shares, avg_price)

**`portfolio_history`** — daily value snapshots for the 90-day chart

**`price_alerts`** — user-defined alert rules (ticker, alert_type, threshold, is_active)

**`telegram_chats`** — registered Telegram chat IDs for alert delivery

---

## Setup

### Dependencies

```bash
pip install fastapi uvicorn yfinance pandas numpy openai psycopg2-binary python-telegram-bot python-multipart itsdangerous
```

### Environment variables (`.env`)

```bash
OPENAI_API_KEY=sk-...                        # required for sentiment analysis
TELEGRAM_BOT_TOKEN=...                       # required for Telegram bot and alerts
API_URL=http://127.0.0.1:8080/analyze/       # used by tg_bot.py

# Auth (optional — defaults shown)
LOGIN_USERNAME=admin
LOGIN_PASSWORD=password
SECRET_KEY=change-me-in-production

# Database (defaults shown)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=aiinvestor
DB_USER=aiinvestor
DB_PASSWORD=aiinvestor123
```

### Start

```bash
# Load env vars
set -a && source .env && set +a

# API server (background)
nohup uvicorn app.main:app --host 0.0.0.0 --port 8080 > app_log.txt 2>&1 &

# Telegram bot (background)
nohup python3 tg_bot.py >> app_log.txt 2>&1 &
```

### Manual test

```bash
curl http://localhost:8080/analyze/AAPL
curl http://localhost:8080/history?limit=10
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Asset Analysis web UI |
| `GET` | `/analyze/{ticker}` | Run full analysis |
| `GET` | `/history?limit=50` | Last N search results from DB |
| `GET` | `/portfolio` | Portfolio Forecaster UI |
| `POST` | `/portfolio/calculate` | Build recommended portfolio |
| `GET` | `/my-portfolio` | My Portfolio UI |
| `GET` | `/my-portfolio/assets` | Live holdings + P&L |
| `POST` | `/my-portfolio/assets` | Add holding |
| `DELETE` | `/my-portfolio/assets/{id}` | Remove holding |
| `GET` | `/my-portfolio/history` | 90-day value history |
| `POST` | `/my-portfolio/forecast` | 10-year AI forecast |
| `GET` | `/alerts` | Alerts UI |
| `GET` | `/alerts/list` | All alerts (JSON) |
| `POST` | `/alerts` | Create alert |
| `DELETE` | `/alerts/{id}` | Delete alert |

### Response shape — `/analyze/{ticker}`

```json
{
  "ticker": "AAPL",
  "asset_type": "STOCK",
  "technical":   { "score": 3, "rsi": 52.1, "trend": "UPTREND", ... },
  "fundamental": { "score": 6, "grade": "STRONG", "breakdown": { ... } },
  "sentiment":   { "score": 4, "label": "BULLISH", "breakdown": { ... } },
  "decision": {
    "decision":    "BUY",
    "score":       13,
    "confidence":  "HIGH",
    "reason":      "...",
    "flags":       [],
    "pillar_scores": { "technical": {"score":3,"max":5}, ... }
  }
}
```

---

## File Structure

```
ai-investor/
├── app/
│   └── main.py                  # FastAPI app, routes, lifespan
├── services/
│   ├── data_service.py          # yfinance fetch
│   ├── technical_analysis.py    # RSI, SMA200, 52w
│   ├── fundamental_analysis.py  # 6-criterion stock scoring
│   ├── etf_analysis.py          # 5-criterion ETF scoring
│   ├── crypto_analysis.py       # 5-criterion crypto scoring
│   ├── sentiment_analysis.py    # OpenAI GPT sentiment
│   ├── decision_engine.py       # gates, vetoes, confidence
│   ├── db_service.py            # PostgreSQL CRUD
│   ├── holdings_service.py      # live portfolio P&L
│   ├── portfolio_service.py     # portfolio forecaster
│   ├── portfolio_forecast_service.py  # 10-year AI forecast
│   └── alert_service.py         # background price & signal alerts
├── static/
│   ├── index.html               # Asset Analysis UI
│   ├── portfolio.html           # Portfolio Forecaster UI
│   ├── my_portfolio.html        # My Portfolio UI
│   ├── alerts.html              # Alerts UI
│   └── login.html               # Login page
├── utils/
│   └── indicators.py            # legacy (unused)
├── tg_bot.py                    # Telegram bot
├── CLAUDE.md                    # Claude Code instructions
└── README.md                    # This file
```
