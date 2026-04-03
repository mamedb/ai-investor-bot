"""
services/sentiment_analysis.py
--------------------------------
AI-powered sentiment analysis using OpenAI GPT.

Three sub-scores (total 0–5):
  1. news_sentiment  (0–2) — recent headlines analysis
  2. analyst_outlook (0–2) — analyst ratings + price target context
  3. macro_context   (0–1) — sector / macro tailwinds or headwinds

Works for both stocks and ETFs. Falls back to neutral (2/5) if the
OpenAI API key is missing or the call fails.

Requires env var: OPENAI_API_KEY
Optional env var: OPENAI_MODEL  (default: gpt-4o-mini)
"""

import os
import json
import logging
from typing import Optional
from openai import OpenAI

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> Optional[OpenAI]:
    global _client
    if _client is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            return None
        _client = OpenAI(api_key=key)
    return _client


# ── Context builder ───────────────────────────────────────────────────────────

def _build_context(data: dict) -> str:
    info = data.get("info", {})
    news = data.get("news", [])

    ticker      = info.get("symbol", "?")
    name        = info.get("longName") or info.get("shortName") or ticker
    asset_type  = info.get("quoteType", "STOCK")
    sector      = info.get("sector") or info.get("category") or "Unknown"
    industry    = info.get("industry", "")
    market_cap  = info.get("marketCap")
    price       = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("navPrice")
    rec_mean    = info.get("recommendationMean")
    rec_count   = info.get("numberOfAnalystOpinions", 0)
    target      = info.get("targetMeanPrice")
    ytd         = info.get("ytdReturn")
    er          = info.get("netExpenseRatio") or info.get("expenseRatio")
    total_assets = info.get("totalAssets")

    lines = [
        f"Ticker: {ticker}",
        f"Name: {name}",
        f"Asset type: {asset_type}",
        f"Sector/Category: {sector}",
    ]
    if industry:
        lines.append(f"Industry: {industry}")
    if market_cap:
        lines.append(f"Market cap: ${market_cap / 1e9:.1f}B")
    if price:
        lines.append(f"Current price: ${price:.2f}")

    # Analyst data (stocks)
    if rec_mean and rec_count:
        scale = {1: "Strong Buy", 2: "Buy", 3: "Hold", 4: "Underperform", 5: "Sell"}
        closest = min(scale, key=lambda k: abs(k - rec_mean))
        lines.append(f"Analyst consensus: {rec_mean:.2f}/5.0 ≈ {scale[closest]} ({int(rec_count)} analysts)")
        if target and price:
            upside = (target - price) / price * 100
            lines.append(f"Mean price target: ${target:.2f} ({upside:+.1f}% vs current price)")

    # ETF-specific
    if asset_type == "ETF":
        if er is not None:
            er_pct = er if er >= 0.01 else er * 100
            lines.append(f"Expense ratio: {er_pct:.3f}%")
        if total_assets:
            lines.append(f"AUM: ${total_assets / 1e9:.1f}B")
        if ytd is not None:
            lines.append(f"YTD return: {ytd * 100:.1f}%")

    # News
    if news:
        lines.append(f"\nRecent news ({len(news[:10])} articles):")
        for item in news[:10]:
            title   = item.get("title", "").strip()
            summary = item.get("summary", "").strip()
            if title:
                lines.append(f"  • {title}")
                if summary and summary != title:
                    lines.append(f"    {summary[:120]}")
    else:
        lines.append("\nNo recent news available.")

    return "\n".join(lines)


# ── OpenAI call ───────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a professional financial analyst specializing in investment sentiment.
Given a ticker's profile and recent news, output a structured JSON sentiment \
assessment for a long-term investor (6–18 month horizon).

Scoring rubric:
  news_sentiment  (0–2): 2=clearly positive news/momentum, 1=mixed or neutral, 0=negative/bearish news
  analyst_outlook (0–2): 2=strong buy consensus with meaningful upside, 1=mixed/hold, 0=sell or no coverage
  macro_context   (0–1): 1=sector/macro tailwinds support the position, 0=headwinds or high uncertainty

label (derived from total):
  BULLISH  → total 4–5
  NEUTRAL  → total 2–3
  BEARISH  → total 0–1

Return ONLY valid JSON, no extra text:
{
  "news_sentiment":  {"score": <int>, "note": "<≤15 words>"},
  "analyst_outlook": {"score": <int>, "note": "<≤15 words>"},
  "macro_context":   {"score": <int>, "note": "<≤15 words>"},
  "label": "<BULLISH|NEUTRAL|BEARISH>",
  "summary": "<one concise sentence overall assessment>"
}"""


def _call_openai(context: str) -> Optional[dict]:
    client = _get_client()
    if client is None:
        return None
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": context},
            ],
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        logger.warning("OpenAI sentiment call failed: %s", e)
        return None


# ── Fallback ──────────────────────────────────────────────────────────────────

def _fallback(reason: str) -> dict:
    note = f"N/A — {reason}"
    return {
        "score": 2,
        "max":   5,
        "label": "NEUTRAL",
        "breakdown": {
            "news_sentiment":  {"score": 1, "max": 2, "note": note},
            "analyst_outlook": {"score": 1, "max": 2, "note": note},
            "macro_context":   {"score": 0, "max": 1, "note": note},
        },
        "summary": f"Sentiment analysis unavailable ({reason}) — neutral default applied",
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def analyze(data: dict) -> dict:
    """
    Run AI-powered sentiment analysis using OpenAI GPT.
    Falls back to neutral (2/5) if API key missing or call fails.
    """
    if not os.getenv("OPENAI_API_KEY"):
        return _fallback("OPENAI_API_KEY not set")

    context = _build_context(data)
    result  = _call_openai(context)

    if result is None:
        return _fallback("OpenAI API error")

    # Parse and validate sub-scores
    def _sub(key: str, max_sc: int) -> dict:
        item  = result.get(key, {})
        score = max(0, min(max_sc, int(item.get("score", 0))))
        note  = str(item.get("note", "N/A"))
        return {"score": score, "max": max_sc, "note": note}

    news_item = _sub("news_sentiment",  2)
    anal_item = _sub("analyst_outlook", 2)
    macro_item = _sub("macro_context",  1)

    total = news_item["score"] + anal_item["score"] + macro_item["score"]
    total = max(0, min(5, total))

    label   = result.get("label", "NEUTRAL")
    if label not in ("BULLISH", "NEUTRAL", "BEARISH"):
        label = "BULLISH" if total >= 4 else "BEARISH" if total <= 1 else "NEUTRAL"

    summary = result.get("summary", "")

    return {
        "score": total,
        "max":   5,
        "label": label,
        "breakdown": {
            "news_sentiment":  news_item,
            "analyst_outlook": anal_item,
            "macro_context":   macro_item,
        },
        "summary": summary,
    }
