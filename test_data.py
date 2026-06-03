from yahooquery import Ticker
import json

symbol = "RELIANCE.NS"
t = Ticker(symbol)

data = {
    "income_statement": t.income_statement().to_dict(orient="records") if hasattr(t.income_statement(), "to_dict") else None,
    "balance_sheet": t.balance_sheet().to_dict(orient="records") if hasattr(t.balance_sheet(), "to_dict") else None,
    "cash_flow": t.cash_flow().to_dict(orient="records") if hasattr(t.cash_flow(), "to_dict") else None,
    "valuation_measures": t.valuation_measures.to_dict(orient="records") if hasattr(t.valuation_measures, "to_dict") else None,
}

# Print keys or some sample to see structure
for key in data:
    if data[key]:
        print(f"--- {key} ---")
        print(data[key][0] if len(data[key]) > 0 else "Empty")

# Peer comparison - Screener style might need manual list or ticker.recommendations
# but Ticker(symbol).financial_data etc. 
