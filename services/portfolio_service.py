"""
Portfolio builder: analyzes a universe of assets, then uses OpenAI to
select up to 10 best-fit assets and determine percentage allocations
based on risk profile and analysis scores.
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from openai import OpenAI

from services.data_service import get_stock_data
from services.technical_analysis import analyze as technical_analysis
from services.fundamental_analysis import analyze as fundamental_analysis
from services.etf_analysis import analyze as etf_analysis
from services.crypto_analysis import analyze as crypto_analysis
from services.sentiment_analysis import analyze as sentiment_analysis
from services.decision_engine import decide as make_decision

logger = logging.getLogger(__name__)

# ── Asset universe ───────────────────────────────────────────────────────────

UNIVERSE: dict[str, list[str]] = {
    "etf":    ["SPY", "QQQ", "VTI", "AGG", "GLD"],
    "stock":  ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "JPM", "LLY", "BRK-B"],
    "crypto": ["BTC-USD", "ETH-USD", "SOL-USD"],
}

# Expected annual return for projection — used when OpenAI doesn't return one
RISK_ANNUAL_RETURN: dict[str, float] = {
    "conservative": 0.07,
    "moderate":     0.10,
    "aggressive":   0.15,
}

# ── OpenAI client ────────────────────────────────────────────────────────────

_client: Optional[OpenAI] = None


def _get_client() -> Optional[OpenAI]:
    global _client
    if _client is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            return None
        _client = OpenAI(api_key=key)
    return _client


# ── Single-ticker analysis ───────────────────────────────────────────────────

def _analyze_one(ticker: str) -> dict[str, Any]:
    """Fetch + run full analysis for one ticker. Returns result dict."""
    try:
        data = get_stock_data(ticker)
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "score": 0, "decision": "AVOID"}

    info = data.get("info", {})
    quote_type = info.get("quoteType", "STOCK")
    is_etf    = quote_type == "ETF"
    is_crypto = quote_type == "CRYPTOCURRENCY"

    try:
        technical  = technical_analysis(data)
        if is_crypto:
            fundamental = crypto_analysis(data)
        elif is_etf:
            fundamental = etf_analysis(data)
        else:
            fundamental = fundamental_analysis(data)
        sentiment = sentiment_analysis(data)
        decision  = make_decision(technical, fundamental, sentiment)
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "score": 0, "decision": "AVOID"}

    price = info.get("currentPrice") or info.get("regularMarketPrice") or 0

    return {
        "ticker":       ticker,
        "name":         info.get("longName") or info.get("shortName") or ticker,
        "quote_type":   quote_type,
        "score":        decision.get("score", 0),
        "decision":     decision.get("decision", "AVOID"),
        "confidence":   decision.get("confidence", "LOW"),
        "price":        price,
        "technical":    technical,
        "fundamental":  fundamental,
        "sentiment":    sentiment,
        "full_decision": decision,
    }


def _analyze_universe() -> list[dict[str, Any]]:
    """Analyze all tickers in UNIVERSE in parallel."""
    tickers_to_run: list[tuple[str, str]] = [
        (cat, ticker)
        for cat, tickers in UNIVERSE.items()
        for ticker in tickers
    ]

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {
            pool.submit(_analyze_one, ticker): (cat, ticker)
            for cat, ticker in tickers_to_run
        }
        for future in as_completed(future_map):
            cat, ticker = future_map[future]
            try:
                res = future.result()
            except Exception as exc:
                res = {"ticker": ticker, "error": str(exc), "score": 0, "decision": "AVOID"}
            res["_category"] = cat
            results.append(res)

    return results


# ── AI allocation ────────────────────────────────────────────────────────────

_PORTFOLIO_SYSTEM_PROMPT = """\
You are a professional portfolio manager. You receive a list of analyzed assets \
(with scores 0–18, decisions, and category) and a risk profile. Your job is to \
select up to 10 assets for the portfolio and assign percentage allocations that \
sum to exactly 100.

Rules:
- Choose assets that best fit the risk profile — no fixed category quotas.
- Higher score and stronger decision (STRONG_BUY > BUY > HOLD > AVOID) should generally mean higher allocation.
- AVOID decisions should be excluded unless there are no better options.
- For conservative: favor lower-volatility assets (ETFs, blue-chip stocks); minimize crypto.
- For moderate: balanced growth-oriented mix; crypto is acceptable in small amounts.
- For aggressive: growth stocks and crypto can receive significant allocations.
- Estimate a realistic expected annual return percentage for the constructed portfolio.

