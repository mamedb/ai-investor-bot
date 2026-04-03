from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from services.data_service import get_stock_data
from services.technical_analysis import analyze as technical_analysis
from services.fundamental_analysis import analyze as fundamental_analysis
from services.etf_analysis import analyze as etf_analysis
from services.sentiment_analysis import analyze as sentiment_analysis
from services.decision_engine import decide as make_decision
import os

app = FastAPI()

_static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/")
def root():
    return FileResponse(
        os.path.join(_static_dir, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/analyze/{ticker}")
def analyze_stock(ticker: str):
    # single yfinance fetch — shared across all modules
    try:
        data = get_stock_data(ticker.upper())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Data fetch failed: {e}")

    is_etf = data.get("info", {}).get("quoteType") == "ETF"

    try:
        technical = technical_analysis(data)
        fundamental = etf_analysis(data) if is_etf else fundamental_analysis(data)
        sentiment = sentiment_analysis(data)
        decision = make_decision(technical, fundamental, sentiment)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")

    return {
        "ticker":      ticker.upper(),
        "asset_type":  "ETF" if is_etf else "STOCK",
        "technical":   technical,
        "fundamental": fundamental,
        "sentiment":   sentiment,
        "decision":    decision,
    }
