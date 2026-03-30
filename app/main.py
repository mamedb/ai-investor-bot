from fastapi import FastAPI
from services.data_service import get_stock_data
from services.fundamental import fundamental_analysis
from services.technical import technical_analysis
from services.sentiment import sentiment_analysis
from services.decision import make_decision

app = FastAPI()

@app.get("/analyze/{ticker}")
def analyze_stock(ticker: str):
    data = get_stock_data(ticker)

    fundamental = fundamental_analysis(data["info"])
    technical = technical_analysis(data["price"])
    sentiment = sentiment_analysis(ticker)

    decision = make_decision(fundamental, technical, sentiment)

    return {
        "ticker": ticker,
        "fundamental": fundamental,
        "technical": technical,
        "sentiment": sentiment,
        "decision": decision
    }
