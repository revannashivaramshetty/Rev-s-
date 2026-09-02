"""
My Trading Partner — Signal Engine V2
Robust daily swing scanner for Indian equities.

V2.1 reliability update:
- Direct Yahoo Finance chart endpoint with retries.
- yfinance fallback.
- Safer parsing for Yahoo MultiIndex responses.
- Parallel price loading with clear success/failure counts.
- Nifty data is validated before signals are evaluated.
- No signal is produced from missing market data.
- Signal strength is labelled as strength, not probability.
"""

import concurrent.futures as cf
import time
from datetime import datetime

import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="My Trading Partner", page_icon="📈", layout="wide")

APP_TITLE = "📈 My Trading Partner"
APP_SUBTITLE = "V2.1 — Regime-aware swing signals, robust data loading & honest backtests"
NIFTY = "^NSEI"
MIN_BARS = 220

YOUR_PICKS = [
    "COFORGE.NS", "PERSISTENT.NS", "MPHASIS.NS", "MODISONLTD.NS",
    "PREMIERPOL.NS", "RPTECH.NS", "BORORENEW.NS", "JARO.NS", "TPLPLASTEH.NS",
]

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
    "IOC.NS", "NAUKRI.NS", "IRFC.NS", "JINDALSTEL.NS", "JSWENERGY.NS",
    "LICI.NS", "LODHA.NS", "LTIM.NS", "MAZDOCK.NS", "PIDILITIND.NS",
    "PFC.NS", "PNB.NS", "RECLTD.NS", "MOTHERSON.NS", "SHREECEM.NS",
    "SIEMENS.NS", "SOLARINDS.NS", "TATAPOWER.NS", "TORNTPHARM.NS", "TVSMOTOR.NS",
    "UNITDSPR.NS", "VBL.NS", "VEDL.NS", "ZYDUSLIFE.NS",
]

EXTRAS = [
    "KAJARIACER.NS", "PIIND.NS", "CDSL.NS", "APLAPOLLO.NS", "KPITTECH.NS",
    "DIXON.NS", "SUPREMEIND.NS", "AMBER.NS", "POLYCAB.NS", "CUMMINSIND.NS",
    "MEESHO.NS", "GROWW.NS", "INDUSTOWER.NS", "MCX.NS", "PINELABS.NS",
    "KAYNES.NS", "ASTERDM.NS", "PWL.NS", "IFCI.NS",
]

PERIOD_DAYS = {"1y": 400, "2y": 800, "3y": 1200}

YF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}


def s1(x):
    if isinstance(x, pd.DataFrame):
        if x.shape[1] == 0:
            return pd.Series(index=x.index, dtype=float)
        return x.iloc[:, 0]
    return x


def clean_ohlcv(df):
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    required = ["Open", "High", "Low", "Close", "Volume"]
    for col in required:
        if col not in df.columns:
            return pd.DataFrame()
        df[col] = pd.to_numeric(s1(df[col]), errors="coerce")
    df = df[required].dropna(subset=["Open", "High", "Low", "Close"])
    if df.empty:
        return pd.DataFrame()
    df.index = pd.to_datetime(df.index, errors="coerce")
    df = df[~df.index.isna()].sort_index()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    return df


def chart_url(ticker, period):
    end = int(time.time())
    start = end - PERIOD_DAYS.get(period, 400) * 86400
    return (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{requests.utils.quote(ticker, safe='')}"
        f"?period1={start}&period2={end}&interval=1d"
        f"&events=history&includeAdjustedClose=true"
    )


