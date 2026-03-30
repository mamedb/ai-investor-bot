def make_decision(fundamental, technical, sentiment):
    score = 0

    # Fundamental 2
    score += fundamental["score"]

    # Technical 2
    if technical["signal"] == "bullish":
        score += 1
    elif technical["signal"] == "bearish":
        score -= 1

    # Sentiment 2
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
