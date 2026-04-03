"""
services/data_service.py
--------------------------
Single fetch point for all yfinance data.
Called once per request in main.py — results passed to each analysis module.

Fetches:
  - info:          company metadata, fundamentals, analyst data
  - daily_closes:  2 years daily closes (for SMA200, 52w range)
  - weekly_closes: 2 years weekly closes (for RSI)
  - financials:    annual income statement (revenue, EPS)
  - cashflow:      annual cash flow statement (FCF)
  - insider_transactions
  - institutional_holders
"""

import yfinance as yf
import pandas as pd


def get_stock_data(ticker: str) -> dict:
    """
    Fetch all data needed by technical, fundamental, and sentiment modules.
    Raises ValueError if the ticker is invalid or returns no data.
    """
    stock = yf.Ticker(ticker)

    # ── price history ─────────────────────────────────────────────────────────
    daily = stock.history(period="2y", interval="1d")
    if daily.empty:
        raise ValueError(f"No price data found for ticker: {ticker}")

    weekly = stock.history(period="2y", interval="1wk")

    # ── fundamentals ──────────────────────────────────────────────────────────
    info = stock.info or {}

    try:
        financials = stock.financials      # annual income statement
    except Exception:
        financials = pd.DataFrame()

    try:
        cashflow = stock.cashflow
    except Exception:
        cashflow = pd.DataFrame()

    # ── sentiment sources ─────────────────────────────────────────────────────
    try:
        insider = stock.insider_transactions
    except Exception:
        insider = pd.DataFrame()

    try:
        institutional = stock.institutional_holders
    except Exception:
        institutional = pd.DataFrame()

    try:
        raw_news = stock.news or []
        news = [
            {
                "title":   item.get("content", {}).get("title", ""),
                "summary": item.get("content", {}).get("summary", ""),
            }
            for item in raw_news
            if item.get("content", {}).get("title")
        ]
    except Exception:
        news = []

    return {
        "daily_closes":          daily["Close"],
        "weekly_closes":         weekly["Close"],
        "info":                  info,
        "financials":            financials,
        "cashflow":              cashflow,
        "insider_transactions":  insider,
        "institutional_holders": institutional,
        "news":                  news,
    }
