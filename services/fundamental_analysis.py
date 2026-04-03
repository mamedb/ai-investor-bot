"""
services/fundamental_analysis.py
----------------------------------
Long-term fundamental scoring system (0–8 points).

Criteria:
  1. Revenue growth YoY        (0–2 pts)
  2. EPS trend 3-year          (0–2 pts)
  3. P/E vs sector median      (0–1 pt)
  4. Debt/Equity ratio         (0–1 pt)
  5. Profit margin             (0–1 pt)
  6. Free cash flow positive   (0–1 pt)

All data sourced from yfinance (no additional API keys required).

Returns:
  {
    "score": int,              # 0–8 composite
    "max_score": 8,
    "grade": str,              # "STRONG" | "ADEQUATE" | "WEAK" | "INSUFFICIENT_DATA"
    "breakdown": dict,         # per-criterion scores + raw values
    "summary": str             # one-line verdict
  }
"""

import numpy as np


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _safe_get(info: dict, *keys, default=None):
    """Try multiple key aliases, return first non-None value."""
    for k in keys:
        v = info.get(k)
        if v is not None and v != "N/A":
            return v
    return default


def _pct_change(new, old):
    if old and old != 0:
        return (new - old) / abs(old)
    return None


# ── CRITERION 1: Revenue Growth YoY ──────────────────────────────────────────

def _revenue_growth(info: dict, financials) -> dict:
    """
    2 pts: >15% YoY revenue growth
    1 pt:  >0% (positive but moderate)
    0 pts: negative or unavailable
    """
    # prefer pre-computed value from info
    growth = _safe_get(info, "revenueGrowth")

    # fallback: compute from financials if available
    if growth is None and financials is not None and not financials.empty:
        try:
            rows = financials.loc["Total Revenue"] if "Total Revenue" in financials.index else None
            if rows is not None and len(rows) >= 2:
                growth = _pct_change(float(rows.iloc[0]), float(rows.iloc[1]))
        except Exception:
            pass

    if growth is None:
        return {"score": 0, "value": None, "note": "N/A"}

    growth_pct = round(growth * 100, 1)
    if growth > 0.15:
        return {"score": 2, "value": growth_pct, "note": f"+{growth_pct}% — strong"}
    elif growth > 0:
        return {"score": 1, "value": growth_pct, "note": f"+{growth_pct}% — moderate"}
    else:
        return {"score": 0, "value": growth_pct, "note": f"{growth_pct}% — declining"}


# ── CRITERION 2: EPS Trend (3-year) ──────────────────────────────────────────

def _eps_trend(info: dict, financials) -> dict:
    """
    2 pts: EPS grew in both of last 2 annual periods
    1 pt:  EPS grew in 1 of 2 periods
    0 pts: declining or unavailable
    """
    eps_data = []

    if financials is not None and not financials.empty:
        try:
            label = next(
                (l for l in financials.index if "EPS" in l or "Earnings Per Share" in l),
                None
            )
            if label:
                eps_data = [
                    float(v) for v in financials.loc[label].iloc[:3] if v is not None]
        except Exception:
            pass

    # fallback to trailing/forward EPS from info
    if len(eps_data) < 2:
        trailing = _safe_get(info, "trailingEps")
        forward = _safe_get(info, "forwardEps")
        if trailing and forward:
            # forward > trailing means expected growth
            eps_data = [forward, trailing]

    if len(eps_data) < 2:
        return {"score": 0, "value": None, "note": "N/A"}

    gains = sum(1 for i in range(len(eps_data) - 1)
                if eps_data[i] > eps_data[i + 1])
    periods = len(eps_data) - 1

    if gains == periods:
        return {"score": 2, "value": eps_data, "note": "Consistently growing"}
    elif gains > 0:
        return {"score": 1, "value": eps_data, "note": "Mixed EPS trend"}
    else:
        return {"score": 0, "value": eps_data, "note": "Declining EPS"}


# ── CRITERION 3: P/E vs Sector ────────────────────────────────────────────────

# Rough sector median P/E benchmarks (2024 estimates)
SECTOR_PE = {
    "Technology":             28,
    "Healthcare":             22,
    "Financial Services":     14,
    "Consumer Cyclical":      20,
    "Consumer Defensive":     18,
    "Energy":                 12,
    "Industrials":            20,
    "Basic Materials":        15,
    "Real Estate":            35,
    "Communication Services": 20,
    "Utilities":              18,
}
DEFAULT_PE = 20


