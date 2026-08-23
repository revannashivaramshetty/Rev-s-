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

_combined = YOUR_PICKS + ADDITIONAL_SCREENED_PICKS
DEFAULT_WATCHLIST = _combined + [t for t in NIFTY_50_CONSTITUENTS if t not in _combined]

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


# ---------------------------------------------------------------------
# FUNDAMENTALS RED-FLAG FILTER
# ---------------------------------------------------------------------

def fundamentals_check(ticker: str, max_retries: int = 3):
    flags, positives, score, data = [], [], 0, {}

    # Yahoo Finance's .info endpoint is notoriously prone to transient
    # failures and rate-limiting, especially fetching 60+ tickers back to
    # back from a shared cloud IP. Retry with backoff before giving up,
    # and treat a suspiciously empty response the same as a failure --
    # yfinance sometimes returns a near-empty dict instead of raising.
    info = None
    last_error = None
    for attempt in range(max_retries):
        try:
            candidate = yf.Ticker(ticker).info
            if candidate and len(candidate) > 5:
                info = candidate
                break
            last_error = "Empty or incomplete response from data source"
        except Exception as e:
            last_error = str(e)
        time.sleep(1.0 + attempt)  # 1s, 2s, 3s backoff between attempts

    if info is None:
        return {
            "status": "UNKNOWN",
            "flags": [f"Could not fetch fundamentals after {max_retries} attempts "
                      f"(likely a temporary rate-limit) — {last_error}. Try the "
                      f"Refresh button in a minute or two."],
            "data": {},
        }

    # Small pacing delay after a successful fetch too, to reduce the
    # chance of tripping the rate limiter on the *next* ticker in line.
    time.sleep(0.2)

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

    return {"status": status, "flags": flags + positives, "data": data}


# ---------------------------------------------------------------------
# DEEP FUNDAMENTALS -- ROCE, PEG, Interest Coverage, FCF, Dividend
# consistency, Piotroski F-Score. Pulled on-demand for ONE stock at a
# time (not the whole watchlist) because these need full financial
# statements, which are slow and prone to Yahoo Finance rate-limits at
# scale. Promoter holding % and Pledge % are NOT included -- Yahoo
# Finance does not carry this India-specific data, so rather than show
# a fabricated number, those fields are left explicitly marked
# unavailable.
# ---------------------------------------------------------------------

def _find_row(df, candidates):
    """Financial statement row labels vary by company/yfinance version.
    Try a list of possible row names and return the first that matches."""
    if df is None or df.empty:
        return None
    for name in candidates:
        if name in df.index:
            return df.loc[name]
    return None


def _latest_two(series):
    """Return (most recent, prior) values from a financial statement row,
    or (None, None) if not enough data."""
    if series is None or len(series) < 1:
        return None, None
    vals = series.dropna()
    if len(vals) < 1:
        return None, None
    latest = vals.iloc[0]
    prior = vals.iloc[1] if len(vals) > 1 else None
    return latest, prior


