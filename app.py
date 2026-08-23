"""
Personal Swing Trading Dashboard (v4 -- with backtest mode)
---------------------------------------------------------------------------
Combines price data, RSI, EMA, MACD, ADX, volume confirmation, Nifty 50
relative strength, and a fundamentals red-flag filter into one screen --
the kind of thing you'd normally flip between Moneycontrol, TradingView,
Sensibull, and Tickertape for. Now also includes a Backtest tab that runs
the exact same rules against historical data so you can see real win
rate and average return instead of guessing whether a filter helps.

Data source: Yahoo Finance (free, ~15-20 min delayed). Good enough for
daily-timeframe swing trading. NOT for intraday scalping or live execution.

HOW TO RUN (on your laptop):
  1. Install Python 3.9+ if you don't have it: https://www.python.org/downloads/
  2. Open a terminal in this folder and run:
       pip install -r requirements.txt
  3. Run:
       streamlit run app.py
  4. It opens automatically in your browser at http://localhost:8501

This does NOT place any trades. It only generates signals for you to
review manually -- which also means it needs no broker API, no SEBI
algo registration, and no risk of a bug firing a real order.

WHAT'S NEW IN v4:
  - Backtest tab: replays the exact same RSI/EMA/MACD/ADX/volume rules
    against 1-2 years of history for any watchlist stock. Simulates
    entering on a BUY signal, exiting on your stop-loss/target/max-hold
    rules (all editable), and reports win rate, average return, and a
    full trade log. This is the honest way to see whether the current
    rules actually work, instead of adding more filters on faith.
  - IMPORTANT CAVEAT: backtests use daily CLOSING prices only (not
    intraday highs/lows) to check stop-loss/target hits, which is a
    simplification -- real intraday moves could trigger a stop or
    target the close-only check misses. Treat backtest numbers as
    directional, not exact. A good historical win rate is also not a
    guarantee of future performance -- markets change.
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime

st.set_page_config(page_title="Swing Trading Dashboard", layout="wide")

# ---------------------------------------------------------------------
# YOUR WATCHLIST -- edit this list to add/remove stocks.
# Use the NSE ticker with ".NS" suffix (e.g. Reliance -> RELIANCE.NS)
# ---------------------------------------------------------------------
DEFAULT_WATCHLIST = [
    "COFORGE.NS",
    "PERSISTENT.NS",
    "MPHASIS.NS",
    "MODISONLTD.NS",
    "PREMIERPOL.NS",
    "RPTECH.NS",        # Rashi Peripherals
    "BORORENEW.NS",     # Borosil Renewables
    "JARO.NS",          # Jaro Institute
    "TPLPLASTEH.NS",    # TPL Plastech
]

NIFTY_TICKER = "^NSEI"

# ---------------------------------------------------------------------
# INDICATOR CALCULATIONS
# ---------------------------------------------------------------------

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def calc_macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    atr = tr.ewm(alpha=1 / period, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(alpha=1 / period, min_periods=period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(alpha=1 / period, min_periods=period).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=1 / period, min_periods=period).mean()
    return adx


# ---------------------------------------------------------------------
# FUNDAMENTALS RED-FLAG FILTER
# ---------------------------------------------------------------------

def fundamentals_check(ticker: str):
    flags = []
    score = 0
    data = {}

    try:
        info = yf.Ticker(ticker).info
    except Exception:
        return {"status": "UNKNOWN", "flags": ["Could not fetch fundamentals"], "data": {}}

    market_cap = info.get("marketCap")
    pe = info.get("trailingPE")
    roe = info.get("returnOnEquity")
    debt_to_equity = info.get("debtToEquity")
    profit_margin = info.get("profitMargins")

    data["Market Cap (Cr)"] = round(market_cap / 1e7, 1) if market_cap else "N/A"
    data["PE"] = round(pe, 1) if pe else "N/A"
    data["ROE %"] = round(roe * 100, 1) if roe is not None else "N/A"
    data["Debt/Equity"] = round(debt_to_equity, 1) if debt_to_equity is not None else "N/A"
    data["Profit Margin %"] = round(profit_margin * 100, 1) if profit_margin is not None else "N/A"

    if market_cap and market_cap < 3_000_000_000:
        flags.append(f"Very small market cap (₹{market_cap/1e7:.0f} Cr) -- low liquidity, easy to move on thin volume")
        score -= 2

    if pe is not None and pe < 0:
        flags.append(f"Negative PE ({pe:.1f}) -- company is currently loss-making")
        score -= 2
    elif pe is not None and pe > 100:
        flags.append(f"Very high PE ({pe:.1f}) -- priced for extreme future growth")
        score -= 1

    if roe is not None and roe < 0.05:
        flags.append(f"Weak ROE ({roe*100:.1f}%) -- business generating little return on shareholder capital")
        score -= 2

    if debt_to_equity is not None and debt_to_equity > 150:
        flags.append(f"High debt/equity ({debt_to_equity:.0f}) -- leveraged balance sheet")
        score -= 1

    if profit_margin is not None and profit_margin < 0:
        flags.append(f"Negative profit margin ({profit_margin*100:.1f}%) -- losing money on operations")
        score -= 2

    if not flags:
        flags.append("No major red flags in basic fundamentals check")
        score = 1

    if score <= -3:
        status = "AVOID — weak fundamentals"
    elif score < 0:
        status = "CAUTION — some weak spots"
    else:
        status = "OK — basic checks passed"

    return {"status": status, "flags": flags, "data": data}


# ---------------------------------------------------------------------
# SIGNAL LOGIC
# ---------------------------------------------------------------------

def generate_signal(rsi, ema9, ema21, ema50, macd, macd_signal, price,
                     adx, vol_ratio, rel_strength):
    reasons = []
    score = 0

    if rsi < 30:
        reasons.append(f"RSI {rsi:.1f} is oversold — bounce potential")
        score += 1
    elif rsi > 70:
        reasons.append(f"RSI {rsi:.1f} is overbought — pullback risk")
        score -= 1
    elif 40 <= rsi <= 60:
        reasons.append(f"RSI {rsi:.1f} neutral, no strong momentum signal")
    else:
        reasons.append(f"RSI {rsi:.1f}")

    if price > ema9 > ema21 > ema50:
        reasons.append("Price above all EMAs, strong uptrend structure")
        score += 2
    elif price < ema9 < ema21 < ema50:
        reasons.append("Price below all EMAs, strong downtrend structure")
        score -= 2
    elif ema9 > ema21:
        reasons.append("Short-term EMA above medium-term — mild bullish bias")
        score += 1
    else:
        reasons.append("Short-term EMA below medium-term — mild bearish bias")
        score -= 1

    if macd > macd_signal and macd > 0:
        reasons.append("MACD above signal line and above zero — bullish momentum")
        score += 1
    elif macd < macd_signal and macd < 0:
        reasons.append("MACD below signal line and below zero — bearish momentum")
        score -= 1
    elif macd > macd_signal:
        reasons.append("MACD just crossed above signal line — early bullish cue")
        score += 0.5
    else:
        reasons.append("MACD below signal line — momentum weakening")
        score -= 0.5

    if adx is not None and not np.isnan(adx):
        if adx < 20:
            reasons.append(f"ADX {adx:.1f} — weak/no trend, signals here are less reliable")
            score *= 0.5
        elif adx > 25:
            reasons.append(f"ADX {adx:.1f} — real trend in place, strengthens the read above")
            score += 0.5 if score > 0 else (-0.5 if score < 0 else 0)
        else:
            reasons.append(f"ADX {adx:.1f} — moderate trend strength")

    if vol_ratio is not None and not np.isnan(vol_ratio):
        if vol_ratio >= 1.5:
            reasons.append(f"Volume {vol_ratio:.1f}x the 20-day average — strong participation")
            score += 0.5 if score > 0 else (-0.5 if score < 0 else 0)
        elif vol_ratio < 0.7:
            reasons.append(f"Volume only {vol_ratio:.1f}x the 20-day average — thin, be cautious")
            score *= 0.7

    if rel_strength is not None and not np.isnan(rel_strength):
        if rel_strength > 0.5:
            reasons.append(f"Outperforming Nifty 50 by {rel_strength:+.2f}% today")
            score += 0.5
        elif rel_strength < -0.5:
            reasons.append(f"Underperforming Nifty 50 by {rel_strength:+.2f}% today")
            score -= 0.5
        else:
            reasons.append("Moving roughly in line with Nifty 50 today")

    if score >= 2.5:
        call = "BUY"
    elif score <= -2.5:
        call = "SELL"
    else:
        call = "HOLD / WATCH"

    return call, round(score, 2), reasons


# ---------------------------------------------------------------------
# DATA FETCH
# ---------------------------------------------------------------------

@st.cache_data(ttl=900)
def fetch_price_data(ticker: str, period="6mo", interval="1d"):
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    return df


@st.cache_data(ttl=3600)
def fetch_fundamentals(ticker: str):
    return fundamentals_check(ticker)


def flatten_series(s):
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return s


# ---------------------------------------------------------------------
# BACKTEST ENGINE
# Replays the same generate_signal() rules day-by-day over history.
# Uses closing prices only for entry/exit checks (see caveat in the
# module docstring) -- a simplification, treat results as directional.
# ---------------------------------------------------------------------

def run_backtest(ticker, nifty_close_pct, sl_pct=1.5, target_pct=3.0,
                  max_hold_days=10, period="2y"):
    df = fetch_price_data(ticker, period=period)
    if df.empty or len(df) < 80:
        return None, "Not enough historical data for this stock."

    close = flatten_series(df["Close"]).dropna()
    high = flatten_series(df["High"]).reindex(close.index)
    low = flatten_series(df["Low"]).reindex(close.index)
    volume = flatten_series(df["Volume"]).reindex(close.index)

    if len(close) < 80:
        return None, "Not enough valid historical data after cleaning."

    rsi = calc_rsi(close)
    ema9 = calc_ema(close, 9)
    ema21 = calc_ema(close, 21)
    ema50 = calc_ema(close, 50)
    macd_line, signal_line, _ = calc_macd(close)
    adx = calc_adx(high, low, close)
    avg_vol_20 = volume.rolling(20).mean()
    vol_ratio_series = volume / avg_vol_20

    stock_pct_change = close.pct_change() * 100
    # align Nifty % change series to this stock's dates
    rel_strength_series = stock_pct_change - nifty_close_pct.reindex(close.index)

    trades = []
    in_position = False
    entry_idx = None
    entry_price = None
    sl_price = None
    target_price = None

    n = len(close)
    start = 60  # need enough history for EMA50/ADX to be meaningful

    for i in range(start, n):
        if not in_position:
            adx_i = adx.iloc[i]
            vol_ratio_i = vol_ratio_series.iloc[i]
            rel_strength_i = rel_strength_series.iloc[i]

            call, score, _ = generate_signal(
                rsi.iloc[i], ema9.iloc[i], ema21.iloc[i], ema50.iloc[i],
                macd_line.iloc[i], signal_line.iloc[i], close.iloc[i],
                adx_i, vol_ratio_i, rel_strength_i
            )
            if call == "BUY":
                in_position = True
                entry_idx = i
                entry_price = close.iloc[i]
                sl_price = entry_price * (1 - sl_pct / 100)
                target_price = entry_price * (1 + target_pct / 100)
        else:
            price_today = close.iloc[i]
            days_held = i - entry_idx
            exit_reason = None

            if price_today <= sl_price:
                exit_reason = "Stop-loss hit"
            elif price_today >= target_price:
                exit_reason = "Target hit"
            elif days_held >= max_hold_days:
                exit_reason = "Max hold reached"

            if exit_reason:
                ret_pct = ((price_today - entry_price) / entry_price) * 100
                trades.append(
                    {
                        "Entry Date": close.index[entry_idx].strftime("%Y-%m-%d"),
                        "Exit Date": close.index[i].strftime("%Y-%m-%d"),
                        "Entry Price": round(float(entry_price), 2),
                        "Exit Price": round(float(price_today), 2),
                        "Days Held": days_held,
                        "Return %": round(float(ret_pct), 2),
                        "Result": "Win" if ret_pct > 0 else "Loss",
                        "Exit Reason": exit_reason,
                    }
                )
                in_position = False

    if not trades:
        return {"trades": pd.DataFrame(), "stats": None}, None

    trades_df = pd.DataFrame(trades)
    wins = trades_df[trades_df["Return %"] > 0]
    losses = trades_df[trades_df["Return %"] <= 0]

    stats = {
        "Total Trades": len(trades_df),
        "Win Rate %": round(len(wins) / len(trades_df) * 100, 1),
        "Avg Return per Trade %": round(trades_df["Return %"].mean(), 2),
        "Avg Win %": round(wins["Return %"].mean(), 2) if len(wins) else 0.0,
        "Avg Loss %": round(losses["Return %"].mean(), 2) if len(losses) else 0.0,
        "Best Trade %": round(trades_df["Return %"].max(), 2),
        "Worst Trade %": round(trades_df["Return %"].min(), 2),
    }
    win_rate_frac = stats["Win Rate %"] / 100
    stats["Expectancy % per Trade"] = round(
        win_rate_frac * stats["Avg Win %"] + (1 - win_rate_frac) * stats["Avg Loss %"], 2
    )

    return {"trades": trades_df, "stats": stats}, None


# ---------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------

st.title("📊 Swing Trading Dashboard")

with st.sidebar:
    st.header("Watchlist")
    watchlist_input = st.text_area(
        "NSE tickers (comma-separated, with .NS suffix)",
        value=", ".join(DEFAULT_WATCHLIST),
        height=140,
    )
    watchlist = [t.strip().upper() for t in watchlist_input.split(",") if t.strip()]
    st.caption("Example: RELIANCE.NS, TCS.NS, INFY.NS")
    st.divider()
    st.markdown(
        "**Disclaimer:** This tool generates rule-based signals from "
        "public price and fundamentals data for your own review. It is "
        "not financial advice, does not place trades, and should not be "
        "the sole basis for any decision. A stock passing these checks "
        "is not a recommendation — it just means it cleared basic filters. "
        "Backtest results use daily closing prices only, are a simplification "
        "of real intraday execution, and past performance never guarantees "
        "future results."
    )

tab_live, tab_backtest = st.tabs(["📈 Live Signals", "🔄 Backtest"])

# Fetch Nifty 50 once, used by both tabs
nifty_df = fetch_price_data(NIFTY_TICKER, period="2y")
nifty_pct_change_today = None
nifty_close_pct_series = pd.Series(dtype=float)
if not nifty_df.empty and len(nifty_df) >= 2:
    nifty_close = flatten_series(nifty_df["Close"]).dropna()
    nifty_close_pct_series = nifty_close.pct_change() * 100
    if len(nifty_close) >= 2:
        nifty_pct_change_today = ((nifty_close.iloc[-1] - nifty_close.iloc[-2]) / nifty_close.iloc[-2]) * 100

# =======================================================================
# TAB 1: LIVE SIGNALS
# =======================================================================
with tab_live:
    st.caption(
        "Fundamentals filter + RSI/EMA/MACD/ADX/Volume/Nifty-relative-strength "
        "in one place. Data is delayed (Yahoo Finance) — treat as directional, "
        f"not tick-precise. Last refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    if nifty_pct_change_today is not None:
        st.metric("Nifty 50 today", f"{nifty_pct_change_today:+.2f}%")

    rows = []
    errors = []

    for ticker in watchlist:
        try:
            fund = fetch_fundamentals(ticker)

            df = fetch_price_data(ticker)
            if df.empty or len(df) < 60:
                errors.append(f"{ticker}: not enough price data returned")
                continue

            close = flatten_series(df["Close"]).dropna()
            high = flatten_series(df["High"]).reindex(close.index)
            low = flatten_series(df["Low"]).reindex(close.index)
            volume = flatten_series(df["Volume"]).reindex(close.index)

            if len(close) < 60:
                errors.append(f"{ticker}: not enough valid price data after cleaning")
                continue

            rsi = calc_rsi(close).iloc[-1]
            ema9 = calc_ema(close, 9).iloc[-1]
            ema21 = calc_ema(close, 21).iloc[-1]
            ema50 = calc_ema(close, 50).iloc[-1]
            macd_line, signal_line, hist = calc_macd(close)
            macd_val = macd_line.iloc[-1]
            macd_sig_val = signal_line.iloc[-1]
            adx_val = calc_adx(high, low, close).iloc[-1]

            price = close.iloc[-1]
            prev_close = close.iloc[-2]
            pct_change = ((price - prev_close) / prev_close) * 100

            avg_vol_20 = volume.rolling(20).mean().iloc[-1]
            today_vol = volume.iloc[-1]
            vol_ratio = (today_vol / avg_vol_20) if avg_vol_20 and avg_vol_20 > 0 else np.nan

            rel_strength = (pct_change - nifty_pct_change_today) if nifty_pct_change_today is not None else np.nan

            if fund["status"].startswith("AVOID"):
                call, score, reasons = "AVOID", -99, ["Fundamentals filter blocked this — see details below"]
            else:
                call, score, reasons = generate_signal(
                    rsi, ema9, ema21, ema50, macd_val, macd_sig_val, price,
                    adx_val, vol_ratio, rel_strength
                )

            rows.append(
                {
                    "Ticker": ticker.replace(".NS", ""),
                    "Price": round(float(price), 2),
                    "% Chg": round(float(pct_change), 2),
                    "Fundamentals": fund["status"],
                    "RSI(14)": round(float(rsi), 1),
                    "ADX": round(float(adx_val), 1) if not np.isnan(adx_val) else None,
                    "Vol x Avg": round(float(vol_ratio), 2) if not np.isnan(vol_ratio) else None,
                    "vs Nifty": round(float(rel_strength), 2) if not np.isnan(rel_strength) else None,
                    "MACD": round(float(macd_val), 2),
                    "Call": call,
                    "Score": score,
                    "Why": " | ".join(reasons),
                    "Fund Flags": " | ".join(fund["flags"]),
                    "Fund Data": fund["data"],
                }
            )
        except Exception as e:
            errors.append(f"{ticker}: {e}")

    if rows:
        result_df = pd.DataFrame(rows).sort_values("Score", ascending=False)

        def color_call(val):
            if val == "BUY":
                return "background-color: #1e5c2f; color: white;"
            elif val in ("SELL", "AVOID"):
                return "background-color: #6b1e1e; color: white;"
            return "background-color: #4a4a1e; color: white;"

        def color_fund(val):
            if val.startswith("AVOID"):
                return "background-color: #6b1e1e; color: white;"
            elif val.startswith("CAUTION"):
                return "background-color: #4a4a1e; color: white;"
            return "background-color: #1e5c2f; color: white;"

        st.subheader("Signal Summary")
        display_cols = ["Ticker", "Price", "% Chg", "Fundamentals", "RSI(14)", "ADX", "Vol x Avg", "vs Nifty", "MACD", "Call"]
        st.dataframe(
            result_df[display_cols]
            .style.map(color_call, subset=["Call"])
            .map(color_fund, subset=["Fundamentals"]),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Full Breakdown")
        for _, row in result_df.iterrows():
            with st.expander(f"{row['Ticker']} — {row['Call']} | {row['Fundamentals']}"):
                st.write(f"**Price:** ₹{row['Price']} ({row['% Chg']:+.2f}% today)")
                st.markdown("**Fundamentals check:**")
                for k, v in row["Fund Data"].items():
                    st.write(f"- {k}: {v}")
                for flag in row["Fund Flags"].split(" | "):
                    st.write(f"⚠️ {flag}")
                st.markdown("**Technical read:**")
                for reason in row["Why"].split(" | "):
                    st.write(f"- {reason}")

    if errors:
        st.warning("Some tickers had issues:\n" + "\n".join(errors))

# =======================================================================
# TAB 2: BACKTEST
# =======================================================================
with tab_backtest:
    st.caption(
        "Replays the exact same RSI/EMA/MACD/ADX/Volume/Nifty-relative-strength "
        "rules against historical data. Shows you the real win rate and average "
        "return of the current strategy, instead of guessing."
    )

    col1, col2 = st.columns(2)
    with col1:
        bt_ticker = st.selectbox("Stock to backtest", options=watchlist)
        bt_period = st.selectbox("History length", options=["1y", "2y", "3y"], index=1)
    with col2:
        bt_sl = st.number_input("Stop-loss %", min_value=0.5, max_value=10.0, value=1.5, step=0.5)
        bt_target = st.number_input("Target %", min_value=0.5, max_value=20.0, value=3.0, step=0.5)
        bt_max_hold = st.number_input("Max hold (trading days)", min_value=1, max_value=60, value=10, step=1)

    if st.button("Run Backtest", type="primary"):
        with st.spinner(f"Replaying {bt_ticker} over {bt_period}..."):
            result, err = run_backtest(
                bt_ticker, nifty_close_pct_series,
                sl_pct=bt_sl, target_pct=bt_target, max_hold_days=bt_max_hold,
                period=bt_period,
            )

        if err:
            st.error(err)
        elif result["stats"] is None:
            st.info("No BUY signals triggered for this stock over this period with the current rules — try a longer history or a different stock.")
        else:
            stats = result["stats"]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total Trades", stats["Total Trades"])
            m2.metric("Win Rate", f"{stats['Win Rate %']}%")
            m3.metric("Avg Return / Trade", f"{stats['Avg Return per Trade %']}%")
            m4.metric("Expectancy / Trade", f"{stats['Expectancy % per Trade']}%")

            m5, m6, m7, m8 = st.columns(4)
            m5.metric("Avg Win", f"{stats['Avg Win %']}%")
            m6.metric("Avg Loss", f"{stats['Avg Loss %']}%")
            m7.metric("Best Trade", f"{stats['Best Trade %']}%")
            m8.metric("Worst Trade", f"{stats['Worst Trade %']}%")

            st.subheader("Trade Log")
            st.dataframe(result["trades"], use_container_width=True, hide_index=True)

            st.caption(
                "Expectancy is the average return you'd expect per trade if this "
                "exact pattern repeats. Positive expectancy with a reasonable "
                "number of trades (20+) is a decent sign; a handful of trades "
                "isn't enough to draw a real conclusion either way."
            )

st.divider()
st.caption(
    "This dashboard combines a fundamentals health check with RSI/EMA/MACD, "
    "ADX, volume confirmation, and Nifty 50 relative strength for live "
    "signals, plus a backtest mode to check those rules against history. "
    "It does not include options data (Sensibull's specialty) or order "
    "execution. Verify everything against a live chart and your own "
    "reading of company filings before acting."
)
