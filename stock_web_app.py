from flask import Flask, render_template, request, jsonify
from datetime import datetime, time, timezone, timedelta
import threading
import time as time_module
import json
from pathlib import Path
import os
import contextlib

app = Flask(__name__)
_nse = None
_stock_predictor = None
_logger = None
_recent_searches = []  # Store recent search history
_nse_exchange_calendar = None
_index_cache_lock = threading.Lock()
_index_cache = {
    'market_open': False,
    'indices': {},
    'server_time': ''
}
_index_updater_thread = None
_stock_cache_lock = threading.Lock()
_stock_cache = {}
_stock_updater_threads = {}
_search_store_lock = threading.Lock()
_search_store = None

TOP_SEARCHED_FILE = Path(__file__).resolve().parent / 'data' / 'top_searched_stocks.json'
DEFAULT_TRENDING_STOCKS = ['RELIANCE', 'TCS', 'INFY', 'HDFC', 'BAJAJFINSV']
STOCK_BASE_METADATA = {
    'RELIANCE': {'name': 'Reliance', 'sector': 'Energy'},
    'TCS': {'name': 'Tata Consultancy', 'sector': 'IT'},
    'INFY': {'name': 'Infosys', 'sector': 'IT'},
    'HDFC': {'name': 'HDFC Bank', 'sector': 'Banking'},
    'BAJAJFINSV': {'name': 'Bajaj Finance', 'sector': 'Finance'},
    'HINDUNILVR': {'name': 'HUL', 'sector': 'FMCG'},
    'LT': {'name': 'Larsen & Toubro', 'sector': 'Engineering'},
    'ASIANPAINT': {'name': 'Asian Paints', 'sector': 'Chemicals'},
    'AXISBANK': {'name': 'Axis Bank', 'sector': 'Banking'},
    'HCLTECH': {'name': 'HCL Tech', 'sector': 'IT'},
    'ONGC': {'name': 'ONGC', 'sector': 'Energy'},
    'CDSL': {'name': 'CDSL', 'sector': 'Financial Services'},
    'BSE': {'name': 'BSE Limited', 'sector': 'Financial Services'},
    'WIPRO': {'name': 'Wipro', 'sector': 'IT'},
    'ICICIBANK': {'name': 'ICICI Bank', 'sector': 'Banking'},
    'SBIN': {'name': 'State Bank of India', 'sector': 'Banking'}
}


def _is_production_mode():
    return os.environ.get('STOCKSENSE_ENV', '').lower() == 'production'


def _run_yf_call(callable_obj, *args, **kwargs):
    """Run yfinance calls with stderr suppression only in production mode."""
    if not _is_production_mode():
        return callable_obj(*args, **kwargs)

    with open(os.devnull, 'w', encoding='utf-8') as devnull, contextlib.redirect_stderr(devnull):
        return callable_obj(*args, **kwargs)

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
    symbol_upper = _normalize_symbol(symbol)
    if not symbol_upper:
        return

    if symbol_upper in _recent_searches:
        _recent_searches.remove(symbol_upper)
    _recent_searches.insert(0, symbol_upper)
    # Keep only the most recent 10 searches
    _recent_searches[:] = _recent_searches[:10]
    _record_search(symbol_upper)


