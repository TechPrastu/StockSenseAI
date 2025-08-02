# StockSenseAI

StockSenseAI is a web application and command-line tool designed to provide users with insights into stock market data, including real-time stock prices, historical data, and AI-driven stock predictions. The application leverages the power of financial data APIs and machine learning algorithms to assist users in making informed investment decisions.

## Features

- **Real-time Stock Data**: Fetches and displays current stock prices and historical data using Yahoo Finance and NSE APIs.
- **Interactive Dashboard**: A user-friendly interface that allows users to input stock symbols and view detailed information, including price charts and historical tables.
- **AI Stock Predictions**: Utilizes machine learning models to predict future stock prices based on historical data.
- **Customizable Themes**: Users can switch between light and dark themes for a personalized experience.
- **Command-Line Interface (CLI)**: Get AI-powered stock insights directly in your terminal.

## Project Structure

```
StockSenseAI
├── ai
│   ├── __init__.py
│   ├── predictor.py
│   ├── utils.py
│   └── logger.py
├── static
│   └── style.css
├── templates
│   └── index.html
├── stock_web_app.py
├── cli_app.py
├── requirements.txt
└── README.md
```

## Installation

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/StockSenseAI.git
   cd StockSenseAI
   ```

2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage

### Web Application

1. Run the application:
   ```
   python stock_web_app.py
   ```

2. Open your web browser and navigate to `http://127.0.0.1:5000/`.

3. Enter stock symbols (comma-separated) in the input field and select the desired time range to view stock data and predictions.

### Command-Line Interface (CLI)

You can also use StockSenseAI directly from your terminal:

```
python cli_app.py [STOCK_SYMBOLS]
```

- `STOCK_SYMBOLS`: Comma-separated list of stock symbols (e.g. RELIANCE,TCS,INFY)
- `--help`: Show help message and usage examples

**Examples:**
```
python cli_app.py RELIANCE
python cli_app.py RELIANCE,TCS
python cli_app.py --help
```

The CLI will display AI-powered insights, predictions, news, and events for each stock symbol.

## AI Module

The AI functionality is encapsulated in the `ai` directory, which includes:

- **predictor.py**: Contains the `StockPredictor` class for training and evaluating stock prediction models.
- **utils.py**: Provides utility functions for data preprocessing and feature extraction.
- **logger.py**: Provides a logger utility for consistent logging across the project.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for any enhancements or bug

