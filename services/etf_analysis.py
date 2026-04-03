"""
services/etf_analysis.py
--------------------------
ETF-specific scoring (0–8 points), used instead of fundamental_analysis
when the ticker quoteType is 'ETF'.

Criteria:
  1. Expense ratio     (0–2 pts) — lower is better
  2. AUM               (0–2 pts) — size / liquidity proxy
  3. 1-year return     (0–2 pts) — computed from daily_closes
  4. Dividend yield    (0–1 pt)
  5. 5-year avg return (0–1 pt)  — from yfinance info

Returns the same shape as fundamental_analysis so decision_engine
and tg_bot can handle both uniformly.
"""


# ── CRITERION 1: Expense Ratio ────────────────────────────────────────────────

def _expense_ratio(info: dict) -> dict:
    er = info.get("netExpenseRatio") or info.get("annualReportExpenseRatio") or info.get("expenseRatio")
    if er is None:
        return {"score": 0, "value": None, "note": "N/A"}
    er = float(er)
    # netExpenseRatio uses percent form (0.03 = 0.03%);
    # legacy keys use fraction form (0.0003 = 0.03%) — detect by magnitude
    er_pct = round(er if er >= 0.01 else er * 100, 3)
    if er_pct <= 0.10:
        return {"score": 2, "value": er_pct, "note": f"{er_pct}% — очень низкий"}
    elif er_pct <= 0.50:
        return {"score": 1, "value": er_pct, "note": f"{er_pct}% — умеренный"}
    else:
        return {"score": 0, "value": er_pct, "note": f"{er_pct}% — высокий"}


# ── CRITERION 2: AUM ──────────────────────────────────────────────────────────

def _aum(info: dict) -> dict:
    total_assets = info.get("totalAssets")
    if total_assets is None:
        return {"score": 0, "value": None, "note": "N/A"}
    aum_b = round(float(total_assets) / 1e9, 1)
    if aum_b >= 10:
        return {"score": 2, "value": aum_b, "note": f"${aum_b}B — крупный фонд"}
    elif aum_b >= 1:
        return {"score": 1, "value": aum_b, "note": f"${aum_b}B — средний фонд"}
    else:
        return {"score": 0, "value": aum_b, "note": f"${aum_b}B — небольшой фонд"}


# ── CRITERION 3: 1-Year Price Return ─────────────────────────────────────────

def _return_1y(daily_closes) -> dict:
    if daily_closes is None or len(daily_closes) < 20:
        return {"score": 0, "value": None, "note": "N/A"}
    window = daily_closes.iloc[-252:] if len(daily_closes) >= 252 else daily_closes
    r = round((float(window.iloc[-1]) / float(window.iloc[0]) - 1) * 100, 1)
    if r >= 15:
        return {"score": 2, "value": r, "note": f"+{r}% — отличный результат"}
    elif r >= 0:
        return {"score": 1, "value": r, "note": f"+{r}% — положительный"}
    else:
        return {"score": 0, "value": r, "note": f"{r}% — отрицательный"}


# ── CRITERION 4: Dividend Yield ───────────────────────────────────────────────

def _dividend_yield(info: dict) -> dict:
    dy = info.get("yield") or info.get("trailingAnnualDividendYield") or info.get("dividendYield")
    if dy is None:
        return {"score": 0, "value": None, "note": "Дивиденды не выплачиваются"}
    dy_pct = round(float(dy) * 100, 2)
    if dy_pct >= 1.0:
        return {"score": 1, "value": dy_pct, "note": f"{dy_pct}% дивидендная доходность"}
    else:
        return {"score": 0, "value": dy_pct, "note": f"{dy_pct}% — низкие дивиденды"}


# ── CRITERION 5: 5-Year Average Annual Return ─────────────────────────────────

def _return_5y(info: dict) -> dict:
    r5 = info.get("fiveYearAverageReturn")
    if r5 is None:
        return {"score": 0, "value": None, "note": "N/A"}
    r5_pct = round(float(r5) * 100, 1)
    if r5_pct >= 7.0:
        return {"score": 1, "value": r5_pct, "note": f"{r5_pct}%/год — выше среднего"}
    else:
        return {"score": 0, "value": r5_pct, "note": f"{r5_pct}%/год — ниже 7%"}


# ── MAIN ENTRY POINT ──────────────────────────────────────────────────────────

def analyze(data: dict) -> dict:
    info = data.get("info", {})
    daily_closes = data.get("daily_closes")

    er = _expense_ratio(info)
    aum = _aum(info)
    ret1y = _return_1y(daily_closes)
    dy = _dividend_yield(info)
    ret5y = _return_5y(info)

    total = er["score"] + aum["score"] + ret1y["score"] + dy["score"] + ret5y["score"]

    data_available = sum(1 for c in [er, aum, ret1y, dy, ret5y] if c["value"] is not None)

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

    name = info.get("longName") or info.get("shortName") or "Unknown"
    category = info.get("category") or info.get("fundFamily") or "ETF"

    return {
        "score":     total,
        "max_score": 8,
        "grade":     grade,
        "sector":    category,
        "name":      name,
        "is_etf":    True,
        "breakdown": {
            "expense_ratio":  er,
            "aum":            aum,
            "return_1y":      ret1y,
            "dividend_yield": dy,
            "return_5y":      ret5y,
        },
        "summary": f"{name} (ETF): {total}/8 — {grade}",
    }
