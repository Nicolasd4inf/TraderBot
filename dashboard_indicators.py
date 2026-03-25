"""
Calculs techniques : RSI, MACD, Fibonacci, zones S/R.
"""

import pandas as pd
import numpy as np


def calc_rsi(series, period=14):
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def compute_macd_detailed(series, fast=12, slow=26, signal=9):
    """Calcule le MACD avec valeurs numériques brutes + proximité du croisement."""
    if len(series) < slow + signal:
        return {"signal": "neutral", "macd_line": None, "signal_line": None,
                "histogram": None, "prev_histogram": None, "hist_trend": None,
                "distance_to_cross": None, "est_days_to_cross": None, "cross_imminent": False}
    ema_fast    = series.ewm(span=fast,   adjust=False).mean()
    ema_slow    = series.ewm(span=slow,   adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram   = macd_line - signal_line

    current_macd      = round(float(macd_line.iloc[-1]),  6)
    current_signal    = round(float(signal_line.iloc[-1]), 6)
    current_histogram = round(float(histogram.iloc[-1]),  6)
    prev_histogram    = round(float(histogram.iloc[-2]),  6)

    if current_macd > current_signal:
        text_signal = "bullish_cross" if prev_histogram <= 0 else "bullish"
    else:
        text_signal = "bearish_cross" if prev_histogram >= 0 else "bearish"

    distance   = abs(current_macd - current_signal)
    hist_trend = "converging" if abs(current_histogram) < abs(prev_histogram) else "diverging"

    if hist_trend == "converging" and abs(current_histogram) > 0:
        daily_conv = abs(prev_histogram) - abs(current_histogram)
        est_days   = round(abs(current_histogram) / daily_conv, 1) if daily_conv > 0 else None
    else:
        est_days = None

    return {
        "signal":          text_signal,
        "macd_line":       current_macd,
        "signal_line":     current_signal,
        "histogram":       current_histogram,
        "prev_histogram":  prev_histogram,
        "hist_trend":      hist_trend,
        "distance_to_cross": round(distance, 6),
        "est_days_to_cross": est_days,
        "cross_imminent":  distance < abs(current_macd * 0.05) if current_macd != 0 else False,
    }


def calculate_fibonacci_levels(df, lookback_period=252):
    def _c(col):
        c = df[col]
        return c.iloc[:, 0] if hasattr(c, "columns") else c
    high_col = _c("High")
    low_col  = _c("Low")
    ath_price = float(high_col.max())
    ath_idx   = high_col.idxmax()
    post_mask = df.index > ath_idx
    post_low  = low_col[post_mask]
    if len(post_low) > 5:
        swing_low     = float(post_low.min())
        swing_low_idx = post_low.idxmin()
    else:
        recent        = low_col.iloc[-lookback_period:]
        swing_low     = float(recent.min())
        swing_low_idx = recent.idxmin()
    diff = ath_price - swing_low
    def _d(v): return str(v.date()) if hasattr(v, "date") else str(v)[:10]
    return {
        "ath":       {"price": round(ath_price, 4), "date": _d(ath_idx)},
        "swing_low": {"price": round(swing_low, 4), "date": _d(swing_low_idx)},
        "fib_0":   round(swing_low, 4),
        "fib_236": round(swing_low + diff * 0.236, 4),
        "fib_382": round(swing_low + diff * 0.382, 4),
        "fib_500": round(swing_low + diff * 0.500, 4),
        "fib_618": round(swing_low + diff * 0.618, 4),
        "fib_786": round(swing_low + diff * 0.786, 4),
        "fib_100": round(ath_price, 4),
    }

def get_current_fib_zone(price, fib):
    zones = [
        ("BELOW_FIB_0",  -1e9,          fib["fib_0"]),
        ("ZONE_0_236",   fib["fib_0"],   fib["fib_236"]),
        ("ZONE_236_382", fib["fib_236"], fib["fib_382"]),
        ("ZONE_382_500", fib["fib_382"], fib["fib_500"]),
        ("ZONE_500_618", fib["fib_500"], fib["fib_618"]),
        ("ZONE_618_786", fib["fib_618"], fib["fib_786"]),
        ("ZONE_786_100", fib["fib_786"], fib["fib_100"]),
        ("ABOVE_ATH",    fib["fib_100"], 1e9),
    ]
    for name, lo, hi in zones:
        if lo <= price < hi:
            return name
    return "UNKNOWN"


def detect_sr_zones(ohlcv, prix, window=5, tolerance=0.015):
    """
    Détecte les zones S/R depuis les données OHLCV.
    - window    : bougies de chaque côté pour valider un swing
    - tolerance : regroupe les niveaux à moins de 1.5% d'écart
    Retourne une liste de zones triées par force (touches desc).
    """
    if len(ohlcv) < window * 2 + 1:
        return []
    levels = []
    for i in range(window, len(ohlcv) - window):
        hi  = ohlcv[i]["high"]
        lo  = ohlcv[i]["low"]
        nbh = [c["high"] for c in ohlcv[i-window:i+window+1]]
        nbl = [c["low"]  for c in ohlcv[i-window:i+window+1]]
        if hi == max(nbh):
            levels.append({"price": hi, "type": "resistance"})
        if lo == min(nbl):
            levels.append({"price": lo, "type": "support"})
    levels.sort(key=lambda x: x["price"])
    # Clustering
    clusters = []
    for lv in levels:
        if clusters and abs(lv["price"] - clusters[-1]["price"]) / clusters[-1]["price"] < tolerance:
            c = clusters[-1]
            c["price"]   = round((c["price"] * c["touches"] + lv["price"]) / (c["touches"] + 1), 4)
            c["touches"] += 1
            if lv["type"] != c["type"]:
                c["type"] = "both"
        else:
            clusters.append({"price": lv["price"], "type": lv["type"], "touches": 1})
    # Score et filtre (±30% du prix actuel)
    result = []
    for c in clusters:
        if prix and abs(c["price"] - prix) / prix > 0.30:
            continue
        c["strength"] = "strong" if c["touches"] >= 3 else ("medium" if c["touches"] == 2 else "weak")
        result.append(c)
    result.sort(key=lambda x: x["touches"], reverse=True)
    return result[:10]
