# core/config.py

import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Coinbase API Credentials
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

# Trading parameters
TRADE_SYMBOL = os.getenv("TRADE_SYMBOL", "BTC-USD")  # Default BTC-USD
TRADE_SIZE = float(os.getenv("TRADE_SIZE", 0.001))   # Default trade size
MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", 0.01))  # 1% risk per trade

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Optional feature flags
USE_STOP_LOSS = os.getenv("USE_STOP_LOSS", "true").lower() == "true"
USE_TAKE_PROFIT = os.getenv("USE_TAKE_PROFIT", "true").lower() == "true"

# Validate required API keys
if not COINBASE_API_KEY or not COINBASE_API_SECRET or not COINBASE_API_PASSPHRASE:
    raise ValueError("Missing Coinbase API credentials in environment variables.")
