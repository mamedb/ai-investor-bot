# AI Investor

Multi-factor stock and ETF analysis system with a web UI, Telegram bot, and PostgreSQL history tracking.

## Features

- **Three-pillar scoring** — Technical (0–5) + Fundamental/ETF (0–8) + AI Sentiment (0–5) = 18 points max
- **Decision engine** — STRONG BUY / BUY / HOLD / AVOID with veto conditions and confidence level
- **Web GUI** — dark-theme dashboard with analysis results and full search history table
- **Top 20 dropdown** — quick access to the 20 largest companies by market cap
- **Telegram bot** — Russian-language formatted results via `/analyze TICKER`
- **PostgreSQL history** — every search is persisted with all 40 indicator columns

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
       │   └── etf_analysis.py     → score 0–8  (expense ratio, AUM, returns, yield)
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
   - Negative FCF **and** negative EPS simultaneously

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
| Indicator | Description | Score |
|---|---|---|
| Weekly RSI (14) | Oversold <35 | 0–2 |
| SMA 200 | Price vs 200-day MA | 0–2 |
| 52-week position | Near low vs near high | 0–1 |

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

### `sentiment_analysis.py`
Uses OpenAI GPT (`gpt-4o-mini` by default) to score:
| Sub-score | Max |
|---|---|
| News sentiment | 2 |
| Analyst outlook | 2 |
| Macro context | 1 |

Falls back to neutral (2/5) if `OPENAI_API_KEY` is not set.

---

## Database

**PostgreSQL 16** — database `aiinvestor`, user `aiinvestor`

### `search_history` table (40 columns)
| Group | Columns |
|---|---|
| Meta | `id`, `ticker`, `searched_at`, `asset_type` |
| Decision | `recommendation`, `total_score`, `confidence`, `reason`, `flags[]` |
| Pillar scores | `tech_score`, `fund_score`, `sent_score` |
| Technical | `tech_rsi`, `tech_signal`, `tech_trend`, `tech_sma200`, `tech_price`, `tech_week52_*` |
| Fundamental | `fund_grade`, `fund_sector`, `fund_name`, per-criterion scores + values |
| Sentiment | `sent_label`, `sent_news_score`, `sent_analyst_score`, `sent_macro_score`, `sent_summary` |

---

## Setup

### Dependencies (install manually)

```bash
pip install fastapi uvicorn yfinance pandas numpy openai psycopg2-binary python-telegram-bot
```

### Environment variables

```bash
OPENAI_API_KEY=sk-...          # required for sentiment analysis
TELEGRAM_BOT_TOKEN=...         # required for Telegram bot
API_URL=http://127.0.0.1:8000/analyze/  # used by tg_bot.py

# Database (defaults shown)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=aiinvestor
DB_USER=aiinvestor
DB_PASSWORD=aiinvestor123
```

### Start the API server

```bash
set -a && source .env && set +a
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Start the Telegram bot

```bash
python tg_bot.py
```

### Manual test

```bash
curl http://localhost:8000/analyze/AAPL
curl http://localhost:8000/history?limit=10
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Web UI |
| `GET` | `/analyze/{ticker}` | Run full analysis |
| `GET` | `/history?limit=50` | Last N search results from DB |

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
│   └── main.py                  # FastAPI app, routes
├── services/
│   ├── data_service.py          # yfinance fetch
│   ├── technical_analysis.py    # RSI, SMA200, 52w
│   ├── fundamental_analysis.py  # 6-criterion stock scoring
│   ├── etf_analysis.py          # 5-criterion ETF scoring
│   ├── sentiment_analysis.py    # OpenAI GPT sentiment
│   ├── decision_engine.py       # gates, vetoes, confidence
│   └── db_service.py            # PostgreSQL save/read
├── static/
│   └── index.html               # Web UI
├── utils/
│   └── indicators.py
├── tg_bot.py                    # Telegram bot
├── CLAUDE.md                    # Claude Code instructions
└── README.md                    # This file
```
