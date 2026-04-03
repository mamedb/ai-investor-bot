"""
services/sentiment_analysis.py
--------------------------------
Long-term sentiment scoring (0–5 points) using three sources:

  1. Analyst consensus        (0–2 pts)  — recommendationMean from yfinance
  2. Insider transactions     (0–2 pts)  — net insider buying over 6 months
  3. Institutional ownership  (0–1 pt)   — top holders increasing positions

No additional API keys required — all data from yfinance.

Returns:
  {
    "score": int,          # 0–5 composite
    "label": str,          # "BULLISH" | "NEUTRAL" | "BEARISH"
    "breakdown": dict,     # per-source scores + raw values
    "summary": str         # one-line verdict for bot message
  }
"""

import pandas as pd
from datetime import datetime, timedelta


# ── CRITERION 1: Analyst Consensus ────────────────────────────────────────────
#
# yfinance recommendationMean scale:
#   1.0 = Strong Buy
#   2.0 = Buy
#   3.0 = Hold
#   4.0 = Underperform
#   5.0 = Sell

def _analyst_consensus(info: dict) -> dict:
    """
    2 pts: mean recommendation ≤ 2.0 (Buy or Strong Buy)
    1 pt:  mean recommendation ≤ 2.8 (leaning Buy)
    0 pts: Hold / Sell / unavailable
    """
    mean = info.get("recommendationMean")
    count = info.get("numberOfAnalystOpinions", 0)

    if mean is None or count == 0:
        return {"score": 0, "value": None, "count": 0, "note": "Нет данных аналитиков"}

    mean = round(float(mean), 2)

    label_map = {
        (1.0, 1.5): "Strong Buy",
        (1.5, 2.0): "Buy",
        (2.0, 2.5): "Weak Buy",
        (2.5, 3.5): "Hold",
        (3.5, 5.0): "Sell/Underperform",
    }
    rec_label = "Unknown"
    for (lo, hi), lbl in label_map.items():
        if lo <= mean < hi:
            rec_label = lbl
            break

    if mean <= 2.0:
        score = 2
    elif mean <= 2.8:
        score = 1
    else:
        score = 0

    return {
        "score": score,
        "value": mean,
        "count": count,
        "label": rec_label,
        "note": f"{rec_label} (mean {mean}, {count} аналитиков)",
    }


# ── CRITERION 2: Insider Transactions ────────────────────────────────────────
#
# Net insider activity over last 6 months.
# Buys by insiders = strong long-term conviction signal.
# Sales are less meaningful (insiders sell for many reasons).

def _insider_transactions(txns) -> dict:
    """
    2 pts: net insider buying (buys > sells in last 6mo)
    1 pt:  neutral (minimal activity or balanced)
    0 pts: net insider selling
    """
    if txns is None or txns.empty:
        return {"score": 1, "value": None, "note": "Нет данных по инсайдерам"}

    # filter to last 6 months
    cutoff = datetime.now() - timedelta(days=180)
    try:
        txns["Start Date"] = pd.to_datetime(
            txns["Start Date"], errors="coerce")
        recent = txns[txns["Start Date"] >= cutoff]
    except Exception:
        recent = txns

    if recent.empty:
        return {"score": 1, "value": None, "note": "Нет сделок инсайдеров за 6 мес"}

    # classify transactions
    try:
        is_buy = recent["Text"].str.contains(
            "Purchase|Buy|Acquisition", case=False, na=False)
        is_sell = recent["Text"].str.contains(
            "Sale|Sell|Disposed", case=False, na=False)
    except Exception:
        return {"score": 1, "value": None, "note": "Не удалось разобрать транзакции"}

    buy_count = int(is_buy.sum())
    sell_count = int(is_sell.sum())
    net = buy_count - sell_count

    if net > 0:
        score = 2
        note = f"Чистые покупки: +{net} (куплено {buy_count}, продано {sell_count})"
    elif net == 0:
        score = 1
        note = f"Нейтрально: {buy_count} покупок / {sell_count} продаж"
    else:
        score = 0
        note = f"Чистые продажи: {net} (куплено {buy_count}, продано {sell_count})"

    return {"score": score, "value": net, "buy": buy_count, "sell": sell_count, "note": note}


# ── CRITERION 3: Institutional Ownership ─────────────────────────────────────
#
# We check whether the top institutional holders have been increasing
# their positions. yfinance provides a snapshot — we use pctHeld
# as a proxy for institutional conviction.

def _institutional_ownership(info: dict, institutional_holders) -> dict:
    """
    1 pt:  institutional ownership ≥ 60% (high smart-money conviction)
            OR top holder count increasing (if data available)
    0 pts: low institutional interest or unavailable
    """
    pct_held = info.get("institutionsPercentHeld")

    # fallback: compute from institutional_holders table
    if pct_held is None:
        try:
            holders = institutional_holders
            if holders is not None and not holders.empty and "% Out" in holders.columns:
                pct_held = float(holders["% Out"].iloc[0]) / 100
        except Exception:
            pass

    if pct_held is None:
        return {"score": 0, "value": None, "note": "Нет данных институционалов"}

    pct = round(float(pct_held) * 100, 1)

    if pct >= 60:
        return {"score": 1, "value": pct, "note": f"{pct}% институционального владения — высокое"}
    elif pct >= 30:
        return {"score": 0, "value": pct, "note": f"{pct}% — умеренное владение"}
    else:
        return {"score": 0, "value": pct, "note": f"{pct}% — низкий интерес институционалов"}


# ── LABEL MAPPER ──────────────────────────────────────────────────────────────

def _score_to_label(score: int) -> str:
    if score >= 4:
        return "BULLISH"
    elif score >= 2:
        return "NEUTRAL"
    else:
        return "BEARISH"


# ── MAIN ENTRY POINT ──────────────────────────────────────────────────────────

def analyze(data: dict) -> dict:
    """
    Run full sentiment analysis using pre-fetched data.
    Never raises — returns partial data with score=0 if sources fail.
    """
    info = data.get("info") or {}

    analyst = _analyst_consensus(info)
    insider = _insider_transactions(data.get("insider_transactions"))
    inst = _institutional_ownership(info, data.get("institutional_holders"))

    total = analyst["score"] + insider["score"] + inst["score"]
    total = max(0, min(5, total))

    label = _score_to_label(total)

    # count sources with real data
    has_data = sum(1 for c in [analyst, insider, inst]
                   if c.get("value") is not None)
    if has_data == 0:
        label = "NEUTRAL"  # can't say anything meaningful

    summary_parts = []
    if analyst.get("label"):
        summary_parts.append(f"Аналитики: {analyst['label']}")
    if insider.get("value") is not None:
        net = insider["value"]
        summary_parts.append(
            f"Инсайдеры: {'покупают' if net > 0 else 'продают' if net < 0 else 'нейтрально'}")
    if inst.get("value") is not None:
        summary_parts.append(f"Институционалы: {inst['value']}%")

    summary = " | ".join(
        summary_parts) if summary_parts else "Данные сентимента недоступны"

    return {
        "score":   total,
        "max":     5,
        "label":   label,
        "breakdown": {
            "analyst": analyst,
            "insider": insider,
            "institutional": inst,
        },
        "summary": summary,
    }