Return ONLY valid JSON:
{
  "allocations": [
    {"ticker": "<TICKER>", "pct": <number>},
    ...
  ],
  "expected_annual_return_pct": <number>,
  "reasoning": "<one or two sentences explaining the portfolio construction>"
}"""


def _ai_allocate(
    assets: list[dict[str, Any]], risk_level: str
) -> tuple[list[dict], float, str]:
    """
    Ask OpenAI to select up to 10 assets and assign percentages.
    Returns (allocations, annual_return_pct, reasoning).
    Falls back to score-based top-10 if OpenAI is unavailable.
    """
    client = _get_client()
    if client is None:
        return _fallback_allocate(assets, risk_level)

    summaries = [
        {
            "ticker":     a["ticker"],
            "name":       a.get("name", a["ticker"]),
            "category":   a.get("_category", "stock"),
            "score":      a.get("score", 0),
            "decision":   a.get("decision", "AVOID"),
            "confidence": a.get("confidence", "LOW"),
        }
        for a in assets
        if "error" not in a
    ]

    user_content = (
        f"Risk level: {risk_level}\n\n"
        f"Analyzed assets:\n{json.dumps(summaries, indent=2)}"
    )

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0.3,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _PORTFOLIO_SYSTEM_PROMPT},
                {"role": "user",   "content": user_content},
            ],
        )
        result = json.loads(resp.choices[0].message.content)
        allocations = result.get("allocations", [])
        annual_return = float(result.get("expected_annual_return_pct", RISK_ANNUAL_RETURN[risk_level] * 100))
        reasoning = result.get("reasoning", "")
        if allocations:
            return allocations, annual_return, reasoning
    except Exception as e:
        logger.warning("OpenAI portfolio allocation failed: %s", e)

    return _fallback_allocate(assets, risk_level)


def _fallback_allocate(
    assets: list[dict[str, Any]], risk_level: str
) -> tuple[list[dict], float, str]:
    """Score-based top-10 fallback when OpenAI is unavailable."""
    candidates = [
        a for a in assets
        if "error" not in a and a.get("decision") != "AVOID"
    ]
    if not candidates:
        candidates = [a for a in assets if "error" not in a]

    candidates.sort(key=lambda x: -x.get("score", 0))
    top = candidates[:10]
    total_score = sum(a.get("score", 1) for a in top) or 1
    allocs = [
        {"ticker": a["ticker"], "pct": round(a.get("score", 1) / total_score * 100, 2)}
        for a in top
    ]
    annual_return = RISK_ANNUAL_RETURN[risk_level] * 100
    return allocs, annual_return, ""


# ── Portfolio builder ────────────────────────────────────────────────────────

def build_portfolio(
    monthly_amount: float,
    duration_months: int,
    risk_level: str,
) -> dict[str, Any]:
    """
    Main entry point. Analyzes the universe, calls OpenAI to pick up to 10
    assets and set allocations, then returns allocations + projection + summary.
    """
    all_results = _analyze_universe()

    # Index by ticker for quick lookup
    by_ticker: dict[str, dict] = {r["ticker"]: r for r in all_results}

    ai_allocs, annual_return_pct, reasoning = _ai_allocate(all_results, risk_level)

    # Renormalize to exactly 100%
    total_pct = sum(a["pct"] for a in ai_allocs) or 1
    for a in ai_allocs:
        a["pct"] = round(a["pct"] / total_pct * 100, 2)

    # Build full allocation records
    allocations: list[dict[str, Any]] = []
    for a in ai_allocs:
        asset = by_ticker.get(a["ticker"])
        if not asset:
            continue
        pct = a["pct"]
        allocations.append({
            "ticker":      asset["ticker"],
            "name":        asset.get("name", asset["ticker"]),
            "category":    asset.get("_category", "stock"),
            "score":       asset.get("score", 0),
            "decision":    asset.get("decision", "AVOID"),
            "confidence":  asset.get("confidence", "LOW"),
            "price":       asset.get("price", 0),
            "pct":         pct,
            "monthly_usd": round(monthly_amount * pct / 100, 2),
        })

    allocations.sort(key=lambda x: -x["pct"])

    # ── Compound growth projection ───────────────────────────────────────────
    annual_rate  = annual_return_pct / 100
    monthly_rate = annual_rate / 12

    projection: list[dict] = []
    for m in range(1, duration_months + 1):
        if monthly_rate > 0:
            fv = monthly_amount * ((1 + monthly_rate) ** m - 1) / monthly_rate * (1 + monthly_rate)
        else:
            fv = monthly_amount * m
        projection.append({
            "month":    m,
            "value":    round(fv, 2),
            "invested": round(monthly_amount * m, 2),
        })

    total_invested  = monthly_amount * duration_months
    projected_value = projection[-1]["value"] if projection else total_invested
    expected_gain   = projected_value - total_invested

    return {
        "allocations": allocations,
        "projection":  projection,
        "summary": {
            "risk_level":            risk_level,
            "monthly_amount":        monthly_amount,
            "duration_months":       duration_months,
            "annual_return_pct":     round(annual_return_pct, 1),
            "total_invested":        round(total_invested, 2),
            "projected_value":       round(projected_value, 2),
            "expected_gain":         round(expected_gain, 2),
            "roi_pct":               round(expected_gain / total_invested * 100, 1) if total_invested else 0,
            "ai_reasoning":          reasoning,
        },
    }