def _ensure_search_store_loaded():
    global _search_store
    with _search_store_lock:
        if _search_store is not None:
            return

        loaded = {}
        try:
            if TOP_SEARCHED_FILE.exists():
                data = json.loads(TOP_SEARCHED_FILE.read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    loaded = {str(k).upper(): v for k, v in data.items() if isinstance(v, dict)}
        except Exception:
            loaded = {}

        _search_store = loaded


def _persist_search_store_locked():
    TOP_SEARCHED_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOP_SEARCHED_FILE.write_text(json.dumps(_search_store, indent=2), encoding='utf-8')


def _record_search(symbol):
    symbol_upper = _normalize_symbol(symbol)
    if not symbol_upper:
        return

    _ensure_search_store_loaded()
    with _search_store_lock:
        entry = _search_store.get(symbol_upper, {})
        entry['count'] = int(entry.get('count', 0)) + 1
        entry['last_searched_at'] = _current_ist_time_str()
        if 'fallback' not in entry:
            entry['fallback'] = {
                'name': STOCK_BASE_METADATA.get(symbol_upper, {}).get('name', symbol_upper),
                'sector': STOCK_BASE_METADATA.get(symbol_upper, {}).get('sector', 'N/A'),
                'price': 'N/A',
                'change': '0.00',
                'updated_at': '--'
            }
        _search_store[symbol_upper] = entry
        _persist_search_store_locked()


def _update_fallback_snapshot(symbol, stock_info):
    symbol_upper = _normalize_symbol(symbol)
    if not symbol_upper:
        return

    _ensure_search_store_loaded()
    with _search_store_lock:
        entry = _search_store.get(symbol_upper, {})
        entry['fallback'] = {
            'name': stock_info.get('name', STOCK_BASE_METADATA.get(symbol_upper, {}).get('name', symbol_upper)),
            'sector': stock_info.get('sector', STOCK_BASE_METADATA.get(symbol_upper, {}).get('sector', 'N/A')),
            'price': stock_info.get('price', 'N/A'),
            'change': stock_info.get('change', '0.00'),
            'updated_at': _current_ist_time_str()
        }
        entry['last_updated_at'] = _current_ist_time_str()
        entry['count'] = int(entry.get('count', 0))
        _search_store[symbol_upper] = entry
        _persist_search_store_locked()


def get_top_searched_symbols(limit=5):
    _ensure_search_store_loaded()
    with _search_store_lock:
        ranked = sorted(
            _search_store.items(),
            key=lambda item: (-int(item[1].get('count', 0)), item[0])
        )
        symbols = [symbol for symbol, _ in ranked[:limit]]

    if symbols:
        return symbols
    return DEFAULT_TRENDING_STOCKS[:limit]


def _build_dynamic_fallback_data(symbols):
    _ensure_search_store_loaded()
    fallback = {}
    with _search_store_lock:
        for symbol in symbols:
            symbol_upper = _normalize_symbol(symbol)
            entry = _search_store.get(symbol_upper, {})
            entry_fallback = entry.get('fallback', {}) if isinstance(entry.get('fallback', {}), dict) else {}
            fallback[symbol_upper] = {
                'name': entry_fallback.get('name', STOCK_BASE_METADATA.get(symbol_upper, {}).get('name', symbol_upper)),
                'sector': entry_fallback.get('sector', STOCK_BASE_METADATA.get(symbol_upper, {}).get('sector', 'N/A')),
                'price': entry_fallback.get('price', 'N/A'),
                'change': entry_fallback.get('change', '0.00'),
                'updated_at': entry_fallback.get('updated_at', '--')
            }
    return fallback

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


def _normalize_symbol(symbol):
    return (symbol or '').strip().split(',')[0].strip().upper()


def _normalize_period(period):
    return (period or '1y').strip().lower()


def _stock_cache_key(symbol, period):
    return (_normalize_symbol(symbol), _normalize_period(period))


def _build_stock_payload(stock):
    return {
        'symbol': stock['symbol'],
        'hist_json': stock['hist_json'],
        'current_price': stock['current_price'],
        'previous_close': stock['previous_close'],
        'price_change': stock['price_change'],
        'price_change_percent': stock['price_change_percent'],
        'market_time': stock['market_time'],
        'value_updated_at': stock.get('market_time') or '--',
        'price_summary': stock['price_summary'],
        'company_essentials': stock['company_essentials'],
        'stock_profile': stock['stock_profile'],
        'server_time': _current_ist_time_str()
    }


def _build_empty_stock_payload(symbol):
    """Safe payload shape returned when upstream market APIs are temporarily unavailable."""
    symbol_upper = _normalize_symbol(symbol)
    base_meta = STOCK_BASE_METADATA.get(symbol_upper, {})
    return {
        'symbol': symbol_upper,
        'hist_json': [],
        'current_price': None,
        'previous_close': None,
        'price_change': None,
        'price_change_percent': None,
        'market_time': '',
        'value_updated_at': '--',
        'price_summary': {
            'today_high': None,
            'today_low': None,
            'week_high': None,
            'week_low': None
        },
        'company_essentials': {
            'market_cap': 'N/A',
            'enterprise_value': 'N/A',
            'no_of_shares': 'N/A',
            'pe_ratio': 'N/A',
            'pb_ratio': 'N/A',
            'face_value': 'N/A',
            'div_yield': 'N/A',
            'book_value': 'N/A',
            'cash': 'N/A',
            'debt': 'N/A',
            'eps': 'N/A',
            'roe': 'N/A',
            'roce': 'N/A',
            'promoter_holding': 'N/A',
            'sales_growth': 'N/A',
            'profit_growth': 'N/A'
        },
        'stock_profile': {
            'company_name': base_meta.get('name', symbol_upper),
            'sector': base_meta.get('sector', 'N/A'),
            'industry': 'N/A',
            'summary': '',
            'website': '',
            'exchange': 'NSE',
            'market_state': ''
        },
        'server_time': _current_ist_time_str(),
        'error': 'Live quote temporarily unavailable'
    }


def _refresh_stock_cache_once(symbol, period):
    normalized_symbol = _normalize_symbol(symbol)
    normalized_period = _normalize_period(period)

    if not normalized_symbol:
        raise ValueError('Invalid symbol')

    stock = get_stock_data(normalized_symbol, period=normalized_period)
    payload = _build_stock_payload(stock)

    with _stock_cache_lock:
        previous_payload = _stock_cache.get((normalized_symbol, normalized_period), {})

    prev_value_signature = (
        previous_payload.get('current_price'),
        previous_payload.get('previous_close'),
        previous_payload.get('price_change'),
        previous_payload.get('price_change_percent')
    )
    curr_value_signature = (
        payload.get('current_price'),
        payload.get('previous_close'),
        payload.get('price_change'),
        payload.get('price_change_percent')
    )

    exchange_time = payload.get('market_time')
    previous_value_time = previous_payload.get('value_updated_at')

    if curr_value_signature != prev_value_signature:
        payload['value_updated_at'] = exchange_time or _current_ist_time_str()
    else:
        payload['value_updated_at'] = previous_value_time or exchange_time or '--'

    with _stock_cache_lock:
        _stock_cache[(normalized_symbol, normalized_period)] = payload

    return payload


def _stock_updater_loop(symbol, period):
    normalized_symbol = _normalize_symbol(symbol)
    normalized_period = _normalize_period(period)

    while True:
        try:
            _refresh_stock_cache_once(normalized_symbol, normalized_period)
            sleep_seconds = 1 if is_indian_market_open() else 30
        except Exception:
            sleep_seconds = 5
        time_module.sleep(sleep_seconds)


def ensure_stock_updater_started(symbol, period='1y'):
    key = _stock_cache_key(symbol, period)
    normalized_symbol, normalized_period = key

    if not normalized_symbol:
        return

    with _stock_cache_lock:
        worker = _stock_updater_threads.get(key)
        if worker and worker.is_alive():
            return

        worker = threading.Thread(
            target=_stock_updater_loop,
            args=(normalized_symbol, normalized_period),
            name=f'stock-cache-updater-{normalized_symbol}-{normalized_period}',
            daemon=True
        )
        _stock_updater_threads[key] = worker
        worker.start()


def get_stock_payload_snapshot(symbol, period='1y'):
    key = _stock_cache_key(symbol, period)
    normalized_symbol, normalized_period = key

    if not normalized_symbol:
        raise ValueError('Invalid symbol')

    ensure_stock_updater_started(normalized_symbol, normalized_period)

    with _stock_cache_lock:
        payload = _stock_cache.get(key)

    if payload:
        return payload

    # First request fallback before thread completes initial cycle.
    try:
        return _refresh_stock_cache_once(normalized_symbol, normalized_period)
    except Exception:
        with _stock_cache_lock:
            payload = _stock_cache.get(key)
        if payload:
            return payload
        return _build_empty_stock_payload(normalized_symbol)


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
            hist = _run_yf_call(ticker.history, period='1d', interval='5m').reset_index()
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
            hist = _run_yf_call(ticker.history, period=yf_period).reset_index()
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
    try:
        info = _run_yf_call(lambda: ticker.info) or {}
    except Exception:
        info = {}
    yq_profile = {}
    yq_detail = {}
    yq_financial = {}
    yq_price = {}
    yq_quote = {}

    def _safe_yq_section(section):
        if isinstance(section, dict):
            return section
        return {}

    try:
        raw_profile = _safe_yq_section(yq_ticker.summary_profile)
        raw_detail = _safe_yq_section(yq_ticker.summary_detail)
        raw_financial = _safe_yq_section(yq_ticker.financial_data)
        raw_price = _safe_yq_section(yq_ticker.price)
        raw_quote = _safe_yq_section(yq_ticker.quote_type)

        yq_profile = _safe_yq_section(raw_profile.get(yf_symbol, {}))
        yq_detail = _safe_yq_section(raw_detail.get(yf_symbol, {}))
        yq_financial = _safe_yq_section(raw_financial.get(yf_symbol, {}))
        yq_price = _safe_yq_section(raw_price.get(yf_symbol, {}))
        yq_quote = _safe_yq_section(raw_quote.get(yf_symbol, {}))
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

    promoter_holding_value = None
    try:
        if hasattr(get_nse(), 'get_quote'):
            quote_data = get_nse().get_quote(symbol.lower())
            if isinstance(quote_data, dict):
                promoter_holding_value = quote_data.get('promoterHolding')
    except Exception:
        promoter_holding_value = None

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
        'promoter_holding': safe_value(promoter_holding_value),
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
    nse_market_time = ''
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
        nse_market_time = (
            nse_data.get('lastUpdateTime')
            or nse_data.get('lastUpdate')
            or nse_data.get('tradeTime')
            or ''
        )
        nse_current_price = _safe_float(nse_data.get('lastPrice') or nse_data.get('ltp'))
        nse_previous_close = _safe_float(nse_data.get('previousClose') or nse_data.get('prevClose'))
        if current_price is None and nse_current_price is not None:
            current_price = nse_current_price
        if previous_close is None and nse_previous_close is not None:
            previous_close = nse_previous_close
    except Exception:
        nse_info = {}

    # If market time is numeric, convert to India time string.
    market_time = yq_price.get('regularMarketTime') or info.get('regularMarketTime') or ''
    if isinstance(market_time, (int, float)) and market_time > 0:
        from datetime import datetime, timezone, timedelta
        india_tz = timezone(timedelta(hours=5, minutes=30))
        try:
            market_time = datetime.fromtimestamp(market_time, tz=timezone.utc).astimezone(india_tz).strftime('%Y-%m-%d %H:%M %Z')
        except Exception:
            market_time = str(market_time)

    if not market_time:
        market_time = nse_market_time or ''

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
    trending_symbols = get_top_searched_symbols(limit=5)
    fallback_data = _build_dynamic_fallback_data(trending_symbols)

    trending = []
    for symbol in trending_symbols:
        symbol_upper = _normalize_symbol(symbol)
        stock_info = fallback_data.get(symbol_upper, {
            'name': STOCK_BASE_METADATA.get(symbol_upper, {}).get('name', symbol_upper),
            'sector': STOCK_BASE_METADATA.get(symbol_upper, {}).get('sector', 'N/A'),
            'price': 'N/A',
            'change': '0.00',
            'updated_at': '--'
        })

        try:
            live_stock = get_stock_payload_snapshot(symbol_upper, period='7d')
            current_price = live_stock.get('current_price')
            change_pct = live_stock.get('price_change_percent')
            stock_info = {
                'name': live_stock['stock_profile'].get('company_name', symbol_upper),
                'sector': live_stock['stock_profile'].get('sector', 'N/A'),
                'price': f"{current_price:.2f}" if isinstance(current_price, (int, float)) else 'N/A',
                'change': f"{change_pct * 100:.2f}" if isinstance(change_pct, (int, float)) else '0.00',
                'updated_at': live_stock.get('value_updated_at', '--')
            }
            _update_fallback_snapshot(symbol_upper, stock_info)
        except Exception:
            pass

        trending.append({
            'symbol': symbol_upper,
            'name': stock_info['name'],
            'sector': stock_info['sector'],
            'price': stock_info['price'],
            'change': stock_info['change'],
            'updated_at': stock_info.get('updated_at', '--'),
        })

    return trending


def _safe_float(value):
    try:
        if isinstance(value, str):
            return float(value.replace(',', ''))
        return float(value)
    except Exception:
        return None


def _format_ist_time_from_epoch(epoch_seconds):
    """Convert epoch seconds to HH:MM:SS IST format."""
    try:
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        ts = float(epoch_seconds)
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ist_tz).strftime('%H:%M:%S IST')
    except Exception:
        return None


