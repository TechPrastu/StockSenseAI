from nsetools import Nse
import yfinance as yf
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
import joblib
import os
import threading
from ai.logger import StockSenseAILogger
# pip install yahooquery
from yahooquery import Ticker
from datetime import datetime, timezone, timedelta

INDIA_TZ = timezone(timedelta(hours=5, minutes=30))
logger = StockSenseAILogger.get_logger(__name__)

# Configurable threshold: consider 'near-breakout' when within this fraction (3%)
NEAR_BREAKOUT_PCT = 0.03

import json
from pathlib import Path

_PATTERN_MAP = None
_PATTERN_MAP_MTIME = None

def load_pattern_map():
    global _PATTERN_MAP, _PATTERN_MAP_MTIME
    p = Path(__file__).parent / 'patterns.json'
    if not p.exists():
        _PATTERN_MAP = {}
        _PATTERN_MAP_MTIME = None
        return _PATTERN_MAP

    try:
        current_mtime = p.stat().st_mtime
        if _PATTERN_MAP is None or _PATTERN_MAP_MTIME != current_mtime:
            _PATTERN_MAP = json.loads(p.read_text())
            _PATTERN_MAP_MTIME = current_mtime
    except Exception:
        if _PATTERN_MAP is None:
            _PATTERN_MAP = {}
    return _PATTERN_MAP

def normalize_pattern_map(patterns):
    normalized = {}
    for key, entry in (patterns or {}).items():
        if not isinstance(entry, dict):
            continue
        normalized[key.strip()] = {
            'title': entry.get('title', key.strip()),
            'description': entry.get('description', ''),
            'suggested_trailing_pct': entry.get('suggested_trailing_pct', 3),
            'notes': entry.get('notes', ''),
            'risk_level': entry.get('risk_level', ''),
            'aliases': [a.lower() for a in entry.get('aliases', []) if isinstance(a, str)],
            **entry,
        }
    return normalized


def find_pattern_map_entry(chart_pattern, patterns):
    if not chart_pattern or not patterns:
        return None
    chart_pattern_text = str(chart_pattern).strip()
    lower_pattern = chart_pattern_text.lower()

    if chart_pattern_text in patterns:
        return patterns[chart_pattern_text]

    for key, entry in patterns.items():
        if key.lower() == lower_pattern:
            return entry

    for key, entry in patterns.items():
        if key.lower() in lower_pattern or lower_pattern in key.lower():
            return entry

    for entry in patterns.values():
        for alias in entry.get('aliases', []):
            if alias and alias in lower_pattern:
                return entry

    return None


def apply_pattern_advice(insights, hist=None):
    """Add `advice`, `trailing_stop_pct`, and structured pattern details to insights."""
    patterns = normalize_pattern_map(load_pattern_map())
    chart_pattern = insights.get('chart_pattern') or ''
    matched = find_pattern_map_entry(chart_pattern, patterns)

    if matched:
        trailing_pct = matched.get('suggested_trailing_pct', 3)
        advice_template = matched.get('advice') or matched.get('description', '')
        advice = advice_template.format(suggested_trailing_pct=trailing_pct)

        insights['pattern_title'] = matched.get('title', chart_pattern)
        insights['pattern_description'] = matched.get('description', '')
        insights['pattern_notes'] = matched.get('notes')
        insights['pattern_risk_level'] = matched.get('risk_level')
        insights['pattern_known'] = True
        insights['trailing_stop_pct'] = trailing_pct
        insights['advice'] = advice
        return insights

    insights['pattern_title'] = chart_pattern or 'Unknown pattern'
    insights['pattern_description'] = ''
    insights['pattern_notes'] = ''
    insights['pattern_risk_level'] = ''
    insights['pattern_known'] = False

    vol = insights.get('volatility')
    conf = insights.get('confidence')
    direction = insights.get('direction')
    if isinstance(vol, (int, float)):
        suggested = max(1.0, round(vol * 200, 1))
    else:
        suggested = 3.0

    if conf is not None and conf >= 0.75 and direction == 'Upside':
        advice = f"Strong upside signal — consider trailing stop to lock profits at ~{suggested}% below price."
    elif conf is not None and conf >= 0.6 and direction == 'Downside':
        advice = f"Downside bias — consider defensive trailing stop ~{suggested}% or reduce position size."
    else:
        advice = f"No clear high-confidence pattern detected. Consider a conservative trailing stop of ~{suggested}%."

    insights['advice'] = advice
    insights['trailing_stop_pct'] = suggested
    return insights


