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
        except Exception:
            forecast_str = "Forecast unavailable"
            predicted_next = None
            current_price = None

        # --- Chart pattern detection (placeholder) ---
        chart_pattern = "No clear pattern detected"  # Replace with real detection logic

        # --- Calculate breakout level ---
        try:
            hist = yf.Ticker(symbol.upper() + ".NS").history(period="1mo")
            if not hist.empty:
                breakout_level = hist['Close'][-20:].max()  # Highest close in last 20 days
            else:
                breakout_level = 0
        except Exception:
            breakout_level = 0

        # Determine direction
        if predicted_next and current_price:
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

        insights = {
            "breakout_confirmation": "No breakout detected",
            "breakout_prediction": f"Breakout will be confirmed if price closes above {breakout_level:.2f}",
            "near_breakout": "Not near breakout",
            "direction": direction,
            "direction_symbol": direction_symbol,
            "forecast": forecast_str,
            "chart_pattern": chart_pattern,
            "news": news_items,
            "events": events_items
        }
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
