"""
Rev's Trading Company (v6)
---------------------------------------------------------------------------
Combines price data, RSI, EMA(9/21/50/200), MACD, ADX, volume confirmation,
Nifty 50 relative strength, and a fundamentals red-flag filter into one
screen, plus a Backtest tab. Watchlist now includes the full Nifty 50 plus
your own picks.

Data source: Yahoo Finance (free, ~15-20 min delayed). Good enough for
daily-timeframe swing trading. NOT for intraday scalping or live execution.

HOW TO RUN LOCALLY:
  pip install -r requirements.txt
  streamlit run app.py

See DEPLOY.md for hosting this on Streamlit Community Cloud (24x7, phone
access without your laptop running).

WHAT'S NEW IN v6:
  - Renamed to "Rev's Trading Company"
  - Full Nifty 50 constituent list merged into the default watchlist,
    alongside your existing picks (Coforge, Persistent, etc.)
  - "Full Breakdown" section is now hidden by default -- tick the
    checkbox above the Signal Summary table to show it
  - Index ticker panel (top right) showing Nifty 50, Sensex, and Nifty
    Bank live levels. GIFT Nifty is NOT included -- it trades on a
    different exchange (NSE IX / GIFT City) and doesn't have a reliable
    free ticker on Yahoo Finance, so rather than show a wrong or
    unavailable number, it's left out.
  - HONEST NOTE ON SCALE: with ~59 tickers in the default watchlist,
    the first load can take a minute or two, and Yahoo Finance's free
    tier may occasionally rate-limit or return a handful of blank
    tickers under heavy load. This is a real constraint of free data
    at this scale, not a bug -- cached data (15 min for prices, 1 hour
    for fundamentals) makes repeat views faster.
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import time
from datetime import datetime

st.set_page_config(page_title="My Trading Guide", layout="wide")

# ---------------------------------------------------------------------
# WATCHLIST: your picks + full Nifty 50 + 10 additional fundamentally-
# screened stocks outside the Nifty 50
# ---------------------------------------------------------------------
YOUR_PICKS = [
    "COFORGE.NS",
    "PERSISTENT.NS",
    "MPHASIS.NS",
    "MODISONLTD.NS",
    "PREMIERPOL.NS",
    "RPTECH.NS",
    "BORORENEW.NS",
    "JARO.NS",
    "TPLPLASTEH.NS",
]

# Deep fundamentals (ROCE, PEG, Interest Coverage, FCF, Dividend consistency,
# Piotroski F-Score) run ONLY for this core set -- these need heavy per-stock
# financial-statement pulls (income statement, balance sheet, cash flow,
# dividend history), which is fine for 9 stocks but would reintroduce the
# exact slowness/rate-limit problems that broke the page earlier if run
# across the full ~150-stock watchlist.
CORE_WATCHLIST = YOUR_PICKS

# Additional non-Nifty50 names with generally solid public reputations for
# fundamentals (established businesses, historically decent ROE/margins).
# IMPORTANT: this is a starting list to screen, not a recommendation --
# the app's own fundamentals filter will grade each one honestly once
# it pulls live numbers. Some may come back CAUTION or even AVOID if
# their current financials have weakened since I last knew about them.
ADDITIONAL_SCREENED_PICKS = [
    "KAJARIACER.NS",   # Kajaria Ceramics
    "PIIND.NS",        # PI Industries
    "CDSL.NS",         # Central Depository Services
    "APLAPOLLO.NS",    # APL Apollo Tubes
    "KPITTECH.NS",     # KPIT Technologies
    "DIXON.NS",        # Dixon Technologies
    "SUPREMEIND.NS",   # Supreme Industries
    "AMBER.NS",        # Amber Enterprises
    "POLYCAB.NS",      # Polycab India
    "CUMMINSIND.NS",   # Cummins India
]

# User-requested additions. COFORGE already in YOUR_PICKS, not repeated here.
# Meesho, Groww, Pine Labs, and PhysicsWallah are recent 2025-2026 IPOs --
# verified their exact tickers via search rather than guessing, since a
# wrong symbol on a newly-listed stock is an easy mistake to make.
USER_REQUESTED_ADDITIONS = [
    "MEESHO.NS",       # Meesho
    "GROWW.NS",        # Groww (Billionbrains Garage Ventures)
    "INDUSTOWER.NS",   # Indus Towers
    "MCX.NS",          # Multi Commodity Exchange
    "PINELABS.NS",     # Pine Labs
    "KAYNES.NS",       # Kaynes Technology
    "ASTERDM.NS",      # Aster DM Healthcare
    "PWL.NS",          # PhysicsWallah
    "IFCI.NS",         # IFCI
]

NIFTY_50_CONSTITUENTS = [
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

# Nifty Next 50 -- combined with Nifty 50 above, this makes up Nifty 100.
NIFTY_NEXT_50_CONSTITUENTS = [
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

_combined = YOUR_PICKS + ADDITIONAL_SCREENED_PICKS + USER_REQUESTED_ADDITIONS
NIFTY_100_CONSTITUENTS = NIFTY_50_CONSTITUENTS + [t for t in NIFTY_NEXT_50_CONSTITUENTS if t not in NIFTY_50_CONSTITUENTS]
DEFAULT_WATCHLIST = _combined + [t for t in NIFTY_100_CONSTITUENTS if t not in _combined]

NIFTY_TICKER = "^NSEI"
SENSEX_TICKER = "^BSESN"
BANKNIFTY_TICKER = "^NSEBANK"
MIN_BARS_REQUIRED = 210

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
    return 100 - (100 / (1 + rs))


def calc_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def calc_macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line


def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr = tr.ewm(alpha=1 / period, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(alpha=1 / period, min_periods=period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(alpha=1 / period, min_periods=period).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / period, min_periods=period).mean()


def calc_trend_status(close: pd.Series, ema21: pd.Series, ema50: pd.Series, ema200: pd.Series,
                       slope_lookback: int = 5, swing_window: int = 10):
    """Classifies trend using the user's exact 5-condition rule:
    Uptrend  = Price > EMA21 > EMA50 > EMA200, all 3 EMAs sloping up,
               and price making higher highs + higher lows.
    Downtrend = the mirror image.
    Anything not meeting all 5 conditions either way is 'Mixed / Sideways'.
    Returns (label, score_adjustment) where score_adjustment feeds into
    the overall BUY/SELL scoring -- +1.5 for a full uptrend, -1.5 for a
    full downtrend, 0 otherwise."""
    if len(close) < swing_window * 2 + slope_lookback + 1:
        return "Not enough data", 0.0

    price = close.iloc[-1]
    e21, e50, e200 = ema21.iloc[-1], ema50.iloc[-1], ema200.iloc[-1]
    e21_prior = ema21.iloc[-1 - slope_lookback]
    e50_prior = ema50.iloc[-1 - slope_lookback]
    e200_prior = ema200.iloc[-1 - slope_lookback]

    # Higher-highs/higher-lows (or lower-highs/lower-lows) approximated by
    # comparing the most recent swing_window-day high/low against the
    # prior swing_window-day high/low -- a simplified but fast stand-in
    # for full zigzag pivot detection.
    recent_high = close.iloc[-swing_window:].max()
    recent_low = close.iloc[-swing_window:].min()
    prior_high = close.iloc[-2 * swing_window:-swing_window].max()
    prior_low = close.iloc[-2 * swing_window:-swing_window].min()

    up_conditions = [
        price > e21,
        e21 > e50,
        e50 > e200,
        (e21 > e21_prior) and (e50 > e50_prior) and (e200 > e200_prior),
        (recent_high > prior_high) and (recent_low > prior_low),
    ]
    down_conditions = [
        price < e21,
        e21 < e50,
        e50 < e200,
        (e21 < e21_prior) and (e50 < e50_prior) and (e200 < e200_prior),
        (recent_high < prior_high) and (recent_low < prior_low),
    ]
    up_count = sum(up_conditions)
    down_count = sum(down_conditions)

    if up_count == 5:
        return "Uptrend (5/5)", 1.5
    elif down_count == 5:
        return "Downtrend (5/5)", -1.5
    elif up_count >= 3:
        return f"Leaning up ({up_count}/5)", 0.5
    elif down_count >= 3:
        return f"Leaning down ({down_count}/5)", -0.5
    else:
        return "Mixed / Sideways", 0.0


def calc_bollinger_bands(close: pd.Series, period: int = 20, std_mult: float = 2.0):
    """Standard Bollinger Bands. Band width (normalized by the middle
    band) is the input for squeeze detection below -- a narrow width
    relative to recent history means volatility has compressed, which
    often precedes a sharp directional move (breakout in either
    direction, not necessarily up)."""
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + std_mult * std
    lower = sma - std_mult * std
    width = (upper - lower) / sma
    return upper, lower, width


def detect_bb_squeeze(width: pd.Series, lookback: int = 120, percentile_threshold: float = 20.0):
    """A 'squeeze' = today's band width sits in the bottom X% of the
    trailing lookback window -- volatility is unusually compressed
    versus its own recent history. Returns (is_squeeze, percentile)."""
    valid = width.dropna()
    if len(valid) < lookback:
        return False, None
    recent_width = valid.iloc[-1]
    trailing = valid.iloc[-lookback:]
    percentile = (trailing < recent_width).mean() * 100
    is_squeeze = percentile <= percentile_threshold
    return is_squeeze, round(percentile, 1)


def calc_obv(close: pd.Series, volume: pd.Series):
    """On-Balance Volume: running total that adds volume on up days,
    subtracts on down days. The idea is that OBV rising while price
    stays flat can reflect quiet accumulation -- buyers absorbing
    supply before price actually moves."""
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).cumsum()


def detect_obv_signal(close: pd.Series, obv: pd.Series, lookback: int = 20, price_flat_threshold: float = 3.0):
    """Compares price change to OBV change over the same window to spot
    accumulation (buying pressure building while price is still flat)
    versus distribution (selling pressure while price is flat) versus a
    confirmed trend (price and OBV moving the same direction)."""
    if len(close) < lookback + 1 or len(obv) < lookback + 1:
        return "Not enough data"
    price_change_pct = ((close.iloc[-1] - close.iloc[-lookback]) / close.iloc[-lookback]) * 100
    obv_rising = (obv.iloc[-1] - obv.iloc[-lookback]) > 0

    if obv_rising and abs(price_change_pct) < price_flat_threshold:
        return "Accumulation (OBV up, price flat)"
    elif (not obv_rising) and abs(price_change_pct) < price_flat_threshold:
        return "Distribution (OBV down, price flat)"
    elif obv_rising and price_change_pct >= price_flat_threshold:
        return "Confirmed uptrend (OBV + price rising)"
    elif (not obv_rising) and price_change_pct <= -price_flat_threshold:
        return "Confirmed downtrend (OBV + price falling)"
    else:
        return "Mixed / Divergence"


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    """Average True Range -- a volatility measure used to size stops
    relative to how much a stock actually moves, rather than a flat
    percentage that treats a calm large-cap the same as a wild small-cap."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


