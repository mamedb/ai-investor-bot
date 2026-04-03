from typing import Optional

"""
services/decision_engine.py
-----------------------------
Multi-factor gate decision engine for long-term investing (6mo+ horizon).

Core principle: fundamentals can veto technicals, but not vice versa.

Input:
  technical:   dict from technical_analysis.analyze()
  fundamental: dict from fundamental_analysis.analyze()
  sentiment:   dict from sentiment_analysis.analyze()  (or legacy string)

Output:
  {
    "decision": "STRONG_BUY" | "BUY" | "HOLD" | "AVOID",
    "score": int,        # 0–18 composite across all three pillars
    "confidence": str,   # "HIGH" | "MEDIUM" | "LOW"
    "reason": str,       # primary reason for decision
    "flags": list[str],  # warning flags (e.g. "HIGH_DEBT", "OVERBOUGHT")
    "pillar_scores": dict
  }
"""


# ── THRESHOLDS ────────────────────────────────────────────────────────────────

TECH_MAX = 5
FUND_MAX = 8
SENT_MAX = 5   # sentiment will be scored 0–5 once that module is built
# for now we accept legacy string or partial dict

# Decision gates (minimum scores required per pillar)
GATES = {
    "STRONG_BUY": {"tech": 4, "fund": 6, "sent": 3, "total": 13},
    "BUY":        {"tech": 2, "fund": 4, "sent": 2, "total": 8},
    "HOLD":       {"tech": 1, "fund": 2, "sent": 1, "total": 4},
    # below HOLD thresholds → AVOID
}

# Hard veto conditions — trigger AVOID regardless of other scores
VETO_CONDITIONS = [
    ("fund_score_lt_2",  "Фундаментал критически слаб (< 2/8)"),
    ("downtrend_low_fund", "Нисходящий тренд + слабый фундаментал"),
    ("negative_fcf_negative_eps", "Отрицательные FCF и EPS одновременно"),
]


# ── SENTIMENT NORMALIZER ──────────────────────────────────────────────────────

def _normalize_sentiment(sentiment) -> dict:
    """
    Accept either:
      - legacy string: "Positive" / "Neutral" / "Negative"
      - new dict from sentiment_analysis.analyze()
    Returns {"score": int, "label": str}
    """
    if isinstance(sentiment, dict):
        return {
            "score": sentiment.get("score", 0),
            "label": sentiment.get("label", "N/A"),
        }

    # legacy string fallback
    mapping = {
        "positive":      {"score": 4, "label": "Positive"},
        "very positive": {"score": 5, "label": "Very Positive"},
        "neutral":       {"score": 2, "label": "Neutral"},
        "negative":      {"score": 1, "label": "Negative"},
        "very negative": {"score": 0, "label": "Very Negative"},
    }
    key = str(sentiment).lower().strip()
    return mapping.get(key, {"score": 2, "label": str(sentiment)})


# ── FLAG DETECTOR ─────────────────────────────────────────────────────────────

def _detect_flags(tech: dict, fund: dict, sent_score: int) -> list[str]:
    flags = []

    # Technical flags
    if tech.get("trend") == "DOWNTREND":
        flags.append("📉 DOWNTREND")
    if tech.get("signal") == "OVERBOUGHT":
        flags.append("🔥 OVERBOUGHT (weekly RSI)")
    if tech.get("week52_signal") == "NEAR_HIGH":
        flags.append("🏔 NEAR 52W HIGH — late entry risk")

    # Fundamental flags
    breakdown = fund.get("breakdown", {})

    de = breakdown.get("debt_equity", {})
    if de.get("value") is not None and float(de["value"]) >= 1.5:
        flags.append("⚠️ HIGH_DEBT (D/E ≥ 1.5)")

    fcf = breakdown.get("free_cash_flow", {})
    if fcf.get("score", 1) == 0 and fcf.get("value") is not None:
        flags.append("🚨 NEGATIVE_FCF")

    eps = breakdown.get("eps_trend", {})
    if eps.get("score", 1) == 0:
        flags.append("📊 DECLINING_EPS")

    margin = breakdown.get("profit_margin", {})
    if margin.get("value") is not None and float(margin["value"]) < 0:
        flags.append("🔴 NEGATIVE_MARGIN")

    if fund.get("grade") == "INSUFFICIENT_DATA":
        flags.append("ℹ️ LIMITED_FUND_DATA (ETF or data gap)")

    # Sentiment flags
    if sent_score <= 1:
        flags.append("📰 NEGATIVE_SENTIMENT")

    return flags


# ── VETO CHECK ────────────────────────────────────────────────────────────────

