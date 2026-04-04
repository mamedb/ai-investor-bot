"""
services/crypto_analysis.py
-----------------------------
Crypto-specific scoring (0–8 points), used instead of fundamental_analysis
when the ticker quoteType is 'CRYPTOCURRENCY'.

Criteria:
  1. Market cap     (0–2) — size / dominance proxy
  2. 1-year return  (0–2) — computed from daily_closes
  3. Liquidity      (0–2) — 24h volume / market cap ratio
  4. Supply health  (0–1) — circulating vs max supply
  5. Volatility     (0–1) — lower 30d vol is better for long-term

Returns the same shape as fundamental_analysis so decision_engine
and the rest of the stack handle it uniformly.
"""

import math


# ── CRITERION 1: Market Cap ───────────────────────────────────────────────────

def _market_cap(info: dict) -> dict:
    mc = info.get("marketCap")
    if mc is None:
        return {"score": 0, "value": None, "note": "N/A"}
    mc_b = round(float(mc) / 1e9, 1)
    if mc_b >= 100:
        return {"score": 2, "value": mc_b, "note": f"${mc_b}B — топ крипто"}
    elif mc_b >= 10:
        return {"score": 1, "value": mc_b, "note": f"${mc_b}B — средняя кап."}
    else:
        return {"score": 0, "value": mc_b, "note": f"${mc_b}B — малая кап."}


# ── CRITERION 2: 1-Year Return ────────────────────────────────────────────────

def _return_1y(daily_closes) -> dict:
    if daily_closes is None or len(daily_closes) < 20:
        return {"score": 0, "value": None, "note": "N/A"}
    window = daily_closes.iloc[-365:] if len(daily_closes) >= 365 else daily_closes
    r = round((float(window.iloc[-1]) / float(window.iloc[0]) - 1) * 100, 1)
    sign = "+" if r >= 0 else ""
    if r >= 50:
        return {"score": 2, "value": r, "note": f"{sign}{r}% — сильный рост за год"}
    elif r >= 0:
        return {"score": 1, "value": r, "note": f"{sign}{r}% — положительная доходность"}
    else:
        return {"score": 0, "value": r, "note": f"{r}% — отрицательная доходность"}


# ── CRITERION 3: Liquidity ────────────────────────────────────────────────────

def _liquidity(info: dict) -> dict:
    vol = info.get("volume24Hr") or info.get("regularMarketVolume")
    mc = info.get("marketCap")
    if vol is None or mc is None or float(mc) == 0:
        return {"score": 0, "value": None, "note": "N/A"}
    ratio = round(float(vol) / float(mc) * 100, 2)
    if ratio >= 3:
        return {"score": 2, "value": ratio, "note": f"{ratio}% — высокая ликвидность"}
    elif ratio >= 0.5:
        return {"score": 1, "value": ratio, "note": f"{ratio}% — умеренная ликвидность"}
    else:
        return {"score": 0, "value": ratio, "note": f"{ratio}% — низкая ликвидность"}


# ── CRITERION 4: Supply Health ────────────────────────────────────────────────

def _supply_health(info: dict) -> dict:
    circ = info.get("circulatingSupply")
    max_s = info.get("maxSupply")
    if circ is None:
        return {"score": 0, "value": None, "note": "N/A"}
    if not max_s or float(max_s) == 0:
        return {"score": 0, "value": None, "note": "Безлимитная эмиссия"}
    ratio = round(float(circ) / float(max_s) * 100, 1)
    if ratio < 80:
        return {"score": 1, "value": ratio, "note": f"{ratio}% выпущено — есть запас"}
    else:
        return {"score": 0, "value": ratio, "note": f"{ratio}% в обращении"}


# ── CRITERION 5: 30-Day Volatility ────────────────────────────────────────────

def _volatility(daily_closes) -> dict:
    if daily_closes is None or len(daily_closes) < 30:
        return {"score": 0, "value": None, "note": "N/A"}
    returns = daily_closes.pct_change().dropna().iloc[-30:]
    vol_ann = round(float(returns.std()) * math.sqrt(365) * 100, 1)
    if vol_ann <= 60:
        return {"score": 1, "value": vol_ann, "note": f"{vol_ann}%/год — умеренная волатильность"}
    else:
        return {"score": 0, "value": vol_ann, "note": f"{vol_ann}%/год — высокая волатильность"}


# ── MAIN ENTRY POINT ──────────────────────────────────────────────────────────

def analyze(data: dict) -> dict:
    info = data.get("info", {})
    daily_closes = data.get("daily_closes")

    mc    = _market_cap(info)
    ret1y = _return_1y(daily_closes)
    liq   = _liquidity(info)
    sup   = _supply_health(info)
    vol   = _volatility(daily_closes)

    total = mc["score"] + ret1y["score"] + liq["score"] + sup["score"] + vol["score"]

    data_available = sum(1 for c in [mc, ret1y, liq] if c["value"] is not None)

    if data_available < 2:
        grade = "INSUFFICIENT_DATA"
    elif total >= 6:
        grade = "STRONG"
    elif total >= 4:
        grade = "ADEQUATE"
    elif total >= 1:
        grade = "WEAK"
    else:
        grade = "POOR"

    name = info.get("longName") or info.get("shortName") or info.get("symbol", "?")

    return {
        "score":     total,
        "max_score": 8,
        "grade":     grade,
        "sector":    "Cryptocurrency",
        "name":      name,
        "is_crypto": True,
        "breakdown": {
            "market_cap":    mc,
            "return_1y":     ret1y,
            "liquidity":     liq,
            "supply_health": sup,
            "volatility":    vol,
        },
        "summary": f"{name} (CRYPTO): {total}/8 — {grade}",
    }
