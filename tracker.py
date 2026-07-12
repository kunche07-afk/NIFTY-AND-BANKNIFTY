"""
Tracks each option contract's all-time-high (ATH) premium -- i.e. the
highest price that specific contract has ever traded at, since it was
listed -- and computes how far the current LTP has dropped off that ATH.

Two sources feed the ATH:
  1. A one-time "backfill" from Upstox's historical daily candles, covering
     every day the contract has traded so far.
  2. Ongoing live LTP updates during the session, which push the ATH higher
     if a new high is made intraday.

Note: options contracts expire (weekly/monthly), so "all-time" here really
means "since this specific contract started trading" -- there's no
multi-year history the way there is for a stock.
"""


class ATHTracker:
    def __init__(self):
        self._ath: dict[str, float] = {}
        self._backfilled: set[str] = set()

    def is_backfilled(self, instrument_key: str) -> bool:
        return instrument_key in self._backfilled

    def backfill(self, instrument_key: str, historical_high: float | None):
        """Seed the ATH from historical daily candles. Call once per contract."""
        if historical_high is not None:
            current = self._ath.get(instrument_key, 0.0)
            self._ath[instrument_key] = max(current, historical_high)
        self._backfilled.add(instrument_key)

    def update(self, instrument_key: str, ltp: float) -> dict:
        """
        Feed the latest LTP for a contract. Returns:
        {"ath": float, "ltp": float, "drop_pct": float}
        """
        prev_ath = self._ath.get(instrument_key, ltp)
        new_ath = max(prev_ath, ltp)
        self._ath[instrument_key] = new_ath

        drop_pct = 0.0
        if new_ath > 0:
            drop_pct = (new_ath - ltp) / new_ath * 100

        return {"ath": new_ath, "ltp": ltp, "drop_pct": drop_pct}

    def reset(self):
        self._ath.clear()
        self._backfilled.clear()
