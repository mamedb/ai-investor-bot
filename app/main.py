from fastapi import FastAPI, HTTPException, Request, Form, Depends
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from services.data_service import get_stock_data
from services.technical_analysis import analyze as technical_analysis
from services.fundamental_analysis import analyze as fundamental_analysis
from services.etf_analysis import analyze as etf_analysis
from services.sentiment_analysis import analyze as sentiment_analysis
from services.decision_engine import decide as make_decision
from services.db_service import save_result, get_history
import os

app = FastAPI()

_SECRET_KEY      = os.environ.get("SECRET_KEY", "change-me-in-production")
_LOGIN_USERNAME  = os.environ.get("LOGIN_USERNAME", "admin")
_LOGIN_PASSWORD  = os.environ.get("LOGIN_PASSWORD", "password")

app.add_middleware(SessionMiddleware, secret_key=_SECRET_KEY)

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
    # single yfinance fetch — shared across all modules
    try:
        data = get_stock_data(ticker.upper())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Data fetch failed: {e}")

    is_etf = data.get("info", {}).get("quoteType") == "ETF"

    try:
        technical = technical_analysis(data)
        fundamental = etf_analysis(data) if is_etf else fundamental_analysis(data)
        sentiment = sentiment_analysis(data)
        decision = make_decision(technical, fundamental, sentiment)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")

    result = {
        "ticker":      ticker.upper(),
        "asset_type":  "ETF" if is_etf else "STOCK",
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
