def make_decision(fundamental, technical, sentiment):
    score = 0

    # 1. Fundamental
    # Если это ETF (0 баллов), даем +1 за надежность индекса
    if fundamental["score"] == 0:
        score += 1
    else:
        score += fundamental["score"]

    # 2. Technical
    if technical["signal"] == "bullish":
        # Бонус за экстремальную перепроданность (панику)
        if technical.get("rsi", 50) < 25:
            score += 2  # Итого +2 за технику
        else:
            score += 1
    elif technical["signal"] == "mildbullish":
        score += 0.5 # Небольшой плюс за накопление
    elif technical["signal"] == "bearish":
        score -= 1

    # 3. Sentiment
    if "positive" in sentiment.lower():
        score += 1
    elif "negative" in sentiment.lower():
        score -= 1

    # Пороги (score 3 — отличная покупка)
    if score >= 3:
        decision = "BUY"
    elif score <= 0:
        decision = "SELL"
    else:
        decision = "HOLD"

    return {
        "decision": decision,
        "score": score
    }