def _pe_vs_sector(info: dict) -> dict:
    """
    1 pt: trailing P/E below sector median (value signal)
    0 pts: above median, negative, or unavailable
    """
    pe = _safe_get(info, "trailingPE", "forwardPE")
    sector = _safe_get(info, "sector", default="Unknown")
    median = SECTOR_PE.get(sector, DEFAULT_PE)

    if pe is None or pe <= 0:
        return {"score": 0, "value": None, "note": "P/E unavailable"}

    pe = round(float(pe), 1)
    if pe < median:
        return {"score": 1, "value": pe, "note": f"P/E {pe} < sector median {median}"}
    else:
        return {"score": 0, "value": pe, "note": f"P/E {pe} ≥ sector median {median}"}


# ── CRITERION 4: Debt/Equity ─────────────────────────────────────────────────

def _debt_equity(info: dict) -> dict:
    """
    1 pt: D/E < 1.0 (manageable leverage)
    0 pts: ≥ 1.0, negative equity, or unavailable
    Note: financials/REITs naturally run higher D/E — sector context matters.
    """
    de = _safe_get(info, "debtToEquity")

    if de is None:
        return {"score": 0, "value": None, "note": "D/E unavailable"}

    # yfinance returns as percentage (e.g. 45.3 = 0.453)
    de = round(float(de) / 100, 2)
    if de < 1.0:
        return {"score": 1, "value": de, "note": f"D/E {de} — manageable"}
    else:
        return {"score": 0, "value": de, "note": f"D/E {de} — elevated"}


# ── CRITERION 5: Profit Margin ────────────────────────────────────────────────

def _profit_margin(info: dict) -> dict:
    """
    1 pt: net profit margin > 15%
    0 pts: below threshold or unavailable
    """
    margin = _safe_get(info, "profitMargins")

    if margin is None:
        return {"score": 0, "value": None, "note": "Margin unavailable"}

    margin_pct = round(float(margin) * 100, 1)
    if margin > 0.15:
        return {"score": 1, "value": margin_pct, "note": f"{margin_pct}% — healthy"}
    elif margin > 0:
        return {"score": 0, "value": margin_pct, "note": f"{margin_pct}% — below threshold"}
    else:
        return {"score": 0, "value": margin_pct, "note": f"{margin_pct}% — negative"}


# ── CRITERION 6: Free Cash Flow ───────────────────────────────────────────────

def _free_cash_flow(info: dict, cashflow) -> dict:
    """
    1 pt: FCF positive (company generates real cash)
    0 pts: negative or unavailable
    """
    fcf = _safe_get(info, "freeCashflow")

    if fcf is None and cashflow is not None and not cashflow.empty:
        try:
            label = next(
                (l for l in cashflow.index if "Free Cash Flow" in l),
                None
            )
            if label:
                fcf = float(cashflow.loc[label].iloc[0])
        except Exception:
            pass

    if fcf is None:
        return {"score": 0, "value": None, "note": "FCF unavailable"}

    fcf_b = round(fcf / 1e9, 2)
    if fcf > 0:
        return {"score": 1, "value": fcf_b, "note": f"${fcf_b}B FCF — positive"}
    else:
        return {"score": 0, "value": fcf_b, "note": f"${fcf_b}B FCF — negative"}


# ── MAIN ENTRY POINT ──────────────────────────────────────────────────────────

def analyze(data: dict) -> dict:
    """
    Run full 8-point fundamental analysis using pre-fetched data.
    """
    info = data["info"]
    financials = data.get("financials")
    cashflow = data.get("cashflow")

    if not info:
        raise ValueError("No fundamental data available")

    # --- run each criterion ---
    rev = _revenue_growth(info, financials)
    eps = _eps_trend(info, financials)
    pe = _pe_vs_sector(info)
    de = _debt_equity(info)
    margin = _profit_margin(info)
    fcf = _free_cash_flow(info, cashflow)

    total = rev["score"] + eps["score"] + pe["score"] + \
        de["score"] + margin["score"] + fcf["score"]

    if total >= 6:
        grade = "STRONG"
    elif total >= 4:
        grade = "ADEQUATE"
    elif total >= 1:
        grade = "WEAK"
    else:
        grade = "POOR"

    # count how many criteria had real data
    data_available = sum(
        1 for c in [rev, eps, pe, de, margin, fcf] if c["value"] is not None)
    if data_available < 3:
        grade = "INSUFFICIENT_DATA"

    sector = _safe_get(info, "sector", default="Unknown")
    name = _safe_get(info, "longName", "shortName", default=ticker)

    summary = f"{name} ({sector}): {total}/8 — {grade}"

    return {
        "score": total,
        "max_score": 8,
        "grade": grade,
        "sector": sector,
        "name": name,
        "breakdown": {
            "revenue_growth": rev,
            "eps_trend":      eps,
            "pe_vs_sector":   pe,
            "debt_equity":    de,
            "profit_margin":  margin,
            "free_cash_flow": fcf,
        },
        "summary": summary,
    }
