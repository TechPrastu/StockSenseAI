from flask import Flask, render_template, request, jsonify
import yfinance as yf
from nsetools import Nse
import pandas as pd
from ai.predictor import StockPredictor
from ai.logger import StockSenseAILogger

app = Flask(__name__)
nse = Nse()
stock_predictor = StockPredictor()
logger = StockSenseAILogger.get_logger(__name__)

def get_stock_data(symbol, period='7d', table_period='7d'):
    yf_symbol = symbol.upper() + '.NS'
    ticker = yf.Ticker(yf_symbol)

    # Historical data
    hist = ticker.history(period=period).reset_index()
    hist['Date'] = pd.to_datetime(hist['Date']).dt.strftime('%Y-%m-%d')
    hist_data = hist[['Date', 'Close', 'Volume']].to_dict(orient='records')

    # Historical Table for table_period, not period
    hist_table_df = ticker.history(period=table_period).reset_index()
    hist_table_df['Date'] = pd.to_datetime(hist_table_df['Date']).dt.strftime('%Y-%m-%d')
    hist_table = hist_table_df[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']].to_html(
        classes='data', index=False)

    # Info
    info = ticker.info
    yf_info = {
        'Current Price': info.get('currentPrice'),
        'Previous Close': info.get('previousClose'),
        '52 Week High': info.get('fiftyTwoWeekHigh'),
        '52 Week Low': info.get('fiftyTwoWeekLow'),
        'Market Cap': info.get('marketCap'),
        'P/E Ratio': info.get('trailingPE'),
        'Sector': info.get('sector'),
        'Website': info.get('website')
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
        'yfinance_fields': yf_info,
        'nse_fields': nse_info,
        'hist_table': hist_table,
        'hist_json': hist_data
    }

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        symbols = request.form.get("symbol", "RELIANCE").replace(" ", "")
        selected_period = request.form.get("period", "7d")
        theme = request.form.get("theme", "light")
    else:
        symbols = "RELIANCE"
        selected_period = "7d"
        theme = "light"

    symbols = symbols.split(",")
    stock_data_list = [get_stock_data(s, period=selected_period, table_period='7d') for s in symbols]

    # AI Prediction
    predictions = {}
    insights_dict = {}
    for symbol in symbols:
        stock_predictor.train(symbol)
        predictions[symbol] = stock_predictor.predict(symbol)
        insights_dict[symbol] = stock_predictor.get_insights(symbol)

    return render_template(
        "index.html",
        symbols=",".join(symbols),
        selected_period=selected_period,
        theme=theme,
        stock_data_list=stock_data_list,
        predictions=predictions,
        insights=insights_dict
    )

@app.route("/table")
def table():
    symbol = request.args.get("symbol")
    period = request.args.get("period", "7d")
    theme = request.args.get("theme", "light")
    stock = get_stock_data(symbol, period)
    return stock["hist_table"]

@app.before_request
def log_request_info():
    logger.info(f"User requested data for {request.args.get('symbol')}")
    logger.debug(f"Request data: {request.args}")

if __name__ == "__main__":
    app.run(debug=True)
# stock_web_app.py
# This file is part of the StockSense AI project.
# It provides a Flask web application to display stock data and predictions.    