def detect_moving_average_breakout(hist):
    """Detect short-term moving average crossing long-term.
    Uses SMA20/SMA50 with confirmation above SMA100 and price above both averages."""
    try:
        if hist is None or hist.empty or 'Close' not in hist.columns:
            return None
        series = hist['Close'].astype(float)
        sma_short = series.rolling(window=20).mean()
        sma_mid = series.rolling(window=50).mean()
        sma_long = series.rolling(window=100).mean()
        if len(sma_long) < 2:
            return None
        if sma_short.iloc[-2] <= sma_mid.iloc[-2] and sma_short.iloc[-1] > sma_mid.iloc[-1] and sma_mid.iloc[-1] > sma_long.iloc[-1]:
            if series.iloc[-1] > sma_short.iloc[-1] and series.iloc[-1] > sma_mid.iloc[-1]:
                return 'Moving Average Breakout'
    except Exception:
        return None
    return None


def detect_double_top(hist):
    """Heuristic double-top detection based on two similar peaks separated by a trough."""
    try:
        if hist is None or hist.empty or 'Close' not in hist.columns:
            return None
        closes = hist['Close'].astype(float)
        window = min(80, len(closes))
        recent = closes[-window:]
        if len(recent) < 10:
            return None
        peaks = recent.rolling(window=5, center=True).apply(lambda x: x[2] == x.max(), raw=True)
        peak_positions = [i for i, val in enumerate(peaks) if val == 1]
        if len(peak_positions) < 2:
            return None
        first, second = peak_positions[-2], peak_positions[-1]
        if second - first < 4:
            return None
        p1 = recent.iloc[first]
        p2 = recent.iloc[second]
        if abs(p1 - p2) / max(p1, p2) > 0.05:
            return None
        trough = recent.iloc[first:second + 1].min()
        if trough < min(p1, p2) * 0.96:
            return 'Double Top'
    except Exception:
        return None
    return None


def detect_double_bottom(hist):
    """Heuristic double-bottom detection based on two similar lows separated by a peak."""
    try:
        if hist is None or hist.empty or 'Close' not in hist.columns:
            return None
        closes = hist['Close'].astype(float)
        window = min(80, len(closes))
        recent = closes[-window:]
        if len(recent) < 10:
            return None
        bottoms = recent.rolling(window=5, center=True).apply(lambda x: x[2] == x.min(), raw=True)
        bottom_positions = [i for i, val in enumerate(bottoms) if val == 1]
        if len(bottom_positions) < 2:
            return None
        first, second = bottom_positions[-2], bottom_positions[-1]
        if second - first < 4:
            return None
        b1 = recent.iloc[first]
        b2 = recent.iloc[second]
        if abs(b1 - b2) / max(b1, b2) > 0.05:
            return None
        peak = recent.iloc[first:second + 1].max()
        if peak > max(b1, b2) * 1.04:
            return 'Double Bottom'
    except Exception:
        return None
    return None


def detect_head_and_shoulders(hist):
    """Simple head-and-shoulders heuristic: three peaks with middle higher than shoulders."""
    try:
        if hist is None or hist.empty or 'Close' not in hist.columns:
            return None
        closes = hist['Close'].astype(float)
        window = min(100, len(closes))
        recent = closes[-window:]
        if len(recent) < 12:
            return None
        peaks = recent.rolling(window=7, center=True).apply(lambda x: x[3] == x.max(), raw=True)
        peak_positions = [i for i, val in enumerate(peaks) if val == 1]
        if len(peak_positions) < 3:
            return None
        left, mid, right = peak_positions[-3], peak_positions[-2], peak_positions[-1]
        if mid - left < 4 or right - mid < 4:
            return None
        p1 = recent.iloc[left]
        p2 = recent.iloc[mid]
        p3 = recent.iloc[right]
        if p2 > p1 * 1.04 and p2 > p3 * 1.04 and abs(p1 - p3) / max(p1, p3) < 0.07:
            trough1 = recent.iloc[left:mid + 1].min()
            trough2 = recent.iloc[mid:right + 1].min()
            if trough1 < p1 * 0.985 and trough2 < p3 * 0.985:
                return 'Head and Shoulders'
    except Exception:
        return None
    return None


