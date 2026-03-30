import asyncio
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Вставьте ваш токен от BotFather
TOKEN = "8138900501:AAGfj-XwK0w3L12q3xqCfLaLriiMRrDsQTE"
# URL вашего запущенного API
API_URL = "http://127.0.0.1:8000/analyze/"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Пришли мне тикер (например, NVDA или VOO), и я проанализирую его для твоей стратегии.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ticker = update.message.text.upper().strip()
    await update.message.reply_text(f"🔍 Анализирую {ticker}...")

    try:
        # Опрашиваем ваш локальный API
        response = requests.get(f"{API_URL}{ticker}")
        if response.status_code == 200:
            data = response.json()
            
            # Формируем красивый ответ
            decision = data['decision']['decision']
            score = data['decision']['score']
            rsi = round(data['technical']['rsi'], 2)
            signal = data['technical']['signal']
            
            # Эмодзи для наглядности
            emoji = "🚀" if decision == "BUY" else "⚖️" if decision == "HOLD" else "⚠️"
            
            text = (
                f"{emoji} *Вердикт: {decision}*\n"
                f"📈 Счет: {score}\n\n"
                f"🔹 *Техника:* RSI {rsi} ({signal})\n"
                f"🔹 *Фундаментал:* {data['fundamental']['score']}/3\n"
                f"🔹 *Сентимент:* {data['sentiment']}"
            )
            await update.message.reply_text(text, parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Ошибка: Тикер не найден или API недоступен.")
    except Exception as e:
        await update.message.reply_text(f"💥 Произошла ошибка: {e}")

if __name__ == "__main__":
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Бот запущен...")
    application.run_polling()