def fetch_chart_yahoo(ticker, period, retries=3):
    last_error = ""
    for attempt in range(retries):
        try:
            r = requests.get(chart_url(ticker, period), headers=YF_HEADERS, timeout=15)
            r.raise_for_status()
            payload = r.json()
            result = payload.get("chart", {}).get("result")
            if not result:
                raise ValueError(payload.get("chart", {}).get("error") or "empty Yahoo result")
            item = result[0]
            ts = item.get("timestamp")
            quote = (item.get("indicators") or {}).get("quote", [{}])[0]
            if not ts or not quote:
                raise ValueError("Yahoo returned no price arrays")
            idx = pd.to_datetime(ts, unit="s")
            data = {
                "Open": quote.get("open"),
                "High": quote.get("high"),
                "Low": quote.get("low"),
                "Close": quote.get("close"),
                "Volume": quote.get("volume"),
            }
            df = clean_ohlcv(pd.DataFrame(data, index=idx))
            if not df.empty:
                return df
            raise ValueError("Yahoo returned no usable OHLCV rows")
        except Exception as exc:
            last_error = str(exc)
            if attempt < retries - 1:
                time.sleep(0.8 * (attempt + 1))
    return pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def get_prices(ticker, period="1y"):
    df = fetch_chart_yahoo(ticker, period)
    if not df.empty:
        return df
    try:
        y = yf.download(
            ticker, period=period, interval="1d",
            progress=False, auto_adjust=False, threads=False,
        )
        df = clean_ohlcv(y)
        if not df.empty:
            return df
    except Exception:
        pass
    return pd.DataFrame()


def ema(x, n):
    return x.ewm(span=n, adjust=False).mean()


def rsi(x, n=14):
    d = x.diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    ag = up.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    al = dn.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(high, low, close, n=14):
    pc = close.shift(1)
    tr = pd.concat([(high-low), (high-pc).abs(), (low-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()


def macd(close):
    m = ema(close, 12) - ema(close, 26)
    sig = ema(m, 9)
    return m, sig, m - sig


def adx(high, low, close, n=14):
    pc = close.shift(1)
    tr = pd.concat([(high-low), (high-pc).abs(), (low-pc).abs()], axis=1).max(axis=1)
    up = high.diff()
    down = -low.diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=close.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=close.index)
    atrv = tr.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False).mean() / atrv
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False).mean() / atrv
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, min_periods=n, adjust=False).mean().fillna(0)


def market_regime(nifty_close):
    c = s1(nifty_close).dropna()
    if len(c) < 210:
        return "UNKNOWN", 0, "Insufficient Nifty history"
    e50 = ema(c, 50)
    e200 = ema(c, 200)
    last = float(c.iloc[-1])
    bull = [last > e200.iloc[-1], e50.iloc[-1] > e200.iloc[-1], e200.iloc[-1] > e200.iloc[-6]]
    bear = [last < e200.iloc[-1], e50.iloc[-1] < e200.iloc[-1], e200.iloc[-1] < e200.iloc[-6]]
    if sum(bull) == 3:
        return "BULL", 10, "Nifty above EMA200, EMA50 above EMA200, long-term slope rising"
    if sum(bear) == 3:
        return "BEAR", -15, "Nifty below EMA200, EMA50 below EMA200, long-term slope falling"
    return "NEUTRAL", 0, "Market structure mixed; require stronger stock confirmation"


def relative_strength(stock_close, nifty_close):
    n = s1(nifty_close).reindex(stock_close.index).ffill()
    return stock_close.pct_change(20) - n.pct_change(20)


