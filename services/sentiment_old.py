from openai import OpenAI

client = OpenAI()

def sentiment_analysis(ticker):
    prompt = f"""
    Analyze sentiment for stock {ticker}.
    Return: positive, neutral, or negative.
    """

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content.strip()
