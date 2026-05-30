import sys
import time
import threading
from ai.predictor import StockPredictor
from stock_web_app import get_stock_data
from ai.logger import StockSenseAILogger

logger = StockSenseAILogger.get_logger(__name__)

class StockSenseAICLI:
    def __init__(self, symbols):
        self.symbols = symbols

    @staticmethod
    def print_ai_thinking(message):
        print(f"[AI] {message}")
        time.sleep(0.7)  # Simulate thinking delay

    @staticmethod
    def print_help():
        print("""
StockSenseAI CLI - AI-powered Indian Stock Insights

Usage:
    python cli_app.py [STOCK_SYMBOLS]

Arguments:
    STOCK_SYMBOLS   Comma-separated list of stock symbols (e.g. RELIANCE,TCS,INFY)

Options:
    --help          Show this help message and exit

Examples:
    python cli_app.py RELIANCE
    python cli_app.py RELIANCE,TCS
""")

    def print_insights(self, symbol):
        predictor = StockPredictor()
        logger.info(f"Fetching and training model for {symbol.upper()}...")
        self.print_ai_thinking(f"Fetching and training model for {symbol.upper()}...")
        predictor.train(symbol)
        self.print_ai_thinking("Predicting next close price...")
        prediction = predictor.predict(symbol)
        logger.debug(f"Prediction for {symbol.upper()}: {prediction}")
        self.print_ai_thinking("Generating insights...")
        insights = predictor.get_insights(symbol)
        self.print_ai_thinking("Fetching latest stock data...")
        stock_data = get_stock_data(symbol)

        print(f"\n=== {symbol.upper()} ===")
        print(f"Current Price: {stock_data['yfinance_fields']['Current Price']}")
        print(f"AI Predicted Next Close: {prediction:.2f}")
        print("\nAI Insights:")
        print(f"  Breakout Confirmation: {insights['breakout_confirmation']}")
        print(f"  Breakout Prediction: {insights['breakout_prediction']}")
        print(f"  Near Breakout: {insights['near_breakout']}")
        print(f"  Direction: {insights['direction']} {insights['direction_symbol']}")
        print(f"  Forecast: {insights['forecast']}")
        print(f"  Chart Pattern: {insights.get('pattern_title') or insights['chart_pattern']}")
        if insights.get('pattern_description'):
            print(f"  Pattern Details: {insights['pattern_description']}")
        if insights.get('pattern_notes'):
            print(f"  Pattern Notes: {insights['pattern_notes']}")
        print(f"  Advice: {insights['advice']}")
        if insights.get('trailing_stop_pct') is not None:
            print(f"  Suggested trailing stop: {insights['trailing_stop_pct']}%")
        if stock_data.get('value_checklist'):
            print("\nValue Stock Checklist:")
            for item in stock_data['value_checklist']:
                status = 'Pass' if item['status'] == 'pass' else 'Fail' if item['status'] == 'fail' else 'Unknown'
                print(f"  - {item['label']}: {item['value_display']} {item['threshold_display']} -> {status}")
        print("\nLatest News:")
        news_list = [n for n in insights['news'] if n.get('title') or n.get('summary')]
        if news_list:
            for news in news_list[:5]:
                print(f"  - {news.get('title', 'No Title')}: {news.get('summary', 'No Summary')}")
        else:
            print("  No news found.")
        print("\nUpcoming Events:")
        for event in insights['events']:
            print(f"  - {event['event']} on {event['date']}")

    def run(self):
        threads = []
        for symbol in self.symbols:
            thread = threading.Thread(target=self.print_insights, args=(symbol,))
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] in ("--help", "-h"):
            StockSenseAICLI.print_help()
            sys.exit(0)
        symbols = [s.strip() for s in sys.argv[1].split(",")]
    else:
        symbols = input("Enter stock symbols (comma separated): ").replace(" ", "").split(",")
    cli = StockSenseAICLI(symbols)
    cli.run()

