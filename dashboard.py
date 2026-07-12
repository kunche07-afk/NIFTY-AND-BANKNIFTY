"""
Live Nifty / Bank Nifty options-premium dashboard.

Run with:
    streamlit run dashboard.py

Flags each option contract's LTP against its own ALL-TIME HIGH (highest
price since that contract was listed), using color bands at 3% / 5% / 7%
drop off that high.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

import config
from market_hours import is_market_open, now_ist
from tracker import ATHTracker
from upstox_provider import UpstoxProvider

st.set_page_config(page_title="NIFTY/BANKNIFTY Options Premium Monitor", layout="wide")
st.title("📉 Options Premium Drop Monitor — NIFTY & BANK NIFTY")
st.caption("Tracking each contract's ALL-TIME HIGH premium (since it was listed)")

# ---------------------------------------------------------------- state --
if "tracker" not in st.session_state:
    st.session_state.tracker = ATHTracker()

if "provider" not in st.session_state:
    try:
        st.session_state.provider = UpstoxProvider()
        st.session_state.provider_error = None
    except ValueError as e:
        st.session_state.provider = None
        st.session_state.provider_error = str(e)

# -------------------------------------------------------------- sidebar --
st.sidebar.header("Settings")

underlying_name = st.sidebar.selectbox("Underlying", list(config.UNDERLYINGS.keys()))
underlying_key = config.UNDERLYINGS[underlying_name]

strike_window = st.sidebar.slider(
    "Strikes to show around spot (each side)", min_value=3, max_value=25, value=6,
    help="Kept small by default -- each contract needs a one-time historical "
         "lookup to seed its ATH, so fewer strikes = faster first load."
)

if st.session_state.provider_error:
    st.error(st.session_state.provider_error)
    st.info(
        "Add your Upstox access token to a `.env` file as "
        "`UPSTOX_ACCESS_TOKEN=...` and restart. See README.md for how to "
        "generate one."
    )
    st.stop()

provider = st.session_state.provider


@st.cache_data(ttl=3600)
def load_expiries(key: str):
    return provider.get_expiries(key)


try:
    expiries = load_expiries(underlying_key)
except Exception as e:
    st.error(f"Could not fetch expiries from Upstox: {e}")
    st.stop()

expiry = st.sidebar.selectbox("Expiry", expiries)

market_open = is_market_open()
status_color = "🟢" if market_open else "🔴"
st.sidebar.markdown(f"**Market status:** {status_color} {'LIVE' if market_open else 'CLOSED'}")
st.sidebar.caption(f"IST time: {now_ist().strftime('%Y-%m-%d %H:%M:%S')}")

if market_open:
    st_autorefresh(interval=config.REFRESH_SECONDS * 1000, key="auto_refresh")
else:
    st.sidebar.info("Market is closed — showing last fetched snapshot. Auto-refresh is paused.")

# ------------------------------------------------------------- fetch data --
try:
    rows = provider.get_option_chain(underlying_key, expiry)
except Exception as e:
    st.error(f"Failed to fetch option chain: {e}")
    st.stop()

if not rows:
    st.warning("No data returned for this expiry.")
    st.stop()

spot = rows[0]["underlying_spot"]

# limit to strikes near spot BEFORE doing any historical backfill calls
strikes_sorted = sorted({r["strike"] for r in rows})
atm_strike = min(strikes_sorted, key=lambda s: abs(s - spot))
atm_idx = strikes_sorted.index(atm_strike)
lo = max(0, atm_idx - strike_window)
hi = min(len(strikes_sorted), atm_idx + strike_window + 1)
visible_strikes = set(strikes_sorted[lo:hi])
rows = [r for r in rows if r["strike"] in visible_strikes]

tracker = st.session_state.tracker

# one-time ATH backfill (concurrent, only for contracts not yet backfilled)
pending = [r["instrument_key"] for r in rows if not tracker.is_backfilled(r["instrument_key"])]
if pending:
    with st.spinner(f"Seeding all-time-high for {len(pending)} contract(s) from history..."):
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {
                pool.submit(provider.get_ath_from_history, key): key for key in pending
            }
            for fut in as_completed(futures):
                key = futures[fut]
                try:
                    hist_high = fut.result()
                except Exception:
                    hist_high = None
                tracker.backfill(key, hist_high)

# update with live LTPs + build display rows
enriched = []
for r in rows:
    stats = tracker.update(r["instrument_key"], r["ltp"])
    enriched.append(
        {
            "Strike": r["strike"],
            "Type": r["type"],
            "LTP": round(stats["ltp"], 2),
            "ATH": round(stats["ath"], 2),
            "Drop %": round(stats["drop_pct"], 2),
            "OI": r["oi"],
            "Volume": r["volume"],
        }
    )

df = pd.DataFrame(enriched).sort_values(["Strike", "Type"])

# --------------------------------------------------------------- summary --
c1, c2, c3, c4 = st.columns(4)
c1.metric(f"{underlying_name} Spot", f"{spot:,.2f}")
c2.metric("Severe drops (≥7%)", int((df["Drop %"] >= config.THRESHOLDS["severe"]).sum()))
c3.metric("Moderate drops (≥5%)", int((df["Drop %"] >= config.THRESHOLDS["moderate"]).sum()))
c4.metric("Mild drops (≥3%)", int((df["Drop %"] >= config.THRESHOLDS["mild"]).sum()))


def flag_row(drop_pct: float) -> str:
    if drop_pct >= config.THRESHOLDS["severe"]:
        return "background-color: #ff6b6b; color: white"
    if drop_pct >= config.THRESHOLDS["moderate"]:
        return "background-color: #ffa94d"
    if drop_pct >= config.THRESHOLDS["mild"]:
        return "background-color: #ffe066"
    return ""


styled = df.style.applymap(flag_row, subset=["Drop %"])
st.dataframe(styled, use_container_width=True, height=650)

st.caption(
    "Yellow = ≥3% off contract's all-time high · Orange = ≥5% · Red = ≥7%. "
    "'ATH' = highest price this specific contract has traded at since it was "
    "listed (historical daily highs + live updates this session). "
    "Data source: Upstox v2 option-chain & historical-candle APIs."
)
