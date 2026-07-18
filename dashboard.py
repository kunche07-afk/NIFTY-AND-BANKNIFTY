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

# update with live LTPs, organize by strike into CE (left) / PE (right)
by_strike = {}
flag_counts = {"severe": 0, "moderate": 0, "mild": 0}

for r in rows:
    stats = tracker.update(r["instrument_key"], r["ltp"])
    d = stats["drop_pct"]
    if d >= config.THRESHOLDS["severe"]:
        flag_counts["severe"] += 1
    if d >= config.THRESHOLDS["moderate"]:
        flag_counts["moderate"] += 1
    if d >= config.THRESHOLDS["mild"]:
        flag_counts["mild"] += 1

    side = by_strike.setdefault(r["strike"], {})
    side[r["type"]] = {"ltp": stats["ltp"], "ath": stats["ath"], "drop_pct": d}


def leg_cols(leg, prefix):
    """Returns (display_values, triggered_flags) for one contract leg."""
    keys = [("\u22657%", config.THRESHOLDS["severe"]),
            ("\u22655%", config.THRESHOLDS["moderate"]),
            ("\u22653%", config.THRESHOLDS["mild"])]

    if leg is None:
        values = {f"{prefix} ATH": None}
        triggers = {}
        for key, _ in keys:
            values[f"{prefix} {key}"] = "\u2014"
            triggers[f"{prefix} {key}"] = False
        return values, triggers

    ath = leg["ath"]
    d = leg["drop_pct"]
    values = {f"{prefix} ATH": round(ath, 2)}
    triggers = {}
    for key, threshold in keys:
        values[f"{prefix} {key}"] = f"{ath * threshold / 100:.2f}"
        triggers[f"{prefix} {key}"] = d is not None and d >= threshold
    return values, triggers


table_rows = []
trigger_rows = []
for strike in sorted(by_strike):
    row, trig = {}, {}
    ce_vals, ce_trig = leg_cols(by_strike[strike].get("CE"), "CE")
    row.update(ce_vals)
    trig.update(ce_trig)
    row["Strike"] = strike
    pe_vals, pe_trig = leg_cols(by_strike[strike].get("PE"), "PE")
    row.update(pe_vals)
    trig.update(pe_trig)
    table_rows.append(row)
    trigger_rows.append(trig)

col_order = [
    "CE ATH", "CE \u22657%", "CE \u22655%", "CE \u22653%",
    "Strike",
    "PE \u22653%", "PE \u22655%", "PE \u22657%", "PE ATH",
]
df = pd.DataFrame(table_rows)[col_order]

# --------------------------------------------------------------- summary --
c1, c2, c3, c4 = st.columns(4)
c1.metric(f"{underlying_name} Spot", f"{spot:,.2f}")
c2.metric("Severe drops (\u22657%)", flag_counts["severe"])
c3.metric("Moderate drops (\u22655%)", flag_counts["moderate"])
c4.metric("Mild drops (\u22653%)", flag_counts["mild"])

flag_colors = {"\u22657%": "#ff6b6b", "\u22655%": "#ffa94d", "\u22653%": "#ffe066"}
flag_columns = [c for c in df.columns if "\u2265" in c]
num_columns = [c for c in df.columns if c.endswith("ATH")]

trigger_df = pd.DataFrame(trigger_rows, index=df.index).reindex(columns=flag_columns, fill_value=False)


def style_grid(_):
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    for col in flag_columns:
        color = next(c for key, c in flag_colors.items() if col.endswith(key))
        mask = trigger_df[col]
        styles.loc[mask, col] = f"background-color: {color}; color: #111"
    return styles


fmt = {c: "{:.2f}" for c in num_columns}
styled = df.style.apply(style_grid, axis=None).format(fmt, na_rep="\u2014")

st.dataframe(styled, use_container_width=True, height=650, hide_index=True)

st.caption(
    "Calls (CE) on the left, strike in the middle, Puts (PE) on the right. "
    "Each threshold column shows the rupee value that % drop represents off "
    "this contract's all-time high (e.g. the \u22657% column shows 7% of ATH in \u20b9). "
    "A cell is highlighted when the contract has actually dropped that much "
    "or more right now. 'ATH' = highest price this specific contract has "
    "traded at since it was listed. Data source: Upstox v2 APIs."
)
