from fastapi import FastAPI, HTTPException, Request, Form, Depends
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from services.data_service import get_stock_data
from services.technical_analysis import analyze as technical_analysis
from services.fundamental_analysis import analyze as fundamental_analysis
from services.etf_analysis import analyze as etf_analysis
from services.crypto_analysis import analyze as crypto_analysis
from services.sentiment_analysis import analyze as sentiment_analysis
from services.decision_engine import decide as make_decision
from services.db_service import save_result, get_history, add_holding, remove_holding, get_portfolio_history, init_portfolio_tables
from services.portfolio_service import build_portfolio
from services.holdings_service import get_live_portfolio
from services.portfolio_forecast_service import get_forecast
import os
from typing import Optional

app = FastAPI()

try:
    init_portfolio_tables()
except Exception as _e:
    import logging as _logging
    _logging.getLogger(__name__).warning("init_portfolio_tables failed (DB may be down): %s", _e)

_SECRET_KEY      = os.environ.get("SECRET_KEY", "change-me-in-production")
_LOGIN_USERNAME  = os.environ.get("LOGIN_USERNAME", "admin")
_LOGIN_PASSWORD  = os.environ.get("LOGIN_PASSWORD", "password")

app.add_middleware(SessionMiddleware, secret_key=_SECRET_KEY, https_only=False)

_static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


class _NotAuthenticated(Exception):
    pass


@app.exception_handler(_NotAuthenticated)
async def _not_auth_handler(request: Request, _exc: _NotAuthenticated):
    return RedirectResponse(url="/login", status_code=303)


def _require_auth(request: Request):
    if not request.session.get("authenticated"):
        raise _NotAuthenticated()


@app.get("/login")
def login_page(request: Request, error: int = 0):
    if request.session.get("authenticated"):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(
        os.path.join(_static_dir, "login.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if username == _LOGIN_USERNAME and password == _LOGIN_PASSWORD:
        request.session["authenticated"] = True
        return RedirectResponse(url="/", status_code=303)
    return RedirectResponse(url="/login?error=1", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/")
def root(_auth=Depends(_require_auth)):
    return FileResponse(
        os.path.join(_static_dir, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/analyze/{ticker}")
def analyze_stock(ticker: str, _auth=Depends(_require_auth)):
    ticker = ticker.upper()

    # single yfinance fetch — shared across all modules
    try:
        data = get_stock_data(ticker)
    except ValueError:
        # Auto-append -USD for bare crypto symbols (BTC → BTC-USD)
        if "-" not in ticker:
            try:
                data = get_stock_data(ticker + "-USD")
                ticker = ticker + "-USD"
            except ValueError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Data fetch failed: {e}")
        else:
            raise HTTPException(status_code=404, detail=f"No data found for {ticker}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Data fetch failed: {e}")

    quote_type = data.get("info", {}).get("quoteType", "")
    is_etf    = quote_type == "ETF"
    is_crypto = quote_type == "CRYPTOCURRENCY"

    try:
        technical = technical_analysis(data)
        if is_crypto:
            fundamental = crypto_analysis(data)
        elif is_etf:
            fundamental = etf_analysis(data)
        else:
            fundamental = fundamental_analysis(data)
        sentiment = sentiment_analysis(data)
        decision = make_decision(technical, fundamental, sentiment)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")

    if is_crypto:
        asset_type = "CRYPTO"
    elif is_etf:
        asset_type = "ETF"
    else:
        asset_type = "STOCK"

    result = {
        "ticker":      ticker,
        "asset_type":  asset_type,
        "technical":   technical,
        "fundamental": fundamental,
        "sentiment":   sentiment,
        "decision":    decision,
    }

    save_result(
        ticker=ticker.upper(),
        asset_type=result["asset_type"],
        technical=technical,
        fundamental=fundamental,
        sentiment=sentiment,
        decision=decision,
    )

    return result


@app.get("/history")
def history(limit: int = 50, _auth=Depends(_require_auth)):
    return get_history(limit)


@app.get("/portfolio")
def portfolio_page(_auth=Depends(_require_auth)):
    return FileResponse(
        os.path.join(_static_dir, "portfolio.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.post("/portfolio/calculate")
def portfolio_calculate(
    request: Request,
    monthly_amount: float = Form(...),
    duration_months: int = Form(...),
    risk_level: str = Form(...),
    investment_type: str = Form(default="monthly"),
    _auth=Depends(_require_auth),
):
    if risk_level not in ("conservative", "moderate", "aggressive"):
        raise HTTPException(status_code=400, detail="Invalid risk_level")
    if monthly_amount <= 0:
        raise HTTPException(status_code=400, detail="monthly_amount must be positive")
    if not (1 <= duration_months <= 600):
        raise HTTPException(status_code=400, detail="duration_months must be 1–600")
    if investment_type not in ("monthly", "onetime"):
        raise HTTPException(status_code=400, detail="investment_type must be 'monthly' or 'onetime'")
    try:
        result = build_portfolio(monthly_amount, duration_months, risk_level, investment_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Portfolio calculation failed: {e}")
    return JSONResponse(content=result)


@app.get("/my-portfolio")
def my_portfolio_page(_auth=Depends(_require_auth)):
    return FileResponse(
        os.path.join(_static_dir, "my_portfolio.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/my-portfolio/assets")
def my_portfolio_assets(_auth=Depends(_require_auth)):
    try:
        return JSONResponse(content=get_live_portfolio())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/my-portfolio/assets")
def my_portfolio_add(
    ticker:    str   = Form(...),
    shares:    float = Form(...),
    avg_price: float = Form(...),
    name:      str   = Form(default=""),
    _auth=Depends(_require_auth),
):
    ticker = ticker.upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker required")
    if shares <= 0 or avg_price <= 0:
        raise HTTPException(status_code=400, detail="shares and avg_price must be positive")
    holding_id, merged = add_holding(ticker, name.strip() or ticker, shares, avg_price)
    return JSONResponse(content={"id": holding_id, "ticker": ticker, "merged": merged})


@app.delete("/my-portfolio/assets/{holding_id}")
def my_portfolio_remove(holding_id: int, _auth=Depends(_require_auth)):
    ok = remove_holding(holding_id)
    if not ok:
        raise HTTPException(status_code=404, detail="holding not found")
    return JSONResponse(content={"deleted": holding_id})


@app.get("/my-portfolio/history")
def my_portfolio_history(_auth=Depends(_require_auth)):
    return JSONResponse(content=get_portfolio_history(90))


@app.post("/my-portfolio/forecast")
def my_portfolio_forecast(_auth=Depends(_require_auth)):
    portfolio = get_live_portfolio()
    result = get_forecast(portfolio["holdings"], portfolio["summary"]["total_value"])
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return JSONResponse(content=result)