def _current_ist_time_str():
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(timezone.utc).astimezone(ist_tz).strftime('%H:%M:%S IST')


def _refresh_index_cache_once():
    market_open = is_indian_market_open()
    fresh_indices = fetch_index_quote_data()

    with _index_cache_lock:
        previous_indices = _index_cache.get('indices', {})

    indices = {}
    now_ist = _current_ist_time_str()
    for index_id, index_info in fresh_indices.items():
        previous = previous_indices.get(index_id, {})
        prev_signature = (
            previous.get('last'),
            previous.get('change'),
            previous.get('percent')
        )
        curr_signature = (
            index_info.get('last'),
            index_info.get('change'),
            index_info.get('percent')
        )

        api_time = index_info.get('api_time')
        prev_updated_at = previous.get('updated_at')

        if curr_signature != prev_signature:
            updated_at = api_time or now_ist
        else:
            updated_at = prev_updated_at or api_time or '--'

        merged = dict(index_info)
        merged['updated_at'] = updated_at
        merged.pop('api_time', None)
        indices[index_id] = merged

    payload = {
        'market_open': market_open,
        'indices': indices,
        'server_time': _current_ist_time_str()
    }
    with _index_cache_lock:
        _index_cache.update(payload)
    return payload


def _index_updater_loop():
    """Background updater that keeps index cache fresh for low-latency API responses."""
    while True:
        try:
            payload = _refresh_index_cache_once()
            sleep_seconds = 1 if payload.get('market_open') else 30
        except Exception:
            sleep_seconds = 5
        time_module.sleep(sleep_seconds)


