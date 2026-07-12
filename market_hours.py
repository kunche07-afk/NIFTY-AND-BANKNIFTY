"""Helpers to determine whether the NSE market is currently live."""

from datetime import datetime
import pytz
import config


def now_ist() -> datetime:
    return datetime.now(pytz.timezone(config.TIMEZONE))


def is_market_open(dt: datetime | None = None) -> bool:
    """
    True on Mon-Fri between MARKET_OPEN and MARKET_CLOSE (IST).
    Does NOT account for NSE trading holidays -- see README for how to
    plug in a holiday calendar if you need that.
    """
    dt = dt or now_ist()

    if dt.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    open_h, open_m = config.MARKET_OPEN
    close_h, close_m = config.MARKET_CLOSE

    open_t = dt.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    close_t = dt.replace(hour=close_h, minute=close_m, second=0, microsecond=0)

    return open_t <= dt <= close_t
