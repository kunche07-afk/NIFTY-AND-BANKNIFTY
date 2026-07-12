# NIFTY / BANK NIFTY Options Premium Drop Monitor

A live dashboard that watches every NIFTY 50 and NIFTY BANK option contract
for a given expiry, tracks each contract's **all-time-high premium** (the
highest price that specific contract has traded at since it was listed),
and flags contracts whose current price (LTP) has dropped **3% / 5% / 7%**
off that high — refreshing automatically while the market is open
(9:15–15:30 IST, Mon–Fri).

**Note on "all-time high":** option contracts expire weekly/monthly, so
there's no multi-year price history the way there is for a stock. "ATH"
here means the highest price *that specific contract* has ever traded at,
from the day it was listed up to now — combining Upstox's historical daily
candles (backfilled once per contract) with live updates during the
session.

Built against the **Upstox v2 API**. It runs on your own machine using your
own API credentials — no keys are ever embedded in the code or sent anywhere
but Upstox.

## 1. Get your Upstox access token

1. Create an app at https://account.upstox.com/developer/apps if you haven't.
2. Complete the OAuth login flow to get an `access_token`. Upstox's own docs
   walk through this: https://upstox.com/developer/api-documentation/authentication/
3. **Note:** standard Upstox access tokens are valid only for the current
   trading day — you'll need to regenerate this each morning and update your
   `.env` file. (Upstox also offers a longer-lived "analytics token" for
   market-data-only use cases, worth asking your Upstox app dashboard about
   if daily regeneration becomes a hassle.)

## 2. Install

```bash
cd nifty-options-dashboard
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# then edit .env and paste your token
```

## 3. Run

```bash
streamlit run dashboard.py
```

This opens a browser tab with the live dashboard. Leave it running during
market hours — it auto-refreshes every 5 seconds (configurable in
`config.py` via `REFRESH_SECONDS`).

## How it works

- `upstox_provider.py` calls Upstox's `/v2/option/chain` endpoint for the
  underlying + expiry you pick in the sidebar (returns each strike's Call
  and Put LTP, OI, volume), and `/v2/historical-candle/.../day/...` to pull
  each contract's daily highs since it was listed.
- `tracker.py` seeds each contract's ATH once from that historical data,
  then raises it further as live LTPs come in, computing
  `% drop = (ath - ltp) / ath * 100`.
- `dashboard.py` renders the option chain as a color-coded table:
  - 🟡 Yellow: ≥3% off the contract's all-time high
  - 🟠 Orange: ≥5% off
  - 🔴 Red: ≥7% off

## Things worth knowing

- **First load is slower than later refreshes.** Every contract needs a
  one-time historical-candle call to seed its ATH (done concurrently, 5 at
  a time). With the default 6-strikes-either-side setting that's ~26
  contracts on first load; after that, ATH is cached in memory for the rest
  of the session and only live LTP polling happens. Widening "Strikes to
  show" in the sidebar makes first load slower — and can bump into Upstox's
  API rate limits if pushed too high.
- **ATH resets if you restart the app** (it's in-memory only). If you want
  it persisted to disk/a database so it survives restarts, that's a
  straightforward addition — say the word.
- **This polls via REST every few seconds** rather than using a websocket
  tick stream. That's simpler and plenty responsive for premium-decay
  monitoring, but if you want true tick-by-tick updates, Upstox's
  `MarketDataStreamerV3` websocket can be swapped in — happy to build that
  next if you want it.
- **Holidays:** `market_hours.py` checks weekday + time only. NSE trading
  holidays (a fixed list published each year) aren't accounted for yet — the
  app will just show stale/empty data gracefully on a holiday. Say the word
  and I'll wire in the NSE holiday calendar.
- **Fyers / Angel One:** you mentioned you have access to more than one
  broker. This version is wired to Upstox since its option-chain and
  historical-candle APIs are the most directly documented for this use
  case. If you actually want to run it against Fyers or Angel One instead
  (or as a fallback), tell me which one and I'll write a matching
  provider — the rest of the app (`tracker.py`, `dashboard.py`) doesn't
  need to change, since they only depend on the provider returning that
  same simple row format.

## Files

| File | Purpose |
|---|---|
| `config.py` | Instruments, thresholds, refresh rate, market hours |
| `market_hours.py` | Is-market-open check (IST, Mon–Fri) |
| `upstox_provider.py` | Talks to Upstox's REST option-chain API |
| `tracker.py` | Tracks each contract's intraday high & % drop |
| `dashboard.py` | Streamlit UI — run this file |
