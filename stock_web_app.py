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


def safe_numeric(value):
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def get_market_state_label(market_state):
    """Convert raw market state values to friendly labels."""
    if not market_state:
        return 'Closed'
    state_lower = str(market_state).lower().strip()
    labels = {
        'postpost': 'After Hours',
        'prepost': 'Pre-Market',
        'postmarket': 'After Hours',
        'premarket': 'Pre-Market',
        'open': 'Open',
        'closed': 'Closed',
        'post': 'After Hours',
        'pre': 'Pre-Market'
    }
    return labels.get(state_lower, market_state or 'Closed')


def ensure_dict(value, default=None):
    """Ensure the value is a dict; return empty dict or default if it's not."""
    if isinstance(value, dict):
        return value
    return default or {}


SUGGESTED_STOCKS = [
    'RELIANCE', 'TCS', 'INFY', 'HDFC', 'BAJAJFINSV', 'HINDUNILVR', 'LT', 'ASIANPAINT',
    'AXISBANK', 'HCLTECH', 'ONGC', 'CDSL', 'BSE', 'WIPRO', 'ICICIBANK', 'SBIN',
    'MARUTI', 'SUNPHARMA', 'DMART', 'NESTLEIND', 'BRITANNIA', 'LTIM', 'POWERGRID',
    'TATAMOTORS', 'BHARTIARTL', 'JSWSTEEL', 'COALINDIA', 'NTPC', 'IOC', 'BPCL'
]


def get_stock_suggestions(symbol):
    """Return top 5 stock suggestions using fuzzy matching or alphabetical proximity."""
    symbol_upper = symbol.upper()
    
    # Check for exact prefix matches first
    prefix_matches = [s for s in SUGGESTED_STOCKS if s.startswith(symbol_upper)]
    if prefix_matches:
        return prefix_matches[:5]
    
    # Fallback to first 5 from suggested list
    return SUGGESTED_STOCKS[:5]