def _check_veto(tech: dict, fund: dict) -> Optional[str]:
    """Returns veto reason string if any veto condition is met, else None."""
    fund_score = fund.get("score", 0)
    breakdown = fund.get("breakdown", {})

    # Hard veto 1: fundamentals critically weak
    if fund_score < 2 and fund.get("grade") != "INSUFFICIENT_DATA":
        return "Фундаментал критически слаб (< 2/8)"

    # Hard veto 2: downtrend + weak fundamentals
    if tech.get("trend") == "DOWNTREND" and fund_score < 4:
        return "Нисходящий тренд при слабом фундаментале"

    # Hard veto 3: both FCF and EPS negative
    fcf_neg = breakdown.get("free_cash_flow", {}).get("score", 1) == 0
    eps_neg = breakdown.get("eps_trend", {}).get("score", 1) == 0
    if fcf_neg and eps_neg and fund.get("grade") != "INSUFFICIENT_DATA":
        return "Отрицательные FCF и EPS одновременно"

    return None


# ── CONFIDENCE ESTIMATOR ──────────────────────────────────────────────────────

def _confidence(tech: dict, fund: dict, sent_score: int) -> str:
    """
    HIGH:   all three pillars agree directionally
    MEDIUM: two pillars agree
    LOW:    mixed signals
    """
    tech_score = tech.get("score", 0)
    fund_score = fund.get("score", 0)

    tech_bull = tech_score >= 3
    fund_bull = fund_score >= 5
    sent_bull = sent_score >= 3

    bulls = sum([tech_bull, fund_bull, sent_bull])

    if bulls == 3:
        return "HIGH"
    elif bulls == 2:
        return "MEDIUM"
    else:
        return "LOW"


# ── MAIN ENTRY POINT ──────────────────────────────────────────────────────────

def decide(technical: dict, fundamental: dict, sentiment) -> dict:
    """
    Combine all three pillars into a single long-term investment decision.

    Args:
        technical:   output of technical_analysis.analyze()
        fundamental: output of fundamental_analysis.analyze()
        sentiment:   output of sentiment_analysis.analyze() OR legacy string
    """
    sent = _normalize_sentiment(sentiment)
    sent_score = sent["score"]

    tech_score = technical.get("score", 0)
    fund_score = fundamental.get("score", 0)
    total = tech_score + fund_score + sent_score

    pillar_scores = {
        "technical":   {"score": tech_score, "max": TECH_MAX},
        "fundamental": {"score": fund_score, "max": FUND_MAX},
        "sentiment":   {"score": sent_score, "max": SENT_MAX},
        "total":       {"score": total,      "max": TECH_MAX + FUND_MAX + SENT_MAX},
    }

    flags = _detect_flags(technical, fundamental, sent_score)

    # ── veto check first ──────────────────────────────────────────────────────
    veto_reason = _check_veto(technical, fundamental)
    if veto_reason:
        return {
            "decision":     "AVOID",
            "score":        total,
            "confidence":   "HIGH",   # confident it's a no
            "reason":       f"🚫 Veto: {veto_reason}",
            "flags":        flags,
            "pillar_scores": pillar_scores,
        }

    # ── gate logic ────────────────────────────────────────────────────────────
    g = GATES

    if (tech_score >= g["STRONG_BUY"]["tech"] and
        fund_score >= g["STRONG_BUY"]["fund"] and
        sent_score >= g["STRONG_BUY"]["sent"] and
            total >= g["STRONG_BUY"]["total"]):
        decision = "STRONG_BUY"
        reason = "Все три фактора сильные — отличная долгосрочная точка входа"

    elif (tech_score >= g["BUY"]["tech"] and
          fund_score >= g["BUY"]["fund"] and
          sent_score >= g["BUY"]["sent"] and
          total >= g["BUY"]["total"]):
        decision = "BUY"
        reason = "Два или более факторов положительные"

    elif (tech_score >= g["HOLD"]["tech"] and
          fund_score >= g["HOLD"]["fund"] and
          total >= g["HOLD"]["total"]):
        decision = "HOLD"
        reason = "Смешанные сигналы — удерживать позицию, не наращивать"

    else:
        decision = "AVOID"
        reason = "Недостаточно позитивных факторов для входа"

    confidence = _confidence(technical, fundamental, sent_score)

    # downgrade confidence if ETF data is limited
    if fundamental.get("grade") == "INSUFFICIENT_DATA":
        confidence = "LOW" if confidence == "HIGH" else confidence

    return {
        "decision":      decision,
        "score":         total,
        "confidence":    confidence,
        "reason":        reason,
        "flags":         flags,
        "pillar_scores": pillar_scores,
    }
