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


def calc_atr(df, period=14):
    """Calcule l'ATR (Average True Range) sur la période donnée depuis un DataFrame OHLC."""
    def _c(col):
        c = df[col]
        return c.iloc[:, 0] if hasattr(c, "columns") else c
    high  = _c("High")
    low   = _c("Low")
    close = _c("Close")
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period, min_periods=period).mean()
    val = atr.iloc[-1]
    return round(float(val), 6) if not np.isnan(float(val)) else None


def enrich_sr_zones(sr_zones, atr, prix, fib_levels=None, multiplier=0.5):
    """
    Enrichit les zones S/R brutes :
    - Ajoute zone_low / zone_high (± 0.5 × ATR autour du mid_price)
    - Fusionne les zones qui se chevauchent (cumule les touches, hérite de la force la plus haute)
    - Détecte la confluence Fibonacci (flag fibo_confluence + fibo_level)
    - Calcule la position du prix : above_zone / in_zone / below_zone
    Rétrocompatible : conserve les champs price, type, strength, touches existants.
    """
    if not sr_zones:
        return []

    half = (atr * multiplier) if atr else 0

    # Étape 1 : ajouter zone_low / zone_high à chaque zone
    zones = []
    for z in sr_zones:
        zc = dict(z)
        zc["mid_price"] = z["price"]
        zc["zone_low"]  = round(z["price"] - half, 4)
        zc["zone_high"] = round(z["price"] + half, 4)
        zones.append(zc)

    # Étape 2 : trier par zone_low et fusionner les chevauchements
    zones.sort(key=lambda x: x["zone_low"])
    force_rank = {"strong": 3, "medium": 2, "weak": 1}
    merged = []
    for z in zones:
        if merged and z["zone_low"] <= merged[-1]["zone_high"]:
            m = merged[-1]
            m["zone_high"] = max(m["zone_high"], z["zone_high"])
            m["touches"]  += z["touches"]
            if force_rank.get(z["strength"], 0) > force_rank.get(m["strength"], 0):
                m["strength"] = z["strength"]
            if m["type"] != z["type"]:
                m["type"] = "both"
            m["mid_price"] = round((m["zone_low"] + m["zone_high"]) / 2, 4)
            m["price"]     = m["mid_price"]
        else:
            merged.append(dict(z))

    # Étape 3 : confluence Fibonacci
    fib_keys = ["fib_0", "fib_236", "fib_382", "fib_500", "fib_618", "fib_786", "fib_100"]
    for z in merged:
        z["fibo_confluence"] = False
        z["fibo_level"]      = None
        if fib_levels:
            for fk in fib_keys:
                fv = fib_levels.get(fk)
                if fv and z["zone_low"] <= fv <= z["zone_high"]:
                    z["fibo_confluence"] = True
                    z["fibo_level"]      = fk
                    break

    # Étape 4 : position du prix
    for z in merged:
        if prix is None:
            z["price_position"] = "unknown"
        elif prix > z["zone_high"]:
            z["price_position"] = "above_zone"
        elif prix < z["zone_low"]:
            z["price_position"] = "below_zone"
        else:
            z["price_position"] = "in_zone"

    return merged


def compute_nearest_zone(zones, prix, close_series, lookback=10):
    """
    Identifie la zone S/R la plus proche du prix actuel.
    Calcule distance_pct, support_broken et days_below_zone
    (nombre de clôtures daily consécutives sous zone_low, réinitialisé dès une clôture >= zone_low).
    """
    if not zones or prix is None:
        return None

    nearest = min(zones, key=lambda z: abs(z["mid_price"] - prix))
    result  = dict(nearest)
    result["distance_pct"]    = round(abs(nearest["mid_price"] - prix) / prix * 100, 2)
    result["support_broken"]  = False
    result["days_below_zone"] = 0

    zone_low = nearest["zone_low"]
    if close_series is not None and len(close_series) >= 2:
        closes = [float(c) for c in close_series.iloc[-lookback:]]
        count  = 0
        for c in reversed(closes):
            if c < zone_low:
                count += 1
            else:
                break
        result["days_below_zone"] = count
        result["support_broken"]  = count >= 1

    return result


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
