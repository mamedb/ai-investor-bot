def make_decision(fundamental, technical, sentiment):
    score = 0

    # Fundamental
    score += fundamental["score"]

    # Technical
    if technical["signal"] == "bullish":
        score += 1
    elif technical["signal"] == "bearish":
        score -= 1

    # Sentiment
    if "positive" in sentiment.lower():
        score += 1
    elif "negative" in sentiment.lower():
        score -= 1

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
