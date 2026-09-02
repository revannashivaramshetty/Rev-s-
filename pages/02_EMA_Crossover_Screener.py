"""
My Trading Partner — 21/50 EMA Crossover Screener

Rules intentionally mirror the user's friend's screener:
- EMA/crossover/slope use completed daily candles only.
- Price uses the latest available market price (latest Yahoo daily close here).
- Confirmed Bullish:
    21 EMA > 50 EMA
    21 EMA rising
    latest price above both EMAs
    last 2 completed daily closes above 21 EMA
    EMA separation >= 1%
- Confirmed Bearish: exact opposite.
- A fresh crossover alone is NOT a confirmed entry.
"""

import concurrent.futures as cf
import time
from datetime import datetime

import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="EMA Crossover | My Trading Partner", page_icon="📈", layout="wide")

NIFTY = "^NSEI"
PERIOD_DAYS = 400
MIN_BARS = 70

# Nifty 100 universe. The extra IndusInd Bank entry completes the 50 + 50 set
# used by this page; invalid/delisted symbols are safely reported as unavailable.
NIFTY_50 = [
    "ADANIENT.NS", "ADANIPORTS.NS", "APOLLOHOSP.NS", "ASIANPAINT.NS", "AXISBANK.NS",
    "BAJAJ-AUTO.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS", "BEL.NS", "BHARTIARTL.NS",
    "CIPLA.NS", "COALINDIA.NS", "DRREDDY.NS", "EICHERMOT.NS", "ETERNAL.NS",
    "GRASIM.NS", "HCLTECH.NS", "HDFCBANK.NS", "HDFCLIFE.NS", "HINDALCO.NS",
    "HINDUNILVR.NS", "ICICIBANK.NS", "INDIGO.NS", "INFY.NS", "ITC.NS",
    "JIOFIN.NS", "JSWSTEEL.NS", "KOTAKBANK.NS", "LT.NS", "M&M.NS",
    "MARUTI.NS", "MAXHEALTH.NS", "NESTLEIND.NS", "NTPC.NS", "ONGC.NS",
    "POWERGRID.NS", "RELIANCE.NS", "SBILIFE.NS", "SHRIRAMFIN.NS", "SBIN.NS",
    "SUNPHARMA.NS", "TCS.NS", "TATACONSUM.NS", "TATAMOTORS.NS", "TATASTEEL.NS",
    "TECHM.NS", "TITAN.NS", "TRENT.NS", "ULTRACEMCO.NS", "WIPRO.NS",
]

NIFTY_NEXT_50 = [
    "ABB.NS", "ADANIENSOL.NS", "ADANIGREEN.NS", "ADANIPOWER.NS", "AMBUJACEM.NS",
    "BAJAJHLDNG.NS", "BAJAJHFL.NS", "BANKBARODA.NS", "BPCL.NS", "BRITANNIA.NS",
    "BOSCHLTD.NS", "CANBK.NS", "CGPOWER.NS", "CHOLAFIN.NS", "DIVISLAB.NS",
    "DLF.NS", "DMART.NS", "GAIL.NS", "GODREJCP.NS", "HAVELLS.NS",
    "HAL.NS", "HINDZINC.NS", "HYUNDAI.NS", "ICICIGI.NS", "INDHOTEL.NS",
    "IOC.NS", "NAUKRI.NS", "IRFC.NS", "INDUSINDBK.NS", "JINDALSTEL.NS",
    "JSWENERGY.NS", "LICI.NS", "LODHA.NS", "LTIM.NS", "MAZDOCK.NS",
    "PIDILITIND.NS", "PFC.NS", "PNB.NS", "RECLTD.NS", "MOTHERSON.NS",
    "SHREECEM.NS", "SIEMENS.NS", "SOLARINDS.NS", "TATAPOWER.NS", "TORNTPHARM.NS",
    "TVSMOTOR.NS", "UNITDSPR.NS", "VBL.NS", "VEDL.NS", "ZYDUSLIFE.NS",
]

WATCHLIST = list(dict.fromkeys(NIFTY_50 + NIFTY_NEXT_50))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}


def clean(df):
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        if c not in df.columns:
            return pd.DataFrame()
        if isinstance(df[c], pd.DataFrame):
            df[c] = df[c].iloc[:, 0]
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    df.index = pd.to_datetime(df.index, errors="coerce")
    df = df[~df.index.isna()].sort_index()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    return df


def yahoo_url(ticker):
    end = int(time.time())
    start = end - PERIOD_DAYS * 86400
    return (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(ticker, safe='')}"
        f"?period1={start}&period2={end}&interval=1d&events=history&includeAdjustedClose=true"
    )


def fetch(ticker):
    try:
        r = requests.get(yahoo_url(ticker), headers=HEADERS, timeout=12)
        r.raise_for_status()
        item = r.json()["chart"]["result"][0]
        ts = item["timestamp"]
        q = item["indicators"]["quote"][0]
        df = clean(pd.DataFrame({
            "Open": q.get("open"), "High": q.get("high"), "Low": q.get("low"),
            "Close": q.get("close"), "Volume": q.get("volume")
        }, index=pd.to_datetime(ts, unit="s")))
        if not df.empty:
            return df
    except Exception:
        pass
    try:
        return clean(yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=False, threads=False))
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def get_prices(ticker):
    return fetch(ticker)


