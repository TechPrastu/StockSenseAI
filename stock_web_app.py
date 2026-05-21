from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
_nse = None
_stock_predictor = None
_logger = None
_recent_searches = []  # Store recent search history

def get_logger():
    global _logger
    if _logger is None:
        from ai.logger import StockSenseAILogger
        _logger = StockSenseAILogger.get_logger(__name__)
    return _logger

def get_nse():
    global _nse
    if _nse is None:
        from nsetools import Nse
        _nse = Nse()
    return _nse

def get_stock_predictor():
    global _stock_predictor
    if _stock_predictor is None:
        from ai.predictor import StockPredictor
        _stock_predictor = StockPredictor()
    return _stock_predictor

def add_recent_search(symbol):
    """Add a symbol to recent searches, keeping only unique entries."""
    global _recent_searches
    symbol_upper = symbol.upper()
    if symbol_upper in _recent_searches:
        _recent_searches.remove(symbol_upper)
    _recent_searches.insert(0, symbol_upper)
    # Keep only the most recent 10 searches
    _recent_searches[:] = _recent_searches[:10]

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


def safe_value(value, default='N/A'):
    return default if value is None else value


def get_stock_data(symbol, period='7d', table_period='7d'):
    import yfinance as yf
    from yahooquery import Ticker
    import pandas as pd
    
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
    # For intraday (1d) requests, ask for a smaller interval and keep time component
    try:
        if period == '1d':
            # request intraday bars (5 minute) for a clearer 1-day chart
            hist = ticker.history(period='1d', interval='5m').reset_index()
            if 'Datetime' in hist.columns:
                date_series = pd.to_datetime(hist['Datetime'])
            else:
                date_series = pd.to_datetime(hist['Date'])

            # Convert intraday timestamps to India local time if possible
            if date_series.dt.tz is None:
                date_series = date_series.dt.tz_localize('UTC')
            date_series = date_series.dt.tz_convert('Asia/Kolkata')
            hist['Date'] = date_series.dt.strftime('%Y-%m-%d %H:%M:%S')
        else:
            hist = ticker.history(period=yf_period).reset_index()
            hist['Date'] = pd.to_datetime(hist['Date']).dt.strftime('%Y-%m-%d')
    except Exception:
        # fallback to a safe empty DataFrame structure
        hist = pd.DataFrame(columns=['Date', 'Close', 'Volume'])

    # Ensure Close and Volume exist and are numeric
    if 'Close' not in hist.columns:
        hist['Close'] = None
    if 'Volume' not in hist.columns:
        hist['Volume'] = 0

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
        'pe_ratio': safe_value(yq_financial.get('trailingPE') or yq_detail.get('trailingPE') or info.get('trailingPE')),
        'pb_ratio': safe_value(yq_financial.get('priceToBook') or info.get('priceToBook')),
        'face_value': safe_value(info.get('faceValue')),
        'div_yield': format_percent(yq_detail.get('dividendYield')),
        'book_value': format_inr(yq_financial.get('bookValue')),
        'cash': format_inr_crore(yq_financial.get('totalCash')),
        'debt': format_inr_crore(yq_financial.get('totalDebt')),
        'eps': safe_value(yq_financial.get('trailingEps') or info.get('trailingEps')),
        'roe': format_percent(yq_financial.get('returnOnEquity')),
        'roce': format_percent(yq_financial.get('returnOnAssets')),
        'promoter_holding': safe_value(get_nse().get_quote(symbol.lower()).get('promoterHolding') if hasattr(get_nse(), 'get_quote') else None),
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
        nse_data = get_nse().get_quote(symbol.lower())
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

    market_time = yq_price.get('regularMarketTime') or ''
    if isinstance(market_time, (int, float)) and market_time > 0:
        from datetime import timezone, timedelta
        india_tz = timezone(timedelta(hours=5, minutes=30))
        try:
            market_time = datetime.fromtimestamp(market_time, tz=timezone.utc).astimezone(india_tz).strftime('%Y-%m-%d %H:%M %Z')
        except Exception:
            market_time = str(market_time)

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
        'market_time': market_time
    }

