"""
services/technical_analysis.py
--------------------------------
Long-term technical analysis using weekly candles.
Replaces daily RSI with weekly RSI, adds 200-SMA trend filter
and 52-week high/low proximity score.

Returns a dict that is backward-compatible with the existing API response:
  {
    "rsi": float,           # weekly RSI (14)
    "signal": str,          # human-readable RSI label
    "trend": str,           # "UPTREND" | "DOWNTREND" | "NEUTRAL"
    "sma200": float,        # current 200-day SMA value
    "price": float,         # latest closing price
    "week52_position": float,  # 0.0–1.0 (0 = at 52w low, 1 = at 52w high)
    "week52_signal": str,   # "NEAR_LOW" | "MID_RANGE" | "NEAR_HIGH"
    "score": int,           # 0–5 composite technical score
    "summary": str          # one-line verdict for the bot message
  }
"""

import yfinance as yf
import pandas as pd


# ── RSI ───────────────────────────────────────────────────────────────────────

def _compute_rsi(series: pd.Series, period: int = 14) -> float:
    """Compute RSI for the last bar of a price series."""
    delta = series.diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, float("inf"))
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)


def _rsi_signal(rsi: float) -> str:
    if rsi < 35:
        return "OVERSOLD"
    elif rsi > 65:
        return "OVERBOUGHT"
    else:
        return "NEUTRAL"


def _rsi_score(rsi: float) -> int:
    """
    Long-term scoring: oversold = bullish entry opportunity.
    Overbought on weekly = caution for new entries.
    """
    if rsi < 35:
        return 2   # strong buy signal
    elif rsi < 50:
        return 1   # mild bullish
    elif rsi < 65:
        return 0   # neutral
    else:
        return -1  # stretched, lower score


# ── 200-DAY SMA ───────────────────────────────────────────────────────────────

def _sma200_analysis(daily_closes: pd.Series) -> dict:
    """
    Price vs 200-day SMA — the classic long-term trend filter.
    Requires at least 200 daily candles.
    """
    if len(daily_closes) < 200:
        return {"sma200": None, "trend": "INSUFFICIENT_DATA", "score": 0}

    sma200 = round(float(daily_closes.rolling(200).mean().iloc[-1]), 2)
    price = round(float(daily_closes.iloc[-1]), 2)
    pct_above = (price - sma200) / sma200 * 100

    if pct_above > 2:
        trend = "UPTREND"
        score = 2
    elif pct_above < -2:
        trend = "DOWNTREND"
        score = 0
    else:
        trend = "NEUTRAL"
        score = 1

    return {"sma200": sma200, "price": price, "trend": trend, "score": score}


# ── 52-WEEK RANGE ─────────────────────────────────────────────────────────────

def _week52_analysis(daily_closes: pd.Series) -> dict:
    """
    Position within 52-week range.
    Near lows with good fundamentals = long-term entry opportunity.
    """
    if len(daily_closes) < 252:
        window = daily_closes
    else:
        window = daily_closes.iloc[-252:]

    high = float(window.max())
    low = float(window.min())
    price = float(daily_closes.iloc[-1])

    if high == low:
        position = 0.5
    else:
        position = round((price - low) / (high - low), 3)

    if position <= 0.25:
        signal = "NEAR_LOW"
        score = 1   # potential value entry
    elif position >= 0.80:
        signal = "NEAR_HIGH"
        score = 0   # chasing momentum, lower score for long-term
    else:
        signal = "MID_RANGE"
        score = 1

    return {
        "week52_high": round(high, 2),
        "week52_low": round(low, 2),
        "week52_position": position,
        "week52_signal": signal,
        "score": score,
    }


# ── MAIN ENTRY POINT ──────────────────────────────────────────────────────────

def analyze(ticker: str) -> dict:
    """
    Run full long-term technical analysis for a ticker.
    Raises ValueError if data cannot be fetched.
    """
    t = yf.Ticker(ticker)

    # --- fetch weekly data for RSI (2 years gives ~104 weekly bars) ---
    weekly = t.history(period="2y", interval="1wk")
    if weekly.empty or len(weekly) < 20:
        raise ValueError(f"Insufficient weekly data for {ticker}")

    weekly_closes = weekly["Close"]

    # --- fetch daily data for SMA200 + 52w range (need 1+ year) ---
    daily = t.history(period="2y", interval="1d")
    if daily.empty:
        raise ValueError(f"Insufficient daily data for {ticker}")

    daily_closes = daily["Close"]

    # --- compute each component ---
    rsi = _compute_rsi(weekly_closes)
    rsi_sig = _rsi_signal(rsi)
    rsi_sc = _rsi_score(rsi)

    sma_data = _sma200_analysis(daily_closes)
    w52_data = _week52_analysis(daily_closes)

    # --- composite score (0–5) ---
    raw_score = rsi_sc + sma_data["score"] + w52_data["score"]
    # clamp to 0–5
    composite = max(0, min(5, raw_score + 1))  # +1 baseline so neutral = 2

    # --- human summary ---
    trend = sma_data.get("trend", "UNKNOWN")
    w52_sig = w52_data["week52_signal"]

    if composite >= 4:
        summary = f"Strong technical setup — {trend}, RSI {rsi} ({rsi_sig}), {w52_sig}"
    elif composite >= 2:
        summary = f"Neutral/mixed — {trend}, RSI {rsi} ({rsi_sig}), {w52_sig}"
    else:
        summary = f"Weak technical — {trend}, RSI {rsi} ({rsi_sig}), {w52_sig}"

    return {
        # backward-compatible keys (existing API uses these)
        "rsi": rsi,
        "signal": rsi_sig,
        # new keys
        "trend": trend,
        "sma200": sma_data.get("sma200"),
        "price": sma_data.get("price", round(float(daily_closes.iloc[-1]), 2)),
        "week52_high": w52_data["week52_high"],
        "week52_low": w52_data["week52_low"],
        "week52_position": w52_data["week52_position"],
        "week52_signal": w52_sig,
        "score": composite,
        "summary": summary,
    }
