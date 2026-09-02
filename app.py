"""
My Trading Partner — Signal Engine V2
Daily swing-trading scanner for Indian equities.

V2 design goals:
- Regime-aware scoring instead of a simple indicator tally.
- Trend + momentum + relative strength + volume + breakout confirmation.
- ATR-based risk levels and extension penalty.
- Fundamental safety gate for live signals.
- Explicit NO TRADE / WAIT states instead of forcing a BUY.
- Backtest enters on the next trading day's open to reduce look-ahead bias.

Data source: Yahoo Finance via yfinance. Data can be delayed/incomplete.
This tool is research software, not investment advice or an execution system.
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime

st.set_page_config(page_title="My Trading Partner", page_icon="📈", layout="wide")

# ================================================================
# CONFIG
# ================================================================
APP_TITLE = "📈 My Trading Partner"
APP_SUBTITLE = "V2 — Regime-aware swing signals, risk levels & honest backtests"
NIFTY = "^NSEI"
BANKNIFTY = "^NSEBANK"
SENSEX = "^BSESN"
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

# ================================================================
# INDICATORS
# ================================================================
def s1(x):
    if isinstance(x, pd.DataFrame):
        return x.iloc[:, 0]
    return x


def ema(x, n):
    return x.ewm(span=n, adjust=False).mean()


def rsi(x, n=14):
    d = x.diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    ag = up.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    al = dn.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(50)


def atr(high, low, close, n=14):
    pc = close.shift(1)
    tr = pd.concat([(high-low), (high-pc).abs(), (low-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, min_periods=n, adjust=False).mean()


def macd(close):
    m = ema(close, 12) - ema(close, 26)
    sig = ema(m, 9)
    return m, sig, m-sig


def adx(high, low, close, n=14):
    pc = close.shift(1)
    tr = pd.concat([(high-low), (high-pc).abs(), (low-pc).abs()], axis=1).max(axis=1)
    up = high.diff()
    down = -low.diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=close.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=close.index)
    atrv = tr.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    pdi = 100 * plus.ewm(alpha=1/n, min_periods=n, adjust=False).mean() / atrv
    mdi = 100 * minus.ewm(alpha=1/n, min_periods=n, adjust=False).mean() / atrv
    dx = 100 * (pdi-mdi).abs() / (pdi+mdi).replace(0, np.nan)
    return dx.ewm(alpha=1/n, min_periods=n, adjust=False).mean().fillna(0)


# ================================================================
# MARKET REGIME
# ================================================================
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
        return "BULL", 10, "Nifty above EMA200; EMA50 above EMA200; long-term slope rising"
    if sum(bear) == 3:
        return "BEAR", -15, "Nifty below EMA200; EMA50 below EMA200; long-term slope falling"
    return "NEUTRAL", 0, "Market structure is mixed — require stronger stock-level confirmation"


# ================================================================
# FUNDAMENTALS
# ================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_fundamentals(ticker):
    try:
        info = yf.Ticker(ticker).info
        if not info or len(info) < 5:
            return {"status":"UNKNOWN", "score":0, "reason":"Fundamental data unavailable"}
        mcap = info.get("marketCap")
        pe = info.get("trailingPE")
        roe = info.get("returnOnEquity")
        de = info.get("debtToEquity")
        margin = info.get("profitMargins")
        score = 0
        reasons = []
        if pe is not None:
            if pe < 0: score -= 3; reasons.append("loss-making")
            elif pe <= 35: score += 1; reasons.append("reasonable PE")
            elif pe > 100: score -= 1; reasons.append("very high PE")
        if roe is not None:
            if roe >= .20: score += 2; reasons.append("ROE ≥20%")
            elif roe >= .12: score += 1; reasons.append("ROE ≥12%")
            elif roe < .05: score -= 2; reasons.append("weak ROE")
        if de is not None:
            if de < 50: score += 1; reasons.append("low leverage")
            elif de > 150: score -= 2; reasons.append("high leverage")
        if margin is not None:
            if margin >= .15: score += 1; reasons.append("strong margin")
            elif margin < 0: score -= 2; reasons.append("negative margin")
        if mcap is not None and mcap < 3e9:
            score -= 2; reasons.append("very small market cap")
        if score <= -3: status = "WEAK"
        elif score <= 0: status = "CAUTION"
        else: status = "HEALTHY"
        return {"status":status, "score":score, "reason":", ".join(reasons) or "basic data passed", "pe":pe, "roe":roe, "de":de, "margin":margin, "mcap":mcap}
    except Exception as e:
        return {"status":"UNKNOWN", "score":0, "reason":str(e)}


# ================================================================
# PRICE DATA
# ================================================================
@st.cache_data(ttl=900, show_spinner=False)
def get_prices(ticker, period="1y"):
    try:
        df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=False)
        if df.empty:
            return pd.DataFrame()
        for col in ["Open","High","Low","Close","Volume"]:
            if col in df:
                df[col] = s1(df[col]).astype(float)
        return df.dropna(subset=["Close"])
    except Exception:
        return pd.DataFrame()


# ================================================================
# V2 SIGNAL ENGINE
# ================================================================
def score_snapshot(df, nifty_df, fund=None):
    c = df["Close"]
    h, l, v = df["High"], df["Low"], df["Volume"]
    e9, e21, e50, e200 = ema(c,9), ema(c,21), ema(c,50), ema(c,200)
    rv = rsi(c)
    av = atr(h,l,c)
    ml, ms, mh = macd(c)
    ax = adx(h,l,c)
    vol20 = v.rolling(20).mean()
    volx = v / vol20
    hh20 = c.rolling(20).max().shift(1)
    stock_ret20 = c.pct_change(20)
    nifty_c = s1(nifty_df["Close"]).reindex(c.index).ffill()
    rel20 = stock_ret20 - nifty_c.pct_change(20)

    price = float(c.iloc[-1]); a = float(av.iloc[-1])
    r = float(rv.iloc[-1]); x = float(volx.iloc[-1]) if np.isfinite(volx.iloc[-1]) else 1
    ad = float(ax.iloc[-1]); rs = float(rel20.iloc[-1]) if np.isfinite(rel20.iloc[-1]) else 0
    atr_pct = a / price * 100 if price else 0
    ext = (price - float(e21.iloc[-1])) / a if a else 0

    score = 0.0
    reasons = []
    breakdown = {}

    # 1. Market regime: 15 points
    regime, regime_pts, regime_reason = market_regime(nifty_df["Close"])
    score += regime_pts
    breakdown["Market regime"] = regime_pts
    reasons.append(regime_reason)

    # 2. Trend structure: 25 points
    trend_pts = 0
    if price > e21.iloc[-1]: trend_pts += 5
    if e21.iloc[-1] > e50.iloc[-1]: trend_pts += 5
    if e50.iloc[-1] > e200.iloc[-1]: trend_pts += 5
    if e21.iloc[-1] > e21.iloc[-6] and e50.iloc[-1] > e50.iloc[-6] and e200.iloc[-1] > e200.iloc[-6]: trend_pts += 5
    if c.iloc[-1] > c.iloc[-11:].max() * .97 and c.iloc[-1] > c.iloc[-21:-1].min(): trend_pts += 5
    score += trend_pts
    breakdown["Trend"] = trend_pts
    trend = "Strong uptrend" if trend_pts >= 20 else ("Bullish" if trend_pts >= 15 else ("Mixed" if trend_pts >= 8 else "Weak"))
    reasons.append(f"Trend: {trend}")

    # 3. Momentum: 15 points. RSI is contextual, not a blind BUY trigger.
    mom = 0
    if 52 <= r <= 68: mom += 7
    elif 48 <= r < 52 or 68 < r <= 72: mom += 3
    elif r > 78: mom -= 5
    elif r < 35: mom -= 2
    if ml.iloc[-1] > ms.iloc[-1]: mom += 4
    if mh.iloc[-1] > mh.iloc[-2]: mom += 4
    score += mom
    breakdown["Momentum"] = mom
    reasons.append(f"Momentum: RSI {r:.1f}, MACD {'improving' if mh.iloc[-1] > mh.iloc[-2] else 'weakening'}")

    # 4. Relative strength: 10 points
    rspts = 6 if rs > .05 else (3 if rs > 0 else (-4 if rs < -.05 else 0))
    score += rspts
    breakdown["Relative strength"] = rspts
    reasons.append(f"20D relative strength vs Nifty: {rs*100:+.1f}%")

    # 5. Volume / breakout: 15 points
    bp = 0
    breakout = price > float(hh20.iloc[-1]) if np.isfinite(hh20.iloc[-1]) else False
    if x >= 1.5: bp += 5
    elif x >= 1.1: bp += 2
    if breakout: bp += 6
    if breakout and x >= 1.5: bp += 4
    score += bp
    breakdown["Volume + breakout"] = bp
    reasons.append(f"Volume {x:.2f}x average; {'20D breakout' if breakout else 'no 20D breakout'}")

    # 6. Risk/extension: 10 points
    riskpts = 5
    if ext > 3: riskpts -= 7
    elif ext > 2: riskpts -= 4
    elif ext > 1.25: riskpts -= 2
    if atr_pct > 6: riskpts -= 3
    score += riskpts
    breakdown["Risk / extension"] = riskpts
    reasons.append(f"Price is {ext:.1f} ATR above EMA21; ATR {atr_pct:.1f}% of price")

    # Fundamentals are a gate/adjustment, not a substitute for price action.
    fscore = fund.get("score",0) if fund else 0
    if fund:
        score += max(-10, min(10, fscore * 2))
        breakdown["Fundamentals"] = max(-10, min(10, fscore * 2))
        reasons.append(f"Fundamentals: {fund.get('status')} — {fund.get('reason')}")
    else:
        breakdown["Fundamentals"] = 0

    # Hard safety gates prevent an attractive score from creating a bad call.
    gates = []
    if fund and fund.get("status") == "WEAK": gates.append("weak fundamentals")
    if regime == "BEAR": gates.append("bear market regime")
    if ad < 15: gates.append("ADX <15: trend too weak")
    if ext > 3: gates.append("price excessively extended from EMA21")
    if not np.isfinite(a) or a <= 0: gates.append("ATR unavailable")

    stop = price - 1.5 * a
    target1 = price + 2.0 * a
    target2 = price + 3.0 * a
    rr = (target1-price) / (price-stop) if price > stop else 0

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

    confidence = int(max(0, min(100, round((score + 15) / 1.1))))
    return {
        "score": round(score,1), "call":call, "confidence":confidence,
        "price":price, "rsi":r, "adx":ad, "volx":x, "rel20":rs*100,
        "atr":a, "atr_pct":atr_pct, "trend":trend, "regime":regime,
        "stop":stop, "target1":target1, "target2":target2, "rr":rr,
        "breakout":breakout, "extension_atr":ext, "breakdown":breakdown,
        "reasons":reasons, "gates":gates,
    }


# ================================================================
# BACKTEST — NEXT OPEN ENTRY + ATR EXITS
# ================================================================
def backtest(ticker, period="3y", rr_target=2.0, max_hold=15):
    df = get_prices(ticker, period)
    nifty = get_prices(NIFTY, period)
    if df.empty or nifty.empty or len(df) < MIN_BARS or len(nifty) < MIN_BARS:
        return None
    c = df["Close"]; h=df["High"]; l=df["Low"]; o=df["Open"]
    e21,e50,e200=ema(c,21),ema(c,50),ema(c,200)
    rv=rsi(c); av=atr(h,l,c); ax=adx(h,l,c); ml,ms,mh=macd(c)
    volx=df["Volume"]/df["Volume"].rolling(20).mean()
    nclose=nifty["Close"].reindex(df.index).ffill()
    rel20=c.pct_change(20)-nclose.pct_change(20)
    regime_series=[]
    ne=nifty["Close"]
    ne50,ne200=ema(ne,50),ema(ne,200)
    for i in range(len(df)):
        if i < 205: regime_series.append("UNKNOWN")
        elif ne.iloc[min(i,len(ne)-1)] > ne200.iloc[min(i,len(ne)-1)] and ne50.iloc[min(i,len(ne)-1)] > ne200.iloc[min(i,len(ne)-1)]: regime_series.append("BULL")
        elif ne.iloc[min(i,len(ne)-1)] < ne200.iloc[min(i,len(ne)-1)] and ne50.iloc[min(i,len(ne)-1)] < ne200.iloc[min(i,len(ne)-1)]: regime_series.append("BEAR")
        else: regime_series.append("NEUTRAL")
    trades=[]; inpos=False; entry=None
    i=205
    while i < len(df)-1:
        if not inpos:
            price=float(c.iloc[i]); r=float(rv.iloc[i]); ad=float(ax.iloc[i]); vx=float(volx.iloc[i]) if np.isfinite(volx.iloc[i]) else 1
            rel=float(rel20.iloc[i]) if np.isfinite(rel20.iloc[i]) else 0
            trend=0
            trend += 5 if price>e21.iloc[i] else 0
            trend += 5 if e21.iloc[i]>e50.iloc[i] else 0
            trend += 5 if e50.iloc[i]>e200.iloc[i] else 0
            trend += 5 if e21.iloc[i]>e21.iloc[i-5] and e50.iloc[i]>e50.iloc[i-5] and e200.iloc[i]>e200.iloc[i-5] else 0
            momentum=(7 if 52<=r<=68 else 3 if 48<=r<=72 else -3 if r>78 else 0)
            momentum += 4 if mh.iloc[i]>mh.iloc[i-1] else 0
            pts=(10 if regime_series[i]=="BULL" else 0 if regime_series[i]=="NEUTRAL" else -15)
            pts += trend + momentum + (6 if rel>.05 else 3 if rel>0 else -4 if rel<-.05 else 0)
            pts += (5 if vx>=1.5 else 2 if vx>=1.1 else 0)
            pts += 4 if c.iloc[i] > c.iloc[i-21:i].max() else 0
            if pts >= 58 and trend >= 15 and r <= 75 and ad >= 15 and regime_series[i] != "BEAR":
                entry_i=i+1; entry_price=float(o.iloc[entry_i]); a=float(av.iloc[i])
                if not np.isfinite(a) or a<=0: i+=1; continue
                stop=entry_price-1.5*a; target=entry_price+rr_target*1.5*a
                inpos=True; entry=(entry_i,entry_price,stop,target,i)
                i+=1; continue
        else:
            entry_i,ep,stop,target,signal_i=entry
            exit_i=None; reason=None
            for j in range(i,min(len(df),entry_i+max_hold+1)):
                hi=float(h.iloc[j]); lo=float(l.iloc[j]); cl=float(c.iloc[j])
                if lo <= stop and hi >= target:
                    exit_i=j; reason="Both touched — conservative stop-first"; xp=stop; break
                if lo <= stop: exit_i=j; reason="Stop"; xp=stop; break
                if hi >= target: exit_i=j; reason="Target"; xp=target; break
            if exit_i is None:
                j=min(len(df)-1,entry_i+max_hold); exit_i=j; xp=float(c.iloc[j]); reason="Time exit"
            ret=(xp-ep)/ep*100
            trades.append({"Entry":df.index[entry_i].strftime("%Y-%m-%d"),"Exit":df.index[exit_i].strftime("%Y-%m-%d"),"Entry Price":round(ep,2),"Exit Price":round(xp,2),"Return %":round(ret,2),"Reason":reason,"Days":exit_i-entry_i})
            inpos=False; entry=None; i=exit_i+1; continue
        i+=1
    t=pd.DataFrame(trades)
    if t.empty: return {"trades":t,"stats":{"Total Trades":0}}
    wins=t[t["Return %"]>0]; losses=t[t["Return %"]<=0]
    gross_win=wins["Return %"].sum(); gross_loss=abs(losses["Return %"].sum())
    equity=(1+t["Return %"]/100).cumprod()
    dd=(equity/equity.cummax()-1)*100
    wr=len(wins)/len(t)*100
    avgwin=wins["Return %"].mean() if len(wins) else 0
    avgloss=losses["Return %"].mean() if len(losses) else 0
    expectancy=(wr/100)*avgwin+(1-wr/100)*avgloss
    return {"trades":t,"stats":{
        "Total Trades":len(t),"Win Rate %":round(wr,1),"Expectancy %":round(expectancy,2),
        "Profit Factor":round(gross_win/gross_loss,2) if gross_loss else np.inf,
        "Max Drawdown %":round(float(dd.min()),2),"Avg Win %":round(avgwin,2),"Avg Loss %":round(avgloss,2),
        "Net Return %":round((equity.iloc[-1]-1)*100,2),"Avg Hold Days":round(t["Days"].mean(),1),
    }}


# ================================================================
# UI
# ================================================================
st.markdown("# " + APP_TITLE)
st.markdown("### " + APP_SUBTITLE)
st.caption("Research dashboard only • No guaranteed returns • Verify every signal on a live chart and company filings")

with st.sidebar:
    st.header("Scanner")
    group = st.radio("Universe", ["Nifty 50", "Nifty 100", "My Picks + Extras", "Custom"], index=0)
    if group == "Nifty 50": watchlist=NIFTY_50
    elif group == "Nifty 100": watchlist=list(dict.fromkeys(NIFTY_50+NIFTY_NEXT_50))
    elif group == "My Picks + Extras": watchlist=list(dict.fromkeys(YOUR_PICKS+EXTRAS))
    else:
        raw=st.text_area("Tickers", value="COFORGE.NS, PERSISTENT.NS, JINDALSTEL.NS, MCX.NS")
        watchlist=[x.strip().upper() for x in raw.split(",") if x.strip()]
    period=st.selectbox("Price history", ["1y","2y","3y"], index=0)
    if st.button("🔄 Clear cache / Refresh"):
        st.cache_data.clear(); st.rerun()

# Market panel
nifty_df=get_prices(NIFTY, period)
if not nifty_df.empty:
    regime,_,regime_reason=market_regime(nifty_df["Close"])
    nc=float(nifty_df["Close"].iloc[-1]); npct=(nc/float(nifty_df["Close"].iloc[-2])-1)*100
else:
    regime="UNKNOWN"; regime_reason="Nifty unavailable"; nc=np.nan; npct=np.nan

c1,c2,c3,c4=st.columns(4)
c1.metric("Nifty 50", f"{nc:,.0f}" if np.isfinite(nc) else "—", f"{npct:+.2f}%" if np.isfinite(npct) else None)
c2.metric("Market regime", regime)
c3.metric("Signals", "V2")
c4.metric("As of", datetime.now().strftime("%d %b %Y %H:%M"))
st.info("**Regime:** " + regime_reason)

# Main scanner
rows=[]; errors=[]
progress=st.progress(0)
for i,ticker in enumerate(watchlist):
    progress.progress((i+1)/len(watchlist), text=f"Scanning {ticker.replace('.NS','')} ({i+1}/{len(watchlist)})")
    df=get_prices(ticker,period)
    if df.empty or len(df)<MIN_BARS:
        errors.append(ticker); continue
    fund=get_fundamentals(ticker)
    snap=score_snapshot(df,nifty_df,fund)
    rows.append({
        "Ticker":ticker.replace('.NS',''),"Price":round(snap["price"],2),"Call":snap["call"],
        "Score":snap["score"],"Confidence":snap["confidence"],"RSI":round(snap["rsi"],1),
        "ADX":round(snap["adx"],1),"Vol x":round(snap["volx"],2),"RS 20D %":round(snap["rel20"],1),
        "Trend":snap["trend"],"Regime":snap["regime"],"Breakout":"YES" if snap["breakout"] else "—",
        "ATR SL":round(snap["stop"],2),"T1":round(snap["target1"],2),"T2":round(snap["target2"],2),
        "R:R":round(snap["rr"],1),"Fund":fund.get("status","UNKNOWN"),
    })
progress.empty()

if rows:
    out=pd.DataFrame(rows).sort_values(["Call","Score"], ascending=[True,False])
    st.subheader("Signal Summary — V2")
    st.caption("The score is a ranking aid, not a probability. A hard gate can override a high score and produce NO TRADE.")
    st.dataframe(out,use_container_width=True,hide_index=True)

    st.subheader("Top actionable setups")
    actionable=out[out["Call"].isin(["STRONG BUY","BUY"])].sort_values("Score",ascending=False).head(10)
    if actionable.empty:
        st.warning("No actionable BUY setup passed the V2 gates right now. That is intentional — the engine can say NO TRADE.")
    else:
        st.dataframe(actionable[["Ticker","Call","Score","Confidence","Price","ATR SL","T1","T2","R:R","RSI","ADX","Vol x","Breakout","Fund"]],use_container_width=True,hide_index=True)

    st.subheader("Why this signal?")
    selected=st.selectbox("Inspect stock",out["Ticker"].tolist())
    sel=selected+".NS"
    sdf=get_prices(sel,period)
    sf=get_fundamentals(sel)
    if not sdf.empty and len(sdf)>=MIN_BARS:
        ss=score_snapshot(sdf,nifty_df,sf)
        a,b,c=st.columns(3)
        a.metric("Call",ss["call"]); b.metric("Score",ss["score"]); c.metric("Confidence",f"{ss['confidence']}%")
        st.write(f"**Entry reference:** ₹{ss['price']:.2f}  |  **ATR stop:** ₹{ss['stop']:.2f}  |  **Target 1:** ₹{ss['target1']:.2f}  |  **Target 2:** ₹{ss['target2']:.2f}")
        if ss["gates"]: st.error("Blocked by: " + "; ".join(ss["gates"]))
        for k,v in ss["breakdown"].items(): st.write(f"- **{k}:** {v:+.1f}")
        for r in ss["reasons"]: st.write("• "+r)

with st.expander("Backtest V2"):
    bt=st.selectbox("Stock",watchlist,key="bt_stock")
    btperiod=st.selectbox("Backtest period",["1y","2y","3y"],index=2,key="bt_period")
    rr=st.selectbox("Target",[1.5,2.0,3.0],index=1)
    hold=st.selectbox("Max holding days",[10,15,20],index=1)
    if st.button("Run V2 Backtest",type="primary"):
        with st.spinner("Running next-open / ATR backtest..."):
            br=backtest(bt,btperiod,rr,hold)
        if br is None:
            st.error("Not enough data for this backtest.")
        else:
            st.json(br["stats"])
            if not br["trades"].empty: st.dataframe(br["trades"],use_container_width=True,hide_index=True)

if errors:
    st.warning(f"{len(errors)} symbols could not be evaluated because price history was unavailable or too short.")

st.divider()
st.caption("My Trading Partner V2 • Yahoo Finance data • Daily swing research • No order execution • No guaranteed accuracy or returns")