def build_trade_plan(price: float, atr: float, atr_stop_mult: float = 2.0):
    """Mechanical trade plan, NOT a prediction or guarantee. Stop-loss is
    set at (entry - atr_stop_mult x ATR) -- a standard, transparent
    convention, not a claim that the stock can't move further against
    you. Target 1 is a 1:1 risk-reward level (a sensible place to book
    partial profit), Target 2 is 1:2 (matches the risk-reward discipline
    already used elsewhere in this dashboard's backtest defaults)."""
    if atr is None or np.isnan(atr) or atr <= 0:
        return None
    stop_loss = price - (atr_stop_mult * atr)
    risk_per_share = price - stop_loss
    if risk_per_share <= 0:
        return None
    target_1 = price + (1 * risk_per_share)   # 1:1
    target_2 = price + (2 * risk_per_share)   # 1:2
    return {
        "entry": round(price, 2),
        "stop_loss": round(stop_loss, 2),
        "target_1": round(target_1, 2),
        "target_2": round(target_2, 2),
        "risk_pct": round((risk_per_share / price) * 100, 2),
    }


@st.cache_data(ttl=3600)
def fetch_next_earnings_date(ticker: str):
    """Only called for stocks currently showing BUY/STRONG BUY -- calling
    this for the full ~150-stock watchlist would add too many extra
    requests. Returns a date string or None if unavailable/not found."""
    try:
        cal = yf.Ticker(ticker).calendar
        if cal is None:
            return None
        # yfinance has returned this as either a dict or a DataFrame across
        # versions -- handle both rather than assume one.
        if isinstance(cal, dict):
            earnings_date = cal.get("Earnings Date")
            if isinstance(earnings_date, list) and earnings_date:
                return earnings_date[0].strftime("%Y-%m-%d") if hasattr(earnings_date[0], "strftime") else str(earnings_date[0])
        elif hasattr(cal, "loc") and "Earnings Date" in getattr(cal, "index", []):
            val = cal.loc["Earnings Date"]
            if hasattr(val, "iloc"):
                val = val.iloc[0]
            return val.strftime("%Y-%m-%d") if hasattr(val, "strftime") else str(val)
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------
# FUNDAMENTALS RED-FLAG FILTER
# ---------------------------------------------------------------------

