

from utils.indicators import calculate_rsi

def technical_analysis(price_df):
    df = price_df.copy()
    df['rsi'] = calculate_rsi(df)
    latest = df.iloc[-1]

    rsi = float(latest['rsi'])

    # Расширенная логика сигнала
    if rsi < 30:
        signal = "bullish"  # Сильный сигнал к покупке (перепродан)
    elif rsi < 40:
        signal = "mildbullish" # Начало накопления
    elif rsi > 70:
        signal = "bearish"  # Сильный сигнал к продаже (перегрет)
    elif rsi > 60:
        signal = "mildbearish" # Осторожность
    else:
        signal = "neutral"

    return {
        "rsi": rsi,
        "signal": signal
    }