def analyse(ticker, df):
    if df.empty or len(df) < MIN_BARS:
        return None

    c = df["Close"]
    e21 = c.ewm(span=21, adjust=False).mean()
    e50 = c.ewm(span=50, adjust=False).mean()

    # All confirmation inputs below are from completed daily candles.
    e21_prev = float(e21.iloc[-2])
    e50_prev = float(e50.iloc[-2])
    e21_now = float(e21.iloc[-1])
    e50_now = float(e50.iloc[-1])
    close1 = float(c.iloc[-1])
    close2 = float(c.iloc[-2])

    ema_sep = abs(e21_now - e50_now) / e50_now * 100 if e50_now else np.nan
    ema21_rising = e21_now > e21_prev
    ema50_rising = e50_now > e50_prev
    bullish_structure = e21_now > e50_now
    bearish_structure = e21_now < e50_now
    above_both = close1 > e21_now and close1 > e50_now
    below_both = close1 < e21_now and close1 < e50_now
    last2_above21 = close1 > e21_now and close2 > float(e21.iloc[-2])
    last2_below21 = close1 < e21_now and close2 < float(e21.iloc[-2])

    # Fresh crossover means the relationship changed on the latest completed candle.
    fresh_bull = e21_now > e50_now and e21_prev <= e50_prev
    fresh_bear = e21_now < e50_now and e21_prev >= e50_prev

    confirmed_bull = bullish_structure and ema21_rising and above_both and last2_above21 and ema_sep >= 1.0
    confirmed_bear = bearish_structure and (not ema21_rising) and below_both and last2_below21 and ema_sep >= 1.0

    if confirmed_bull:
        status = "Confirmed Bullish"
    elif confirmed_bear:
        status = "Confirmed Bearish"
    elif fresh_bull or fresh_bear:
        status = "Fresh Crossover"
    else:
        status = "Waiting Confirmation"

    return {
        "Ticker": ticker.replace(".NS", ""),
        "Price": close1,
        "21 EMA": e21_now,
        "50 EMA": e50_now,
        "EMA Sep %": ema_sep,
        "21 EMA Slope": "Rising" if ema21_rising else "Falling",
        "Price vs EMAs": "Above both" if above_both else "Below both" if below_both else "Between",
        "Last 2 Closes vs 21": "Confirmed" if last2_above21 or last2_below21 else "Not confirmed",
        "Status": status,
        "Fresh Bull": fresh_bull,
        "Fresh Bear": fresh_bear,
    }


st.title("📈 21/50 EMA Crossover Screener")
st.caption("Trend Following Screener — Nifty 100")
st.write("**EMA, crossover and slope use completed daily candles. Price uses the latest available market price.**")

if st.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.rerun()

with st.spinner("Scanning Nifty 100…"):
    results = {}
    failures = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(get_prices, t): t for t in WATCHLIST}
        for f in cf.as_completed(futures):
            t = futures[f]
            try:
                d = f.result()
                r = analyse(t, d)
                if r is None:
                    failures.append(t)
                else:
                    results[t] = r
            except Exception:
                failures.append(t)

rows = list(results.values())
res = pd.DataFrame(rows)

if res.empty:
    st.error("No usable market data was returned. Please refresh and retry.")
    st.stop()

# Exact category counts for the rule set.
counts = res["Status"].value_counts()
confirmed_bull = int(counts.get("Confirmed Bullish", 0))
waiting = int(counts.get("Waiting Confirmation", 0))
confirmed_bear = int(counts.get("Confirmed Bearish", 0))
fresh = int(counts.get("Fresh Crossover", 0))

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Confirmed Bullish", confirmed_bull)
c2.metric("Waiting Confirmation", waiting)
c3.metric("Confirmed Bearish", confirmed_bear)
c4.metric("Fresh Crossover", fresh)
c5.metric("Total Stocks", len(res))

with st.expander("ℹ️ Confirmation rules", expanded=True):
    st.markdown(
        "**Bullish:** 21 EMA > 50 EMA, 21 EMA rising, live/latest price above both EMAs, "
        "last 2 completed daily closes above 21 EMA, and EMA separation ≥ 1%.\n\n"
        "**Bearish:** exact opposite.\n\n"
        "**A fresh crossover alone is not treated as a confirmed entry.**"
    )

st.caption("Completed-candle calculations prevent an intraday EMA move from becoming a false confirmation.")
st.caption(f"🕐 Last updated: {datetime.now().strftime('%d-%m-%Y %I:%M:%S %p')} IST")

st.subheader(f"📋 EMA Crossover Results — {len(res)} stocks")

display = res[["Ticker", "Price", "21 EMA", "50 EMA", "EMA Sep %", "21 EMA Slope", "Price vs EMAs", "Last 2 Closes vs 21", "Status"]].copy()
display = display.sort_values(["Status", "EMA Sep %"], ascending=[True, False])
st.dataframe(display.style.format({
    "Price": "₹{:.2f}", "21 EMA": "₹{:.2f}", "50 EMA": "₹{:.2f}", "EMA Sep %": "{:.2f}%"
}), use_container_width=True, hide_index=True)

if failures:
    st.warning(f"{len(failures)} stock(s) could not be evaluated because price history was unavailable or too short.")

st.info("This EMA screener is an additional confirmation module. It does not replace the V2 regime, momentum, volume, risk and backtest checks on the main Signal Scanner.")