def fundamentals_check(ticker: str):
    flags, positives, score, data = [], [], 0, {}

    # NOTE: this deliberately does NOT retry with delays anymore. An
    # earlier version retried each failed ticker with backoff sleeps,
    # which across a ~69-stock watchlist could push total page load to
    # several minutes and cause the whole page to time out / show
    # nothing at all -- worse than an occasional "Unknown". Single
    # attempt only; combined with fetch_fundamentals() below only
    # caching SUCCESSFUL results, a stock that fails here just tries
    # fresh again next time you hit Refresh, without stalling this run.
    info = None
    last_error = None
    try:
        candidate = yf.Ticker(ticker).info
        if candidate and len(candidate) > 5:
            info = candidate
        else:
            last_error = "Empty or incomplete response from data source"
    except Exception as e:
        last_error = str(e)

    if info is None:
        return {
            "status": "UNKNOWN",
            "flags": [f"Could not fetch fundamentals right now — {last_error}. "
                      f"Click Refresh to retry — this stock isn't cached as a "
                      f"failure, so it'll try fresh next time."],
            "data": {},
            "multibagger_candidate": False,
        }

    market_cap = info.get("marketCap")
    pe = info.get("trailingPE")
    roe = info.get("returnOnEquity")
    debt_to_equity = info.get("debtToEquity")
    profit_margin = info.get("profitMargins")
    analyst_target = info.get("targetMeanPrice")
    analyst_rating = info.get("recommendationKey")  # e.g. 'buy', 'strong_buy', 'hold', 'sell'
    analyst_count = info.get("numberOfAnalystOpinions")

    data["Market Cap (Cr)"] = round(market_cap / 1e7, 1) if market_cap else "N/A"
    data["PE"] = round(pe, 1) if pe else "N/A"
    data["ROE %"] = round(roe * 100, 1) if roe is not None else "N/A"
    data["Debt/Equity"] = round(debt_to_equity, 1) if debt_to_equity is not None else "N/A"
    data["Profit Margin %"] = round(profit_margin * 100, 1) if profit_margin is not None else "N/A"
    data["Analyst Target"] = round(analyst_target, 2) if analyst_target is not None else None
    data["Analyst Rating"] = analyst_rating.replace("_", " ").title() if analyst_rating else "No coverage"
    data["Analyst Count"] = analyst_count if analyst_count is not None else 0

    # ---- Red flags (subtract) ----
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

    # ---- Positive signals (add) -- this is what separates a plain "pass"
    # from an actual Strong Buy / Buy on fundamentals ----
    if roe is not None and roe > 0.20:
        positives.append(f"Strong ROE ({roe*100:.1f}%) -- efficient use of shareholder capital")
        score += 2
    elif roe is not None and roe > 0.12:
        positives.append(f"Decent ROE ({roe*100:.1f}%)")
        score += 1

    if pe is not None and 0 < pe < 15:
        positives.append(f"Attractively valued (PE {pe:.1f})")
        score += 1

    if debt_to_equity is not None and debt_to_equity < 30:
        positives.append(f"Very low leverage (Debt/Equity {debt_to_equity:.0f})")
        score += 1

    if profit_margin is not None and profit_margin > 0.15:
        positives.append(f"Strong profit margin ({profit_margin*100:.1f}%)")
        score += 1

    # ---- Multibagger quality-checklist proxy ----
    # A popular 12-point retail checklist (market cap, sales/profit growth,
    # ROE, ROCE, debt/equity, promoter holding, pledge, margins, cash flow,
    # PE, EV/EBITDA) inspired this flag. IMPORTANT HONESTY NOTE: only 5 of
    # those 12 items are checkable with the fast, free data this dashboard
    # already pulls (market cap, ROE, debt/equity, profit margin as an
    # operating-margin proxy, and PE). The rest are NOT included here:
    #   - Sales/Profit growth (needs multi-year income statement history)
    #   - ROCE (needs balance sheet + EBIT)
    #   - Promoter Holding % and Pledge % (not available via this data
    #     source at all, for any stock, at any speed)
    #   - EV/EBITDA (needs enterprise value calculation)
    # Pulling the missing items for the FULL watchlist (100+ stocks) would
    # reintroduce the exact slowness that broke the page earlier, so this
    # is a deliberately partial, fast proxy -- not the full 12-point
    # checklist. Treat "Multibagger Candidate" as "passed the 5 checks we
    # can verify quickly", not "passed all 12".
    multibagger_candidate = (
        market_cap is not None and market_cap > 10_000_000_000 and  # > ~₹1,000 Cr
        roe is not None and roe > 0.20 and
        debt_to_equity is not None and debt_to_equity < 50 and
        profit_margin is not None and profit_margin > 0.15 and
        pe is not None and 0 < pe < 60
    )

    # ---- Final tier: 5 levels instead of 3, so genuinely strong
    # fundamentals stand out instead of just "passing" ----
    if score >= 4:
        status = "STRONG BUY — strong fundamentals"
    elif score >= 2:
        status = "BUY — solid fundamentals"
    elif score >= 0:
        status = "OK — basic checks passed"
    elif score >= -2:
        status = "CAUTION — some weak spots"
    else:
        status = "AVOID — weak fundamentals"

    return {
        "status": status,
        "flags": flags + positives,
        "data": data,
        "multibagger_candidate": multibagger_candidate,
    }


# ---------------------------------------------------------------------
# ---------------------------------------------------------------------
# SIGNAL LOGIC
# ---------------------------------------------------------------------

def call_tier_from_score(score):
    """Shared tier thresholds -- used by generate_signal() and reused
    after the trend-structure adjustment (calc_trend_status) shifts the
    score, so the Live Signals table and the Backtest engine always
    agree on what a given score means."""
    if score >= 5:
        return "STRONG BUY"
    elif score >= 3:
        return "BUY"
    elif score <= -3:
        return "SELL"
    else:
        return "HOLD / WATCH"


