"""
tg_bot.py — updated message formatting for enriched technical response.
Only the handle_message function changes; everything else stays the same.
Replace the text = (...) block in your existing handle_message with this.
"""

# ── drop-in replacement for the text formatting block ─────────────────────────

import os
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram import Update
import requests
import asyncio


def format_response(data: dict) -> str:
    dec = data['decision']
    decision = dec['decision']
    score = dec['score']
    confidence = dec.get('confidence', 'N/A')
    reason = dec.get('reason', '')
    flags = dec.get('flags', [])
    pillars = dec.get('pillar_scores', {})

    # ── Technical ────────────────────────────────────────────────────────────
    tech = data['technical']
    rsi = round(tech['rsi'], 2)
    signal = tech['signal']
    trend = tech.get('trend', 'N/A')
    sma200 = tech.get('sma200', 'N/A')
    price = tech.get('price', 'N/A')
    w52_pos = tech.get('week52_position')
    w52_sig = tech.get('week52_signal', 'N/A')
    w52_hi = tech.get('week52_high', 'N/A')
    w52_lo = tech.get('week52_low', 'N/A')
    tech_sc = pillars.get('technical', {}).get(
        'score', tech.get('score', 'N/A'))
    w52_pct = f"{round(w52_pos * 100)}%" if w52_pos is not None else "N/A"

    # ── Fundamental ──────────────────────────────────────────────────────────
    fund = data['fundamental']
    fund_sc = pillars.get('fundamental', {}).get(
        'score', fund.get('score', 'N/A'))
    fund_grade = fund.get('grade', '')
    breakdown = fund.get('breakdown', {})

    def fmt_criterion(label, key):
        c = breakdown.get(key, {})
        sc = c.get('score', 0)
        note = c.get('note', 'N/A')
        dot = "🟢" if sc >= 2 else "🟡" if sc == 1 else "🔴"
        return f"  {dot} {label}: {note}"

    fund_lines = "\n".join([
        fmt_criterion("Выручка",   "revenue_growth"),
        fmt_criterion("EPS",       "eps_trend"),
        fmt_criterion("P/E",       "pe_vs_sector"),
        fmt_criterion("Долг/Кап",  "debt_equity"),
        fmt_criterion("Маржа",     "profit_margin"),
        fmt_criterion("FCF",       "free_cash_flow"),
    ])

    # ── Sentiment ────────────────────────────────────────────────────────────
    sent_raw = data.get('sentiment', {})
    if isinstance(sent_raw, dict):
        sent_label = sent_raw.get('label', 'N/A')
        sent_sc = sent_raw.get('score', 'N/A')
    else:
        sent_label = str(sent_raw)
        sent_sc = pillars.get('sentiment', {}).get('score', 'N/A')

    # ── Decision header ───────────────────────────────────────────────────────
    emoji_map = {
        "STRONG_BUY": "🚀",
        "BUY":        "✅",
        "HOLD":       "⚖️",
        "AVOID":      "🚫",
    }
    conf_map = {"HIGH": "🔵", "MEDIUM": "🟡", "LOW": "⚪"}
    emoji = emoji_map.get(decision, "❓")
    conf_emoji = conf_map.get(confidence, "⚪")

    total_max = 5 + 8 + 5  # tech + fund + sent

    # ── Flags block ───────────────────────────────────────────────────────────
    flags_block = ""
    if flags:
        flags_block = "⚑ *Флаги:*\n" + \
            "\n".join(f"  {f}" for f in flags) + "\n"

    text = (
        f"{emoji} *{decision}* {conf_emoji} уверенность: {confidence}\n"
        f"📊 Итог: {score}/{total_max} | Причина: {reason}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📈 *Техника* ({tech_sc}/5)\n"
        f"  • Тренд: {trend} (цена {price} / SMA200 {sma200})\n"
        f"  • RSI (weekly): {rsi} — {signal}\n"
        f"  • 52w: {w52_lo}–{w52_hi} | {w52_pct} ({w52_sig})\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏦 *Фундаментал* ({fund_sc}/8 — {fund_grade})\n"
        f"{fund_lines}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📰 *Сентимент* ({sent_sc}/5): {sent_label}\n"
    )

    if flags_block:
        text += f"━━━━━━━━━━━━━━━\n{flags_block}"

    return text


# ── updated handle_message ────────────────────────────────────────────────────


TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")   # ← move to .env
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000/analyze/")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Пришли мне тикер (например, NVDA или VOO), "
        "и я проанализирую его для долгосрочной стратегии."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ticker = update.message.text.upper().strip()
    await update.message.reply_text(f"🔍 Анализирую {ticker}...")

    try:
        response = requests.get(f"{API_URL}{ticker}", timeout=15)
        if response.status_code == 200:
            data = response.json()
            text = format_response(data)
            await update.message.reply_text(text, parse_mode="Markdown")
        elif response.status_code == 404:
            await update.message.reply_text(f"❌ Тикер `{ticker}` не найден.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ API вернул ошибку {response.status_code}.")
    except requests.exceptions.Timeout:
        await update.message.reply_text("⏱ Таймаут — API не ответил за 15 секунд.")
    except Exception as e:
        await update.message.reply_text(f"💥 Ошибка: {e}")


if __name__ == "__main__":
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    application.run_polling()
