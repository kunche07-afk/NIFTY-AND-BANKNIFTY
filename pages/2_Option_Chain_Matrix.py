"""
Option Chain -- Visual Matrix
A richer, single-page view: OI heatmap, change-in-OI chart, IV skew,
Max Pain, PCR, ATM IV, a simple trading-bias gauge, the option chain table
itself (Calls left / Strike center / Puts right), key takeaways, and
illustrative strategy cards.

Drop this file into a `pages/` folder alongside your existing dashboard.py
in the same Streamlit app -- Streamlit will automatically pick it up as a
second page in the sidebar.

Needs the same UPSTOX_ACCESS_TOKEN secret/env var as dashboard.py.
Needs `plotly` added to requirements.txt.
"""

import os
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------------------- config --
UNDERLYINGS = {
    "NIFTY 50": "NSE_INDEX|Nifty 50",
    "NIFTY BANK": "NSE_INDEX|Nifty Bank",
    "BSE SENSEX": "BSE_INDEX|SENSEX",
}
VIX_KEY = "NSE_INDEX|India VIX"
UPSTOX_BASE_URL = "https://api.upstox.com/v2"

# Approximate lot sizes -- these change periodically per exchange circulars;
# treat as illustrative, not authoritative.
LOT_SIZES = {"NIFTY 50": 75, "NIFTY BANK": 30, "BSE SENSEX": 20}

st.set_page_config(page_title="Option Chain -- Visual Matrix", layout="wide")

# ----------------------------------------------------------------- auth --
ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "")
if not ACCESS_TOKEN:
    st.error(
        "Missing Upstox access token. Set UPSTOX_ACCESS_TOKEN as a secret / "
        "environment variable (same one dashboard.py uses)."
    )
    st.stop()

session = requests.Session()
session.headers.update(
    {"Accept": "application/json", "Authorization": f"Bearer {ACCESS_TOKEN}"}
)


@st.cache_data(ttl=15)
def fetch_option_chain(instrument_key: str, expiry_date: str) -> dict:
    url = f"{UPSTOX_BASE_URL}/option/chain"
    resp = session.get(
        url, params={"instrument_key": instrument_key, "expiry_date": expiry_date}, timeout=10
    )
    resp.raise_for_status()
    raw = resp.json().get("data", [])
    spot = raw[0].get("underlying_spot_price") if raw else None

    def leg(entry, key):
        d = entry.get(key)
        if not d:
            return None
        md = d.get("market_data") or {}
        gk = d.get("option_greeks") or {}
        if md.get("ltp") is None:
            return None
        return {
            "ltp": float(md.get("ltp") or 0),
            "oi": float(md.get("oi") or 0),
            "prev_oi": float(md.get("prev_oi") or 0),
            "volume": float(md.get("volume") or 0),
            "iv": float(gk.get("iv") or 0),
        }

    rows = [
        {"strike": e.get("strike_price"), "ce": leg(e, "call_options"), "pe": leg(e, "put_options")}
        for e in raw
    ]
    return {"spot": spot, "rows": rows}