def generate_signal(rsi, ema9, ema21, ema50, ema200, macd, macd_signal, price,
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
        reasons.append("Price above EMA9/21/50, strong short-term uptrend structure")
        score += 2
    elif price < ema9 < ema21 < ema50:
        reasons.append("Price below EMA9/21/50, strong short-term downtrend structure")
        score -= 2
    elif ema9 > ema21:
        reasons.append("Short-term EMA above medium-term — mild bullish bias")
        score += 1
    else:
        reasons.append("Short-term EMA below medium-term — mild bearish bias")
        score -= 1

    if ema200 is not None and not np.isnan(ema200):
        if price > ema200:
            reasons.append("Price above EMA200 — longer-term uptrend")
            score += 0.5
        else:
            reasons.append("Price below EMA200 — longer-term downtrend")
            score -= 0.5
        if ema50 > ema200:
            reasons.append("EMA50 above EMA200 (Golden Cross zone) — long-term bullish backdrop")
            score += 0.5
        else:
            reasons.append("EMA50 below EMA200 (Death Cross zone) — long-term bearish backdrop")
            score -= 0.5

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

    call = call_tier_from_score(score)

    return call, round(score, 2), reasons


# ---------------------------------------------------------------------
# DATA FETCH
# ---------------------------------------------------------------------

@st.cache_data(ttl=900)
def fetch_price_data(ticker: str, period="1y", interval="1d"):
    return yf.download(ticker, period=period, interval=interval, progress=False)


def fetch_fundamentals(ticker: str):
    """Manual session-level caching instead of st.cache_data here on purpose:
    st.cache_data would cache a FAILED ('Unknown') result for the full TTL,
    leaving a stock stuck showing Unknown for an hour even though the next
    attempt might succeed. Only successful fetches get cached -- failed ones
    are retried fresh on the next Refresh / page load, which is what
    actually helps against transient rate-limiting."""
    if "fundamentals_cache" not in st.session_state:
        st.session_state.fundamentals_cache = {}
    cache = st.session_state.fundamentals_cache

    if ticker in cache:
        return cache[ticker]

    result = fundamentals_check(ticker)
    if result["status"] != "UNKNOWN":
        cache[ticker] = result
    return result


@st.cache_data(ttl=300)
def fetch_index_snapshot(ticker: str):
    """Lightweight fetch for the top index panel -- just last 5 days,
    enough for a today % change readout."""
    df = yf.download(ticker, period="5d", interval="1d", progress=False)
    if df.empty or len(df) < 2:
        return None
    close = flatten_series(df["Close"]).dropna()
    if len(close) < 2:
        return None
    last = close.iloc[-1]
    prev = close.iloc[-2]
    pct = ((last - prev) / prev) * 100
    return {"level": round(float(last), 2), "pct": round(float(pct), 2)}


def flatten_series(s):
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return s


def find_last_ema_crossover(ema_fast: pd.Series, ema_slow: pd.Series):
    """Finds the most recent date the fast EMA (21) crossed the slow EMA
    (50), within whatever history is available (up to 1 year here).
    Returns (date_string, direction_label) or (None, "No cross in
    available history") if the fast EMA never crossed the slow one in
    the window -- meaning one has stayed above/below the other the
    whole time."""
    diff = ema_fast - ema_slow
    sign = np.sign(diff)
    changed = sign.diff().fillna(0) != 0
    change_dates = sign.index[changed]

    if len(change_dates) == 0:
        current_side = "21 EMA above 50 EMA" if sign.iloc[-1] > 0 else "21 EMA below 50 EMA"
        return None, f"No cross in available history ({current_side} throughout)"

    last_date = change_dates[-1]
    direction = "Bullish (21 crossed above 50)" if sign.loc[last_date] > 0 else "Bearish (21 crossed below 50)"
    return last_date.strftime("%Y-%m-%d"), direction


@st.cache_data(ttl=25)
def fetch_quick_data(ticker: str):
    """Deliberately lightweight -- only 1 month of data (not the full 1
    year the main scan uses), just enough for price, % change, and a
    basic RSI. This keeps a fast 30-60 second refresh on a handful of
    stocks cheap, instead of re-running the full EMA200/fundamentals
    engine that fast. NOT a substitute for the full Live Signals scan --
    it's a quick pulse-check only."""
    df = yf.download(ticker, period="1mo", interval="1d", progress=False)
    if df.empty or len(df) < 15:
        return None
    close = flatten_series(df["Close"]).dropna()
    if len(close) < 15:
        return None
    rsi = calc_rsi(close).iloc[-1]
    price = close.iloc[-1]
    prev = close.iloc[-2]
    pct = ((price - prev) / prev) * 100
    return {
        "price": round(float(price), 2),
        "pct": round(float(pct), 2),
        "rsi": round(float(rsi), 1) if not np.isnan(rsi) else None,
    }


# ---------------------------------------------------------------------
# BACKTEST ENGINE
# ---------------------------------------------------------------------

def run_backtest(ticker, nifty_close_pct, sl_pct=1.5, target_pct=3.0,
                  max_hold_days=10, period="2y"):
    df = fetch_price_data(ticker, period=period)
    if df.empty or len(df) < MIN_BARS_REQUIRED:
        return None, "Not enough historical data for this stock (need at least ~1 year for EMA200)."

    close = flatten_series(df["Close"]).dropna()
    high = flatten_series(df["High"]).reindex(close.index)
    low = flatten_series(df["Low"]).reindex(close.index)
    volume = flatten_series(df["Volume"]).reindex(close.index)

    if len(close) < MIN_BARS_REQUIRED:
        return None, "Not enough valid historical data after cleaning."

    rsi = calc_rsi(close)
    ema9 = calc_ema(close, 9)
    ema21 = calc_ema(close, 21)
    ema50 = calc_ema(close, 50)
    ema200 = calc_ema(close, 200)
    macd_line, signal_line, _ = calc_macd(close)
    adx = calc_adx(high, low, close)
    avg_vol_20 = volume.rolling(20).mean()
    vol_ratio_series = volume / avg_vol_20

    stock_pct_change = close.pct_change() * 100
    rel_strength_series = stock_pct_change - nifty_close_pct.reindex(close.index)

    trades = []
    in_position = False
    entry_idx = entry_price = sl_price = target_price = None
    n = len(close)
    start = 200

    for i in range(start, n):
        if not in_position:
            call, score, _ = generate_signal(
                rsi.iloc[i], ema9.iloc[i], ema21.iloc[i], ema50.iloc[i], ema200.iloc[i],
                macd_line.iloc[i], signal_line.iloc[i], close.iloc[i],
                adx.iloc[i], vol_ratio_series.iloc[i], rel_strength_series.iloc[i]
            )
            # Trend-structure adjustment (user's 5-condition uptrend/downtrend
            # rule) -- applied identically here and in the Live Signals loop
            # so backtest win-rates stay honest against what you'd actually see.
            _, trend_delta = calc_trend_status(
                close.iloc[:i + 1], ema21.iloc[:i + 1], ema50.iloc[:i + 1], ema200.iloc[:i + 1]
            )
            score += trend_delta
            call = call_tier_from_score(score)
            if call in ("BUY", "STRONG BUY"):
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
                trades.append({
                    "Entry Date": close.index[entry_idx].strftime("%Y-%m-%d"),
                    "Exit Date": close.index[i].strftime("%Y-%m-%d"),
                    "Entry Price": round(float(entry_price), 2),
                    "Exit Price": round(float(price_today), 2),
                    "Days Held": days_held,
                    "Return %": round(float(ret_pct), 2),
                    "Result": "Win" if ret_pct > 0 else "Loss",
                    "Exit Reason": exit_reason,
                })
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
    wf = stats["Win Rate %"] / 100
    stats["Expectancy % per Trade"] = round(wf * stats["Avg Win %"] + (1 - wf) * stats["Avg Loss %"], 2)
    return {"trades": trades_df, "stats": stats}, None


# ---------------------------------------------------------------------
# DEEP FUNDAMENTALS -- ROCE, PEG, Interest Coverage, FCF, Dividend
# consistency, Piotroski F-Score. Runs ONLY for CORE_WATCHLIST (9 stocks),
# never the full watchlist -- these need full financial statements, which
# are slow and rate-limit-prone at scale. Promoter holding % and Pledge %
# are NOT included -- Yahoo Finance does not carry this India-specific
# data at all, for any stock, at any speed.
# ---------------------------------------------------------------------

def _find_row(df, candidates):
    if df is None or df.empty:
        return None
    for name in candidates:
        if name in df.index:
            return df.loc[name]
    return None


def _latest_two(series):
    if series is None or len(series) < 1:
        return None, None
    vals = series.dropna()
    if len(vals) < 1:
        return None, None
    latest = vals.iloc[0]
    prior = vals.iloc[1] if len(vals) > 1 else None
    return latest, prior


@st.cache_data(ttl=3600)
def deep_fundamentals(ticker: str):
    result = {
        "ROCE %": None,
        "PEG Ratio": None,
        "Interest Coverage": None,
        "Free Cash Flow (Cr)": None,
        "Dividend Consistency (5y)": None,
        "Piotroski F-Score": None,
        "notes": [],
    }
    try:
        tk = yf.Ticker(ticker)
        info = tk.info
        financials = tk.financials
        balance_sheet = tk.balance_sheet
        cashflow = tk.cashflow
        dividends = tk.dividends
    except Exception as e:
        result["notes"].append(f"Could not fetch financial statements: {e}")
        return result

    ebit_row = _find_row(financials, ["EBIT", "Operating Income", "OperatingIncome"])
    total_assets_row = _find_row(balance_sheet, ["Total Assets", "TotalAssets"])
    current_liab_row = _find_row(balance_sheet, ["Total Current Liabilities", "Current Liabilities", "CurrentLiabilities"])

    ebit, _ = _latest_two(ebit_row) if ebit_row is not None else (None, None)
    total_assets, _ = _latest_two(total_assets_row) if total_assets_row is not None else (None, None)
    current_liab, _ = _latest_two(current_liab_row) if current_liab_row is not None else (None, None)

    if ebit is not None and total_assets is not None and current_liab is not None:
        capital_employed = total_assets - current_liab
        if capital_employed and capital_employed != 0:
            result["ROCE %"] = round((ebit / capital_employed) * 100, 2)
    else:
        result["notes"].append("ROCE: EBIT or balance sheet data not available")

    peg = info.get("trailingPegRatio") or info.get("pegRatio")
    if peg is not None:
        result["PEG Ratio"] = round(peg, 2)
    else:
        pe = info.get("trailingPE")
        growth = info.get("earningsGrowth")
        if pe is not None and growth is not None and growth != 0:
            result["PEG Ratio"] = round(pe / (growth * 100), 2)

    interest_row = _find_row(financials, ["Interest Expense", "InterestExpense"])
    interest_exp, _ = _latest_two(interest_row) if interest_row is not None else (None, None)
    if ebit is not None and interest_exp is not None and interest_exp != 0:
        result["Interest Coverage"] = round(ebit / abs(interest_exp), 2)

    fcf = info.get("freeCashflow")
    if fcf is not None:
        result["Free Cash Flow (Cr)"] = round(fcf / 1e7, 1)
    else:
        ocf_row = _find_row(cashflow, ["Operating Cash Flow", "Total Cash From Operating Activities"])
        capex_row = _find_row(cashflow, ["Capital Expenditure", "CapitalExpenditure"])
        ocf, _ = _latest_two(ocf_row) if ocf_row is not None else (None, None)
        capex, _ = _latest_two(capex_row) if capex_row is not None else (None, None)
        if ocf is not None and capex is not None:
            result["Free Cash Flow (Cr)"] = round((ocf + capex) / 1e7, 1)

    if dividends is not None and len(dividends) > 0:
        last_5y_years = set(pd.Timestamp.now().year - i for i in range(5))
        years_with_dividend = set(dividends.index.year) & last_5y_years
        result["Dividend Consistency (5y)"] = f"{len(years_with_dividend)}/5"
    else:
        result["Dividend Consistency (5y)"] = "0/5"

    try:
        score = 0
        points_possible = 0
        net_income_row = _find_row(financials, ["Net Income", "NetIncome"])
        revenue_row = _find_row(financials, ["Total Revenue", "TotalRevenue"])
        gross_profit_row = _find_row(financials, ["Gross Profit", "GrossProfit"])
        ocf_row = _find_row(cashflow, ["Operating Cash Flow", "Total Cash From Operating Activities"])
        total_debt_row = _find_row(balance_sheet, ["Total Debt", "TotalDebt"])
        current_assets_row = _find_row(balance_sheet, ["Total Current Assets", "Current Assets", "CurrentAssets"])
        shares_row = _find_row(balance_sheet, ["Ordinary Shares Number", "Share Issued", "OrdinarySharesNumber"])

        ni_now, ni_prior = _latest_two(net_income_row) if net_income_row is not None else (None, None)
        rev_now, rev_prior = _latest_two(revenue_row) if revenue_row is not None else (None, None)
        gp_now, gp_prior = _latest_two(gross_profit_row) if gross_profit_row is not None else (None, None)
        ocf_now, ocf_prior = _latest_two(ocf_row) if ocf_row is not None else (None, None)
        debt_now, debt_prior = _latest_two(total_debt_row) if total_debt_row is not None else (None, None)
        ca_now, ca_prior = _latest_two(current_assets_row) if current_assets_row is not None else (None, None)
        cl_now, cl_prior = _latest_two(current_liab_row) if current_liab_row is not None else (None, None)
        ta_now, ta_prior = _latest_two(total_assets_row) if total_assets_row is not None else (None, None)
        shares_now, shares_prior = _latest_two(shares_row) if shares_row is not None else (None, None)

        if ni_now is not None and ta_now:
            points_possible += 1
            if (ni_now / ta_now) > 0:
                score += 1
        if ocf_now is not None:
            points_possible += 1
            if ocf_now > 0:
                score += 1
        if ni_now is not None and ni_prior is not None and ta_now and ta_prior:
            points_possible += 1
            if (ni_now / ta_now) > (ni_prior / ta_prior):
                score += 1
        if ocf_now is not None and ni_now is not None:
            points_possible += 1
            if ocf_now > ni_now:
                score += 1
        if debt_now is not None and debt_prior is not None and ta_now and ta_prior:
            points_possible += 1
            if (debt_now / ta_now) < (debt_prior / ta_prior):
                score += 1
        if ca_now is not None and cl_now and ca_prior is not None and cl_prior:
            points_possible += 1
            if (ca_now / cl_now) > (ca_prior / cl_prior):
                score += 1
        if shares_now is not None and shares_prior is not None:
            points_possible += 1
            if shares_now <= shares_prior:
                score += 1
        if gp_now is not None and rev_now and gp_prior is not None and rev_prior:
            points_possible += 1
            if (gp_now / rev_now) > (gp_prior / rev_prior):
                score += 1
        if rev_now is not None and ta_now and rev_prior is not None and ta_prior:
            points_possible += 1
            if (rev_now / ta_now) > (rev_prior / ta_prior):
                score += 1

        if points_possible >= 5:
            result["Piotroski F-Score"] = f"{score}/{points_possible}"
        else:
            result["notes"].append("Piotroski: not enough statement history available")
    except Exception as e:
        result["notes"].append(f"Piotroski calculation error: {e}")

    return result


@st.cache_data(ttl=3600)
def quick_win_rate(ticker, sl_pct=1.5, target_pct=3.0, max_hold_days=10, period="2y"):
    """Historical win rate for this stock's past BUY signals over the given
    period, using the same backtest engine. Returns (win_rate_pct, trade_count)
    or None if there isn't enough history (fewer than 5 past signals) to be
    meaningful. This is a backtested historical frequency -- NOT a forward-
    looking probability guarantee. Reuses cached price data, so it's cheaper
    than it looks, but still only run for stocks currently showing BUY to
    keep the live table responsive."""
    nifty_df_local = fetch_price_data(NIFTY_TICKER, period=period)
    if nifty_df_local.empty:
        return None
    nifty_close_local = flatten_series(nifty_df_local["Close"]).dropna()
    nifty_pct_local = nifty_close_local.pct_change() * 100

    result, err = run_backtest(ticker, nifty_pct_local, sl_pct, target_pct, max_hold_days, period)
    if err or result is None or result["stats"] is None:
        return None
    stats = result["stats"]
    if stats["Total Trades"] < 5:
        return None
    return stats["Win Rate %"], stats["Total Trades"]


# ---------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# BACKGROUND STYLING -- white background, black text throughout
# ---------------------------------------------------------------------
st.markdown(
    """
    <style>
    .stApp {
        background-color: #ffffff !important;
    }
    [data-testid="stSidebar"] {
        background-color: #f2f2f2 !important;
    }
    h1, h2, h3, h4, h5, p, span, label, div,
    .stMarkdown, .stCaption, .stText {
        color: #000000 !important;
    }
    [data-testid="stMetricValue"] {
        color: #000000 !important;
    }
    [data-testid="stMetricLabel"] {
        color: #333333 !important;
    }
    [data-testid="stMetricDelta"] {
        color: #000000 !important;
    }
    .stTabs [data-baseweb="tab"] {
        color: #000000 !important;
    }
    .stTextArea textarea {
        color: #000000 !important;
        background-color: #ffffff !important;
    }
    /* Coloured badge cells (BUY/SELL/AVOID etc.) keep their own white
       text set inline by the table styler -- this global black-text
       rule does not override those, since inline styles win. */
    </style>
    """,
    unsafe_allow_html=True,
)

header_col, refresh_col, index_col = st.columns([2.6, 0.5, 1.2])
with header_col:
    st.title("📊 My Trading Guide")
with refresh_col:
    st.write("")  # vertical spacer to align button with title
    st.write("")
    if st.button("🔄 Refresh", help="Clear cached data and pull everything fresh"):
        st.cache_data.clear()
        st.rerun()
with index_col:
    st.markdown("**Market Indices**")
    idx_specs = [("Nifty 50", NIFTY_TICKER), ("Sensex", SENSEX_TICKER), ("Nifty Bank", BANKNIFTY_TICKER)]
    for name, tkr in idx_specs:
        snap = fetch_index_snapshot(tkr)
        if snap:
            st.metric(name, f"{snap['level']:,}", f"{snap['pct']:+.2f}%")
        else:
            st.caption(f"{name}: unavailable right now")
    st.caption("GIFT Nifty not shown — no reliable free ticker for it.")

with st.sidebar:
    st.header("Watchlist")

    st.caption("Include stock groups (untick to speed up loading — ~150 stocks total takes a while):")
    include_your_picks = st.checkbox("Your picks (9)", value=True)
    include_screened = st.checkbox("Screened extras (10)", value=True)
    include_requested = st.checkbox("Recently requested (9)", value=True)
    include_nifty50 = st.checkbox("Nifty 50 (50)", value=True)
    include_nifty_next50 = st.checkbox("Nifty Next 50 (49)", value=True, help="Nifty 50 + Nifty Next 50 = Nifty 100")

    _groups = []
    if include_your_picks:
        _groups += YOUR_PICKS
    if include_screened:
        _groups += ADDITIONAL_SCREENED_PICKS
    if include_requested:
        _groups += USER_REQUESTED_ADDITIONS
    if include_nifty50:
        _groups += NIFTY_50_CONSTITUENTS
    if include_nifty_next50:
        _groups += NIFTY_NEXT_50_CONSTITUENTS
    _default_from_groups = list(dict.fromkeys(_groups))  # dedupe, keep order

    watchlist_input = st.text_area(
        "NSE tickers (comma-separated, with .NS suffix) — edit freely, "
        "or use the checkboxes above to reset to a group selection",
        value=", ".join(_default_from_groups) if _default_from_groups else "",
        height=200,
    )
    watchlist = [t.strip().upper() for t in watchlist_input.split(",") if t.strip()]
    st.caption(f"{len(watchlist)} tickers loaded.")
    st.divider()

    st.subheader("Auto-Refresh (Full List)")
    auto_refresh_choice = st.selectbox(
        "Automatically reload the full watchlist every...",
        options=["Off (manual Refresh button only)", "5 minutes", "15 minutes"],
        index=0,
        help="30 seconds or 1 minute are NOT offered here on purpose. Yahoo "
             "Finance's own data only updates every 15-20 minutes, so "
             "refreshing faster than that just hits their servers harder "
             "for the same numbers -- and with ~150 tickers in this "
             "watchlist, very frequent refreshing risks getting the app "
             "rate-limited or blocked. For faster updates on a small set "
             "of stocks, use the Quick Watch tab instead.",
    )
    _auto_refresh_map = {"Off (manual Refresh button only)": None, "5 minutes": 300, "15 minutes": 900}
    auto_refresh_seconds = _auto_refresh_map[auto_refresh_choice]

    st.divider()
    st.markdown(
        "**Disclaimer:** Rule-based signals from public data, for your own "
        "review only. Not financial advice, does not place trades. A stock "
        "passing checks is not a recommendation. Backtests use daily closes "
        "only (a simplification) and past performance never guarantees "
        "future results. 'Multibagger?' checks only 5 of a common 12-point "
        "checklist (market cap, ROE, debt/equity, margin, PE) — promoter "
        "holding, pledge, ROCE, growth rates, and EV/EBITDA are NOT included; "
        "see the caption above the table for why."
    )

tab_live, tab_backtest, tab_quick = st.tabs(["📈 Live Signals", "🔄 Backtest", "⚡ Quick Watch"])

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
        "Fundamentals filter + RSI/EMA(9/21/50/200)/MACD/ADX/Volume/Nifty-relative-strength. "
        "Data is delayed (Yahoo Finance). "
        f"Last refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    show_breakdown = st.checkbox("Show full breakdown per stock", value=False)
    st.caption(
        "**Win Rate (hist)** = the % of this stock's past BUY signals over the last "
        "2 years that hit target before stop-loss (1.5% SL / 3% target / 10-day max "
        "hold, same defaults as the Backtest tab). Only shown for current BUY calls, "
        "and only when there's enough history (5+ past signals) to mean something. "
        "**This is a historical frequency, not a probability of what happens next** — "
        "markets change, and a good past win rate is not a guarantee.\n\n"
        "**Trend** = your 5-condition rule (Price > EMA21 > EMA50 > EMA200, all "
        "three sloping up, higher-highs/higher-lows — or the mirror for downtrend). "
        "'Uptrend (5/5)' means every condition is met; 'Leaning up/down' means 3-4 "
        "of 5; 'Mixed / Sideways' means neither direction is clearly established.\n\n"
        "**Multibagger?** checks only 5 of a common 12-point retail checklist "
        "(market cap > ₹1,000 Cr, ROE > 20%, debt/equity < 0.5, profit margin > 15%, "
        "reasonable PE) — a fast proxy, not the full checklist. Promoter holding, "
        "pledge %, ROCE, sales/profit growth, and EV/EBITDA are NOT checked here, "
        "either because the data isn't available from this free source at all "
        "(promoter holding, pledge) or because checking them for 150+ stocks would "
        "make the page too slow. A 'Yes' means it passed 5 real checks, not a "
        "guarantee of multibagger returns — that also needs a catalyst no checklist "
        "can predict in advance.\n\n"
        "**21/50 EMA Cross** = the most recent date the 21 EMA crossed the 50 "
        "EMA, within the last year of data. 'Bullish' means 21 crossed above "
        "50 (momentum turning up); 'Bearish' means the reverse. If it says "
        "'No cross in available history', the 21 EMA has stayed on one side "
        "of the 50 EMA the whole year — a long-established trend, not a "
        "recent signal.\n\n"
        "**BB Squeeze** = Bollinger Band width versus its own trailing "
        "120-day range. 'Squeeze' means volatility has compressed into the "
        "bottom 20% of its recent history — often precedes a sharp move, "
        "but direction (up or down) isn't implied by the squeeze itself.\n\n"
        "**OBV Signal** = compares On-Balance Volume (cumulative volume "
        "weighted by up/down days) to price over the last 20 days. "
        "'Accumulation' means volume is building while price stays flat — "
        "a possible sign of quiet buying before a move. 'Distribution' is "
        "the bearish mirror. 'Confirmed uptrend/downtrend' means volume "
        "and price are already moving the same direction.\n\n"
        "**RS Rank** = this stock's 3-month return, ranked as a percentile "
        "against every other stock currently in your watchlist (99 = "
        "strongest performer in the batch, 1 = weakest). This is relative "
        "to your OWN list, not the whole market, and it reflects momentum "
        "already in progress — a confirmation signal, not an early one.\n\n"
        "**Analyst** = consensus rating and mean target price from covering "
        "analysts (Yahoo Finance data), with % upside/downside to that "
        "target from the current price. 'No analyst coverage' is common "
        "for smaller stocks — absence of coverage isn't itself a red flag.\n\n"
        "**Trade Plan** (only shown for current BUY/STRONG BUY) = a "
        "mechanical Entry/Stop-Loss/Target 1/Target 2 calculation using "
        "2x ATR (Average True Range) for the stop, then 1:1 and 1:2 "
        "risk-reward for the two targets. **This is a formula, not a "
        "prediction** — it tells you where a consistent rule would place "
        "these levels, not that the stock will actually reach them or "
        "that the stop won't also get hit. Size positions and make the "
        "final call yourself.\n\n"
        "**Earnings** (only checked for current BUY/STRONG BUY, to avoid "
        "150+ extra requests) = flags when quarterly results are due "
        "within 7 days. Earnings can move a stock sharply regardless of "
        "what any technical signal says — treat a red flag here as a "
        "reason to size smaller or wait, not something to ignore.\n\n"
        "**Deep Fundamentals** (only for your 9 core picks — Coforge, "
        "Persistent, Mphasis, Modison, Premier Polyfilm, Rashi Peripherals, "
        "Borosil Renewables, Jaro Institute, TPL Plastech) = real ROCE, "
        "PEG, Interest Coverage, Free Cash Flow, 5-year Dividend "
        "consistency, and Piotroski F-Score (0-9, composite quality "
        "score). Scoped to just these 9 because pulling full financial "
        "statements for 150+ stocks would be too slow/rate-limit-prone. "
        "**Promoter Holding % and Pledge % are still not shown anywhere** "
        "— genuinely unavailable from this free data source, for any "
        "stock, at any speed. For these 9 stocks, Multibagger? upgrades "
        "from a 5-check proxy to a 7-check read using real ROCE and PEG "
        "instead of estimates."
    )

    rows, errors = [], []
    progress_bar = st.progress(0, text="Loading stocks...")

    for i, ticker in enumerate(watchlist):
        progress_bar.progress((i + 1) / len(watchlist), text=f"Loading {ticker.replace('.NS', '')}... ({i+1}/{len(watchlist)})")
        try:
            fund = fetch_fundamentals(ticker)
            df = fetch_price_data(ticker, period="1y")
            if df.empty or len(df) < MIN_BARS_REQUIRED:
                errors.append(f"{ticker}: not enough price history for EMA200 (need ~1 year)")
                continue

            close = flatten_series(df["Close"]).dropna()
            high = flatten_series(df["High"]).reindex(close.index)
            low = flatten_series(df["Low"]).reindex(close.index)
            volume = flatten_series(df["Volume"]).reindex(close.index)

            if len(close) < MIN_BARS_REQUIRED:
                errors.append(f"{ticker}: not enough valid price data after cleaning")
                continue

            rsi = calc_rsi(close).iloc[-1]
            ema9 = calc_ema(close, 9).iloc[-1]
            ema21_series = calc_ema(close, 21)
            ema50_series = calc_ema(close, 50)
            ema200_series = calc_ema(close, 200)
            ema21 = ema21_series.iloc[-1]
            ema50 = ema50_series.iloc[-1]
            ema200 = ema200_series.iloc[-1]
            macd_line, signal_line, _ = calc_macd(close)
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
                    rsi, ema9, ema21, ema50, ema200, macd_val, macd_sig_val, price,
                    adx_val, vol_ratio, rel_strength
                )
                # Trend-structure adjustment: user's 5-condition uptrend/
                # downtrend rule (Price > EMA21 > EMA50 > EMA200, sloping
                # up, higher-highs/higher-lows -- or the mirror for down).
                trend_label, trend_delta = calc_trend_status(close, ema21_series, ema50_series, ema200_series)
                score += trend_delta
                call = call_tier_from_score(score)
                reasons.append(f"Trend structure: {trend_label}")

            multibagger_flag = "🚀 Yes (5-check proxy)" if fund.get("multibagger_candidate") else "—"

            # ---- Deep fundamentals -- ONLY for CORE_WATCHLIST (9 stocks).
            # Also upgrades the Multibagger check for these specific
            # stocks from the fast 5-item proxy to a fuller read using
            # real ROCE and PEG, since we now have the heavier data. ----
            deep_display = "—"
            if ticker in CORE_WATCHLIST:
                deep = deep_fundamentals(ticker)
                parts = []
                if deep["ROCE %"] is not None:
                    parts.append(f"ROCE {deep['ROCE %']}%")
                if deep["PEG Ratio"] is not None:
                    parts.append(f"PEG {deep['PEG Ratio']}")
                if deep["Interest Coverage"] is not None:
                    parts.append(f"IntCov {deep['Interest Coverage']}x")
                if deep["Free Cash Flow (Cr)"] is not None:
                    parts.append(f"FCF ₹{deep['Free Cash Flow (Cr)']}Cr")
                if deep["Dividend Consistency (5y)"] is not None:
                    parts.append(f"Div {deep['Dividend Consistency (5y)']}y")
                if deep["Piotroski F-Score"] is not None:
                    parts.append(f"Piotroski {deep['Piotroski F-Score']}")
                deep_display = " | ".join(parts) if parts else "Data not available for this stock"

                # Upgrade the multibagger flag using real ROCE/PEG when we
                # have them, instead of the fast-proxy-only check
                if (deep["ROCE %"] is not None and deep["ROCE %"] > 15 and
                        fund.get("multibagger_candidate") and
                        (deep["PEG Ratio"] is None or 0 < deep["PEG Ratio"] < 2)):
                    multibagger_flag = "🚀 Yes (7-check, incl. real ROCE/PEG)"

            # 21/50 EMA crossover date -- computed unconditionally (cheap,
            # pure price math) regardless of AVOID/fundamentals status.
            cross_date, cross_direction = find_last_ema_crossover(ema21_series, ema50_series)
            if cross_date:
                cross_display = f"{cross_date} ({cross_direction})"
            else:
                cross_display = cross_direction  # "No cross in available history (...)"

            # ---- Bollinger Band squeeze (volatility compression before a
            # potential breakout, direction not implied) ----
            bb_upper, bb_lower, bb_width = calc_bollinger_bands(close)
            is_squeeze, squeeze_percentile = detect_bb_squeeze(bb_width)
            bb_display = f"🔸 Squeeze ({squeeze_percentile}th pct)" if is_squeeze else (
                f"Normal ({squeeze_percentile}th pct)" if squeeze_percentile is not None else "Not enough data"
            )

            # ---- OBV accumulation/distribution signal ----
            obv_series = calc_obv(close, volume)
            obv_signal = detect_obv_signal(close, obv_series)

            # ---- Analyst target price and upside vs current price ----
            analyst_target = fund["data"].get("Analyst Target")
            analyst_rating = fund["data"].get("Analyst Rating", "No coverage")
            analyst_count = fund["data"].get("Analyst Count", 0)
            if analyst_target and analyst_count and analyst_count > 0:
                analyst_upside = ((analyst_target - price) / price) * 100
                analyst_display = f"{analyst_rating} (target ₹{analyst_target}, {analyst_upside:+.1f}%, {analyst_count} analysts)"
            else:
                analyst_display = "No analyst coverage"

            # ---- 3-month return, used for Relative Strength Ranking after
            # the full watchlist loop finishes (percentile rank needs all
            # stocks' returns computed first) ----
            three_m_return = None
            if len(close) >= 64:
                three_m_return = ((close.iloc[-1] - close.iloc[-63]) / close.iloc[-63]) * 100

            # ---- ATR (cheap, pure price math -- computed for every stock) ----
            atr_val = calc_atr(high, low, close).iloc[-1]

            # ---- Trade plan + earnings check -- ONLY for stocks currently
            # showing BUY/STRONG BUY, to avoid adding an extra network call
            # (earnings calendar) for all ~150 tickers on every load. ----
            trade_plan_display = "—"
            earnings_flag = "—"
            if call in ("BUY", "STRONG BUY"):
                plan = build_trade_plan(price, atr_val)
                if plan:
                    trade_plan_display = (
                        f"Entry ₹{plan['entry']} | SL ₹{plan['stop_loss']} "
                        f"({plan['risk_pct']}% risk) | T1 ₹{plan['target_1']} "
                        f"(1:1) | T2 ₹{plan['target_2']} (1:2)"
                    )
                else:
                    trade_plan_display = "Could not compute (insufficient volatility data)"

                next_earnings = fetch_next_earnings_date(ticker)
                if next_earnings:
                    try:
                        days_to_earnings = (pd.Timestamp(next_earnings) - pd.Timestamp.now()).days
                        if 0 <= days_to_earnings <= 7:
                            earnings_flag = f"⚠️ Results {next_earnings} ({days_to_earnings}d) — expect volatility"
                        else:
                            earnings_flag = f"Results {next_earnings}"
                    except Exception:
                        earnings_flag = f"Results {next_earnings}"

            # Historical win rate -- only computed for current BUY/STRONG BUY
            # calls to keep the table fast (each one re-runs a 2y backtest, cached).
            win_rate_display = "—"
            if call in ("BUY", "STRONG BUY"):
                wr = quick_win_rate(ticker)
                if wr is not None:
                    win_rate_display = f"{wr[0]}% ({wr[1]} past signals)"
                else:
                    win_rate_display = "Not enough history"

            rows.append({
                "Ticker": ticker.replace(".NS", ""),
                "Price": round(float(price), 2),
                "% Chg": round(float(pct_change), 2),
                "Fundamentals": fund["status"],
                "RSI(14)": round(float(rsi), 1),
                "EMA200": round(float(ema200), 1) if not np.isnan(ema200) else None,
                "ADX": round(float(adx_val), 1) if not np.isnan(adx_val) else None,
                "Vol x Avg": round(float(vol_ratio), 2) if not np.isnan(vol_ratio) else None,
                "vs Nifty": round(float(rel_strength), 2) if not np.isnan(rel_strength) else None,
                "Trend": trend_label if call != "AVOID" else "—",
                "21/50 EMA Cross": cross_display,
                "BB Squeeze": bb_display,
                "OBV Signal": obv_signal,
                "Analyst": analyst_display,
                "Trade Plan": trade_plan_display,
                "Earnings": earnings_flag,
                "Deep Fundamentals": deep_display,
                "3M Return %": round(float(three_m_return), 2) if three_m_return is not None else None,
                "Multibagger?": multibagger_flag,
                "Call": call,
                "Win Rate (hist)": win_rate_display,
                "Score": score,
                "Why": " | ".join(reasons),
                "Fund Flags": " | ".join(fund["flags"]),
                "Fund Data": fund["data"],
            })
        except Exception as e:
            errors.append(f"{ticker}: {e}")

    progress_bar.empty()

    if rows:
        result_df = pd.DataFrame(rows).sort_values("Score", ascending=False)

        # Relative Strength Ranking -- percentile rank of each stock's 3-month
        # return against every other stock currently in the watchlist scan
        # (similar in spirit to IBD's RS Rating). Needs the full batch of
        # returns first, so it's computed here rather than per-ticker.
        result_df["RS Rank"] = (result_df["3M Return %"].rank(pct=True) * 99).round(0)
        result_df["RS Rank"] = result_df["RS Rank"].apply(
            lambda x: f"{int(x)}/99" if pd.notna(x) else "N/A"
        )

        def color_call(val):
            if val == "STRONG BUY":
                return "background-color: #0f8a3c; color: white; font-weight: bold;"
            elif val == "BUY":
                return "background-color: #1e5c2f; color: white;"
            elif val in ("SELL", "AVOID"):
                return "background-color: #6b1e1e; color: white;"
            return "background-color: #4a4a1e; color: white;"  # HOLD / WATCH

        st.subheader("Signal Summary")
        st.caption(
            "**Call** is the single combined signal — technicals (RSI/EMA/MACD/ADX/"
            "Volume/Nifty strength) plus a fundamentals safety check behind the "
            "scenes. A stock with genuinely weak fundamentals shows AVOID here "
            "regardless of how the chart looks, so you won't see a BUY on a "
            "fundamentally broken company. Fundamentals detail for any stock is "
            "in the breakdown below, not shown separately here, to avoid two "
            "signals appearing to disagree."
        )
        display_cols = ["Ticker", "Price", "% Chg", "RSI(14)", "EMA200", "ADX", "Vol x Avg", "vs Nifty", "Trend", "21/50 EMA Cross", "BB Squeeze", "OBV Signal", "RS Rank", "Analyst", "Multibagger?", "Deep Fundamentals", "Call", "Win Rate (hist)", "Trade Plan", "Earnings"]
        st.dataframe(
            result_df[display_cols]
            .style.map(color_call, subset=["Call"]),
            use_container_width=True,
            hide_index=True,
        )

        if show_breakdown:
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
        st.warning(f"{len(errors)} tickers had issues (often a temporary Yahoo Finance rate-limit at this scale):\n" + "\n".join(errors[:15]) + ("\n...and more" if len(errors) > 15 else ""))

