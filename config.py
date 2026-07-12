"""
Configuration for the Nifty/Bank Nifty Options Premium Dashboard.

All secrets are read from environment variables (or a local .env file via
python-dotenv) so you never hard-code your access token in source control.
"""

import os
from dotenv import load_dotenv

load_dotenv()  # reads a local .env file if present

# ---- Broker credentials -----------------------------------------------
# Upstox access tokens are valid only for the current trading day and must
# be regenerated daily via the login/OAuth flow. Paste today's token here
# (or set it as an environment variable UPSTOX_ACCESS_TOKEN).
UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "")

# ---- Instruments to track ----------------------------------------------
# Upstox instrument_key format for indices.
UNDERLYINGS = {
    "NIFTY 50": "NSE_INDEX|Nifty 50",
    "NIFTY BANK": "NSE_INDEX|Nifty Bank",
}

# ---- Drop thresholds (percent off the day's high premium) -------------
THRESHOLDS = {
    "mild": 3.0,     # yellow
    "moderate": 5.0,  # orange
    "severe": 7.0,    # red
}

# ---- Refresh / market-hours settings -----------------------------------
REFRESH_SECONDS = 5          # how often to poll Upstox while market is open
MARKET_OPEN = (9, 15)        # 09:15 IST
MARKET_CLOSE = (15, 30)      # 15:30 IST
TIMEZONE = "Asia/Kolkata"

UPSTOX_BASE_URL = "https://api.upstox.com/v2"