@st.cache_data(ttl=3600)
def fetch_expiries(instrument_key: str) -> list:
    url = f"{UPSTOX_BASE_URL}/option/contract"
    resp = session.get(url, params={"instrument_key": instrument_key}, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return sorted({row["expiry"] for row in data if "expiry" in row})


@st.cache_data(ttl=15)
def fetch_quote(instrument_key: str) -> dict:
    url = f"{UPSTOX_BASE_URL}/market-quote/quote"
    resp = session.get(url, params={"instrument_key": instrument_key}, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("data", {})
    if not data:
        return {"ltp": None, "prev_close": None}
    q = next(iter(data.values()))
    return {"ltp": q.get("last_price"), "prev_close": (q.get("ohlc") or {}).get("close")}


# --------------------------------------------------------------- sidebar --
st.sidebar.header("Settings")
underlying_name = st.sidebar.selectbox("Underlying", list(UNDERLYINGS.keys()))
underlying_key = UNDERLYINGS[underlying_name]

try:
    expiries = fetch_expiries(underlying_key)
except Exception as e:
    st.error(f"Could not fetch expiries: {e}")
    st.stop()

expiry = st.sidebar.selectbox("Expiry", expiries)
strike_window = st.sidebar.slider("Strikes each side of ATM", 5, 20, 10)

# ------------------------------------------------------------- fetch data --
try:
    chain = fetch_option_chain(underlying_key, expiry)
except Exception as e:
    st.error(f"Failed to fetch option chain: {e}")
    st.stop()

spot = chain["spot"]
rows = [r for r in chain["rows"] if r["ce"] or r["pe"]]
if not rows or spot is None:
    st.warning("No data returned for this expiry.")
    st.stop()

try:
    idx_quote = fetch_quote(underlying_key)
except Exception:
    idx_quote = {"ltp": spot, "prev_close": None}

try:
    vix_quote = fetch_quote(VIX_KEY)
except Exception:
    vix_quote = {"ltp": None, "prev_close": None}

# limit to strikes near ATM
strikes_sorted = sorted({r["strike"] for r in rows})
atm_strike = min(strikes_sorted, key=lambda s: abs(s - spot))
atm_idx = strikes_sorted.index(atm_strike)
lo = max(0, atm_idx - strike_window)
hi = min(len(strikes_sorted), atm_idx + strike_window + 1)
visible_strikes = set(strikes_sorted[lo:hi])
rows = [r for r in rows if r["strike"] in visible_strikes]
rows.sort(key=lambda r: r["strike"])

# --------------------------------------------------------- derived stats --
total_ce_oi = sum((r["ce"] or {}).get("oi", 0) for r in rows)
total_pe_oi = sum((r["pe"] or {}).get("oi", 0) for r in rows)
pcr_oi = (total_pe_oi / total_ce_oi) if total_ce_oi else 0

total_ce_vol = sum((r["ce"] or {}).get("volume", 0) for r in rows)
total_pe_vol = sum((r["pe"] or {}).get("volume", 0) for r in rows)
pcr_vol = (total_pe_vol / total_ce_vol) if total_ce_vol else 0

atm_row = next((r for r in rows if r["strike"] == atm_strike), None)
atm_ce_iv = (atm_row["ce"] or {}).get("iv") if atm_row else None
atm_pe_iv = (atm_row["pe"] or {}).get("iv") if atm_row else None
ivs = [v for v in (atm_ce_iv, atm_pe_iv) if v]
atm_iv = sum(ivs) / len(ivs) if ivs else None

# Max Pain: strike minimizing total option-writer payout across ALL strikes
# (uses the full fetched chain, not just the visible window, for accuracy).
all_rows = [r for r in chain["rows"] if r["ce"] or r["pe"]]


def total_payout(settle_strike):
    payout = 0.0
    for r in all_rows:
        k = r["strike"]
        ce_oi = (r["ce"] or {}).get("oi", 0)
        pe_oi = (r["pe"] or {}).get("oi", 0)
        payout += ce_oi * max(0, settle_strike - k)
        payout += pe_oi * max(0, k - settle_strike)
    return payout


candidate_strikes = sorted({r["strike"] for r in all_rows})
max_pain = min(candidate_strikes, key=total_payout) if candidate_strikes else None

# support/resistance: strikes with highest PE OI / CE OI near spot
support_strike = max(rows, key=lambda r: (r["pe"] or {}).get("oi", 0))["strike"]
resistance_strike = max(rows, key=lambda r: (r["ce"] or {}).get("oi", 0))["strike"]

# simple bias heuristic (illustrative, not investment advice)
bias_score = 0
if pcr_oi > 1.15:
    bias_score += 1
elif pcr_oi < 0.85:
    bias_score -= 1
if max_pain is not None:
    if spot > max_pain:
        bias_score -= 1
    elif spot < max_pain:
        bias_score += 1
bias_label = {2: "Bullish", 1: "Mildly Bullish", 0: "Neutral", -1: "Mildly Bearish", -2: "Bearish"}.get(bias_score, "Neutral")

# -------------------------------------------------------------- header ---
st.title(f"{underlying_name} Option Chain \u2014 Visual Matrix")
st.caption("See the market's positioning at a glance \u2014 illustrative analytics, not investment advice.")

spot_change = None
spot_pct = None
if idx_quote.get("prev_close"):
    spot_change = spot - idx_quote["prev_close"]
    spot_pct = spot_change / idx_quote["prev_close"] * 100

h1, h2, h3, h4, h5 = st.columns(5)
h1.metric(
    underlying_name, f"{spot:,.2f}",
    f"{spot_change:+,.2f} ({spot_pct:+.2f}%)" if spot_change is not None else None,
)
h2.metric("India VIX", f"{vix_quote['ltp']:.2f}" if vix_quote.get("ltp") else "\u2014")
h3.metric("Max Pain", f"{max_pain:,.0f}" if max_pain is not None else "\u2014")
h4.metric("PCR (OI)", f"{pcr_oi:.2f}")
h5.metric("ATM IV", f"{atm_iv:.1f}%" if atm_iv else "\u2014")

st.markdown(f"**Trading bias (heuristic):** {bias_label}  \u00b7  ATM strike: **{atm_strike:,.0f}**")

st.divider()

# ------------------------------------------------------------- charts ----
chart_col, table_col = st.columns([1, 2])

with chart_col:
    st.subheader("Open Interest Heatmap")
    oi_fig = go.Figure()
    oi_fig.add_trace(go.Bar(
        y=[r["strike"] for r in rows],
        x=[-(r["ce"] or {}).get("oi", 0) for r in rows],
        orientation="h", name="Call OI", marker_color="#2ecc71",
    ))
    oi_fig.add_trace(go.Bar(
        y=[r["strike"] for r in rows],
        x=[(r["pe"] or {}).get("oi", 0) for r in rows],
        orientation="h", name="Put OI", marker_color="#e74c3c",
    ))
    oi_fig.update_layout(
        barmode="overlay", height=380, template="plotly_dark",
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Open Interest (Calls \u2190 | \u2192 Puts)",
    )
    st.plotly_chart(oi_fig, use_container_width=True)

    st.subheader("Change in OI (Net)")
    chg_fig = go.Figure()
    chg_fig.add_trace(go.Bar(
        x=[r["strike"] for r in rows],
        y=[(r["ce"] or {}).get("oi", 0) - (r["ce"] or {}).get("prev_oi", 0) for r in rows],
        name="Call \u0394OI", marker_color="#2ecc71",
    ))
    chg_fig.add_trace(go.Bar(
        x=[r["strike"] for r in rows],
        y=[(r["pe"] or {}).get("oi", 0) - (r["pe"] or {}).get("prev_oi", 0) for r in rows],
        name="Put \u0394OI", marker_color="#e74c3c",
    ))
    chg_fig.update_layout(
        barmode="group", height=300, template="plotly_dark",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(chg_fig, use_container_width=True)

    st.subheader("Implied Volatility Skew")
    iv_fig = go.Figure()
    iv_fig.add_trace(go.Scatter(
        x=[r["strike"] for r in rows],
        y=[(r["ce"] or {}).get("iv") for r in rows],
        mode="lines+markers", name="Call IV", line=dict(color="#2ecc71"),
    ))
    iv_fig.add_trace(go.Scatter(
        x=[r["strike"] for r in rows],
        y=[(r["pe"] or {}).get("iv") for r in rows],
        mode="lines+markers", name="Put IV", line=dict(color="#e74c3c"),
    ))
    iv_fig.update_layout(
        height=280, template="plotly_dark",
        margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title="IV (%)",
    )
    st.plotly_chart(iv_fig, use_container_width=True)

with table_col:
    st.subheader("Calls (CE)  \u2190\u2192  Strike  \u2190\u2192  Puts (PE)")
    table_rows = []
    for r in rows:
        ce, pe = r["ce"] or {}, r["pe"] or {}
        table_rows.append({
            "OI (CE)": ce.get("oi", 0), "\u0394OI (CE)": ce.get("oi", 0) - ce.get("prev_oi", 0),
            "Vol (CE)": ce.get("volume", 0), "IV (CE)": ce.get("iv", 0), "LTP (CE)": ce.get("ltp", 0),
            "Strike": r["strike"],
            "LTP (PE)": pe.get("ltp", 0), "IV (PE)": pe.get("iv", 0),
            "Vol (PE)": pe.get("volume", 0), "\u0394OI (PE)": pe.get("oi", 0) - pe.get("prev_oi", 0),
            "OI (PE)": pe.get("oi", 0),
        })
    tdf = pd.DataFrame(table_rows)

    def highlight_row(row):
        styles = [""] * len(row)
        if row["Strike"] == atm_strike:
            styles = ["background-color: #3b3b1f; color: #ffd93d"] * len(row)
        return styles

    styled_tdf = tdf.style.apply(highlight_row, axis=1).format(
        {"OI (CE)": "{:,.0f}", "\u0394OI (CE)": "{:+,.0f}", "Vol (CE)": "{:,.0f}", "IV (CE)": "{:.1f}",
         "LTP (CE)": "{:.2f}", "Strike": "{:,.0f}", "LTP (PE)": "{:.2f}", "IV (PE)": "{:.1f}",
         "Vol (PE)": "{:,.0f}", "\u0394OI (PE)": "{:+,.0f}", "OI (PE)": "{:,.0f}"}
    )
    st.dataframe(styled_tdf, use_container_width=True, height=560, hide_index=True)

st.divider()

# ---------------------------------------------------------- key metrics --
m1, m2 = st.columns(2)
with m1:
    st.subheader("Key Metrics")
    st.write(f"- **Max Pain:** {max_pain:,.0f}" if max_pain is not None else "- Max Pain: \u2014")
    st.write(f"- **PCR (OI):** {pcr_oi:.2f}")
    st.write(f"- **PCR (Volume):** {pcr_vol:.2f}")
    st.write(f"- **ATM IV:** {atm_iv:.1f}%" if atm_iv else "- ATM IV: \u2014")
    st.write(f"- **Lot size (approx.):** {LOT_SIZES.get(underlying_name, '\u2014')}")

with m2:
    st.subheader("Key Takeaways")
    st.write(f"- **Support zone (near):** {support_strike:,.0f} (highest Put OI)")
    st.write(f"- **Resistance zone (near):** {resistance_strike:,.0f} (highest Call OI)")
    st.write(f"- **Max Pain:** {max_pain:,.0f}" if max_pain is not None else "")
    st.write(f"- **Bias (heuristic):** {bias_label}")

st.divider()

# --------------------------------------------------------- strategy cards --
s1, s2, s3 = st.columns(3)
with s1:
    st.markdown("##### \U0001F402 Bullish setup (illustrative)")
    st.write(f"Entry: Buy {support_strike:,.0f} CE")
    st.write(f"When: OI + volume build near {support_strike:,.0f}")
with s2:
    st.markdown("##### \U0001F43B Bearish setup (illustrative)")
    st.write(f"Entry: Buy {resistance_strike:,.0f} PE")
    st.write(f"When: {resistance_strike:,.0f} breaks down")
with s3:
    st.markdown("##### \U0001F4CA Range strategy (illustrative)")
    st.write(f"Sell {resistance_strike:,.0f} CE + Sell {support_strike:,.0f} PE")
    st.write(f"When: price stays between {support_strike:,.0f}\u2013{resistance_strike:,.0f}")

st.caption(
    "Strategy cards and bias label are simple, rule-based illustrations of how "
    "OI/PCR/Max-Pain data is commonly read \u2014 not a recommendation. Do your own "
    "research or consult a licensed advisor before trading."
)
