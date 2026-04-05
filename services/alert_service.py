"""
services/alert_service.py
--------------------------
Background alert checker.

Alert types:
  price_below  — notify when price drops at or below threshold
  price_above  — notify when price rises at or above threshold
  buy_signal   — notify when full analysis returns BUY or STRONG_BUY
  avoid_signal — notify when full analysis returns AVOID

Schedule (runs as a long-lived asyncio task):
  Price alerts : every 30 minutes  (cheap — yfinance fast_info only)
  Score alerts : every 6 hours     (expensive — full analysis pipeline)

Alerts are one-shot: deactivated after firing to prevent repeat spam.
Notifications are sent to every Telegram chat_id in the telegram_chats table.
"""

import asyncio
import logging
import os
import time
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)


# ── Telegram helper ───────────────────────────────────────────────────────────

async def _send_telegram_message(message: str) -> None:
    """Send *message* to all registered Telegram chats."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not set — alert notification skipped")
        return
    try:
        from telegram import Bot
        from services.db_service import get_telegram_chats
        bot = Bot(token=token)
        chat_ids = get_telegram_chats()
        if not chat_ids:
            logger.info("No Telegram chats registered — alert not delivered")
            return
        for chat_id in chat_ids:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
    except Exception as e:
        logger.error("Telegram alert send failed: %s", e)


# ── Data helpers ──────────────────────────────────────────────────────────────

def _get_current_price(ticker: str) -> Optional[float]:
    """Return the latest price via yfinance fast_info (no full data fetch)."""
    try:
        price = yf.Ticker(ticker).fast_info.last_price
        return float(price) if price else None
    except Exception:
        return None


def _run_full_analysis(ticker: str) -> tuple[Optional[str], Optional[int]]:
    """Run the full analysis pipeline synchronously. Returns (decision, score)."""
    try:
        from services.data_service import get_stock_data
        from services.technical_analysis import analyze as technical_analysis
        from services.fundamental_analysis import analyze as fundamental_analysis
        from services.etf_analysis import analyze as etf_analysis
        from services.crypto_analysis import analyze as crypto_analysis
        from services.sentiment_analysis import analyze as sentiment_analysis
        from services.decision_engine import decide as make_decision

        data = get_stock_data(ticker)
        quote_type = data.get("info", {}).get("quoteType", "")
        is_etf    = quote_type == "ETF"
        is_crypto = quote_type == "CRYPTOCURRENCY"

        technical = technical_analysis(data)
        if is_crypto:
            fundamental = crypto_analysis(data)
        elif is_etf:
            fundamental = etf_analysis(data)
        else:
            fundamental = fundamental_analysis(data)
        sentiment = sentiment_analysis(data)
        decision  = make_decision(technical, fundamental, sentiment)
        return decision.get("decision"), decision.get("score")
    except Exception as e:
        logger.error("Full analysis failed for %s: %s", ticker, e)
        return None, None


# ── Alert checkers ────────────────────────────────────────────────────────────

async def check_price_alerts() -> None:
    """Check all active price_below / price_above alerts."""
    try:
        from services.db_service import get_active_alerts, deactivate_alert
        alerts = get_active_alerts(alert_types=["price_below", "price_above"])
        if not alerts:
            return

        loop = asyncio.get_event_loop()
        for alert in alerts:
            ticker    = alert["ticker"]
            threshold = float(alert["threshold"])
            price = await loop.run_in_executor(None, _get_current_price, ticker)
            if price is None:
                continue

            triggered = False
            msg = ""
            if alert["alert_type"] == "price_below" and price <= threshold:
                triggered = True
                msg = (
                    f"🔔 *Price Alert* — {ticker}\n"
                    f"Price dropped to *${price:.2f}* "
                    f"(target: below ${threshold:.2f})"
                )
            elif alert["alert_type"] == "price_above" and price >= threshold:
                triggered = True
                msg = (
                    f"🔔 *Price Alert* — {ticker}\n"
                    f"Price rose to *${price:.2f}* "
                    f"(target: above ${threshold:.2f})"
                )

            if triggered:
                await _send_telegram_message(msg)
                deactivate_alert(alert["id"])
                logger.info("Price alert %s triggered for %s @ %.2f", alert["id"], ticker, price)

    except Exception as e:
        logger.error("check_price_alerts error: %s", e)


async def check_score_alerts() -> None:
    """Check all active buy_signal / avoid_signal alerts (full analysis)."""
    try:
        from services.db_service import get_active_alerts, deactivate_alert
        alerts = get_active_alerts(alert_types=["buy_signal", "avoid_signal"])
        if not alerts:
            return

        # Group by ticker to avoid running analysis more than once per ticker
        by_ticker: dict[str, list[dict]] = {}
        for alert in alerts:
            by_ticker.setdefault(alert["ticker"], []).append(alert)

        loop = asyncio.get_event_loop()
        for ticker, ticker_alerts in by_ticker.items():
            decision, score = await loop.run_in_executor(None, _run_full_analysis, ticker)
            if decision is None:
                continue

            for alert in ticker_alerts:
                triggered = False
                msg = ""
                if alert["alert_type"] == "buy_signal" and decision in ("BUY", "STRONG_BUY"):
                    triggered = True
                    emoji = "🚀" if decision == "STRONG_BUY" else "✅"
                    msg = (
                        f"{emoji} *Signal Alert* — {ticker}\n"
                        f"*{decision}* detected! Score: {score}/18"
                    )
                elif alert["alert_type"] == "avoid_signal" and decision == "AVOID":
                    triggered = True
                    msg = (
                        f"🚫 *Signal Alert* — {ticker}\n"
                        f"*AVOID* detected! Score: {score}/18"
                    )

                if triggered:
                    await _send_telegram_message(msg)
                    deactivate_alert(alert["id"])
                    logger.info("Score alert %s triggered for %s: %s", alert["id"], ticker, decision)

    except Exception as e:
        logger.error("check_score_alerts error: %s", e)


# ── Background loop ───────────────────────────────────────────────────────────

async def alert_loop() -> None:
    """
    Long-running coroutine started at app startup.
    Price alerts checked every 30 min; score alerts every 6 hours.
    """
    PRICE_INTERVAL = 30 * 60    # seconds
    SCORE_INTERVAL = 6 * 3600   # seconds
    last_score_check = 0.0

    logger.info("Alert loop started (price: 30min, score: 6h)")

    while True:
        try:
            await asyncio.sleep(PRICE_INTERVAL)
            await check_price_alerts()

            if time.time() - last_score_check >= SCORE_INTERVAL:
                await check_score_alerts()
                last_score_check = time.time()

        except asyncio.CancelledError:
            logger.info("Alert loop cancelled")
            break
        except Exception as e:
            logger.error("Alert loop unexpected error: %s", e)
            await asyncio.sleep(60)  # brief pause before retrying