def get_trending_stocks():
    """Fetch trending stocks data for the home page based on recent searches."""
    global _recent_searches
    
    # Default fallback stocks
    default_stocks = ['RELIANCE', 'TCS', 'INFY', 'HDFC', 'BAJAJFINSV']
    
    # Use recent searches if available, otherwise use defaults
    trending_symbols = _recent_searches[:5] if _recent_searches else default_stocks[:5]
    
    # Fallback data for all possible stocks
    fallback_data = {
        'RELIANCE': {'name': 'Reliance', 'sector': 'Energy', 'price': '3050.00', 'change': '2.50'},
        'TCS': {'name': 'Tata Consultancy', 'sector': 'IT', 'price': '3820.00', 'change': '-1.20'},
        'INFY': {'name': 'Infosys', 'sector': 'IT', 'price': '1890.00', 'change': '1.80'},
        'HDFC': {'name': 'HDFC Bank', 'sector': 'Banking', 'price': '2120.00', 'change': '0.95'},
        'BAJAJFINSV': {'name': 'Bajaj Finance', 'sector': 'Finance', 'price': '1580.00', 'change': '-0.50'},
        'HINDUNILVR': {'name': 'HUL', 'sector': 'FMCG', 'price': '2290.00', 'change': '1.30'},
        'LT': {'name': 'Larsen & Toubro', 'sector': 'Engineering', 'price': '3210.00', 'change': '2.10'},
        'ASIANPAINT': {'name': 'Asian Paints', 'sector': 'Chemicals', 'price': '3150.00', 'change': '-0.80'},
        'AXISBANK': {'name': 'Axis Bank', 'sector': 'Banking', 'price': '1190.00', 'change': '1.50'},
        'HCLTECH': {'name': 'HCL Tech', 'sector': 'IT', 'price': '1620.00', 'change': '0.70'},
        'ONGC': {'name': 'ONGC', 'sector': 'Energy', 'price': '315.00', 'change': '1.20'},
        'CDSL': {'name': 'CDSL', 'sector': 'Financial Services', 'price': '1186.20', 'change': '0.32'},
        'BSE': {'name': 'BSE Limited', 'sector': 'Financial Services', 'price': '3888.80', 'change': '0.96'},
        'WIPRO': {'name': 'Wipro', 'sector': 'IT', 'price': '520.00', 'change': '0.75'},
        'ICICIBANK': {'name': 'ICICI Bank', 'sector': 'Banking', 'price': '940.00', 'change': '-0.40'},
        'SBIN': {'name': 'State Bank of India', 'sector': 'Banking', 'price': '720.00', 'change': '0.60'},
    }
    
    trending = []
    for symbol in trending_symbols:
        stock_info = fallback_data.get(symbol)
        if stock_info is None:
            try:
                live_stock = get_stock_data(symbol, period='7d')
                current_price = live_stock.get('current_price')
                change_pct = live_stock.get('price_change_percent')
                stock_info = {
                    'name': live_stock['stock_profile'].get('company_name', symbol),
                    'sector': live_stock['stock_profile'].get('sector', 'N/A'),
                    'price': f"{current_price:.2f}" if isinstance(current_price, (int, float)) else 'N/A',
                    'change': f"{change_pct * 100:.2f}" if isinstance(change_pct, (int, float)) else '0.00'
                }
            except Exception:
                stock_info = {
                    'name': symbol,
                    'sector': 'N/A',
                    'price': 'N/A',
                    'change': '0.00'
                }
        trending.append({
            'symbol': symbol,
            'name': stock_info['name'],
            'sector': stock_info['sector'],
            'price': stock_info['price'],
            'change': stock_info['change'],
        })

    return trending

@app.route("/")
def home():
    theme = request.args.get("theme", "light")
    trending_stocks = get_trending_stocks()
    return render_template("home.html", theme=theme, trending_stocks=trending_stocks)

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if request.method == "POST":
        symbol = request.form.get("symbol", "RELIANCE").strip().split(",")[0].strip()
        theme = request.form.get("theme", "light")
    else:
        symbol = request.args.get("symbol", "RELIANCE").strip().split(",")[0].strip()
        theme = request.args.get("theme", "light")

    if not symbol:
        symbol = "RELIANCE"

    # Add to recent searches
    add_recent_search(symbol)

    stock_data_list = [get_stock_data(symbol, period='1y')]

    # AI Prediction
    predictions = {}
    insights_dict = {}
    symbol_upper = symbol.upper()
    get_stock_predictor().train(symbol_upper)
    predictions[symbol_upper] = get_stock_predictor().predict(symbol_upper)
    insights_dict[symbol_upper] = get_stock_predictor().get_insights(symbol_upper)

    return render_template(
        "dashboard.html",
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
    pass  # Logging disabled for now
    # get_logger().info(f"User requested data for {request.args.get('symbol')}")
    # get_logger().debug(f"Request data: {request.args}")

if __name__ == "__main__":
    app.run(debug=True)
# stock_web_app.py
# This file is part of the StockSense AI project.
# It provides a Flask web application to display stock data and predictions.    