def deep_fundamentals(ticker: str):
    result = {
        "ROCE %": "N/A",
        "PEG Ratio": "N/A",
        "Promoter Holding %": "Not available (not in this data source)",
        "Promoter Pledge %": "Not available (not in this data source)",
        "Interest Coverage": "N/A",
        "Free Cash Flow (Cr)": "N/A",
        "Dividend Yield %": "N/A",
        "Dividend Consistency (5y)": "N/A",
        "Piotroski F-Score": "N/A",
        "notes": [],
    }
    try:
        tk = yf.Ticker(ticker)
        info = tk.info
        financials = tk.financials          # annual income statement
        balance_sheet = tk.balance_sheet    # annual balance sheet
        cashflow = tk.cashflow              # annual cash flow statement
        dividends = tk.dividends            # dividend payment history
    except Exception as e:
        result["notes"].append(f"Could not fetch financial statements: {e}")
        return result

    # ---- ROCE = EBIT / (Total Assets - Current Liabilities) ----
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
        result["notes"].append("ROCE: EBIT or balance sheet data not available for this stock")

    # ---- PEG Ratio ----
    peg = info.get("trailingPegRatio") or info.get("pegRatio")
    if peg is not None:
        result["PEG Ratio"] = round(peg, 2)
    else:
        pe = info.get("trailingPE")
        growth = info.get("earningsGrowth")
        if pe is not None and growth is not None and growth != 0:
            result["PEG Ratio"] = round(pe / (growth * 100), 2)
        else:
            result["notes"].append("PEG: not provided by data source and could not be computed")

    # ---- Interest Coverage = EBIT / Interest Expense ----
    interest_row = _find_row(financials, ["Interest Expense", "InterestExpense"])
    interest_exp, _ = _latest_two(interest_row) if interest_row is not None else (None, None)
    if ebit is not None and interest_exp is not None and interest_exp != 0:
        result["Interest Coverage"] = round(ebit / abs(interest_exp), 2)
    else:
        result["notes"].append("Interest Coverage: interest expense not available (can mean low/no debt, or data gap)")

    # ---- Free Cash Flow = Operating Cash Flow - CapEx ----
    fcf = info.get("freeCashflow")
    if fcf is not None:
        result["Free Cash Flow (Cr)"] = round(fcf / 1e7, 1)
    else:
        ocf_row = _find_row(cashflow, ["Operating Cash Flow", "Total Cash From Operating Activities"])
        capex_row = _find_row(cashflow, ["Capital Expenditure", "CapitalExpenditure"])
        ocf, _ = _latest_two(ocf_row) if ocf_row is not None else (None, None)
        capex, _ = _latest_two(capex_row) if capex_row is not None else (None, None)
        if ocf is not None and capex is not None:
            result["Free Cash Flow (Cr)"] = round((ocf + capex) / 1e7, 1)  # capex usually negative already
        else:
            result["notes"].append("Free Cash Flow: cash flow statement data not available for this stock")

    # ---- Dividend yield & consistency ----
    div_yield = info.get("dividendYield")
    if div_yield is not None:
        result["Dividend Yield %"] = round(div_yield * 100, 2) if div_yield < 1 else round(div_yield, 2)
    if dividends is not None and len(dividends) > 0:
        last_5y_years = set(pd.Timestamp.now().year - i for i in range(5))
        years_with_dividend = set(dividends.index.year) & last_5y_years
        result["Dividend Consistency (5y)"] = f"{len(years_with_dividend)}/5 years"
    else:
        result["Dividend Consistency (5y)"] = "No dividends paid in available history"

    # ---- Piotroski F-Score (0-9) ----
    try:
        score = 0
        checks = []

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

        points_possible = 0

        if ni_now is not None and ta_now:
            points_possible += 1
            if (ni_now / ta_now) > 0:
                score += 1
            checks.append(f"ROA positive: {'Yes' if (ni_now/ta_now) > 0 else 'No'}")

        if ocf_now is not None:
            points_possible += 1
            if ocf_now > 0:
                score += 1
            checks.append(f"Operating cash flow positive: {'Yes' if ocf_now > 0 else 'No'}")

        if ni_now is not None and ni_prior is not None and ta_now and ta_prior:
            points_possible += 1
            roa_now = ni_now / ta_now
            roa_prior = ni_prior / ta_prior
            if roa_now > roa_prior:
                score += 1
            checks.append(f"ROA improving: {'Yes' if roa_now > roa_prior else 'No'}")

        if ocf_now is not None and ni_now is not None:
            points_possible += 1
            if ocf_now > ni_now:
                score += 1
            checks.append(f"Cash flow quality (OCF > Net Income): {'Yes' if ocf_now > ni_now else 'No'}")

        if debt_now is not None and debt_prior is not None and ta_now and ta_prior:
            points_possible += 1
            if (debt_now / ta_now) < (debt_prior / ta_prior):
                score += 1
            checks.append("Leverage decreasing: checked")

        if ca_now is not None and cl_now and ca_prior is not None and cl_prior:
            points_possible += 1
            if (ca_now / cl_now) > (ca_prior / cl_prior):
                score += 1
            checks.append("Current ratio improving: checked")

        if shares_now is not None and shares_prior is not None:
            points_possible += 1
            if shares_now <= shares_prior:
                score += 1
            checks.append(f"No new shares issued: {'Yes' if shares_now <= shares_prior else 'No'}")

        if gp_now is not None and rev_now and gp_prior is not None and rev_prior:
            points_possible += 1
            if (gp_now / rev_now) > (gp_prior / rev_prior):
                score += 1
            checks.append("Gross margin improving: checked")

        if rev_now is not None and ta_now and rev_prior is not None and ta_prior:
            points_possible += 1
            if (rev_now / ta_now) > (rev_prior / ta_prior):
                score += 1
            checks.append("Asset turnover improving: checked")

        if points_possible >= 5:  # only report if enough data existed to be meaningful
            result["Piotroski F-Score"] = f"{score} / {points_possible} checks available (out of 9 total)"
        else:
            result["notes"].append("Piotroski F-Score: not enough financial statement history available for this stock")
    except Exception as e:
        result["notes"].append(f"Piotroski F-Score calculation error: {e}")

    return result


