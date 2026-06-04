# StockSenseAI

StockSenseAI is a web application and command-line tool for Indian stock market insights. It combines live NSE and Yahoo Finance data with AI-powered forecasting, modern dashboard UX, and automated CI workflows.

## Features

- **Live Market Indexes**: Home page displays live NSE index cards, including NIFTY, BANK NIFTY, FIN NIFTY, SENSEX, and MIDCP NIFTY.
- **Stock Search & Preview**: Search symbols with autocomplete and preview live stock prices instantly.
- **Dashboard Analytics**: View stock overview, company essentials, price charts, historical trend data, and AI prediction insights.
- **Top Searched Stocks**: Dashboard highlights frequently searched NSE stocks as a “Top Searched Stocks” table.
- **Custom Themes**: Light and dark theme support for better readability.
- **AI Predictions**: Historical model-based insights and direction forecasts for selected stocks.
- **CLI Support**: Use the command-line interface for quick stock lookup and AI-driven insights.
- **GitHub Actions CI**: Workflow coverage includes Python test and lint pipelines with Python 3.12 support.

## Project Structure

```text
StockSenseAI
├── .github
│   └── workflows
│       ├── python-package.yml
│       └── python-test.yml
├── ai
│   ├── __init__.py
│   ├── logger.py
│   ├── patterns.json
│   ├── predictor.py
│   └── utils.py
├── static
│   └── style.css
├── templates
│   ├── dashboard.html
│   └── home.html
├── tests
│   ├── __init__.py
│   └── test_predictor.py
├── cli_app.py
├── inspect_yq.py
├── stock_web_app.py
├── test_data.py
├── requirements.txt
└── README.md
```

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/TechPrastu/StockSenseAI.git
   cd StockSenseAI
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Web Application

1. Start the Flask app:
   ```bash
   python stock_web_app.py
   ```

2. Open your browser and go to:
   ```text
   http://127.0.0.1:5000/
   ```

3. Search for stock symbols like `RELIANCE`, `TCS`, or `INFY` to view the dashboard and stock overview.

### Command-Line Interface (CLI)

Run stock lookups from the terminal:

```bash
python cli_app.py RELIANCE
python cli_app.py RELIANCE,TCS
python cli_app.py --help
```

## Testing

Run the unit tests with pytest:

```bash
pytest tests/test_predictor.py -q
```

## Key Notes

- Home page now uses live index data and removes unsupported `GIFT NIFTY` cards.
- Dashboard no longer shows a misleading peer comparison section — it now displays top searched stocks.
- CI workflows were improved with YAML fixes, Python 3.12 support, and `actions/setup-python@v5` alignment.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for any enhancements or bug
fixes.

## Recent Changes

- CI updates: added Python 3.12 to the test matrix, upgraded `actions/setup-python` to `v5`, and
   migrated artifact uploads to `actions/upload-artifact@v4` with safe `if-no-files-found: ignore` to
   prevent failures when no artifacts are produced.
- Dashboard/UI: removed unsupported index "GIFT NIFTY" from the home page and renamed the
   dashboard "Peer Comparison" section to "Top Searched Stocks" to better reflect displayed data.
- Tests: fixed a missing `pattern_title` field returned by `ai.predictor.StockPredictor.get_insights()`
   which resolved a unit test expectation.
- Branch workflow: please avoid committing directly to `main`; create a feature branch and open a PR
   for changes (example branch name: `fix/ci-upload-artifact-v4`).

If you'd like, I can open a small PR with only this README update on the current feature branch.
Contributions are welcome! Please open an issue or submit a pull request for new features, bug fixes, or documentation updates.

## License

This repository does not currently specify a license. Add one if you want to share the project publicly.


