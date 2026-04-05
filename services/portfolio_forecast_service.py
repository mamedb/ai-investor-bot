"""
services/portfolio_forecast_service.py
---------------------------------------
Sends current portfolio holdings to OpenAI and gets a 10-year
compound growth forecast broken down year-by-year.

OpenAI returns expected / optimistic / pessimistic annual return %
for the portfolio as a whole, considering each asset's type, weight,
and current market context. The compound math is done here.
"""

import os
import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            return None
        _client = OpenAI(api_key=key)
    return _client


_SYSTEM_PROMPT = """\
You are a senior portfolio analyst. Given a real investor's portfolio holdings,
estimate the expected long-term annual return for the portfolio as a whole.

Consider:
- Asset type weights (ETFs, stocks, crypto have different return profiles)
- Individual asset quality and growth outlook
- Portfolio diversification and risk
- Current macroeconomic context (use your knowledge up to your cutoff)

Return ONLY valid JSON, no extra text:
{
  "expected_annual_return_pct": <float, e.g. 9.5>,
  "optimistic_annual_return_pct": <float, e.g. 14.0>,
  "pessimistic_annual_return_pct": <float, e.g. 4.0>,
  "rationale": "<2-3 sentences explaining the forecast>",
  "asset_notes": [
    {"ticker": "<TICKER>", "weight_pct": <float>, "outlook": "<≤12 words>"}
  ]
}

Rules:
- expected = realistic base-case annualised total return (price + dividends)
- optimistic = 80th-percentile scenario
- pessimistic = 20th-percentile scenario
- Crypto assets: use wider spread between optimistic and pessimistic
- All values are percentage per year (e.g. 9.5 means 9.5% per year)
"""


def _build_prompt(holdings: list, total_value: float) -> str:
    lines = [
        f"Portfolio total current value: ${total_value:,.2f}",
        "",
        "Holdings:",
    ]
    for h in holdings:
        weight = (h["market_value"] / total_value * 100) if total_value else 0
        lines.append(
            f"  {h['ticker']} ({h['name']}): "
            f"{h['shares']} shares @ avg ${h['avg_price']:.2f}, "
            f"current ${h['current_price']:.2f}, "
            f"market value ${h['market_value']:,.2f} ({weight:.1f}% of portfolio), "
            f"unrealised P&L: {h['gain_pct']:+.1f}%"
        )
    return "\n".join(lines)


def _compound(current_value: float, annual_rate_pct: float, years: int) -> float:
    r = annual_rate_pct / 100
    return round(current_value * ((1 + r) ** years), 2)


def get_forecast(holdings: list, total_value: float) -> dict:
    """
    Returns:
    {
      "years": [
        {
          "year": 1,
          "expected_value": ..., "expected_profit": ..., "expected_return_pct": ...,
          "optimistic_value": ..., "optimistic_profit": ...,
          "pessimistic_value": ..., "pessimistic_profit": ...
        }, ...
      ],
      "expected_annual_return_pct": ...,
      "optimistic_annual_return_pct": ...,
      "pessimistic_annual_return_pct": ...,
      "rationale": "...",
      "asset_notes": [...]
    }
    """
    client = _get_client()
    if client is None:
        return {"error": "OPENAI_API_KEY not set"}
    if not holdings or total_value <= 0:
        return {"error": "No holdings to forecast"}

    prompt = _build_prompt(holdings, total_value)
    model  = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception as e:
        logger.error("portfolio forecast OpenAI call failed: %s", e)
        return {"error": f"OpenAI error: {e}"}

    exp  = float(data.get("expected_annual_return_pct",    9.0))
    opt  = float(data.get("optimistic_annual_return_pct",  14.0))
    pess = float(data.get("pessimistic_annual_return_pct", 4.0))

    years_out = []
    for y in range(1, 11):
        exp_val  = _compound(total_value, exp,  y)
        opt_val  = _compound(total_value, opt,  y)
        pess_val = _compound(total_value, pess, y)
        exp_ret_pct = round((exp_val - total_value) / total_value * 100, 1)
        years_out.append({
            "year":                 y,
            "expected_value":       exp_val,
            "expected_profit":      round(exp_val  - total_value, 2),
            "expected_return_pct":  exp_ret_pct,
            "optimistic_value":     opt_val,
            "optimistic_profit":    round(opt_val  - total_value, 2),
            "pessimistic_value":    pess_val,
            "pessimistic_profit":   round(pess_val - total_value, 2),
        })

    return {
        "years":                         years_out,
        "expected_annual_return_pct":    exp,
        "optimistic_annual_return_pct":  opt,
        "pessimistic_annual_return_pct": pess,
        "rationale":   data.get("rationale", ""),
        "asset_notes": data.get("asset_notes", []),
    }