def get_corporate_events(ticker_obj):
    """Extract corporate events (splits, dividends) from yfinance ticker."""
    events = []
    try:
        # Get stock splits
        if hasattr(ticker_obj, 'splits') and ticker_obj.splits is not None and len(ticker_obj.splits) > 0:
            for date, split_ratio in ticker_obj.splits.items():
                events.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'type': 'Stock Split',
                    'detail': f'{split_ratio}:1 split',
                    'description': f'Stock split at ratio {split_ratio}:1'
                })
        
        # Get dividends
        if hasattr(ticker_obj, 'dividends') and ticker_obj.dividends is not None and len(ticker_obj.dividends) > 0:
            for date, dividend in ticker_obj.dividends.items():
                events.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'type': 'Dividend',
                    'detail': f'₹ {dividend:.2f}',
                    'description': f'Dividend of ₹{dividend:.2f} per share'
                })
    except Exception as e:
        get_logger().debug(f"Could not fetch corporate events: {str(e)}")
    
    # Sort by date, most recent first
    return sorted(events, key=lambda x: x['date'], reverse=True)


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

    # Ensure all API responses are dicts
    yq_profile = ensure_dict(yq_profile)
    yq_detail = ensure_dict(yq_detail)
    yq_financial = ensure_dict(yq_financial)
    yq_price = ensure_dict(yq_price)
    yq_quote = ensure_dict(yq_quote)

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

    sentiment = 'neutral'
    if change is not None:
        sentiment = 'positive' if change > 0 else 'negative' if change < 0 else 'neutral'

    nse_quote = {}
    try:
        nse_quote = get_nse().get_quote(symbol.lower())
        if not isinstance(nse_quote, dict):
            nse_quote = {}
    except Exception:
        nse_quote = {}

    pe_ratio_value = safe_numeric(yq_financial.get('trailingPE') or yq_detail.get('trailingPE') or info.get('trailingPE'))
    pb_ratio_value = safe_numeric(yq_financial.get('priceToBook') or info.get('priceToBook'))
    price_to_fcf_value = safe_numeric(yq_detail.get('priceToFreeCashFlow') or info.get('priceToFreeCashFlow'))
    peg_ratio_value = safe_numeric(yq_financial.get('pegRatio') or info.get('pegRatio'))
    roic_value = safe_numeric(
        yq_financial.get('returnOnCapital')
        or yq_financial.get('returnOnCapitalEmployment')
        or info.get('returnOnCapital')
        or yq_financial.get('returnOnAssets')
    )
    gross_margin_value = safe_numeric(
        yq_financial.get('grossMargins')
        or yq_financial.get('grossProfitMargins')
        or info.get('grossMargins')
    )

    nse_quote = {}
    try:
        nse_quote = get_nse().get_quote(symbol.lower())
        if not isinstance(nse_quote, dict):
            nse_quote = {}
    except Exception:
        nse_quote = {}

    def format_check_value(value, is_percent=False):
        if value is None:
            return 'N/A'
        return f"{value * 100:.2f}%" if is_percent else f"{value:.2f}"

    def check_status(value, threshold, direction='lt'):
        if value is None:
            return 'unknown'
        if direction == 'lt':
            return 'pass' if value < threshold else 'fail'
        return 'pass' if value > threshold else 'fail'

    value_checklist = [
        {
            'label': 'P/E Ratio < 20',
            'value_display': format_check_value(pe_ratio_value),
            'threshold_display': '< 20',
            'status': check_status(pe_ratio_value, 20, 'lt'),
            'tooltip': 'A lower P/E ratio may indicate a more attractively valued stock relative to earnings.'
        },
        {
            'label': 'Price / FCF < 20',
            'value_display': format_check_value(price_to_fcf_value),
            'threshold_display': '< 20',
            'status': check_status(price_to_fcf_value, 20, 'lt'),
            'tooltip': 'Price-to-free-cash-flow helps gauge valuation against cash generation; lower is typically better.'
        },
        {
            'label': 'P/B Ratio < 2',
            'value_display': format_check_value(pb_ratio_value),
            'threshold_display': '< 2',
            'status': check_status(pb_ratio_value, 2, 'lt'),
            'tooltip': 'Price-to-book measures market value versus accounting value; lower values often fit value investing screens.'
        },
        {
            'label': 'PEG Ratio < 2',
            'value_display': format_check_value(peg_ratio_value),
            'threshold_display': '< 2',
            'status': check_status(peg_ratio_value, 2, 'lt'),
            'tooltip': 'PEG ratio adjusts valuation for growth; under 2 is commonly viewed as reasonable for value stocks.'
        },
        {
            'label': 'ROIC > 10%',
            'value_display': format_check_value(roic_value, is_percent=True),
            'threshold_display': '> 10%',
            'status': check_status(roic_value, 0.10, 'gt'),
            'tooltip': 'Return on invested capital shows how effectively the business deploys capital into returns.'
        },
        {
            'label': 'Gross Margin > 50%',
            'value_display': format_check_value(gross_margin_value, is_percent=True),
            'threshold_display': '> 50%',
            'status': check_status(gross_margin_value, 0.50, 'gt'),
            'tooltip': 'A strong gross margin indicates the business retains more revenue after direct costs.'
        }
    ]

    company_essentials = {
        'market_cap': format_inr_crore(yq_price.get('marketCap') or info.get('marketCap')),
        'enterprise_value': format_inr_crore(yq_financial.get('enterpriseValue')),
        'no_of_shares': format_inr(yq_financial.get('sharesOutstanding') or info.get('sharesOutstanding')),
        'pe_ratio': safe_value(pe_ratio_value),
        'pb_ratio': safe_value(pb_ratio_value),
        'price_to_fcf': safe_value(price_to_fcf_value),
        'peg_ratio': safe_value(peg_ratio_value),
        'roic': format_percent(roic_value),
        'gross_margin': format_percent(gross_margin_value),
        'face_value': safe_value(info.get('faceValue')),
        'div_yield': format_percent(yq_detail.get('dividendYield')),
        'book_value': format_inr(yq_financial.get('bookValue')),
        'cash': format_inr_crore(yq_financial.get('totalCash')),
        'debt': format_inr_crore(yq_financial.get('totalDebt')),
        'eps': safe_value(yq_financial.get('trailingEps') or info.get('trailingEps')),
        'roe': format_percent(yq_financial.get('returnOnEquity')),
        'roce': format_percent(yq_financial.get('returnOnAssets')),
        'promoter_holding': safe_value(nse_quote.get('promoterHolding')),
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
        'market_state': get_market_state_label(yq_price.get('marketState') or info.get('market_state'))
    }

    # NSE live data
    nse_info = {}
    if nse_quote:
        nse_info = {
            'Last Traded Price': nse_quote.get('lastPrice'),
            'Day High': nse_quote.get('dayHigh'),
            'Day Low': nse_quote.get('dayLow'),
            '52 Week High': nse_quote.get('high52'),
            '52 Week Low': nse_quote.get('low52'),
            'Volume': nse_quote.get('quantityTraded')
        }
    else:
        try:
            nse_data = get_nse().get_quote(symbol.lower())
            if isinstance(nse_data, dict):
                nse_info = {
                    'Last Traded Price': nse_data.get('lastPrice'),
                    'Day High': nse_data.get('dayHigh'),
                    'Day Low': nse_data.get('dayLow'),
                    '52 Week High': nse_data.get('high52'),
                    '52 Week Low': nse_data.get('low52'),
                    'Volume': nse_data.get('quantityTraded')
                }
        except Exception:
            nse_info = {}

    market_time = yq_price.get('regularMarketTime') or ''
    if isinstance(market_time, (int, float)) and market_time > 0:
        from datetime import timezone, timedelta
        india_tz = timezone(timedelta(hours=5, minutes=30))
        try:
            market_time = datetime.fromtimestamp(market_time, tz=timezone.utc).astimezone(india_tz).strftime('%Y-%m-%d %H:%M %Z')
        except Exception:
            market_time = str(market_time)

    # Fetch corporate events
    corporate_events = get_corporate_events(ticker)

    return {
        'symbol': symbol.upper(),
        'yfinance_fields': yfinance_fields,
        'nse_fields': nse_info,
        'hist_json': hist_data,
        'stock_profile': company_info,
        'price_summary': price_summary,
        'company_essentials': company_essentials,
        'value_checklist': value_checklist,
        'current_price': current_price,
        'previous_close': previous_close,
        'price_change': change,
        'price_change_percent': change_percent,
        'market_time': market_time,
        'market_sentiment': {
            'icon': '📈' if sentiment == 'positive' else '📉' if sentiment == 'negative' else '⏸️',
            'label': 'Bullish' if sentiment == 'positive' else 'Bearish' if sentiment == 'negative' else 'Neutral',
            'class': sentiment
        },
        'corporate_events': corporate_events
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
    symbol_upper = symbol.upper()

    try:
        stock_data_list = [get_stock_data(symbol, period='1y')]
        
        # Check if stock data is invalid (no price data)
        if not stock_data_list or stock_data_list[0].get('current_price') is None:
            suggestions = get_stock_suggestions(symbol)
            return render_template(
                "error.html",
                theme=theme,
                error_message=f"Stock symbol '{symbol_upper}' not found or has no data.",
                suggestions=suggestions
            ), 404

        # AI Prediction
        predictions = {}
        insights_dict = {}
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
    except AttributeError as e:
        suggestions = get_stock_suggestions(symbol)
        return render_template(
            "error.html",
            theme=theme,
            error_message=f"Error processing stock '{symbol_upper}'. It may not exist or be delisted. Please try another symbol.",
            suggestions=suggestions
        ), 400
    except Exception as e:
        get_logger().error(f"Dashboard error for {symbol_upper}: {str(e)}")
        suggestions = get_stock_suggestions(symbol)
        return render_template(
            "error.html",
            theme=theme,
            error_message=f"Error loading stock data. Please check the symbol and try again.",
            suggestions=suggestions
        ), 500

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