def ensure_index_updater_started():
    global _index_updater_thread
    if _index_updater_thread and _index_updater_thread.is_alive():
        return

    with _index_cache_lock:
        if _index_updater_thread and _index_updater_thread.is_alive():
            return

        _index_updater_thread = threading.Thread(
            target=_index_updater_loop,
            name='index-cache-updater',
            daemon=True
        )
        _index_updater_thread.start()


def get_index_payload_snapshot():
    ensure_index_updater_started()

    with _index_cache_lock:
        has_data = bool(_index_cache.get('indices'))
        payload = dict(_index_cache)

    if has_data:
        return payload

    # First request fallback before thread completes initial cycle.
    return _refresh_index_cache_once()


def get_nse_exchange_calendar():
    """Lazily load NSE trading calendar used for holiday/session checks."""
    global _nse_exchange_calendar
    if _nse_exchange_calendar is None:
        try:
            import exchange_calendars as xcals
            _nse_exchange_calendar = xcals.get_calendar("XNSE")
        except Exception:
            # If calendar lib is unavailable, keep a disabled sentinel.
            _nse_exchange_calendar = False
    return _nse_exchange_calendar


def is_nse_trading_holiday(date_ist):
    """Return True if date is a non-session day on NSE (includes exchange holidays)."""
    calendar = get_nse_exchange_calendar()
    if not calendar:
        return False

    try:
        import pandas as pd
        session_label = pd.Timestamp(date_ist)
        return not calendar.is_session(session_label)
    except Exception:
        return False


