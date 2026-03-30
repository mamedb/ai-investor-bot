def fundamental_analysis(info):
    score = 0

    pe = info.get("trailingPE", None)
    growth = info.get("revenueGrowth", 0)

    if pe and pe < 20:
        score += 1

    if growth and growth > 0.1:
        score += 1

    if info.get("debtToEquity", 100) < 100:
        score += 1

    return {
        "score": score,
        "max_score": 3
    }