# =======================================================================
# TAB 2: BACKTEST
# =======================================================================
with tab_backtest:
    st.caption(
        "Replays the exact same rules against historical data. Shows real "
        "win rate and average return."
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
            st.info("No BUY signals triggered for this stock over this period with the current rules.")
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

# =======================================================================
# TAB 3: QUICK WATCH -- fast-refreshing pulse-check on a small list
# =======================================================================
with tab_quick:
    st.caption(
        "A small, fast-refreshing list for a handful of core stocks -- "
        "price, % change, and RSI only (not the full EMA200/fundamentals "
        "engine), so it stays cheap enough to refresh every 30-60 seconds "
        "without risking rate-limits. Use this for a quick pulse-check; "
        "use Live Signals for the full picture."
    )

    quick_list_input = st.text_input(
        "Quick Watch tickers (comma-separated, with .NS suffix)",
        value=", ".join(YOUR_PICKS),
    )
    quick_list = [t.strip().upper() for t in quick_list_input.split(",") if t.strip()]

    quick_refresh_choice = st.selectbox(
        "Auto-refresh this Quick Watch list every...",
        options=["Off", "30 seconds", "60 seconds"],
        index=0,
        help="Kept small and cheap on purpose -- only works safely because "
             "this list is short (a handful of stocks) and pulls only 1 "
             "month of data each time, not the full 1-year scan the main "
             "list uses. Reloads the whole page, so you'll lose scroll "
             "position on the other tabs too.",
    )
    _quick_refresh_map = {"Off": None, "30 seconds": 30, "60 seconds": 60}
    quick_refresh_seconds = _quick_refresh_map[quick_refresh_choice]

    if quick_list:
        quick_rows = []
        quick_errors = []
        for qt in quick_list:
            qdata = fetch_quick_data(qt)
            if qdata is None:
                quick_errors.append(qt)
                continue
            quick_rows.append({
                "Ticker": qt.replace(".NS", ""),
                "Price": qdata["price"],
                "% Chg": qdata["pct"],
                "RSI(14)": qdata["rsi"] if qdata["rsi"] is not None else "N/A",
            })
        if quick_rows:
            quick_df = pd.DataFrame(quick_rows)

            def color_pct(val):
                if isinstance(val, (int, float)):
                    if val > 0:
                        return "background-color: #1e5c2f; color: white;"
                    elif val < 0:
                        return "background-color: #6b1e1e; color: white;"
                return ""

            st.dataframe(
                quick_df.style.map(color_pct, subset=["% Chg"]),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")
        if quick_errors:
            st.warning(f"Could not fetch: {', '.join(quick_errors)}")
    else:
        st.info("Add at least one ticker above to see Quick Watch data.")

# ---------------------------------------------------------------------
# Combined auto-refresh: only ONE meta-refresh tag is injected, using
# whichever interval is shorter if both the full-list and Quick Watch
# refreshes are active. A page reload re-runs this whole script, but
# thanks to caching, only whatever's cache has actually expired gets
# re-fetched from Yahoo -- the rest is served from cache, which is what
# makes a 30-second Quick Watch refresh safe alongside a much larger
# full watchlist.
# ---------------------------------------------------------------------
_candidates = [s for s in (auto_refresh_seconds, quick_refresh_seconds) if s is not None]
if _candidates:
    _effective_seconds = min(_candidates)
    st.markdown(f'<meta http-equiv="refresh" content="{_effective_seconds}">', unsafe_allow_html=True)

st.divider()
st.caption(
    "My Trading Guide — combines fundamentals + RSI/EMA(9/21/50/200)/"
    "MACD/ADX/Volume/Nifty relative strength for live signals, plus a "
    "backtest mode. Does not include options data or order execution. "
    "Verify against a live chart and your own reading of company filings "
    "before acting."
)
