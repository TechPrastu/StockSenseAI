from nsetools import Nse
import yfinance as yf
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
import joblib
import os
import threading
from ai.logger import StockSenseAILogger

logger = StockSenseAILogger.get_logger(__name__)

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
        feature_cols = ["Open", "High", "Low", "Volume", "NSE_DayHigh", "NSE_DayLow", "NSE_Volume"]
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

        feature_cols = ["Open", "High", "Low", "Volume", "NSE_DayHigh", "NSE_DayLow", "NSE_Volume"]
        X_pred = data[feature_cols].iloc[[-1]]
        return float(self.model.predict(X_pred)[0])

    def get_insights(self, symbol):
        # --- Forecast price range for next 3 days ---
        # Dummy logic: use model to predict next 3 closes (replace with real logic)
        try:
            data = yf.Ticker(symbol.upper() + ".NS").history(period="10d")
            feature_cols = ["Open", "High", "Low", "Volume", "NSE_DayHigh", "NSE_DayLow", "NSE_Volume"]
            # Add dummy NSE columns if missing
            for col in ["NSE_DayHigh", "NSE_DayLow", "NSE_Volume"]:
                if col not in data.columns:
                    data[col] = data["High"] if "High" in col else data["Low"] if "Low" in col else data["Volume"]
            preds = []
            for i in range(1, 4):
                X_pred = data[feature_cols].iloc[[-i]]
                preds.append(float(self.model.predict(X_pred)[0]))
            forecast_str = f"Price range {min(preds):.2f} to {max(preds):.2f} for next 3 days"
        except Exception:
            forecast_str = "Forecast unavailable"

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

        insights = {
            "breakout_confirmation": "No breakout detected",
            "breakout_prediction": f"Breakout will be confirmed if price closes above {breakout_level:.2f}",
            "near_breakout": "Not near breakout",
            "direction": "Upside",  # or "Downside"
            "direction_symbol": "↑",  # "↑" for Upside, "↓" for Downside
            "forecast": forecast_str,
            "chart_pattern": chart_pattern,
            "news": [
                {
                    "title": "Company announces dividend",
                    "summary": "The company declared a dividend for shareholders for Q2.",
                },
                {
                    "title": "Stock hits 52-week high",
                    "summary": "The stock price reached a new 52-week high amid strong earnings.",
                }
            ],
            "events": [
                {"event": "Earnings Call", "date": "2025-08-10"},
                {"event": "AGM", "date": "2025-09-01"}
            ]
        }
        return insights

def retrain_in_background(symbol, predictor):
    def retrain():
        predictor.train(symbol)
    thread = threading.Thread(target=retrain)
    thread.daemon = True
    thread.start()
