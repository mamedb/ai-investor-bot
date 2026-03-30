import yfinance as yf

def get_stock_data(ticker: str):
    stock = yf.Ticker(ticker)

    hist = stock.history(period="6mo")
    info = stock.info

    return {
        "price": hist,
        "info": info
    }