def score_snapshot(df, nifty_df):
    if df.empty or nifty_df.empty or len(df) < MIN_BARS or len(nifty_df) < MIN_BARS:
        return None

    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    e21, e50, e200 = ema(c, 21), ema(c, 50), ema(c, 200)
    rv, av, ax = rsi(c), atr(h, l, c), adx(h, l, c)
    ml, ms, mh = macd(c)
    volx = v / v.rolling(20).mean()
    hh20 = c.rolling(20).max().shift(1)
    rel20 = relative_strength(c, nifty_df["Close"])

    price = float(c.iloc[-1])
    a = float(av.iloc[-1])
    r = float(rv.iloc[-1])
    ad = float(ax.iloc[-1])
    x = float(volx.iloc[-1]) if np.isfinite(volx.iloc[-1]) else 1.0
    rs = float(rel20.iloc[-1]) if np.isfinite(rel20.iloc[-1]) else 0.0
    atr_pct = (a / price * 100) if price else 0.0
    ext = ((price - float(e21.iloc[-1])) / a) if a and np.isfinite(a) else 0.0
    breakout = bool(np.isfinite(hh20.iloc[-1]) and price > float(hh20.iloc[-1]))

    regime, regime_pts, regime_reason = market_regime(nifty_df["Close"])

    score = regime_pts
    breakdown = {"Market regime": regime_pts}
    reasons = [regime_reason]

    trend_pts = 0
    trend_pts += 5 if price > e21.iloc[-1] else 0
    trend_pts += 5 if e21.iloc[-1] > e50.iloc[-1] else 0
    trend_pts += 5 if e50.iloc[-1] > e200.iloc[-1] else 0
    trend_pts += 5 if e21.iloc[-1] > e21.iloc[-6] and e50.iloc[-1] > e50.iloc[-6] and e200.iloc[-1] > e200.iloc[-6] else 0
    trend_pts += 5 if price >= c.iloc[-11:].max() * 0.97 else 0
    score += trend_pts
    breakdown["Trend"] = trend_pts
    trend = "Strong uptrend" if trend_pts >= 20 else "Bullish" if trend_pts >= 15 else "Mixed" if trend_pts >= 8 else "Weak"
    reasons.append(f"Trend: {trend}")

    mom = 0
    if 52 <= r <= 68:
        mom += 7
    elif 48 <= r < 52 or 68 < r <= 72:
        mom += 3
    elif r > 78:
        mom -= 5
    elif r < 35:
        mom -= 2
    mom += 4 if ml.iloc[-1] > ms.iloc[-1] else 0
    mom += 4 if mh.iloc[-1] > mh.iloc[-2] else 0
    score += mom
    breakdown["Momentum"] = mom
    reasons.append(f"Momentum: RSI {r:.1f}, MACD {'improving' if mh.iloc[-1] > mh.iloc[-2] else 'weakening'}")

    rspts = 6 if rs > 0.05 else 3 if rs > 0 else -4 if rs < -0.05 else 0
    score += rspts
    breakdown["Relative strength"] = rspts
    reasons.append(f"20D relative strength vs Nifty: {rs * 100:+.1f}%")

    bp = 0
    bp += 5 if x >= 1.5 else 2 if x >= 1.1 else 0
    bp += 6 if breakout else 0
    bp += 4 if breakout and x >= 1.5 else 0
    score += bp
    breakdown["Volume + breakout"] = bp
    reasons.append(f"Volume {x:.2f}x average; {'20D breakout' if breakout else 'no 20D breakout'}")

    riskpts = 5
    if ext > 3:
        riskpts -= 7
    elif ext > 2:
        riskpts -= 4
    elif ext > 1.25:
        riskpts -= 2
    if atr_pct > 6:
        riskpts -= 3
    score += riskpts
    breakdown["Risk / extension"] = riskpts
    reasons.append(f"Price is {ext:.1f} ATR above EMA21; ATR {atr_pct:.1f}% of price")

    gates = []
    if regime == "BEAR":
        gates.append("bear market regime")
    if ad < 15:
        gates.append("ADX <15: trend too weak")
    if ext > 3:
        gates.append("price excessively extended from EMA21")
    if not np.isfinite(a) or a <= 0:
        gates.append("ATR unavailable")

    stop = price - 1.5 * a if np.isfinite(a) else np.nan
    target1 = price + 2.0 * a if np.isfinite(a) else np.nan
    target2 = price + 3.0 * a if np.isfinite(a) else np.nan

    if gates:
        call = "NO TRADE"
    elif score >= 72 and trend_pts >= 15 and r <= 72:
        call = "STRONG BUY"
    elif score >= 58 and trend_pts >= 12 and r <= 75:
        call = "BUY"
    elif score >= 45:
        call = "WATCH"
    else:
        call = "WAIT"

    strength = int(np.clip(round((score + 15) / 1.1), 0, 100))

    return {
        "score": round(score, 1), "call": call, "strength": strength,
        "price": price, "rsi": r, "adx": ad, "volx": x, "rel20": rs * 100,
        "atr_pct": atr_pct, "trend": trend, "regime": regime,
        "stop": stop, "target1": target1, "target2": target2,
        "breakout": breakout, "extension_atr": ext, "breakdown": breakdown,
        "reasons": reasons, "gates": gates,
    }


