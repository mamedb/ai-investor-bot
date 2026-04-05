"""
Fetch current prices for all portfolio holdings and compute P&L.
"""
import logging
from services.db_service import get_holdings, save_portfolio_snapshot
from services.data_service import get_stock_data

logger = logging.getLogger(__name__)

def get_live_portfolio() -> dict:
    """
    Load holdings from DB, fetch live price for each, compute P&L.
    Returns:
      {
        "holdings": [...],   # enriched rows
        "summary": {total_value, total_cost, total_gain, total_gain_pct}
      }
    """
    rows = get_holdings()
    enriched = []
    total_value = 0.0
    total_cost  = 0.0

    for row in rows:
        ticker = row["ticker"]
        shares = float(row["shares"])
        avg_price = float(row["avg_price"])
        cost = round(shares * avg_price, 2)

        current_price = 0.0
        try:
            data = get_stock_data(ticker)
            info = data.get("info", {})
            current_price = float(
                info.get("currentPrice") or
                info.get("regularMarketPrice") or
                info.get("previousClose") or 0
            )
        except Exception as e:
            logger.warning("price fetch failed for %s: %s", ticker, e)

        market_value = round(shares * current_price, 2)
        gain         = round(market_value - cost, 2)
        gain_pct     = round((gain / cost * 100) if cost else 0, 2)

        enriched.append({
            "id":            row["id"],
            "ticker":        ticker,
            "name":          row.get("name") or ticker,
            "shares":        shares,
            "avg_price":     avg_price,
            "current_price": current_price,
            "cost":          cost,
            "market_value":  market_value,
            "gain":          gain,
            "gain_pct":      gain_pct,
            "added_at":      row.get("added_at"),
        })

        total_value += market_value
        total_cost  += cost

    total_gain     = round(total_value - total_cost, 2)
    total_gain_pct = round((total_gain / total_cost * 100) if total_cost else 0, 2)

    # Record snapshot for history chart
    if enriched:
        save_portfolio_snapshot(round(total_value, 2), round(total_cost, 2))

    return {
        "holdings": enriched,
        "summary": {
            "total_value":    round(total_value, 2),
            "total_cost":     round(total_cost, 2),
            "total_gain":     total_gain,
            "total_gain_pct": total_gain_pct,
        }
    }
