from utils.indicators import calculate_rsi

def technical_analysis(price_df):
    df = price_df.copy()

    df['rsi'] = calculate_rsi(df)

    latest = df.iloc[-1]

    signal = "neutral"

    if latest['rsi'] < 30:
        signal = "bullish"
    elif latest['rsi'] > 70:
        signal = "bearish"

    return {
        "rsi": float(latest['rsi']),
        "signal": signal
    }
