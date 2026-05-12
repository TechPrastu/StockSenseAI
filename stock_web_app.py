from flask import Flask, render_template, request, jsonify
import yfinance as yf
from yahooquery import Ticker
from nsetools import Nse
import pandas as pd
from ai.predictor import StockPredictor
from ai.logger import StockSenseAILogger

app = Flask(__name__)
nse = Nse()
stock_predictor = StockPredictor()
logger = StockSenseAILogger.get_logger(__name__)

def format_inr(value):
    if value is None:
        return 'N/A'
    try:
        return f"₹ {value:,.2f}"
    except Exception:
        return str(value)


def format_inr_crore(value):
    if value is None:
        return 'N/A'
    try:
        return f"₹ {value / 1e7:,.2f} Cr."
    except Exception:
        return str(value)


def format_percent(value, scale=True):
    if value is None:
        return 'N/A'
    try:
        if scale:
            return f"{value * 100:.2f} %"
        return f"{value:.2f} %"
    except Exception:
        return str(value)


def get_stock_data(symbol, period='7d', table_period='7d'):
    period_map = {
        '1w': '5d',
        '1m': '1mo',
        '3m': '3mo',
        '6m': '6mo',
        '1y': '1y',
        '3y': '3y',
        '5y': '5y'
    }
    yf_period = period_map.get(period, period)
    yf_symbol = symbol.upper() + '.NS'
    ticker = yf.Ticker(yf_symbol)
    yq_ticker = Ticker(yf_symbol)

    # Historical data
    hist = ticker.history(period=yf_period).reset_index()
    hist['Date'] = pd.to_datetime(hist['Date']).dt.strftime('%Y-%m-%d')
    hist_data = hist[['Date', 'Close', 'Volume']].to_dict(orient='records')

    # Info
    info = ticker.info
    yq_profile = {}
    yq_detail = {}
    yq_financial = {}
    yq_price = {}
    yq_quote = {}
    try:
        yq_profile = yq_ticker.summary_profile.get(yf_symbol, {}) or {}
        yq_detail = yq_ticker.summary_detail.get(yf_symbol, {}) or {}
        yq_financial = yq_ticker.financial_data.get(yf_symbol, {}) or {}
        yq_price = yq_ticker.price.get(yf_symbol, {}) or {}
        yq_quote = yq_ticker.quote_type.get(yf_symbol, {}) or {}
    except Exception:
        pass

    yfinance_fields = {
        'Current Price': info.get('currentPrice'),
        'Previous Close': info.get('previousClose'),
        '52 Week High': info.get('fiftyTwoWeekHigh'),
        '52 Week Low': info.get('fiftyTwoWeekLow'),
        'Market Cap': info.get('marketCap'),
        'P/E Ratio': info.get('trailingPE'),
        'Sector': info.get('sector'),
        'Website': info.get('website')
    }

    price_summary = {
        'today_high': yq_detail.get('dayHigh') or info.get('dayHigh'),
        'today_low': yq_detail.get('dayLow') or info.get('dayLow'),
        'week_high': info.get('fiftyTwoWeekHigh'),
        'week_low': info.get('fiftyTwoWeekLow')
    }

    current_price = yq_price.get('regularMarketPrice') or info.get('currentPrice')
    previous_close = yq_price.get('regularMarketPreviousClose') or info.get('previousClose')
    change = None
    change_percent = None
    if current_price is not None and previous_close is not None:
        try:
            change = current_price - previous_close
            if previous_close != 0:
                change_percent = change / previous_close
        except Exception:
            change = None
            change_percent = None

    company_essentials = {
        'market_cap': format_inr_crore(yq_price.get('marketCap') or info.get('marketCap')),
        'enterprise_value': format_inr_crore(yq_financial.get('enterpriseValue')),
        'no_of_shares': format_inr(yq_financial.get('sharesOutstanding') or info.get('sharesOutstanding')),
        'pe_ratio': yq_financial.get('trailingPE') or yq_detail.get('trailingPE') or info.get('trailingPE'),
        'pb_ratio': yq_financial.get('priceToBook') or info.get('priceToBook'),
        'face_value': info.get('faceValue') or 'N/A',
        'div_yield': format_percent(yq_detail.get('dividendYield')),
        'book_value': format_inr(yq_financial.get('bookValue')),
        'cash': format_inr_crore(yq_financial.get('totalCash')),
        'debt': format_inr_crore(yq_financial.get('totalDebt')),
        'eps': yq_financial.get('trailingEps') or info.get('trailingEps'),
        'roe': format_percent(yq_financial.get('returnOnEquity')),
        'roce': format_percent(yq_financial.get('returnOnAssets')),
        'promoter_holding': nse.get_quote(symbol.lower()).get('promoterHolding') if hasattr(nse, 'get_quote') else 'N/A',
        'sales_growth': 'N/A',
        'profit_growth': 'N/A'
    }

    company_info = {
        'company_name': yq_quote.get('longName') or yq_quote.get('shortName') or info.get('shortName') or symbol.upper(),
        'sector': yq_profile.get('sectorDisp') or info.get('sector'),
        'industry': yq_profile.get('industryDisp') or info.get('industry'),
        'summary': yq_profile.get('longBusinessSummary') or '',
        'website': yq_profile.get('website') or info.get('website'),
        'exchange': yq_price.get('exchangeName') or info.get('exchange'),
        'market_state': yq_price.get('marketState') or ''
    }

    # NSE live data
    try:
        nse_data = nse.get_quote(symbol.lower())
        nse_info = {
            'Last Traded Price': nse_data.get('lastPrice'),
            'Day High': nse_data.get('dayHigh'),
            'Day Low': nse_data.get('dayLow'),
            '52 Week High': nse_data.get('high52'),
            '52 Week Low': nse_data.get('low52'),
            'Volume': nse_data.get('quantityTraded')
        }
    except Exception as e:
        nse_info = {}

    return {
        'symbol': symbol.upper(),
        'yfinance_fields': yfinance_fields,
        'nse_fields': nse_info,
        'hist_json': hist_data,
        'stock_profile': company_info,
        'price_summary': price_summary,
        'company_essentials': company_essentials,
        'current_price': current_price,
        'previous_close': previous_close,
        'price_change': change,
        'price_change_percent': change_percent,
        'market_time': yq_price.get('regularMarketTime') or ''
    }

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        symbol = request.form.get("symbol", "RELIANCE").strip().split(",")[0].strip()
        theme = request.form.get("theme", "light")
    else:
        symbol = "RELIANCE"
        theme = "light"

    if not symbol:
        symbol = "RELIANCE"

    stock_data_list = [get_stock_data(symbol, period='1y')]

    # AI Prediction
    predictions = {}
    insights_dict = {}
    symbol_upper = symbol.upper()
    stock_predictor.train(symbol_upper)
    predictions[symbol_upper] = stock_predictor.predict(symbol_upper)
    insights_dict[symbol_upper] = stock_predictor.get_insights(symbol_upper)

    return render_template(
        "index.html",
        symbol=symbol_upper,
        theme=theme,
        stock_data_list=stock_data_list,
        predictions=predictions,
        insights=insights_dict
    )

@app.route("/chart_data")
def chart_data():
    symbol = request.args.get("symbol", "RELIANCE").strip().split(",")[0].strip()
    period = request.args.get("period", "1y")
    if not symbol:
        symbol = "RELIANCE"
    stock = get_stock_data(symbol, period=period)
    return jsonify(hist_json=stock["hist_json"])

@app.before_request
def log_request_info():
    logger.info(f"User requested data for {request.args.get('symbol')}")
    logger.debug(f"Request data: {request.args}")

if __name__ == "__main__":
    app.run(debug=True)
# stock_web_app.py
# This file is part of the StockSense AI project.
# It provides a Flask web application to display stock data and predictions.    