def load_many(tickers, period):
    results = {}
    failures = []
    workers = min(8, max(2, len(tickers)))
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(get_prices, t, period): t for t in tickers}
        for fut in cf.as_completed(futures):
            ticker = futures[fut]
            try:
                df = fut.result()
                if df is not None and len(df) >= 20:
                    results[ticker] = df
                else:
                    failures.append(ticker)
            except Exception:
                failures.append(ticker)
    return results, failures


def backtest(ticker, period="3y", max_hold=15):
    df = get_prices(ticker, period)
    nifty = get_prices(NIFTY, period)
    if df.empty or nifty.empty or len(df) < MIN_BARS or len(nifty) < MIN_BARS:
        return None

    c, h, l, o = df["Close"], df["High"], df["Low"], df["Open"]
    e21, e50, e200 = ema(c, 21), ema(c, 50), ema(c, 200)
    rv, av, ax = rsi(c), atr(h, l, c), adx(h, l, c)
    ml, ms, mh = macd(c)
    volx = df["Volume"] / df["Volume"].rolling(20).mean()
    nclose = nifty["Close"].reindex(df.index).ffill()
    rel20 = c.pct_change(20) - nclose.pct_change(20)

    ne = nifty["Close"]
    ne50, ne200 = ema(ne, 50), ema(ne, 200)
    ne_aligned = ne.reindex(df.index).ffill()
    ne50_aligned = ne50.reindex(df.index).ffill()
    ne200_aligned = ne200.reindex(df.index).ffill()
    trades = []
    i = 205

    while i < len(df) - 1:
        price = float(c.iloc[i])
        r = float(rv.iloc[i])
        ad = float(ax.iloc[i])
        vx = float(volx.iloc[i]) if np.isfinite(volx.iloc[i]) else 1
        rel = float(rel20.iloc[i]) if np.isfinite(rel20.iloc[i]) else 0
        trend = (
            (5 if price > e21.iloc[i] else 0)
            + (5 if e21.iloc[i] > e50.iloc[i] else 0)
            + (5 if e50.iloc[i] > e200.iloc[i] else 0)
            + (5 if e21.iloc[i] > e21.iloc[i-5] and e50.iloc[i] > e50.iloc[i-5] and e200.iloc[i] > e200.iloc[i-5] else 0)
        )
        momentum = (7 if 52 <= r <= 68 else 3 if 48 <= r <= 72 else -3 if r > 78 else 0)
        momentum += 4 if mh.iloc[i] > mh.iloc[i-1] else 0
        regime = "BULL" if ne_aligned.iloc[i] > ne200_aligned.iloc[i] and ne50_aligned.iloc[i] > ne200_aligned.iloc[i] else "BEAR" if ne_aligned.iloc[i] < ne200_aligned.iloc[i] and ne50_aligned.iloc[i] < ne200_aligned.iloc[i] else "NEUTRAL"
        pts = (10 if regime == "BULL" else -15 if regime == "BEAR" else 0) + trend + momentum
        pts += 6 if rel > .05 else 3 if rel > 0 else -4 if rel < -.05 else 0
        pts += 5 if vx >= 1.5 else 2 if vx >= 1.1 else 0
        pts += 4 if i >= 21 and c.iloc[i] > c.iloc[i-21:i].max() else 0
        a = float(av.iloc[i]) if np.isfinite(av.iloc[i]) else np.nan

        if pts >= 58 and trend >= 15 and r <= 75 and ad >= 15 and regime != "BEAR" and np.isfinite(a) and a > 0:
            entry_i = i + 1
            ep = float(o.iloc[entry_i])
            stop = ep - 1.5 * a
            target = ep + 3.0 * a
            exit_i = None
            xp = None
            reason = None

            for j in range(entry_i, min(len(df), entry_i + max_hold + 1)):
                hi, lo = float(h.iloc[j]), float(l.iloc[j])
                if lo <= stop and hi >= target:
                    exit_i, xp, reason = j, stop, "Both touched — stop first"
                    break
                if lo <= stop:
                    exit_i, xp, reason = j, stop, "Stop"
                    break
                if hi >= target:
                    exit_i, xp, reason = j, target, "Target"
                    break

            if exit_i is None:
                exit_i = min(len(df) - 1, entry_i + max_hold)
                xp = float(c.iloc[exit_i])
                reason = "Time exit"

            trades.append({
                "Entry": df.index[entry_i].strftime("%Y-%m-%d"),
                "Exit": df.index[exit_i].strftime("%Y-%m-%d"),
                "Entry Price": round(ep, 2), "Exit Price": round(xp, 2),
                "Return %": round((xp - ep) / ep * 100, 2),
                "Days": exit_i - entry_i, "Reason": reason,
            })
            i = exit_i + 1
        else:
            i += 1

    t = pd.DataFrame(trades)
    if t.empty:
        return {"trades": t, "stats": {"Total Trades": 0}}

    wins = t[t["Return %"] > 0]
    losses = t[t["Return %"] <= 0]
    wr = len(wins) / len(t) * 100
    avgwin = wins["Return %"].mean() if not wins.empty else 0
    avgloss = losses["Return %"].mean() if not losses.empty else 0
    expectancy = (wr / 100) * avgwin + (1 - wr / 100) * avgloss
    gross_win = wins["Return %"].sum()
    gross_loss = abs(losses["Return %"].sum())
    equity = (1 + t["Return %"] / 100).cumprod()
    dd = equity / equity.cummax() - 1

    return {"trades": t, "stats": {
        "Total Trades": len(t), "Win Rate %": round(wr, 1),
        "Expectancy %": round(expectancy, 2),
        "Profit Factor": round(gross_win / gross_loss, 2) if gross_loss else np.inf,
        "Max Drawdown %": round(float(dd.min() * 100), 2),
        "Avg Win %": round(avgwin, 2), "Avg Loss %": round(avgloss, 2),
        "Net Return %": round((equity.iloc[-1] - 1) * 100, 2),
        "Avg Hold Days": round(t["Days"].mean(), 1),
    }}


