"""
Portfolio builder: analyzes a universe of assets and constructs a
risk-weighted allocation with compound-growth projections.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from services.data_service import get_stock_data
from services.technical_analysis import analyze as technical_analysis
from services.fundamental_analysis import analyze as fundamental_analysis
from services.etf_analysis import analyze as etf_analysis
from services.crypto_analysis import analyze as crypto_analysis
from services.sentiment_analysis import analyze as sentiment_analysis
from services.decision_engine import decide as make_decision

# ── Asset universe ───────────────────────────────────────────────────────────

UNIVERSE: dict[str, list[str]] = {
    "etf":    ["SPY", "QQQ", "VTI", "AGG", "GLD"],
    "stock":  ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "JPM", "LLY", "BRK-B"],
    "crypto": ["BTC-USD", "ETH-USD", "SOL-USD"],
}

# Category weights per risk profile (must sum to 1.0)
RISK_WEIGHTS: dict[str, dict[str, float]] = {
    "conservative": {"etf": 0.65, "stock": 0.35, "crypto": 0.00},
    "moderate":     {"etf": 0.35, "stock": 0.55, "crypto": 0.10},
    "aggressive":   {"etf": 0.15, "stock": 0.55, "crypto": 0.30},
}

# Expected annual return for projection (simplified)
RISK_ANNUAL_RETURN: dict[str, float] = {
    "conservative": 0.07,
    "moderate":     0.10,
    "aggressive":   0.15,
}

# Minimum score to be included in the portfolio (out of 18)
MIN_SCORE: dict[str, int] = {
    "conservative": 10,
    "moderate":     7,
    "aggressive":   4,
}


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
        "ticker":     ticker,
        "name":       info.get("longName") or info.get("shortName") or ticker,
        "quote_type": quote_type,
        "score":      decision.get("score", 0),
        "decision":   decision.get("decision", "AVOID"),
        "confidence": decision.get("confidence", "LOW"),
        "price":      price,
        "technical":  technical,
        "fundamental": fundamental,
        "sentiment":  sentiment,
        "full_decision": decision,
    }


def analyze_universe(risk_level: str) -> list[dict[str, Any]]:
    """
    Analyze all tickers in UNIVERSE in parallel (thread pool).
    Returns list of result dicts for the categories relevant to risk_level.
    """
    weights = RISK_WEIGHTS[risk_level]
    tickers_to_run: list[tuple[str, str]] = []   # (category, ticker)
    for category, weight in weights.items():
        if weight > 0:
            for t in UNIVERSE.get(category, []):
                tickers_to_run.append((category, t))

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {
            pool.submit(_analyze_one, ticker): (category, ticker)
            for category, ticker in tickers_to_run
        }
        for future in as_completed(future_map):
            category, ticker = future_map[future]
            try:
                res = future.result()
            except Exception as exc:
                res = {"ticker": ticker, "error": str(exc), "score": 0, "decision": "AVOID"}
            res["_category"] = category
            results.append(res)

    return results


# ── Portfolio builder ────────────────────────────────────────────────────────

def build_portfolio(
    monthly_amount: float,
    duration_months: int,
    risk_level: str,
) -> dict[str, Any]:
    """
    Main entry point.  Analyzes universe assets and returns:
      allocations  – list of per-asset dicts with weights and monthly amounts
      projection   – month-by-month portfolio value
      summary      – totals / metadata
    """
    all_results = analyze_universe(risk_level)
    weights     = RISK_WEIGHTS[risk_level]
    min_score   = MIN_SCORE[risk_level]

    # Group passing assets by category
    by_cat: dict[str, list[dict]] = {"etf": [], "stock": [], "crypto": []}
    for r in all_results:
        cat = r.get("_category", "stock")
        if r.get("score", 0) >= min_score and "error" not in r:
            by_cat[cat].append(r)

    # Build weighted allocations
    allocations: list[dict[str, Any]] = []

    for category, cat_weight in weights.items():
        if cat_weight == 0:
            continue
        candidates = by_cat.get(category, [])
        if not candidates:
            # fall back: take top-3 by score regardless of min_score
            candidates = sorted(
                [r for r in all_results if r.get("_category") == category and "error" not in r],
                key=lambda x: -x.get("score", 0),
            )[:3]
        if not candidates:
            continue

        total_score = sum(c["score"] for c in candidates) or 1
        for asset in candidates:
            share = cat_weight * (asset["score"] / total_score)
            allocations.append({
                "ticker":        asset["ticker"],
                "name":          asset.get("name", asset["ticker"]),
                "category":      category,
                "score":         asset["score"],
                "decision":      asset["decision"],
                "confidence":    asset.get("confidence", "LOW"),
                "price":         asset.get("price", 0),
                "pct":           round(share * 100, 2),
                "monthly_usd":   round(monthly_amount * share, 2),
            })

    # Renormalize so allocations sum to exactly 100 %
    total_pct = sum(a["pct"] for a in allocations) or 1
    for a in allocations:
        a["pct"]         = round(a["pct"] / total_pct * 100, 2)
        a["monthly_usd"] = round(monthly_amount * a["pct"] / 100, 2)

    allocations.sort(key=lambda x: -x["pct"])

    # ── Compound growth projection ───────────────────────────────────────────
    annual_rate  = RISK_ANNUAL_RETURN[risk_level]
    monthly_rate = annual_rate / 12

    projection: list[dict] = []
    for m in range(1, duration_months + 1):
        if monthly_rate > 0:
            fv = monthly_amount * ((1 + monthly_rate) ** m - 1) / monthly_rate * (1 + monthly_rate)
        else:
            fv = monthly_amount * m
        invested = monthly_amount * m
        projection.append({
            "month":    m,
            "value":    round(fv, 2),
            "invested": round(invested, 2),
        })

    total_invested  = monthly_amount * duration_months
    projected_value = projection[-1]["value"] if projection else total_invested
    expected_gain   = projected_value - total_invested

    return {
        "allocations": allocations,
        "projection":  projection,
        "summary": {
            "risk_level":       risk_level,
            "monthly_amount":   monthly_amount,
            "duration_months":  duration_months,
            "annual_return_pct": annual_rate * 100,
            "total_invested":   round(total_invested, 2),
            "projected_value":  round(projected_value, 2),
            "expected_gain":    round(expected_gain, 2),
            "roi_pct":          round(expected_gain / total_invested * 100, 1) if total_invested else 0,
        },
    }
