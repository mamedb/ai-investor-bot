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
    # ── Decision ──────────────────────────────────────────────────────────────
    dec = data['decision']
    decision = dec['decision']
    score = dec['score']
    confidence = dec.get('confidence', 'N/A')
    reason = dec.get('reason', '')
    flags = dec.get('flags', [])
    pillars = dec.get('pillar_scores', {})

    emoji_map = {"STRONG_BUY": "🚀", "BUY": "✅", "HOLD": "⚖️", "AVOID": "🚫"}
    conf_map = {"HIGH": "🔵", "MEDIUM": "🟡", "LOW": "⚪"}
    emoji = emoji_map.get(decision, "❓")
    conf_emoji = conf_map.get(confidence, "⚪")

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
    tech_sc = pillars.get('technical', {}).get('score', tech.get('score', '?'))
    w52_pct = f"{round(w52_pos * 100)}%" if w52_pos is not None else "N/A"

    # ── Fundamental ──────────────────────────────────────────────────────────
    fund = data['fundamental']
    fund_sc = pillars.get('fundamental', {}).get(
        'score', fund.get('score', '?'))
    fund_grade = fund.get('grade', '')
    breakdown = fund.get('breakdown', {})

    def fmt_f(label, key):
        c = breakdown.get(key, {})
        sc = c.get('score', 0)
        note = c.get('note', 'N/A')
        dot = "🟢" if sc >= 2 else "🟡" if sc == 1 else "🔴"
        return f"  {dot} {label}: {note}"

    fund_lines = "\n".join([
        fmt_f("Выручка",  "revenue_growth"),
        fmt_f("EPS",      "eps_trend"),
        fmt_f("P/E",      "pe_vs_sector"),
        fmt_f("Долг/Кап", "debt_equity"),
        fmt_f("Маржа",    "profit_margin"),
        fmt_f("FCF",      "free_cash_flow"),
    ])

    # ── Sentiment ────────────────────────────────────────────────────────────
    sent = data.get('sentiment', {})
    sent_sc = pillars.get('sentiment', {}).get('score', sent.get('score', '?'))
    sent_lbl = sent.get('label', 'N/A') if isinstance(sent,
                                                      dict) else str(sent)
    sent_bd = sent.get('breakdown', {}) if isinstance(sent, dict) else {}

    def fmt_s(label, key):
        c = sent_bd.get(key, {})
        sc = c.get('score', 0)
        note = c.get('note', 'N/A')
        max_sc = 2 if key != 'institutional' else 1
        dot = "🟢" if sc >= max_sc else "🟡" if sc > 0 else "🔴"
        return f"  {dot} {label}: {note}"

    sent_lines = "\n".join([
        fmt_s("Аналитики",     "analyst"),
        fmt_s("Инсайдеры",     "insider"),
        fmt_s("Институционалы", "institutional"),
    ])

    # ── Flags ─────────────────────────────────────────────────────────────────
    flags_block = ""
    if flags:
        flags_block = "━━━━━━━━━━━━━━━\n⚑ *Флаги:*\n" + \
            "\n".join(f"  {f}" for f in flags) + "\n"

    total_max = 5 + 8 + 5

    text = (
        f"{emoji} *{decision}* {conf_emoji} уверенность: {confidence}\n"
        f"📊 Итог: {score}/{total_max} | {reason}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📈 *Техника* ({tech_sc}/5)\n"
        f"  • Тренд: {trend} (цена {price} / SMA200 {sma200})\n"
        f"  • RSI weekly: {rsi} — {signal}\n"
        f"  • 52w: {w52_lo}–{w52_hi} | {w52_pct} ({w52_sig})\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏦 *Фундаментал* ({fund_sc}/8 — {fund_grade})\n"
        f"{fund_lines}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📰 *Сентимент* ({sent_sc}/5 — {sent_lbl})\n"
        f"{sent_lines}\n"
        f"{flags_block}"
    )
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