def detect_ascending_triangle(hist):
    """Heuristic ascending triangle detection using rising lows and flat highs."""
    try:
        if hist is None or hist.empty or 'Close' not in hist.columns:
            return None
        closes = hist['Close'].astype(float)
        window = min(60, len(closes))
        recent = closes[-window:]
        if len(recent) < 12:
            return None
        highs = recent.rolling(window=5).max().dropna()
        lows = recent.rolling(window=5).min().dropna()
        if len(highs) < 6 or len(lows) < 6:
            return None
        top_levels = highs.nlargest(4)
        if top_levels.max() - top_levels.min() > top_levels.max() * 0.03:
            return None
        low_slope = (lows.iloc[-1] - lows.iloc[0]) / lows.iloc[0]
        if low_slope > 0.03:
            return 'Ascending Triangle'
    except Exception:
        return None
    return None


def detect_descending_triangle(hist):
    """Heuristic descending triangle detection using falling highs and flat lows."""
    try:
        if hist is None or hist.empty or 'Close' not in hist.columns:
            return None
        closes = hist['Close'].astype(float)
        window = min(60, len(closes))
        recent = closes[-window:]
        if len(recent) < 12:
            return None
        highs = recent.rolling(window=5).max().dropna()
        lows = recent.rolling(window=5).min().dropna()
        if len(highs) < 6 or len(lows) < 6:
            return None
        low_levels = lows.nsmallest(4)
        if low_levels.max() - low_levels.min() > low_levels.min() * 0.03:
            return None
        high_slope = (highs.iloc[-1] - highs.iloc[0]) / highs.iloc[0]
        if high_slope < -0.03:
            return 'Descending Triangle'
    except Exception:
        return None
    return None


def detect_bull_flag(hist):
    """Heuristic bull flag detection: strong run-up followed by tight consolidation."""
    try:
        if hist is None or hist.empty or 'Close' not in hist.columns:
            return None
        closes = hist['Close'].astype(float)
        if len(closes) < 15:
            return None
        recent = closes[-15:]
        run_up = (recent.iloc[4] - recent.iloc[0]) / recent.iloc[0]
        consolidation = recent.iloc[5:].max() - recent.iloc[5:].min()
        if run_up > 0.08 and consolidation / recent.iloc[5:].min() < 0.02:
            return 'Bull Flag'
    except Exception:
        return None
    return None


def detect_bear_flag(hist):
    """Heuristic bear flag detection: steep drop followed by narrow corrective bounce."""
    try:
        if hist is None or hist.empty or 'Close' not in hist.columns:
            return None
        closes = hist['Close'].astype(float)
        if len(closes) < 15:
            return None
        recent = closes[-15:]
        drop = (recent.iloc[4] - recent.iloc[0]) / recent.iloc[0]
        correction = recent.iloc[5:].max() - recent.iloc[5:].min()
        if drop < -0.08 and correction / recent.iloc[5:].max() < 0.02:
            return 'Bear Flag'
    except Exception:
        return None
    return None

