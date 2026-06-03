from yahooquery import Ticker
import pandas as pd

symbol = "RELIANCE.NS"
t = Ticker(symbol)

# Quarterly Income Statement
income_q = t.income_statement(frequency='q')
print("--- Quarterly Income Statement ---")
print(income_q.tail())

# Annual Income Statement
income_a = t.income_statement(frequency='a')
print("--- Annual Income Statement ---")
print(income_a.tail())

# Peers
# Yahooquery doesn't have a direct "peers" list like Screener, 
# but we can try to find related symbols or just use a predefined list for top sectors.
# Alternatively, use ticker.recommendations or something similar if available.
# Screener usually has "Peer comparison" based on sector.

# Let's see what modules are available
# print(t.all_modules[symbol].keys())