st.markdown("# " + APP_TITLE)
st.markdown("### " + APP_SUBTITLE)
st.caption("Research dashboard only • No guaranteed returns • Verify every signal on a live chart and company filings")

with st.sidebar:
    st.header("Scanner")
    group = st.radio("Universe", ["Nifty 50", "Nifty 100", "My Picks + Extras", "Custom"], index=0)
    if group == "Nifty 50":
        watchlist = NIFTY_50
    elif group == "Nifty 100":
        watchlist = list(dict.fromkeys(NIFTY_50 + NIFTY_NEXT_50))
    elif group == "My Picks + Extras":
        watchlist = list(dict.fromkeys(YOUR_PICKS + EXTRAS))
    else:
        raw = st.text_area("Tickers", value="COFORGE.NS, PERSISTENT.NS, JINDALSTEL.NS, MCX.NS")
        watchlist = [x.strip().upper() for x in raw.split(",") if x.strip()]
    period = st.selectbox("Price history", ["1y", "2y", "3y"], index=0)
    if st.button("🔄 Clear cache / Refresh"):
        st.cache_data.clear()
        st.rerun()

nifty_df = get_prices(NIFTY, period)
if nifty_df.empty or len(nifty_df) < MIN_BARS:
    regime = "DATA UNAVAILABLE"
    regime_reason = "Nifty price history could not be loaded. Scanner is paused."
    nc = np.nan
    npct = np.nan
else:
    regime, _, regime_reason = market_regime(nifty_df["Close"])
    nc = float(nifty_df["Close"].iloc[-1])
    npct = float(nifty_df["Close"].pct_change().iloc[-1] * 100)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Nifty 50", f"{nc:,.0f}" if np.isfinite(nc) else "—", f"{npct:+.2f}%" if np.isfinite(npct) else None)