# ---------------------------------------------------------------------
# SIGNAL LOGIC
# ---------------------------------------------------------------------

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

    if score >= 3:
        call = "BUY"
    elif score <= -3:
        call = "SELL"
    else:
        call = "HOLD / WATCH"

    return call, round(score, 2), reasons


# ---------------------------------------------------------------------
# DATA FETCH
# ---------------------------------------------------------------------

@st.cache_data(ttl=900)
def fetch_price_data(ticker: str, period="1y", interval="1d"):
    return yf.download(ticker, period=period, interval=interval, progress=False)


@st.cache_data(ttl=3600)
def fetch_fundamentals(ticker: str):
    return fundamentals_check(ticker)


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
    watchlist_input = st.text_area(
        "NSE tickers (comma-separated, with .NS suffix)",
        value=", ".join(DEFAULT_WATCHLIST),
        height=200,
    )
    watchlist = [t.strip().upper() for t in watchlist_input.split(",") if t.strip()]
    st.caption(f"{len(watchlist)} tickers loaded (your picks + 10 screened extras + full Nifty 50).")
    st.divider()
    st.markdown(
        "**Disclaimer:** Rule-based signals from public data, for your own "
        "review only. Not financial advice, does not place trades. A stock "
        "passing checks is not a recommendation. Backtests use daily closes "
        "only (a simplification) and past performance never guarantees "
        "future results."
    )

