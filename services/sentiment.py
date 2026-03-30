from openai import OpenAI

client = OpenAI()

def sentiment_analysis(ticker):
    # Добавляем контекст "финансового аналитика" и жесткие рамки
    system_prompt = (
        "You are a professional financial analyst. "
        "Your response must be exactly one word: 'Positive', 'Neutral', or 'Negative'. "
        "Do not provide any reasoning or extra text."
    )
    
    user_prompt = f"Analyze sentiment for {ticker} based on recent market trends."

    response = client.chat.completions.create(
        model="gpt-4o", # Убедитесь, что используете актуальную модель
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0, # Нулевая температура делает ответы предсказуемыми
        max_tokens=10  # Ограничиваем ответ парой слов
    )

    return response.choices[0].message.content.strip()