c2.metric("Market regime", regime)
c3.metric("Requested", len(watchlist))
c4.metric("As of", datetime.now().strftime("%d %b %Y %H:%M"))

st.info(f"**Regime:** {regime_reason}")

if nifty_df.empty or len(nifty_df) < MIN_BARS:
    st.error("Market data is unavailable, so no stock signal will be generated. Use **Clear cache / Refresh** once and retry.")
    st.stop()

with st.spinner(f"Loading {len(watchlist)} symbols…"):
    price_map, failures = load_many(watchlist, period)

rows = []
for ticker, df in price_map.items():
    snap = score_snapshot(df, nifty_df)
    if snap is not None:
        rows.append({
            "Ticker": ticker.replace(".NS", ""), "Price": snap["price"],
            "RSI": snap["rsi"], "ADX": snap["adx"], "Vol x": snap["volx"],
            "vs Nifty 20D %": snap["rel20"], "Trend": snap["trend"],
            "Regime": snap["regime"], "Call": snap["call"], "Strength": snap["strength"],
            "Stop": snap["stop"], "Target 1": snap["target1"], "Target 2": snap["target2"],
            "Score": snap["score"],
        })

if failures:
    st.warning(f"{len(failures)} symbol(s) could not be loaded this run. Successful: {len(rows)} / {len(watchlist)}.")

if rows:
    out = pd.DataFrame(rows).sort_values(["Call", "Score"], ascending=[True, False])
    st.subheader("Signal Scanner")
    st.dataframe(out.style.format({
        "Price": "{:.2f}", "RSI": "{:.1f}", "ADX": "{:.1f}", "Vol x": "{:.2f}",
        "vs Nifty 20D %": "{:+.1f}", "Stop": "{:.2f}", "Target 1": "{:.2f}",
        "Target 2": "{:.2f}", "Score": "{:.1f}",
    }), use_container_width=True, hide_index=True)

    st.subheader("Actionable setups")
    actionable = out[out["Call"].isin(["STRONG BUY", "BUY"])].head(10)
    if actionable.empty:
        st.info("No actionable BUY setup under the current V2 rules.")
    else:
        st.dataframe(actionable, use_container_width=True, hide_index=True)

    choices = [x for x in price_map if x.replace(".NS", "") in out["Ticker"].tolist()]
    if choices:
        selected = st.selectbox("Why this signal?", choices, index=0)
        snap = score_snapshot(price_map[selected], nifty_df)
        if snap:
            st.markdown(f"### {selected.replace('.NS', '')} — {snap['call']}")
            st.write(f"**Signal strength:** {snap['strength']}/100  • **Score:** {snap['score']}  • **RSI:** {snap['rsi']:.1f}  • **ADX:** {snap['adx']:.1f}")
            st.write(f"**Entry reference:** ₹{snap['price']:.2f}  • **Stop:** ₹{snap['stop']:.2f}  • **Target 1:** ₹{snap['target1']:.2f}  • **Target 2:** ₹{snap['target2']:.2f}")
            for reason in snap["reasons"]:
                st.write("• " + reason)
            if snap["gates"]:
                st.warning("Gates: " + "; ".join(snap["gates"]))

    with st.expander("Backtest V2"):
        valid_bt = [x for x in price_map.keys() if len(price_map[x]) >= MIN_BARS]
        bt_ticker = st.selectbox("Stock", valid_bt, index=0 if valid_bt else None)
        if bt_ticker:
            bt = backtest(bt_ticker, "3y")
            if bt:
                st.json(bt["stats"])
                if not bt["trades"].empty:
                    st.dataframe(bt["trades"], use_container_width=True, hide_index=True)
else:
    st.error("No usable stock price history was returned. Please refresh and retry.")

st.caption("My Trading Partner V2.1 • Yahoo Finance chart data with yfinance fallback • Daily swing research • No order execution • Signal strength is not a calibrated probability")