def is_indian_market_open(now_utc=None):
    """Return True during regular NSE/BSE cash session hours (Mon-Fri, 09:15-15:30 IST), excluding exchange holidays."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    ist_tz = timezone(timedelta(hours=5, minutes=30))
    now_ist = now_utc.astimezone(ist_tz)

    if now_ist.weekday() >= 5:
        return False

    if is_nse_trading_holiday(now_ist.date()):
        return False

    market_open_time = time(9, 15)
    market_close_time = time(15, 30)
    return market_open_time <= now_ist.time() <= market_close_time


def _fetch_sensex_quote():
    """Fetch SENSEX with multiple fallbacks because yfinance.info can be stale/intermittent."""
    import yfinance as yf

    ticker = yf.Ticker('^BSESN')
    quote = {
        'last': None,
        'previousClose': None,
        'percentChange': None,
        'variation': None,
        'marketTime': None
    }

    try:
        fast_info = getattr(ticker, 'fast_info', {}) or {}
        quote['last'] = _safe_float(fast_info.get('lastPrice') or fast_info.get('last_price'))
        quote['previousClose'] = _safe_float(fast_info.get('previousClose') or fast_info.get('previous_close'))
    except Exception:
        pass

    try:
        if quote['last'] is None:
            intraday = _run_yf_call(ticker.history, period='1d', interval='1m')
            if intraday is not None and not intraday.empty and 'Close' in intraday:
                last_close = intraday['Close'].dropna()
                if not last_close.empty:
                    quote['last'] = _safe_float(last_close.iloc[-1])

        if quote['previousClose'] is None:
            daily = _run_yf_call(ticker.history, period='5d', interval='1d')
            if daily is not None and not daily.empty and 'Close' in daily:
                daily_close = daily['Close'].dropna()
                if len(daily_close) >= 2:
                    quote['previousClose'] = _safe_float(daily_close.iloc[-2])
                elif len(daily_close) == 1:
                    quote['previousClose'] = _safe_float(daily_close.iloc[-1])
    except Exception:
        pass

    try:
        if quote['last'] is None or quote['previousClose'] is None:
            info = _run_yf_call(lambda: ticker.info) or {}
            quote['last'] = quote['last'] or _safe_float(info.get('regularMarketPrice'))
            quote['previousClose'] = quote['previousClose'] or _safe_float(info.get('regularMarketPreviousClose'))
            quote['percentChange'] = _safe_float(info.get('regularMarketChangePercent'))
            quote['marketTime'] = _safe_float(info.get('regularMarketTime'))
    except Exception:
        pass

    if quote['last'] is not None and quote['previousClose'] is not None:
        quote['variation'] = round(quote['last'] - quote['previousClose'], 2)
        if quote['percentChange'] is None and quote['previousClose'] != 0:
            quote['percentChange'] = round((quote['variation'] / quote['previousClose']) * 100, 2)

    return quote


def fetch_index_quote_data():
    index_map = {
        'nifty50': 'NIFTY 50',
        'banknifty': 'NIFTY BANK',
        'finnifty': 'NIFTY FIN SERVICE',
        'sensex': '^BSESN',
        'midcpnifty': 'NIFTY MID SELECT'
    }
    index_data = {}

    for index_id, api_name in index_map.items():
        quote = {}
        if index_id == 'sensex':
            try:
                quote = _fetch_sensex_quote()
            except Exception:
                quote = {}
        else:
            try:
                quote = get_nse().get_index_quote(api_name) or {}
            except Exception:
                quote = {}

        last = _safe_float(quote.get('last') or quote.get('current_price') or quote.get('previousClose'))
        previous = _safe_float(quote.get('previousClose') or quote.get('prevclose') or quote.get('prev_close') or quote.get('previousDayVal'))
        percent = _safe_float(quote.get('percentChange') or quote.get('percent_change') or quote.get('percentchange') or quote.get('variation'))
        variation = _safe_float(quote.get('variation') or quote.get('change') or quote.get('net_change'))

        if last is not None and previous is not None and variation is None:
            variation = round(last - previous, 2)
        if percent is None and last is not None and previous is not None and previous != 0:
            percent = round((last - previous) / previous * 100, 2)

        quote_time = _format_ist_time_from_epoch(
            quote.get('marketTime')
            or quote.get('regularMarketTime')
            or quote.get('timeVal')
            or quote.get('timestamp')
        )

        direction = 'positive' if last is not None and previous is not None and last >= previous else 'negative'
        index_data[index_id] = {
            'last': f"{last:,.2f}" if last is not None else 'N/A',
            'change': f"{variation:+,.2f}" if variation is not None else 'N/A',
            'percent': f"{percent:.2f}" if percent is not None else 'N/A',
            'direction': direction,
            'raw_change': variation,
            'raw_percent': percent,
            'api_time': quote_time
        }

    return index_data


@app.route("/")
def home():
    theme = request.args.get("theme", "light")
    trending_stocks = get_trending_stocks()
    market_indices = []

    try:
        live_index_data = get_index_payload_snapshot().get('indices', {})
        index_names = {
            'nifty50': 'NIFTY 50',
            'banknifty': 'BANK NIFTY',
            'finnifty': 'FIN NIFTY',
            'sensex': 'SENSEX',
            'midcpnifty': 'MIDCP NIFTY'
        }
        market_indices = [
            {
                'id': index_id,
                'name': index_names.get(index_id, index_id.upper()),
                'value': index_info.get('last', 'N/A'),
                'change': index_info.get('change', 'N/A'),
                'percent': index_info.get('percent', 'N/A'),
                'direction': index_info.get('direction', 'negative'),
                'updated_at': index_info.get('updated_at', '--')
            }
            for index_id, index_info in live_index_data.items()
        ]
    except Exception:
        market_indices = [
            {'id': 'nifty50', 'name': 'NIFTY 50', 'value': '23,547.75', 'change': '-359.40', 'percent': '-1.50', 'direction': 'down', 'updated_at': '--'},
            {'id': 'banknifty', 'name': 'BANK NIFTY', 'value': '54,239.20', 'change': '-614.65', 'percent': '-1.12', 'direction': 'down', 'updated_at': '--'},
            {'id': 'finnifty', 'name': 'FIN NIFTY', 'value': '25,354.00', 'change': '-398.20', 'percent': '-1.55', 'direction': 'down', 'updated_at': '--'},
            {'id': 'sensex', 'name': 'SENSEX', 'value': '74,775.74', 'change': '-1,092.06', 'percent': '-1.44', 'direction': 'down', 'updated_at': '--'},
            {'id': 'midcpnifty', 'name': 'MIDCP NIFTY', 'value': '14,474.90', 'change': '-231.05', 'percent': '-1.57', 'direction': 'down', 'updated_at': '--'},
        ]

    return render_template("home.html", theme=theme, trending_stocks=trending_stocks, market_indices=market_indices)

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if request.method == "POST":
        symbol = request.form.get("symbol", "RELIANCE").strip().split(",")[0].strip()
        theme = request.form.get("theme", "dark")
    else:
        symbol = request.args.get("symbol", "RELIANCE").strip().split(",")[0].strip()
        theme = request.args.get("theme", "dark")

    if not symbol:
        symbol = "RELIANCE"

    # Add to recent searches
    add_recent_search(symbol)

    stock_data_list = [get_stock_payload_snapshot(symbol, period='1y')]
    peer_stocks = get_trending_stocks()

    # AI Prediction
    predictions = {}
    insights_dict = {}
    symbol_upper = symbol.upper()
    
    try:
        get_stock_predictor().train(symbol_upper)
        predictions[symbol_upper] = get_stock_predictor().predict(symbol_upper)
        insights_dict[symbol_upper] = get_stock_predictor().get_insights(symbol_upper)
    except Exception as e:
        # Gracefully handle prediction errors (delisted stocks, API failures, model not trained, etc.)
        error_msg = str(e)
        get_logger().warning(f"Predictor error for {symbol_upper}: {error_msg}")
        predictions[symbol_upper] = {}
        insights_dict[symbol_upper] = {
            'direction': 'Data processing',
            'direction_symbol': '⏳',
            'confidence': None,
            'breakout_confirmation': 'Model training in background. Check back soon.',
            'forecast': 'Insufficient historical data for predictions',
            'predicted_next': None,
            'advice': 'Showing latest market data. AI insights will be available after training.',
            'trailing_stop_pct': None
        }

    return render_template(
        "dashboard.html",
        symbol=symbol_upper,
        theme=theme,
        stock_data_list=stock_data_list,
        predictions=predictions,
        insights=insights_dict,
        peer_stocks=peer_stocks
    )

@app.route("/index_data")
def index_data():
    try:
        payload = get_index_payload_snapshot()
    except Exception as e:
        return jsonify(error="Unable to fetch index data", details=str(e)), 500
    response = jsonify(payload)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route("/market_status")
def market_status():
    response = jsonify(market_open=is_indian_market_open())
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route("/chart_data")
def chart_data():
    symbol = request.args.get("symbol", "RELIANCE").strip().split(",")[0].strip()
    period = request.args.get("period", "1y")
    if not symbol:
        symbol = "RELIANCE"
    stock = get_stock_payload_snapshot(symbol, period=period)
    return jsonify(hist_json=stock["hist_json"])

@app.route("/stock_data")
def stock_data():
    symbol = request.args.get("symbol", "RELIANCE").strip().split(",")[0].strip()
    period = request.args.get("period", "1y")
    if not symbol:
        symbol = "RELIANCE"

    try:
        stock = get_stock_payload_snapshot(symbol, period=period)
    except Exception as e:
        return jsonify(
            symbol=symbol.upper(),
            hist_json=[],
            current_price=None,
            previous_close=None,
            price_change=None,
            price_change_percent=None,
            market_time='',
            price_summary={},
            company_essentials={},
            stock_profile={
                'company_name': symbol.upper(),
                'sector': 'N/A',
                'industry': 'N/A',
                'summary': '',
                'website': '',
                'exchange': 'NSE',
                'market_state': ''
            },
            server_time=_current_ist_time_str(),
            error="Unable to fetch stock data",
            details=str(e)
        ), 200

    return jsonify(stock)

@app.before_request
def log_request_info():
    pass  # Logging disabled for now
    # get_logger().info(f"User requested data for {request.args.get('symbol')}")
    # get_logger().debug(f"Request data: {request.args}")

if __name__ == "__main__":
    # Replace the default Flask server banner with a custom local startup message.
    import os
    import flask.cli
    flask.cli.show_server_banner = lambda *args, **kwargs: None

    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        print("StockSense AI local server starting at http://127.0.0.1:5000")

    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
# stock_web_app.py
# This file is part of the StockSense AI project.
# It provides a Flask web application to display stock data and predictions.
