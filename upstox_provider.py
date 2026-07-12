"""
Thin wrapper around the Upstox v2 option-chain REST endpoint.

Docs: https://upstox.com/developer/api-documentation/get-pc-option-chain/

GET /v2/option/chain?instrument_key=<key>&expiry_date=YYYY-MM-DD
Response (per strike):
{
  "expiry": "...",
  "strike_price": 22000,
  "underlying_spot_price": 21985.4,
  "call_options": {
      "instrument_key": "...",
      "market_data": {"ltp": 123.45, "volume": ..., "oi": ..., "close_price": ...},
      "option_greeks": {...}
  },
  "put_options": {... same shape ...}
}
"""

from datetime import date, timedelta

import requests
import config


class UpstoxProvider:
    def __init__(self, access_token: str | None = None):
        self.access_token = access_token or config.UPSTOX_ACCESS_TOKEN
        if not self.access_token:
            raise ValueError(
                "Missing Upstox access token. Set UPSTOX_ACCESS_TOKEN in your "
                ".env file (see README for how to generate one)."
            )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Authorization": f"Bearer {self.access_token}",
            }
        )

    def get_expiries(self, instrument_key: str) -> list[str]:
        """Fetch the list of available expiry dates for an underlying."""
        url = f"{config.UPSTOX_BASE_URL}/option/contract"
        resp = self.session.get(url, params={"instrument_key": instrument_key}, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        expiries = sorted({row["expiry"] for row in data if "expiry" in row})
        return expiries

    def get_option_chain(self, instrument_key: str, expiry_date: str) -> list[dict]:
        """
        Returns a flat list of rows, one per (strike, CE/PE), e.g.:
        {
          "strike": 22000, "type": "CE", "instrument_key": "...",
          "ltp": 123.45, "oi": 111000, "volume": 5400,
          "underlying_spot": 21985.4
        }
        """
        url = f"{config.UPSTOX_BASE_URL}/option/chain"
        resp = self.session.get(
            url,
            params={"instrument_key": instrument_key, "expiry_date": expiry_date},
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json().get("data", [])

        rows = []
        for entry in raw:
            spot = entry.get("underlying_spot_price")
            strike = entry.get("strike_price")

            for side, tag in (("call_options", "CE"), ("put_options", "PE")):
                leg = entry.get(side) or {}
                md = leg.get("market_data") or {}
                ltp = md.get("ltp")
                if ltp is None:
                    continue
                rows.append(
                    {
                        "strike": strike,
                        "type": tag,
                        "instrument_key": leg.get("instrument_key"),
                        "ltp": float(ltp),
                        "oi": md.get("oi"),
                        "volume": md.get("volume"),
                        "underlying_spot": spot,
                    }
                )
        return rows

    def get_ath_from_history(self, instrument_key: str, lookback_days: int = 180) -> float | None:
        """
        Highest daily 'high' for this specific option contract since it started
        trading (or over `lookback_days`, whichever is shorter -- options
        contracts don't live longer than a few months anyway).

        Uses GET /v2/historical-candle/{instrument_key}/day/{to_date}/{from_date}
        Candle row format: [timestamp, open, high, low, close, volume, oi]
        """
        to_date = (date.today() - timedelta(days=1)).isoformat()
        from_date = (date.today() - timedelta(days=lookback_days)).isoformat()
        url = f"{config.UPSTOX_BASE_URL}/historical-candle/{instrument_key}/day/{to_date}/{from_date}"

        resp = self.session.get(url, timeout=10)
        if resp.status_code == 404:
            # Contract too new to have any daily candles yet -- not an error.
            return None
        resp.raise_for_status()

        candles = resp.json().get("data", {}).get("candles", [])
        if not candles:
            return None
        return max(c[2] for c in candles)  # index 2 = high