def calculate_rsi(series, window=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

class StockPredictor:
    def __init__(self):
        self.model = None
        self.trained = False
        self.nse = Nse()
        self.model_path = "models"
        if not os.path.exists(self.model_path):
            os.makedirs(self.model_path)

    def get_model_filename(self, symbol):
        return os.path.join(self.model_path, f"{symbol.upper()}_rf_model.pkl")

    def save_model(self, symbol):
        if self.model:
            joblib.dump(self.model, self.get_model_filename(symbol))

    def load_model(self, symbol):
        model_file = self.get_model_filename(symbol)
        if os.path.exists(model_file):
            self.model = joblib.load(model_file)
            self.trained = True
            return True
        return False

    def train(self, symbol):
        logger.info(f"Training model for {symbol}")
        # Try to load model first
        if self.load_model(symbol):
            return
        # Fetch historical data from yfinance
        data = yf.Ticker(symbol.upper() + ".NS").history(period="1y")
        if len(data) < 2:
            logger.warning("Insufficient data for training")
            self.trained = False
            return

        data = data.dropna()

        # Add technical indicators
        data['SMA_5'] = data['Close'].rolling(window=5).mean()
        data['SMA_10'] = data['Close'].rolling(window=10).mean()
        data['RSI'] = calculate_rsi(data['Close'])
        data = data.dropna()  # Remove NaN from indicators

        # Optionally, fetch latest NSE data and add as features
        try:
            nse_data = self.nse.get_quote(symbol.lower())
            # Example: add 'dayHigh', 'dayLow', 'quantityTraded' as new features for the last row
            for col, nse_key in [('NSE_DayHigh', 'dayHigh'), ('NSE_DayLow', 'dayLow'), ('NSE_Volume', 'quantityTraded')]:
                value = nse_data.get(nse_key)
                data[col] = float(value) if value not in [None, '-'] else data['High'] if col == 'NSE_DayHigh' else data['Low'] if col == 'NSE_DayLow' else data['Volume']
        except Exception:
            # If NSE data is unavailable, fill with yfinance data
            data['NSE_DayHigh'] = data['High']
            data['NSE_DayLow'] = data['Low']
            data['NSE_Volume'] = data['Volume']

        # Prepare features and labels
        feature_cols = ["Open", "High", "Low", "Volume", "NSE_DayHigh", "NSE_DayLow", "NSE_Volume", "SMA_5", "SMA_10", "RSI"]
        X = data[feature_cols][:-1]
        y = data["Close"][1:]
        self.model = RandomForestRegressor()
        try:
            logger.info(f"Features used: {X.columns.tolist()}")
            self.model.fit(X, y)
        except Exception:
            logger.error("Failed to train model", exc_info=True)
            self.trained = False
            return
        self.trained = True
        # After training:
        self.save_model(symbol)

    def predict(self, symbol):
        if not self.trained or self.model is None:
            raise Exception("Model has not been trained yet.")
        data = yf.Ticker(symbol.upper() + ".NS").history(period="7d")
        try:
            nse_data = self.nse.get_quote(symbol.lower())
            for col, nse_key in [('NSE_DayHigh', 'dayHigh'), ('NSE_DayLow', 'dayLow'), ('NSE_Volume', 'quantityTraded')]:
                value = nse_data.get(nse_key)
                data[col] = float(value) if value not in [None, '-'] else data['High'] if col == 'NSE_DayHigh' else data['Low'] if col == 'NSE_DayLow' else data['Volume']
        except Exception:
            data['NSE_DayHigh'] = data['High']
            data['NSE_DayLow'] = data['Low']
            data['NSE_Volume'] = data['Volume']

        # Add technical indicators
        data['SMA_5'] = data['Close'].rolling(window=5).mean()
        data['SMA_10'] = data['Close'].rolling(window=10).mean()
        data['RSI'] = calculate_rsi(data['Close'])

        feature_cols = ["Open", "High", "Low", "Volume", "NSE_DayHigh", "NSE_DayLow", "NSE_Volume", "SMA_5", "SMA_10", "RSI"]
        X_pred = data[feature_cols].iloc[[-1]]
        return float(self.model.predict(X_pred)[0])

    def get_insights(self, symbol):
        # --- Forecast price range for next 3 days ---
        try:
            data = yf.Ticker(symbol.upper() + ".NS").history(period="1mo")  # More data for volatility
            # Add NSE columns if missing
            for col in ["NSE_DayHigh", "NSE_DayLow", "NSE_Volume"]:
                if col not in data.columns:
                    data[col] = data["High"] if "High" in col else data["Low"] if "Low" in col else data["Volume"]
            # Add technical indicators
            data['SMA_5'] = data['Close'].rolling(window=5).mean()
            data['SMA_10'] = data['Close'].rolling(window=10).mean()
            data['RSI'] = calculate_rsi(data['Close'])
            data = data.dropna()

            current_price = data['Close'].iloc[-1]
            returns = data['Close'].pct_change().dropna()
            volatility = returns.std()

            feature_cols = ["Open", "High", "Low", "Volume", "NSE_DayHigh", "NSE_DayLow", "NSE_Volume", "SMA_5", "SMA_10", "RSI"]
            X_pred = data[feature_cols].iloc[[-1]]
            predicted_next = float(self.model.predict(X_pred)[0])

            lower = predicted_next * (1 - 2 * volatility)
            upper = predicted_next * (1 + 2 * volatility)
            forecast_str = f"Predicted next close: {predicted_next:.2f}, Range: {lower:.2f} to {upper:.2f}"

            # Simple confidence metric (higher volatility -> lower confidence)
            try:
                confidence = max(0.0, min(1.0, 1.0 - volatility * 2.0))
            except Exception:
                confidence = None
        except Exception:
            forecast_str = "Forecast unavailable"
            predicted_next = None
            current_price = None
            volatility = None
            confidence = None

        # --- Chart pattern detection (rule-based) ---
        chart_pattern = None
        try:
            # prefer recently prepared `data` (with indicators)
            pattern = (
                detect_moving_average_breakout(data)
                or detect_ascending_triangle(data)
                or detect_descending_triangle(data)
                or detect_double_bottom(data)
                or detect_head_and_shoulders(data)
                or detect_double_top(data)
                or detect_bull_flag(data)
                or detect_bear_flag(data)
            )
            chart_pattern = pattern or "No clear pattern detected"
        except Exception:
            chart_pattern = "No clear pattern detected"

        # --- Calculate breakout level ---
        try:
            hist = yf.Ticker(symbol.upper() + ".NS").history(period="1mo")
            if not hist.empty:
                breakout_level = hist['Close'][-20:].max()  # Highest close in last 20 days
            else:
                breakout_level = None
        except Exception:
            breakout_level = None

        # Determine direction
        if isinstance(predicted_next, (int, float)) and isinstance(current_price, (int, float)):
            if predicted_next > current_price:
                direction = "Upside"
                direction_symbol = "↑"
            else:
                direction = "Downside"
                direction_symbol = "↓"
        else:
            direction = "Neutral"
            direction_symbol = "→"

        # --- Fetch latest news ---
        ticker = yf.Ticker(symbol.upper() + ".NS")
        news_items = []
        try:
            for item in ticker.news[:5]:  # Get latest 5 news
                news_items.append({
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "date": format_news_date(item.get("providerPublishTime", 0))
                })
        except Exception:
            news_items = []

        # --- Fetch corporate events (newly added) ---
        events_items = []
        try:
            yq_ticker = Ticker(symbol.upper() + ".NS")
            corp_events = yq_ticker.calendar
            if corp_events is not None:
                for event, date in corp_events.items():
                    if isinstance(date, str) or isinstance(date, float):
                        events_items.append({"event": event, "date": str(date)})
        except Exception:
            events_items = []

        # Determine near-breakout using a 2% proximity rule if breakout_level and current price exist
        if isinstance(breakout_level, (int, float)) and isinstance(current_price, (int, float)) and breakout_level > 0:
            pct_diff = abs(current_price - breakout_level) / breakout_level
            near_breakout = "Approaching breakout" if pct_diff <= NEAR_BREAKOUT_PCT else "Not near breakout"
            breakout_prediction = f"Breakout will be confirmed if price closes above {breakout_level:.2f}"
            breakout_confirmation = "No breakout detected"
        else:
            near_breakout = "Not applicable"
            breakout_prediction = "Breakout level unavailable"
            breakout_confirmation = "No breakout detected"

        insights = {
            "breakout_confirmation": breakout_confirmation,
            "breakout_prediction": breakout_prediction,
            "near_breakout": near_breakout,
            "breakout_level": breakout_level,
            "direction": direction,
            "direction_symbol": direction_symbol,
            "forecast": forecast_str,
            "predicted_next": predicted_next,
            "forecast_lower": lower if 'lower' in locals() else None,
            "forecast_upper": upper if 'upper' in locals() else None,
            "volatility": volatility,
            "confidence": confidence,
            "chart_pattern": chart_pattern,
            "news": news_items,
            "events": events_items
        }
        # enrich with pattern-based advice
        insights = apply_pattern_advice(insights)
        return insights

def retrain_in_background(symbol, predictor):
    def retrain():
        predictor.train(symbol)
    thread = threading.Thread(target=retrain)
    thread.daemon = True
    thread.start()

def format_news_date(ts):
    try:
        if isinstance(ts, (int, float)) and ts > 0:
            return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(INDIA_TZ).strftime('%Y-%m-%d %H:%M %Z')
        return str(ts)
    except Exception:
        return ""
