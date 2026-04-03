"""
services/db_service.py
-----------------------
Persist each analysis result to the search_history table in PostgreSQL.

Connection is configured via environment variables (with sensible defaults
for the local dev setup):
  DB_HOST      (default: localhost)
  DB_PORT      (default: 5432)
  DB_NAME      (default: aiinvestor)
  DB_USER      (default: aiinvestor)
  DB_PASSWORD  (default: aiinvestor123)
"""

import os
import logging
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)

_conn: Optional[psycopg2.extensions.connection] = None


def _get_conn():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 5432)),
            dbname=os.getenv("DB_NAME", "aiinvestor"),
            user=os.getenv("DB_USER", "aiinvestor"),
            password=os.getenv("DB_PASSWORD", "aiinvestor123"),
        )
        _conn.autocommit = True
    return _conn


def _safe(val, cast=None):
    """Return None instead of crashing on missing/non-numeric values."""
    if val is None:
        return None
    try:
        return cast(val) if cast else val
    except (TypeError, ValueError):
        return None


def save_result(ticker: str, asset_type: str,
                technical: dict, fundamental: dict,
                sentiment: dict, decision: dict) -> None:
    """
    Insert one row into search_history.
    Failures are logged but never raised so they don't break the API response.
    """
    try:
        conn = _get_conn()
        cur  = conn.cursor()

        tech_bd  = technical  or {}
        fund_bd  = (fundamental or {}).get("breakdown", {})
        sent_bd  = (sentiment  or {}).get("breakdown", {})
        dec      = decision    or {}
        ps       = dec.get("pillar_scores", {})

        row = (
            ticker.upper(),
            asset_type,
            # decision
            dec.get("decision"),
            _safe(dec.get("score"), int),
            dec.get("confidence"),
            dec.get("reason"),
            dec.get("flags") or [],
            # pillar scores
            _safe((ps.get("technical")   or {}).get("score"), int),
            _safe((ps.get("fundamental") or {}).get("score"), int),
            _safe((ps.get("sentiment")   or {}).get("score"), int),
            # technical indicators
            _safe(tech_bd.get("rsi"),              float),
            tech_bd.get("signal"),
            tech_bd.get("trend"),
            _safe(tech_bd.get("sma200"),           float),
            _safe(tech_bd.get("price"),            float),
            _safe(tech_bd.get("week52_high"),      float),
            _safe(tech_bd.get("week52_low"),       float),
            _safe(tech_bd.get("week52_position"),  float),
            tech_bd.get("week52_signal"),
            # fundamental
            (fundamental or {}).get("grade"),
            (fundamental or {}).get("sector"),
            (fundamental or {}).get("name"),
            _safe((fund_bd.get("revenue_growth") or {}).get("value"), float),
            _safe((fund_bd.get("revenue_growth") or {}).get("score"), int),
            _safe((fund_bd.get("eps_trend")      or {}).get("score"), int),
            _safe((fund_bd.get("pe_vs_sector")   or {}).get("value"), float),
            _safe((fund_bd.get("pe_vs_sector")   or {}).get("score"), int),
            _safe((fund_bd.get("debt_equity")    or {}).get("value"), float),
            _safe((fund_bd.get("debt_equity")    or {}).get("score"), int),
            _safe((fund_bd.get("profit_margin")  or {}).get("value"), float),
            _safe((fund_bd.get("profit_margin")  or {}).get("score"), int),
            _safe((fund_bd.get("free_cash_flow") or {}).get("value"), float),
            _safe((fund_bd.get("free_cash_flow") or {}).get("score"), int),
            # sentiment
            (sentiment or {}).get("label"),
            _safe((sent_bd.get("news_sentiment")  or {}).get("score"), int),
            _safe((sent_bd.get("analyst_outlook") or {}).get("score"), int),
            _safe((sent_bd.get("macro_context")   or {}).get("score"), int),
            (sentiment or {}).get("summary"),
        )

        cur.execute("""
            INSERT INTO search_history (
                ticker, asset_type,
                recommendation, total_score, confidence, reason, flags,
                tech_score, fund_score, sent_score,
                tech_rsi, tech_signal, tech_trend, tech_sma200, tech_price,
                tech_week52_high, tech_week52_low, tech_week52_position, tech_week52_signal,
                fund_grade, fund_sector, fund_name,
                fund_revenue_growth, fund_revenue_score,
                fund_eps_score,
                fund_pe_value, fund_pe_score,
                fund_de_value, fund_de_score,
                fund_margin_value, fund_margin_score,
                fund_fcf_value, fund_fcf_score,
                sent_label, sent_news_score, sent_analyst_score, sent_macro_score,
                sent_summary
            ) VALUES (
                %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s
            )
        """, row)

        logger.info("search_history: saved %s → %s", ticker, dec.get("decision"))

    except Exception as e:
        logger.error("search_history: failed to save %s — %s", ticker, e)


def get_history(limit: int = 50) -> list[dict]:
    """Return the most recent `limit` rows from search_history."""
    try:
        conn = _get_conn()
        cur  = conn.cursor()
        cur.execute("""
            SELECT
                id, ticker, searched_at, asset_type,
                recommendation, total_score, confidence, reason, flags,
                tech_score, fund_score, sent_score,
                tech_rsi, tech_signal, tech_trend, tech_price,
                tech_sma200, tech_week52_position, tech_week52_signal,
                fund_grade, fund_sector, fund_name,
                fund_revenue_growth, fund_revenue_score,
                fund_eps_score,
                fund_pe_value, fund_pe_score,
                fund_de_value, fund_de_score,
                fund_margin_value, fund_margin_score,
                fund_fcf_value, fund_fcf_score,
                sent_label, sent_news_score, sent_analyst_score, sent_macro_score,
                sent_summary
            FROM search_history
            ORDER BY searched_at DESC
            LIMIT %s
        """, (limit,))
        cols = [desc[0] for desc in cur.description]
        rows = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            # make JSON-serializable
            if d.get("searched_at"):
                d["searched_at"] = d["searched_at"].isoformat()
            for k, v in d.items():
                if hasattr(v, "__float__"):
                    d[k] = float(v)
            rows.append(d)
        return rows
    except Exception as e:
        logger.error("get_history failed: %s", e)
        return []