tab_live, tab_backtest, tab_deep = st.tabs(["📈 Live Signals", "🔄 Backtest", "🔬 Deep Fundamentals"])

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
        "markets change, and a good past win rate is not a guarantee."
    )

    rows, errors = [], []

    for ticker in watchlist:
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
            ema21 = calc_ema(close, 21).iloc[-1]
            ema50 = calc_ema(close, 50).iloc[-1]
            ema200 = calc_ema(close, 200).iloc[-1]
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

            # Historical win rate -- only computed for current BUY calls to
            # keep the table fast (each one re-runs a 2y backtest, cached).
            win_rate_display = "—"
            if call == "BUY":
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
                "Call": call,
                "Win Rate (hist)": win_rate_display,
                "Score": score,
                "Why": " | ".join(reasons),
                "Fund Flags": " | ".join(fund["flags"]),
                "Fund Data": fund["data"],
            })
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
            elif val.startswith("STRONG BUY"):
                return "background-color: #0f8a3c; color: white; font-weight: bold;"
            elif val.startswith("BUY"):
                return "background-color: #1e5c2f; color: white;"
            return "background-color: #3a3a3a; color: white;"  # OK — neutral pass

        st.subheader("Signal Summary")
        display_cols = ["Ticker", "Price", "% Chg", "Fundamentals", "RSI(14)", "EMA200", "ADX", "Vol x Avg", "vs Nifty", "Call", "Win Rate (hist)"]
        st.dataframe(
            result_df[display_cols]
            .style.map(color_call, subset=["Call"])
            .map(color_fund, subset=["Fundamentals"]),
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
# TAB 3: DEEP FUNDAMENTALS
# =======================================================================
with tab_deep:
    st.caption(
        "Deeper fundamentals for ONE stock at a time — ROCE, PEG, Interest "
        "Coverage, Free Cash Flow, Dividend consistency, and Piotroski "
        "F-Score. Run one at a time (not the whole watchlist) since these "
        "need full financial statements, which are slower and more prone "
        "to rate-limits than the quick checks in Live Signals."
    )
    st.warning(
        "**Promoter Holding % and Pledge % are not shown.** Yahoo Finance "
        "(this dashboard's data source) does not carry this India-specific "
        "shareholding data. Rather than show a made-up number, these fields "
        "are left explicitly marked unavailable — check Screener.in or "
        "Trendlyne directly for these two figures."
    )

    deep_ticker = st.selectbox("Stock to analyze", options=watchlist, key="deep_ticker_select")

    if st.button("Run Deep Analysis", type="primary"):
        with st.spinner(f"Pulling financial statements for {deep_ticker}..."):
            deep = deep_fundamentals(deep_ticker)

        c1, c2, c3 = st.columns(3)
        c1.metric("ROCE", f"{deep['ROCE %']}%" if deep["ROCE %"] != "N/A" else "N/A")
        c2.metric("PEG Ratio", deep["PEG Ratio"])
        c3.metric("Interest Coverage", deep["Interest Coverage"])

        c4, c5, c6 = st.columns(3)
        c4.metric("Free Cash Flow", f"₹{deep['Free Cash Flow (Cr)']} Cr" if deep["Free Cash Flow (Cr)"] != "N/A" else "N/A")
        c5.metric("Dividend Yield", f"{deep['Dividend Yield %']}%" if deep["Dividend Yield %"] != "N/A" else "N/A")
        c6.metric("Dividend Consistency", deep["Dividend Consistency (5y)"])

        st.metric("Piotroski F-Score", deep["Piotroski F-Score"])

        st.markdown("**Promoter Holding %:** " + deep["Promoter Holding %"])
        st.markdown("**Promoter Pledge %:** " + deep["Promoter Pledge %"])

        if deep["notes"]:
            st.markdown("**Data availability notes:**")
            for note in deep["notes"]:
                st.write(f"- {note}")

        with st.expander("What do these mean?"):
            st.markdown(
                "- **ROCE (Return on Capital Employed):** profit generated per rupee of capital used, "
                "including debt. Higher is generally better; compare against the company's own history "
                "and sector peers rather than a fixed number.\n"
                "- **PEG Ratio:** PE ratio divided by earnings growth rate. Below 1 is often considered "
                "reasonably priced for the growth rate; above 2 suggests the price has run ahead of growth.\n"
                "- **Interest Coverage:** how many times over the company can pay its interest expense "
                "from operating profit. Below 2-3x is a warning sign of debt-servicing stress.\n"
                "- **Free Cash Flow:** actual cash generated after capital spending, not just accounting "
                "profit. Persistent negative FCF despite reported profit is worth investigating.\n"
                "- **Piotroski F-Score:** a 0-9 composite checking profitability, leverage, and efficiency "
                "trends year-over-year. 7-9 is considered strong, 0-3 weak — but it's a screening aid, "
                "not a verdict on its own."
            )

st.divider()
st.caption(
    "My Trading Guide — combines fundamentals + RSI/EMA(9/21/50/200)/"
    "MACD/ADX/Volume/Nifty relative strength for live signals, plus a "
    "backtest mode. Does not include options data or order execution. "
    "Verify against a live chart and your own reading of company filings "
    "before acting."
)
