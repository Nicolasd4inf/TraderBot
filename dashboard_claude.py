#!/usr/bin/env python3
"""
Portfolio Signal Dashboard Generator — CTO
============================================
Génère un dashboard HTML avec les signaux techniques de tous les actifs du portefeuille CTO.

Installation :
    pip install yfinance pandas numpy

Usage :
    python dashboard_claude.py
    -> Ouvre automatiquement dashboard.html dans le navigateur

Planification automatique :
    Windows : Planificateur de taches -> executer chaque matin a 9h
    Mac/Linux : crontab -e -> 0 9 * * 1-5 python /chemin/dashboard_claude.py
"""

import json
import yfinance as yf
import pandas as pd
import numpy as np
import webbrowser
import os
import requests
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────

TICKER_MAP = {
    "GOLD":  {"primary": "GOLD.PA",  "fallbacks": ["GLDA.PA"],          "nom": "Or — Amundi Physical Gold",      "categorie": "metaux",  "devise": "€", "isin": "FR0013416716"},
    "PHAG":  {"primary": "PHAG.AS",  "fallbacks": ["PHAG.L"],            "nom": "Argent — WisdomTree Physical",   "categorie": "metaux",  "devise": "€", "isin": "JE00B1VS3333"},
    "BTC":   {"primary": "BTC-USD",  "fallbacks": ["BTC-EUR"],           "nom": "Bitcoin",                        "categorie": "crypto",  "devise": "$"},
    "EQQQ":  {"primary": "EQQQ.PA",  "fallbacks": ["EQQQ.AS","EQQQ.L"], "nom": "Nasdaq-100 — Invesco",           "categorie": "actions", "devise": "€"},
    "VUSA":  {"primary": "VUSA.AS",  "fallbacks": ["VUSA.L"],            "nom": "S&P 500 — Vanguard",             "categorie": "actions", "devise": "€"},
    "IJPA":  {"primary": "IJPA.AS",  "fallbacks": ["SJPA.AS","IJPA.L"], "nom": "MSCI Japan — iShares",           "categorie": "actions", "devise": "€"},
    "PAASI": {"primary": "PAASI.PA", "fallbacks": [],                    "nom": "MSCI EM Asia — Amundi",          "categorie": "actions", "devise": "€"},
    "EMIM":  {"primary": "EMIM.AS",  "fallbacks": ["EIMI.AS","EMIM.L"], "nom": "MSCI EM IMI — iShares",          "categorie": "actions", "devise": "€"},
    "ETZ":   {"primary": "ETZ.PA",   "fallbacks": [],                    "nom": "STOXX Europe 600 — BNP",         "categorie": "actions", "devise": "€"},
    "VHYL":  {"primary": "VHYL.AS",  "fallbacks": ["VHYL.L"],           "nom": "All-World High Div — Vanguard",  "categorie": "actions", "devise": "€"},
}
ASSETS = TICKER_MAP  # alias for backward compat

ASSET_CATEGORY = {k: v["categorie"] for k, v in TICKER_MAP.items()}

EXIT_RSI_THRESHOLDS = {
    "metaux":  {"sell_50": 78, "sell_100": 85, "rebuy": 50},
    "crypto":  {"sell_50": 80, "sell_100": 88, "rebuy": 45},
    "actions": {"sell_50": 75, "sell_100": 82, "rebuy": 55},
}

ETF_KEYS = ["EQQQ", "VUSA", "IJPA", "PAASI", "EMIM", "ETZ", "VHYL"]

# ── CALCULS TECHNIQUES ────────────────────────────────────────────────────────

def calc_rsi(series, period=14):
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_macd(series, fast=12, slow=26, signal=9):
    ema_fast    = series.ewm(span=fast,   adjust=False).mean()
    ema_slow    = series.ewm(span=slow,   adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line

def detect_crossover(macd_line, signal_line):
    if len(macd_line) < 3:
        return "neutral"
    m, s = macd_line.iloc[-3:], signal_line.iloc[-3:]
    if m.iloc[-2] < s.iloc[-2] and m.iloc[-1] >= s.iloc[-1]:
        return "bullish_cross"
    if m.iloc[-2] > s.iloc[-2] and m.iloc[-1] <= s.iloc[-1]:
        return "bearish_cross"
    return "bullish" if m.iloc[-1] > s.iloc[-1] else "bearish"


def fetch_tradegate_price(isin):
    """
    Récupère le prix en temps réel depuis Tradegate Exchange.
    Utilise une session pour obtenir le cookie puis appelle /json/.
    Retourne un float ou None.
    """
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        })
        # 1. Visite la page principale pour obtenir les cookies de session
        base_url = "https://www.tradegate.de/orderbuch.php?isin=" + isin
        session.get(base_url, timeout=10)
        # 2. Appel de l'API JSON avec Referer
        session.headers["Referer"] = base_url
        r = session.get("https://www.tradegate.de/json/?isin=" + isin, timeout=10)
        r.raise_for_status()
        data = r.json()
        # Champs possibles selon la réponse Tradegate
        for field in ("last", "Last", "price", "kurs", "Kurs"):
            if field in data:
                val = data[field]
                # Format européen : "86,224" → 86.224
                if isinstance(val, str):
                    val = val.replace(".", "").replace(",", ".")
                return round(float(val), 4)
    except Exception as e:
        print("  [ERR Tradegate] " + isin + ": " + str(e))
    return None


# ── FIBONACCI DYNAMIQUE ───────────────────────────────────────────────────────

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


# ── FETCH ASSET ───────────────────────────────────────────────────────────────

def fetch_asset(ticker, isin_fallback=None, ticker_fallback=None, ticker_rt=None, fallbacks=None):
    try:
        # Try all fallback tickers
        all_tickers = [ticker] + ([ticker_fallback] if ticker_fallback else []) + (fallbacks or [])
        tk   = None
        df_d = None
        df_w = None
        used_ticker = ticker
        for t in all_tickers:
            tk_try   = yf.Ticker(t)
            df_d_try = tk_try.history(period="2y", interval="1d")
            df_w_try = tk_try.history(period="5y", interval="1wk")
            if not df_d_try.empty:
                tk         = tk_try
                df_d       = df_d_try
                df_w       = df_w_try
                used_ticker = t
                if t != ticker:
                    print("  [INFO] " + ticker + " vide -> essai " + t)
                break

        if df_d is None or df_d.empty:
            # Dernier recours : prix Tradegate uniquement (pas d'indicateurs)
            if isin_fallback:
                print("  [INFO] " + ticker + " -> tentative prix Tradegate (" + isin_fallback + ")")
                prix_tg = fetch_tradegate_price(isin_fallback)
                if prix_tg:
                    _empty = {"rsi": None, "hist": None, "crossover": "neutral"}
                    return {"ok": True, "prix": prix_tg, "variation": None,
                            "source": "tradegate", "daily": _empty.copy(), "weekly": _empty.copy(),
                            "fibonacci": {}}
            return None

        # Compatibilité yfinance 0.2.x (colonnes MultiIndex → aplatir)
        def _close(df):
            c = df["Close"]
            return c.iloc[:, 0] if hasattr(c, "columns") else c
        close_d = _close(df_d)
        close_w = _close(df_w) if not df_w.empty else None

        # MA50 / MA200 sur la série complète 2 ans
        ma50_s  = close_d.rolling(50).mean()
        ma200_s = close_d.rolling(200).mean()
        ma50_val  = round(float(ma50_s.iloc[-1]),  4) if not pd.isna(ma50_s.iloc[-1])  else None
        ma200_val = round(float(ma200_s.iloc[-1]), 4) if not pd.isna(ma200_s.iloc[-1]) else None
        if ma50_val and ma200_val:
            ma_cross = "golden" if ma50_val > ma200_val else "death"
        else:
            ma_cross = None

        df_d["RSI"]  = calc_rsi(close_d)
        df_d["MACD"], df_d["Sig"], df_d["Hist"] = calc_macd(close_d)
        if not df_w.empty:
            df_w["RSI"]  = calc_rsi(close_w)
            df_w["MACD"], df_w["Sig"], df_w["Hist"] = calc_macd(close_w)
        prix      = round(float(close_d.iloc[-1]), 4)
        variation = round(float((close_d.iloc[-1] / close_d.iloc[-2] - 1) * 100), 2)

        # Fibo auto depuis le swing 6 mois (dernières 126 bougies)
        def _col(df, col):
            c = df[col]
            return c.iloc[:, 0] if hasattr(c, "columns") else c
        df_6m   = df_d.iloc[-126:]
        high_6m = float(_col(df_6m, "High").max())
        low_6m  = float(_col(df_6m, "Low").min())
        fibo_auto = {r: round(high_6m - (high_6m - low_6m) * r, 4) for r in [0.236, 0.382, 0.500, 0.618, 0.786]}

        # Fibonacci dynamique (2 ans d'historique)
        try:
            fib_levels = calculate_fibonacci_levels(df_d)
            fib_levels["current_zone"] = get_current_fib_zone(prix, fib_levels)
        except Exception as e:
            print("  [WARN Fib] " + ticker + ": " + str(e))
            fib_levels = {}

        # OHLCV pour le chart (6 derniers mois) + séries MA alignées
        ohlcv      = []
        ma50_data  = []
        ma200_data = []
        vol_s      = _col(df_6m, "Volume")
        ma50_6m    = ma50_s.iloc[-126:]
        ma200_6m   = ma200_s.iloc[-126:]
        for i in range(len(df_6m)):
            try:
                t = df_6m.index[i]
                t = t.date().isoformat() if hasattr(t, "date") else str(t)[:10]
                o = round(float(_col(df_6m, "Open").iloc[i]),  4)
                c = round(float(_col(df_6m, "Close").iloc[i]), 4)
                ohlcv.append({
                    "time":   t,
                    "open":   o,
                    "high":   round(float(_col(df_6m, "High").iloc[i]), 4),
                    "low":    round(float(_col(df_6m, "Low").iloc[i]),  4),
                    "close":  c,
                    "volume": int(float(vol_s.iloc[i])),
                    "up":     c >= o,
                })
                v50 = ma50_6m.iloc[i]
                if not pd.isna(v50):
                    ma50_data.append({"time": t, "value": round(float(v50), 4)})
                v200 = ma200_6m.iloc[i]
                if not pd.isna(v200):
                    ma200_data.append({"time": t, "value": round(float(v200), 4)})
            except Exception:
                pass

        # Zones S/R (calculées ici pour réutilisation dans build_card)
        sr_zones = detect_sr_zones(ohlcv, prix)
        nearest_sup = next((z for z in sorted(sr_zones, key=lambda z: z["price"], reverse=True) if z["price"] < prix), None)
        nearest_res = next((z for z in sorted(sr_zones, key=lambda z: z["price"]) if z["price"] > prix), None)

        # Prix intraday : fast_info > Tradegate > yfinance 2m
        prix_source  = "yahoo"
        prix_close_d = prix

        def _update_prix(new_prix, source):
            nonlocal prix, variation, prix_source
            if not new_prix: return
            diff = abs(new_prix - prix_close_d) / prix_close_d
            if diff >= 0.15: return          # aberrant, ignorer
            prix        = new_prix
            prix_source = source
            # Variation intraday seulement si le prix RT est vraiment différent (>0.01%)
            if diff > 0.0001:
                variation = round((new_prix / prix_close_d - 1) * 100, 2)
            # sinon on garde la variation J-2→J-1 déjà calculée

        # 1. ticker_rt dédié (ex: GOLD-EUR.PA) si défini
        if ticker_rt:
            try:
                import warnings, logging
                logging.getLogger("yfinance").setLevel(logging.CRITICAL)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    fi_rt = yf.Ticker(ticker_rt).fast_info
                    if fi_rt.last_price:
                        _update_prix(round(float(fi_rt.last_price), 4), "realtime")
            except Exception:
                pass
            finally:
                logging.getLogger("yfinance").setLevel(logging.WARNING)

        # 2. yfinance fast_info sur le ticker principal
        if prix_source == "yahoo":
            try:
                import warnings, logging
                logging.getLogger("yfinance").setLevel(logging.CRITICAL)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    fi = tk.fast_info
                    if fi.last_price:
                        _update_prix(round(float(fi.last_price), 4), "realtime")
            except Exception:
                pass
            finally:
                logging.getLogger("yfinance").setLevel(logging.WARNING)

        # 3. Tradegate (si fast_info absent, pour ETPs IE/JE)
        if prix_source == "yahoo" and isin_fallback:
            _update_prix(fetch_tradegate_price(isin_fallback), "tradegate")

        # 4. yfinance intraday 2m (dernier recours)
        if prix_source == "yahoo":
            try:
                df_rt = tk.history(period="1d", interval="2m")
                if not df_rt.empty:
                    _update_prix(round(float(_close(df_rt).iloc[-1]), 4), "yahoo_rt")
            except Exception:
                pass

        if prix_source != "yahoo":
            print("  [" + prix_source.upper() + "] " + ticker + " intraday: " + str(prix))

        return {
            "ok": True, "prix": prix, "variation": variation, "prix_source": prix_source,
            "swing": {"high": round(high_6m, 4), "low": round(low_6m, 4)},
            "fibo_auto": fibo_auto,
            "fibonacci": fib_levels,
            "ohlcv": ohlcv,
            "ma50":  ma50_val, "ma200": ma200_val, "ma_cross": ma_cross,
            "ma50_series": ma50_data, "ma200_series": ma200_data,
            "sr_zones": sr_zones,
            "nearest_sup": nearest_sup, "nearest_res": nearest_res,
            "daily": {
                "rsi":       round(float(df_d["RSI"].iloc[-1]), 1),
                "hist":      round(float(df_d["Hist"].iloc[-1]), 4),
                "crossover": detect_crossover(df_d["MACD"], df_d["Sig"]),
            },
            "weekly": {
                "rsi":       round(float(df_w["RSI"].iloc[-1]), 1)  if not df_w.empty else None,
                "hist":      round(float(df_w["Hist"].iloc[-1]), 4) if not df_w.empty else None,
                "crossover": detect_crossover(df_w["MACD"], df_w["Sig"]) if not df_w.empty else "neutral",
            },
        }
    except Exception as e:
        print("  [ERR] " + ticker + ": " + str(e))
        _empty = {"rsi": None, "hist": None, "crossover": "neutral"}
        return {"ok": False, "prix": None, "variation": None,
                "swing": {"high": None, "low": None}, "fibo_auto": {}, "fibonacci": {}, "ohlcv": [],
                "ma50": None, "ma200": None, "ma_cross": None,
                "ma50_series": [], "ma200_series": [], "sr_zones": [],
                "nearest_sup": None, "nearest_res": None,
                "daily": _empty.copy(), "weekly": _empty.copy()}


# ── ZONES SUPPORT / RÉSISTANCE ────────────────────────────────────────────────

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


# ── LOGIQUE TIER ──────────────────────────────────────────────────────────────

def _find_strong_support(prix, sr_zones, fib_382=None):
    cands = [z for z in sr_zones if z["price"] < prix and z["type"] in ["support","both"]
             and (z["strength"] in ["strong","medium"] or z["touches"] >= 2)]
    if cands:
        return max(cands, key=lambda z: z["price"])["price"]
    return fib_382

def evaluate_tier(key, d):
    if not d or not d.get("ok"):
        return {"tier": 0, "pct": 0, "label": "Données indisponibles", "next_missing": None, "conditions": {}}
    cat    = ASSET_CATEGORY.get(key, "actions")
    rsi_d  = d["daily"]["rsi"]
    rsi_w  = d["weekly"]["rsi"]
    macd_d = d["daily"]["crossover"]
    macd_w = d["weekly"]["crossover"]
    prix   = d["prix"]
    ma_cross = d.get("ma_cross")
    fib    = d.get("fibonacci", {})
    fib_382 = fib.get("fib_382")
    sr     = d.get("sr_zones", [])
    strong_sup = _find_strong_support(prix, sr, fib_382) if prix else None
    above_sup  = (prix > strong_sup) if strong_sup else (bool(fib_382 and prix and prix > fib_382))

    if cat == "metaux":
        c1_rsi = (rsi_d or 999) < 40
        c1_fib = fib_382 is None or not prix or prix > fib_382
        t1 = c1_rsi and c1_fib
        t2 = t1 and macd_d in ["bullish","bullish_cross"]
        t3 = t2 and macd_w in ["bullish","bullish_cross"]
        conds = {
            "tier_1": {"rsi_d_below_40": c1_rsi, "above_fib_382": c1_fib},
            "tier_2": {"tier_1_met": t1, "macd_d_bullish": macd_d in ["bullish","bullish_cross"]},
            "tier_3": {"tier_2_met": t2, "macd_w_confirms": macd_w in ["bullish","bullish_cross"]},
        }
        tiers_list = [(3,100,"Conviction pleine"),(2,60,"Renforcement"),(1,25,"Surveillance active"),(0,0,"Hors zone")]
        met_list   = [t3, t2, t1, True]
    elif cat == "crypto":
        c1_rsi = (rsi_w or 999) < 35
        c1_fib = fib_382 is None or not prix or prix > fib_382
        t1 = c1_rsi and c1_fib
        t2 = t1 and macd_d in ["bullish","bullish_cross"]
        t3 = t2 and macd_w in ["bullish","bullish_cross"] and ma_cross != "death"
        conds = {
            "tier_1": {"rsi_w_below_35": c1_rsi, "above_fib_382": c1_fib},
            "tier_2": {"tier_1_met": t1, "macd_d_bullish": macd_d in ["bullish","bullish_cross"]},
            "tier_3": {"tier_2_met": t2, "macd_w_bullish": macd_w in ["bullish","bullish_cross"], "no_death_cross": ma_cross != "death"},
        }
        tiers_list = [(3,100,"Retournement confirmé"),(2,60,"Rebond technique"),(1,30,"Capitulation"),(0,0,"Hors zone")]
        met_list   = [t3, t2, t1, True]
    else:
        c1_rsi = (rsi_d or 999) < 40
        t1 = c1_rsi and above_sup
        t2 = t1 and macd_d in ["bullish","bullish_cross"]
        t3 = t2 and macd_w in ["bullish","bullish_cross"]
        conds = {
            "tier_1": {"rsi_d_below_40": c1_rsi, "above_strong_support": above_sup},
            "tier_2": {"tier_1_met": t1, "macd_d_bullish": macd_d in ["bullish","bullish_cross"]},
            "tier_3": {"tier_2_met": t2, "macd_w_confirms": macd_w in ["bullish","bullish_cross"]},
        }
        tiers_list = [(3,100,"Tendance confirmée"),(2,60,"Momentum retourne"),(1,25,"Survente — entrée progressive"),(0,0,"Hors zone")]
        met_list   = [t3, t2, t1, True]

    tier, pct, label = next((t,p,l) for (t,p,l),m in zip(tiers_list, met_list) if m)
    next_missing = None
    if tier < 3:
        for k, v in conds.get("tier_" + str(tier+1), {}).items():
            if not v:
                next_missing = k.replace("_", " ")
                break
    return {"tier": tier, "pct": pct, "label": label, "next_missing": next_missing, "conditions": conds}


# ── LOGIQUE EXIT ──────────────────────────────────────────────────────────────

def evaluate_exit_signal(key, d):
    cat = ASSET_CATEGORY.get(key, "actions")
    th  = EXIT_RSI_THRESHOLDS.get(cat, EXIT_RSI_THRESHOLDS["actions"])
    rsi_w = d["weekly"]["rsi"] if d and d.get("ok") else None
    if rsi_w is None:
        return {"status": "UNKNOWN", "rsi_w": None, **th, "dist_sell50": None}
    status = ("SELL_100" if rsi_w > th["sell_100"] else
              "SELL_50"  if rsi_w > th["sell_50"]  else
              "REBUY"    if rsi_w < th["rebuy"]     else "HOLD")
    return {"status": status, "rsi_w": rsi_w, "dist_sell50": round(th["sell_50"] - rsi_w, 1), **th}


# ── LOGIQUE SIGNAL ────────────────────────────────────────────────────────────

def evaluate_signal(key, cfg, d):
    if not d or not d.get("ok"):
        return {"label": "DONNEES INDISPONIBLES", "color": "gray", "action": "—"}
    tier_info = evaluate_tier(key, d)
    exit_s    = evaluate_exit_signal(key, d)
    tier, pct, label = tier_info["tier"], tier_info["pct"], tier_info["label"]
    next_m = tier_info["next_missing"]
    # Exit signals take priority
    if exit_s["status"] == "SELL_100":
        return {"label": "VENDRE 100%", "color": "red",
                "action": "RSI weekly " + str(exit_s["rsi_w"]) + " > " + str(exit_s["sell_100"]) + " — alléger totalement"}
    if exit_s["status"] == "SELL_50":
        return {"label": "VENDRE 50%", "color": "orange",
                "action": "RSI weekly " + str(exit_s["rsi_w"]) + " > " + str(exit_s["sell_50"]) + " — alléger 50%"}
    colors = {3: "green", 2: "yellow", 1: "teal", 0: "gray"}
    if tier == 3:
        action = "T3 " + str(pct) + "% — " + label
    elif tier == 2:
        action = "T2 " + str(pct) + "% — " + label + " · manque T3 : " + (next_m or "?")
    elif tier == 1:
        action = "T1 " + str(pct) + "% — " + label + " · manque T2 : " + (next_m or "?")
    else:
        rsi_d = d["daily"]["rsi"]
        fib = d.get("fibonacci", {})
        fib_zone = fib.get("current_zone", "")
        action = "Hors zone — manque T1 : " + (next_m or "?")
        if rsi_d: action += " · RSI D: " + str(rsi_d)
        if fib_zone: action += " · " + fib_zone
    return {"label": "T" + str(tier) + " : " + label if tier > 0 else "HORS ZONE",
            "color": colors[tier], "action": action}


# ── HTML HELPERS ──────────────────────────────────────────────────────────────

MACD_LABELS = {
    "bullish_cross": "CROISE UP",
    "bullish":       "HAUSSIER",
    "bearish_cross": "CROISE DN",
    "bearish":       "BAISSIER",
    "neutral":       "NEUTRE",
}

def ml(c):  return MACD_LABELS.get(c, "—")
def mc(c):
    if c in ["bullish_cross","bullish"]: return "bullish"
    if c in ["bearish_cross","bearish"]: return "bearish"
    return "neutral"

def rc(rsi):
    if rsi is None: return "neutral"
    if rsi > 70:    return "overbought"
    if rsi < 30:    return "oversold"
    if rsi > 55:    return "bullish"
    if rsi < 45:    return "bearish"
    return "neutral"

def fmt_price(p, devise):
    if p is None: return "—"
    if p > 10000: return "{:,.0f}".format(p)
    if p > 100:   return "{:,.2f}".format(p)
    return "{:,.3f}".format(p)

def h(tag, cls, content):
    return "<" + tag + " class='" + cls + "'>" + content + "</" + tag + ">"

def _fmt_level(level, devise):
    if level is None: return "—"
    if level >= 1000: return devise + "{:,.0f}".format(level)
    if level >= 10:   return devise + "{:,.2f}".format(level)
    return devise + "{:.4f}".format(level)

def fibo_auto_pills(prix, fibo_auto, devise):
    if not fibo_auto: return ""
    out = "<div class='fibo-auto-row'><span class='fibo-auto-label'>FIBO AUTO ·</span>"
    for r, level in fibo_auto.items():
        in_zone = prix is not None and abs(prix - level) / level <= 0.02
        cls = "fibo-pill active" if in_zone else "fibo-pill"
        out += "<span class='" + cls + "' title='Fibo " + "{:.1f}".format(r*100) + "%'>" + "{:.1f}".format(r*100) + "% " + _fmt_level(level, devise) + "</span>"
    out += "</div>"
    return out

def fibo_alert(prix, fibo_auto, static_zones, devise, swing):
    if prix is None or not fibo_auto: return ""
    best_r = min(fibo_auto, key=lambda r: abs(fibo_auto[r] - prix))
    level  = fibo_auto[best_r]
    dist   = (prix - level) / level * 100
    out    = ""
    direction = "au-dessus" if dist > 0 else "en-dessous"
    if abs(dist) <= 1.0:
        out += "<div class='fibo-alert-pill close'>⚠ PRIX SUR FIBO " + "{:.1f}".format(best_r*100) + "% — " + "{:+.1f}".format(dist) + "% " + direction + "</div>"
    elif abs(dist) <= 3.0:
        out += "<div class='fibo-alert-pill'>&#128205; Approche Fibo " + "{:.1f}".format(best_r*100) + "% — " + "{:+.1f}".format(dist) + "% " + direction + "</div>"
    return out

def _ma_cls(prix, ma_val):
    """Classe CSS selon prix au-dessus / en-dessous de la MA."""
    if prix is None or ma_val is None: return "neutral"
    return "bullish" if prix > ma_val else "bearish"

def _sr_row(zone, devise):
    """Ligne texte pour une zone S/R."""
    if zone is None: return "—"
    sym = "▲" if zone["type"] == "resistance" else ("▼" if zone["type"] == "support" else "◆")
    strength_map = {"strong": "●●●", "medium": "●●○", "weak": "●○○"}
    return sym + " " + _fmt_level(zone["price"], devise) + " " + strength_map.get(zone["strength"], "")


# ── BUILD CARD ────────────────────────────────────────────────────────────────

def build_card(key, cfg, d, sig):
    prix_val  = d["prix"]      if d else None
    var_val   = d["variation"] if d else None
    rsi_d     = d["daily"]["rsi"]       if d else None
    rsi_w     = d["weekly"]["rsi"]      if d else None
    cd        = d["daily"]["crossover"]  if d else "neutral"
    cw        = d["weekly"]["crossover"] if d else "neutral"
    fa        = d.get("fibo_auto", {})  if d else {}
    swing     = d.get("swing")          if d else None
    ma50      = d.get("ma50")           if d else None
    ma200     = d.get("ma200")          if d else None
    ma_cross  = d.get("ma_cross")       if d else None
    n_sup     = d.get("nearest_sup")    if d else None
    n_res     = d.get("nearest_res")    if d else None
    var_str      = ("+" if var_val and var_val > 0 else "") + (str(var_val) + "%" if var_val is not None else "—")
    var_cls      = "up" if var_val and var_val > 0 else ("down" if var_val and var_val < 0 else "flat")
    prix_source  = d.get("prix_source", "yahoo") if d else "yahoo"
    _src_labels  = {"realtime": "RT", "tradegate": "TG", "yahoo_rt": "~RT"}
    source_badge = ("<span class='source-tg'>" + _src_labels[prix_source] + "</span>") if prix_source in _src_labels else ""
    color        = sig["color"]

    # MA cross label + couleur
    cross_label = "GOLDEN ✦" if ma_cross == "golden" else ("DEATH ✕" if ma_cross == "death" else "—")
    cross_cls   = "bullish" if ma_cross == "golden" else ("bearish" if ma_cross == "death" else "neutral")

    # Tier badge
    tier_info = evaluate_tier(key, d)
    exit_s    = evaluate_exit_signal(key, d)
    tier      = tier_info["tier"]
    tier_bars = "".join(
        "<span class='tb-filled t" + str(tier) + "'></span>" if i <= tier else "<span class='tb-empty'></span>"
        for i in range(1, 4)
    )
    tier_html = (
        "<div class='tier-row'>"
        + "<div class='tier-bar'>" + tier_bars + "</div>"
        + "<span class='tier-badge t" + str(tier) + "'>T" + str(tier) + " " + str(tier_info["pct"]) + "%</span>"
        + "<span class='tier-label'>" + tier_info["label"] + "</span>"
        + ("<span class='tier-next'>→ manque : " + tier_info["next_missing"] + "</span>" if tier_info["next_missing"] and tier < 3 else "")
        + "</div>"
    )
    # Exit badge
    es = exit_s["status"]
    es_colors = {"HOLD": "green", "SELL_50": "orange", "SELL_100": "red", "REBUY": "teal", "UNKNOWN": "gray"}
    exit_html = (
        "<div class='exit-row'>"
        + h("span", "exit-badge ex-" + es_colors.get(es,"gray"), es)
        + " RSI W: " + (str(exit_s["rsi_w"]) if exit_s["rsi_w"] else "—")
        + (" · dist→sell50: " + str(exit_s.get("dist_sell50","—")) + " pts" if es == "HOLD" else "")
        + "</div>"
    )
    # Fibonacci dynamique bar
    fib = d.get("fibonacci", {}) if d else {}
    fib_html = ""
    if fib and "fib_0" in fib and "fib_100" in fib:
        lo, hi = fib["fib_0"], fib["fib_100"]
        rng = hi - lo
        if rng > 0:
            def _pct(v): return round((v - lo) / rng * 100, 1)
            zone_segments = [
                ("fib_0","fib_236","#ff4757"),("fib_236","fib_382","#ffa726"),
                ("fib_382","fib_500","#ffee58"),("fib_500","fib_618","#26c6da"),
                ("fib_618","fib_786","#00e676"),("fib_786","fib_100","#3d7aed"),
            ]
            segs = "".join(
                "<div class='fib-seg' style='left:" + str(_pct(fib[s])) + "%;width:" + str(_pct(fib[e])-_pct(fib[s])) + "%;background:" + c + "'></div>"
                for s,e,c in zone_segments
            )
            pos = max(0, min(100, _pct(prix_val))) if prix_val else 50
            segs += "<div class='fib-marker' style='left:" + str(pos) + "%'></div>"
            zone_label = fib.get("current_zone","")
            fib_html = (
                "<div class='fib-dyn-label'>FIBO ATH→SWING LOW · " + zone_label + "</div>"
                + "<div class='fib-dyn-bar'>" + segs + "</div>"
                + "<div class='fib-dyn-vals'>"
                + "<span>0% " + _fmt_level(fib["fib_0"], cfg["devise"]) + "</span>"
                + "<span>38.2% " + _fmt_level(fib["fib_382"], cfg["devise"]) + "</span>"
                + "<span>61.8% " + _fmt_level(fib["fib_618"], cfg["devise"]) + "</span>"
                + "<span>ATH " + _fmt_level(fib["fib_100"], cfg["devise"]) + "</span>"
                + "</div>"
            )

    return (
        "<div class='asset-card " + color + "'>"
        + "<div class='card-top'>"
        + "<div>" + h("div","asset-name",cfg["nom"]) + h("div","asset-ticker",cfg["primary"]) + "</div>"
        + "<div class='price-block'>"
        + h("div","price-value", cfg["devise"] + fmt_price(prix_val, cfg["devise"]) + source_badge)
        + h("div","price-change " + var_cls, var_str)
        + "</div></div>"
        + h("div","signal-badge badge-" + color, sig["label"])
        + h("div","signal-action", sig["action"])
        + "<div class='indicators'>"
        + "<div class='ind-block'>" + h("div","ind-label","RSI Daily")   + h("div","ind-value "+rc(rsi_d), str(round(rsi_d)) if rsi_d else "—") + "</div>"
        + "<div class='ind-block'>" + h("div","ind-label","MACD D")      + h("div","ind-value "+mc(cd), ml(cd)) + "</div>"
        + "<div class='ind-block'>" + h("div","ind-label","RSI Weekly")  + h("div","ind-value "+rc(rsi_w), str(round(rsi_w)) if rsi_w else "—") + "</div>"
        + "<div class='ind-block'>" + h("div","ind-label","MACD W")      + h("div","ind-value "+mc(cw), ml(cw)) + "</div>"
        + "</div>"
        + "<div class='indicators ma-row'>"
        + "<div class='ind-block'>" + h("div","ind-label","MA 50")    + h("div","ind-value "+_ma_cls(prix_val,ma50),  _fmt_level(ma50,  cfg["devise"]) if ma50  else "—") + "</div>"
        + "<div class='ind-block'>" + h("div","ind-label","MA 200")   + h("div","ind-value "+_ma_cls(prix_val,ma200), _fmt_level(ma200, cfg["devise"]) if ma200 else "—") + "</div>"
        + "<div class='ind-block'>" + h("div","ind-label","MA Cross") + h("div","ind-value "+cross_cls, cross_label) + "</div>"
        + "<div class='ind-block'>" + h("div","ind-label","Support")     + h("div","ind-value sr-sup",  _sr_row(n_sup, cfg["devise"])) + "</div>"
        + "<div class='ind-block'>" + h("div","ind-label","Résistance")  + h("div","ind-value sr-res",  _sr_row(n_res, cfg["devise"])) + "</div>"
        + "</div>"
        + tier_html + exit_html + fib_html
        + "<div class='fibo-zones'>" + fibo_auto_pills(prix_val, fa, cfg["devise"]) + "</div>"
        + fibo_alert(prix_val, fa, None, cfg["devise"], swing)
        + "<button class='chart-toggle' onclick=\"var w=this.nextElementSibling;w.classList.toggle('open');this.textContent=w.classList.contains('open')?'▲ Masquer le chart':'▼ Afficher le chart';\">▼ Afficher le chart</button>"
        + "<div class='chart-wrap' id='chart-" + key + "' style='height:220px'></div>"
        + "</div>"
    )


# ── CSS (raw string — pas de .format()) ──────────────────────────────────────

CSS = """\
:root {
  --bg:#080c14;--bg2:#0d1420;--bg3:#111b2e;--border:#1e2d45;
  --text:#c8d8f0;--text-dim:#4a6080;--text-bright:#e8f2ff;
  --green:#00e676;--green-bg:rgba(0,230,118,0.08);
  --red:#ff4757;--red-bg:rgba(255,71,87,0.08);
  --orange:#ffa726;--orange-bg:rgba(255,167,38,0.08);
  --yellow:#ffee58;--yellow-bg:rgba(255,238,88,0.07);
  --teal:#26c6da;--teal-bg:rgba(38,198,218,0.08);
  --gray:#546e7a;--gray-bg:rgba(84,110,122,0.08);
  --gold:#ffd54f;--accent:#3d7aed;
}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:'JetBrains Mono',monospace;font-size:13px;min-height:100vh;padding:20px}
body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:linear-gradient(rgba(61,122,237,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(61,122,237,.03) 1px,transparent 1px);
  background-size:40px 40px}
.wrapper{position:relative;z-index:1;max-width:1400px;margin:0 auto}
.header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid var(--border);gap:16px}
.header-left h1{font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:var(--text-bright);letter-spacing:-.5px}
.header-left h1 span{color:var(--accent)}
.subtitle{color:var(--text-dim);font-size:11px;margin-top:4px;letter-spacing:1px;text-transform:uppercase}
.timestamp{text-align:right;color:var(--text-dim);font-size:11px;line-height:1.8;flex-shrink:0}
.timestamp .date{color:var(--gold);font-size:14px;font-weight:600}
.section-title{font-family:'Syne',sans-serif;font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--text-dim);margin:20px 0 10px;display:flex;align-items:center;gap:8px}
.section-title::after{content:'';flex:1;height:1px;background:var(--border)}
.assets-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}
.asset-card{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:14px 16px;position:relative;overflow:hidden}
.asset-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--border)}
.asset-card.green::before{background:var(--green)}
.asset-card.red::before{background:var(--red)}
.asset-card.orange::before{background:var(--orange)}
.asset-card.yellow::before{background:var(--yellow)}
.asset-card.teal::before{background:var(--teal)}
.asset-card.gray::before{background:var(--gray)}
.card-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px}
.asset-name{font-family:'Syne',sans-serif;font-size:13px;font-weight:700;color:var(--text-bright)}
.asset-ticker{font-size:10px;color:var(--text-dim);margin-top:1px;letter-spacing:1px}
.price-block{text-align:right;flex-shrink:0}
.price-value{font-family:'Syne',sans-serif;font-size:18px;font-weight:700;color:var(--gold)}
.price-change{font-size:11px;margin-top:1px}
.price-change.up{color:var(--green)}
.price-change.down{color:var(--red)}
.price-change.flat{color:var(--text-dim)}
.signal-badge{display:inline-block;padding:4px 10px;border-radius:4px;font-size:11px;font-weight:600;margin-bottom:6px}
.badge-green{background:var(--green-bg);color:var(--green);border:1px solid rgba(0,230,118,.3)}
.badge-red{background:var(--red-bg);color:var(--red);border:1px solid rgba(255,71,87,.3)}
.badge-orange{background:var(--orange-bg);color:var(--orange);border:1px solid rgba(255,167,38,.3)}
.badge-yellow{background:var(--yellow-bg);color:var(--yellow);border:1px solid rgba(255,238,88,.3)}
.badge-teal{background:var(--teal-bg);color:var(--teal);border:1px solid rgba(38,198,218,.3)}
.badge-gray{background:var(--gray-bg);color:var(--gray);border:1px solid rgba(84,110,122,.3)}
.signal-action{font-size:11px;color:var(--text);margin-bottom:10px;line-height:1.5}
.indicators{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)}
.ind-block{text-align:center}
.ind-label{font-size:9px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px}
.ind-value{font-size:12px;font-weight:600}
.ind-value.bullish{color:var(--green)}
.ind-value.bearish{color:var(--red)}
.ind-value.neutral{color:var(--text-dim)}
.ind-value.overbought{color:var(--orange)}
.ind-value.oversold{color:var(--teal)}
.source-tg{font-size:9px;font-weight:700;padding:1px 4px;border-radius:3px;background:rgba(38,198,218,.15);border:1px solid rgba(38,198,218,.4);color:var(--teal);margin-left:5px;vertical-align:middle;letter-spacing:.5px}
.ma-row{margin-top:6px;padding-top:6px;border-top:1px dashed var(--border);grid-template-columns:1fr 1fr 1fr 1fr 1fr}
.ind-value.sr-sup{color:var(--green);font-size:10px}
.ind-value.sr-res{color:var(--red);font-size:10px}
.fibo-zones{margin-top:8px;display:flex;gap:6px;flex-wrap:wrap}
.fibo-pill{font-size:10px;padding:2px 7px;border-radius:3px;background:var(--bg3);border:1px solid var(--border);color:var(--text-dim)}
.fibo-pill.active{background:rgba(61,122,237,.12);border-color:rgba(61,122,237,.4);color:#7ab4ff}
.error-note{background:var(--red-bg);border:1px solid rgba(255,71,87,.3);border-radius:6px;padding:10px 14px;font-size:11px;color:var(--red);margin-bottom:16px}
.footer{margin-top:28px;padding-top:16px;border-top:1px solid var(--border);color:var(--text-dim);font-size:10px;text-align:center;line-height:2}
.chart-toggle{width:100%;margin-top:10px;padding:5px;background:var(--bg3);border:1px solid var(--border);border-radius:4px;color:var(--text-dim);font-size:10px;font-family:'JetBrains Mono',monospace;cursor:pointer;text-align:center;letter-spacing:1px;text-transform:uppercase}
.chart-toggle:hover{border-color:var(--accent);color:var(--accent)}
.chart-wrap{display:none;margin-top:8px;border-radius:4px;overflow:hidden}
.chart-wrap.open{display:block}
.fibo-auto-row{margin-top:6px;display:flex;gap:5px;flex-wrap:wrap;align-items:center}
.fibo-auto-label{font-size:9px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px;white-space:nowrap}
.fibo-alert-pill{display:block;padding:4px 10px;border-radius:4px;font-size:10px;font-weight:600;background:rgba(255,238,88,.12);border:1px solid rgba(255,238,88,.4);color:var(--yellow);margin-top:6px;text-align:center}
.fibo-alert-pill.close{background:rgba(255,167,38,.15);border-color:rgba(255,167,38,.6);color:var(--orange);animation:pulse-border 1.5s ease-in-out infinite}
@keyframes pulse-border{0%,100%{border-color:rgba(255,167,38,.6)}50%{border-color:rgba(255,167,38,1)}}
.fibo-recalib-pill{display:block;padding:3px 8px;border-radius:3px;font-size:10px;background:rgba(84,110,122,.12);border:1px dashed var(--gray);color:var(--gray);margin-top:4px;text-align:center}
/* Tier badges */
.tier-row{display:flex;align-items:center;gap:8px;margin:8px 0 4px;flex-wrap:wrap}
.tier-bar{display:flex;gap:2px}
.tb-filled,.tb-empty{width:10px;height:10px;border-radius:2px}
.tb-empty{background:var(--border)}
.tb-filled.t3{background:var(--green)}
.tb-filled.t2{background:var(--yellow)}
.tb-filled.t1{background:var(--teal)}
.tb-filled.t0{background:var(--gray)}
.tier-badge{display:inline-block;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:700}
.tier-badge.t3{background:var(--green-bg);color:var(--green);border:1px solid rgba(0,230,118,.3)}
.tier-badge.t2{background:var(--yellow-bg);color:var(--yellow);border:1px solid rgba(255,238,88,.3)}
.tier-badge.t1{background:var(--teal-bg);color:var(--teal);border:1px solid rgba(38,198,218,.3)}
.tier-badge.t0{background:var(--gray-bg);color:var(--gray);border:1px solid rgba(84,110,122,.3)}
.tier-label{font-size:11px;color:var(--text-dim)}
.tier-next{font-size:10px;color:var(--orange)}
/* Exit badges */
.exit-row{font-size:11px;color:var(--text-dim);margin-bottom:6px}
.exit-badge{display:inline-block;padding:2px 7px;border-radius:3px;font-size:10px;font-weight:700}
.ex-green{background:var(--green-bg);color:var(--green);border:1px solid rgba(0,230,118,.3)}
.ex-orange{background:var(--orange-bg);color:var(--orange);border:1px solid rgba(255,167,38,.3)}
.ex-red{background:var(--red-bg);color:var(--red);border:1px solid rgba(255,71,87,.3)}
.ex-teal{background:var(--teal-bg);color:var(--teal);border:1px solid rgba(38,198,218,.3)}
.ex-gray{background:var(--gray-bg);color:var(--gray);border:1px solid rgba(84,110,122,.3)}
/* Dynamic Fibonacci bar */
.fib-dyn-label{font-size:9px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px;margin-top:8px}
.fib-dyn-bar{position:relative;height:12px;background:var(--bg3);border-radius:2px;margin:4px 0 2px;overflow:hidden;border:1px solid var(--border)}
.fib-seg{position:absolute;top:0;height:100%;opacity:0.4}
.fib-marker{position:absolute;top:0;width:2px;height:100%;background:var(--gold);z-index:2}
.fib-dyn-vals{display:flex;justify-content:space-between;font-size:9px;color:var(--text-dim);flex-wrap:wrap}
/* Summary banner */
.summary-banner{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap;align-items:center}
.sum-pill{padding:7px 14px;border-radius:5px;border:1px solid;font-size:12px;font-weight:700;font-family:'Syne',sans-serif}
.sum-t3{background:var(--green-bg);border-color:var(--green);color:var(--green)}
.sum-t2{background:var(--yellow-bg);border-color:var(--yellow);color:var(--yellow)}
.sum-t1{background:var(--teal-bg);border-color:var(--teal);color:var(--teal)}
.sum-t0{background:var(--gray-bg);border-color:var(--gray);color:var(--gray)}
.sum-exit{background:var(--red-bg);border-color:var(--red);color:var(--red)}
.risk-badge{margin-left:auto;padding:7px 14px;border-radius:5px;font-size:11px;font-weight:700;letter-spacing:1px}
.risk-HIGH{background:var(--red-bg);border:1px solid var(--red);color:var(--red)}
.risk-MEDIUM{background:var(--orange-bg);border:1px solid var(--orange);color:var(--orange)}
.risk-LOW{background:var(--green-bg);border:1px solid var(--green);color:var(--green)}
/* ETF Ranking */
.etf-ranking{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px;margin-bottom:20px}
.etf-rank-card{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:10px 12px;display:flex;align-items:center;gap:8px}
.etf-rank-card.first{border-color:var(--gold);background:rgba(255,213,79,.04)}
.etf-rank-num{font-size:18px;font-weight:800;font-family:'Syne',sans-serif;color:var(--text-dim);width:22px}
.etf-rank-card.first .etf-rank-num{color:var(--gold)}
.etf-rank-info .name{font-weight:700;color:var(--text-bright);font-size:12px}
.etf-rank-info .rsi{font-size:10px;color:var(--text-dim)}
/* Cross signals */
.cross-signals{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin-bottom:20px}
.cross-card{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:10px 14px}
.cross-card .cc-label{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--text-dim);margin-bottom:4px}
.cross-card .cc-value{font-size:14px;font-weight:700;font-family:'Syne',sans-serif}
.cc-green{color:var(--green)}.cc-red{color:var(--red)}.cc-yellow{color:var(--yellow)}.cc-teal{color:var(--teal)}.cc-gray{color:var(--gray)}
@media(max-width:900px){
  .assets-grid{grid-template-columns:1fr}
  body{padding:12px}
}
@media(max-width:520px){
  .header{flex-direction:column}
  .timestamp{text-align:left}
  .price-value{font-size:15px}
  body{padding:8px}
}
"""

# ── BUILD FULL HTML ───────────────────────────────────────────────────────────

def build_html(now, cards_by_cat, conds, errors, charts_json="{}"):

    # Summary banner
    summary_html = (
        "<div class='summary-banner'>"
        + "<div class='sum-pill sum-t3'>T3 : " + str(conds["t3"]) + "</div>"
        + "<div class='sum-pill sum-t2'>T2 : " + str(conds["t2"]) + "</div>"
        + "<div class='sum-pill sum-t1'>T1 : " + str(conds["t1"]) + "</div>"
        + "<div class='sum-pill sum-t0'>T0 : " + str(conds["t0"]) + "</div>"
        + "<div class='sum-pill sum-exit'>" + str(conds["exits"]) + " sortie(s) active(s)</div>"
        + "<div class='risk-badge risk-" + conds["risk"] + "'>RISQUE : " + conds["risk"] + "</div>"
        + "</div>"
    )

    # ETF ranking
    etf_html = "<div class='section-title'>Classement ETF — Premier de la classe</div><div class='etf-ranking'>"
    for item in conds.get("etf_ranking", []):
        is_first = item["rank"] == 1
        etf_html += (
            "<div class='etf-rank-card" + (" first" if is_first else "") + "'>"
            + "<div class='etf-rank-num'>#" + str(item["rank"]) + "</div>"
            + "<div class='etf-rank-info'>"
            + "<div class='name'>" + item["ticker"] + (" 🥇" if is_first else "") + "</div>"
            + "<div class='rsi'>RSI D: <span class='" + rc(item.get("rsi_d")) + "'>" + (str(item["rsi_d"]) if item.get("rsi_d") else "—") + "</span></div>"
            + "<span class='tier-badge t" + str(item["tier"]) + "'>T" + str(item["tier"]) + "</span>"
            + "</div></div>"
        )
    etf_html += "</div>"

    # Cross signals
    cross = conds.get("cross", {})
    metals_conv = cross.get("metals_conviction","normal")
    btc_death   = cross.get("btc_death_cross", False)
    etf_first   = cross.get("etf_first","—")
    etf_t1      = cross.get("etf_t1_count", 0)
    cross_html = (
        "<div class='section-title'>Signaux Croises</div>"
        + "<div class='cross-signals'>"
        + "<div class='cross-card'><div class='cc-label'>Conviction Metaux</div><div class='cc-value cc-" + ("green" if metals_conv=="high" else "yellow") + "'>" + metals_conv.upper() + "</div></div>"
        + "<div class='cross-card'><div class='cc-label'>BTC MA Cross</div><div class='cc-value cc-" + ("red" if btc_death else "green") + "'>" + ("DEATH CROSS" if btc_death else "OK") + "</div></div>"
        + "<div class='cross-card'><div class='cc-label'>ETF Premier de classe</div><div class='cc-value cc-yellow'>" + str(etf_first) + "</div><div style='font-size:10px;color:var(--text-dim)'>" + str(etf_t1) + " ETF(s) en T1+</div></div>"
        + "</div>"
    )

    TITLES = {
        "metaux":  "ETCs Metaux Precieux · CTO",
        "crypto":  "Crypto",
        "actions": "ETFs Actions · CTO",
    }
    ORDER = ["metaux", "crypto", "actions"]
    cards_html = ""
    for cat in ORDER:
        if cards_by_cat.get(cat):
            cards_html += (
                "<div class='section-title'>" + TITLES[cat] + "</div>"
                + "<div class='assets-grid'>" + cards_by_cat[cat] + "</div>"
            )

    err_html = ""
    if errors:
        err_html = "<div class='error-note'>Donnees indisponibles : " + ", ".join(errors) + "</div>"

    return (
        "<!DOCTYPE html><html lang='fr'><head>"
        + "<meta charset='UTF-8'>"
        + "<meta name='viewport' content='width=device-width,initial-scale=1.0'>"
        + "<title>Portfolio Signal Dashboard — CTO</title>"
        + "<link href='https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Syne:wght@400;600;700;800&display=swap' rel='stylesheet'>"
        + "<style>" + CSS + "</style>"
        + "</head><body><div class='wrapper'>"

        + "<div class='header'>"
        + "<div class='header-left'><h1>Portfolio <span>CTO</span> Dashboard</h1>"
        + "<div class='subtitle'>MACD 12/26/9 · RSI 14 · Fibonacci ATH · Tier 1-2-3 · Yahoo Finance</div></div>"
        + "<div class='timestamp'><div class='date'>" + now.strftime("%d/%m/%Y") + "</div>"
        + "<div>Mise a jour : " + now.strftime("%H:%M:%S") + "</div></div>"
        + "</div>"

        + summary_html + etf_html + cross_html + err_html + cards_html

        + "<div class='footer'>Donnees : Yahoo Finance · MACD(12,26,9) · RSI(14) · Fibonacci ATH · MA50/MA200 · Support/Résistance · Tier 1-2-3"
        + "<br>Analyse personnelle — Pas un conseil financier · Relancer le script pour actualiser</div>"
        + "</div>"
        + "<script src='https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js'></script>"
        + "<script>"
        + "const CHARTS=(" + charts_json + ");"
        + """
document.addEventListener('DOMContentLoaded',function(){
  for(const [key,d] of Object.entries(CHARTS)){
    const el=document.getElementById('chart-'+key);
    if(!el||!d.ohlcv||!d.ohlcv.length) continue;
    const chart=LightweightCharts.createChart(el,{
      width:el.clientWidth,height:260,
      layout:{background:{color:'#0d1420'},textColor:'#c8d8f0'},
      grid:{vertLines:{color:'#1e2d45'},horzLines:{color:'#1e2d45'}},
      timeScale:{borderColor:'#1e2d45',timeVisible:true},
      rightPriceScale:{borderColor:'#1e2d45',scaleMargins:{top:0.08,bottom:0.22}},
      crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
    });
    // Bougies
    const candles=chart.addCandlestickSeries({
      upColor:'#00e676',downColor:'#ff4757',
      borderVisible:false,
      wickUpColor:'#00e676',wickDownColor:'#ff4757',
    });
    candles.setData(d.ohlcv.map(c=>({time:c.time,open:c.open,high:c.high,low:c.low,close:c.close})));
    // Volume (histogramme superposé, échelle séparée)
    const volSeries=chart.addHistogramSeries({
      priceFormat:{type:'volume'},
      priceScaleId:'vol',
    });
    chart.priceScale('vol').applyOptions({scaleMargins:{top:0.82,bottom:0},borderVisible:false});
    volSeries.setData(d.ohlcv.map(c=>({
      time:c.time,value:c.volume,
      color:c.up?'rgba(0,230,118,0.25)':'rgba(255,71,87,0.25)',
    })));
    // Zones S/R uniquement
    const srColors={resistance:'#ff4757',support:'#00e676',both:'#ffa726'};
    for(const z of (d.zones||[])){
      candles.createPriceLine({
        price:z.price,
        color:srColors[z.type]||'#ffa726',
        lineWidth:z.strength==='strong'?2:1,
        lineStyle:z.strength==='weak'?LightweightCharts.LineStyle.Dashed:LightweightCharts.LineStyle.Solid,
        axisLabelVisible:z.strength!=='weak',
        title:z.strength==='strong'?'● '+z.type.toUpperCase():'○',
      });
    }
    // MA50 (or)
    if(d.ma50_series&&d.ma50_series.length){
      const ma50=chart.addLineSeries({color:'#ffd54f',lineWidth:1,priceLineVisible:false,lastValueVisible:true,title:'MA50'});
      ma50.setData(d.ma50_series);
    }
    // MA200 (orange)
    if(d.ma200_series&&d.ma200_series.length){
      const ma200=chart.addLineSeries({color:'#ff7043',lineWidth:1,priceLineVisible:false,lastValueVisible:true,title:'MA200'});
      ma200.setData(d.ma200_series);
    }
    // Prix actuel
    if(d.prix) candles.createPriceLine({
      price:d.prix,color:'#ffd54f',lineWidth:1,
      lineStyle:LightweightCharts.LineStyle.Dashed,
      axisLabelVisible:true,title:'▶',
    });
    chart.timeScale().fitContent();
    new ResizeObserver(()=>chart.applyOptions({width:el.clientWidth})).observe(el);
  }
});
"""
        + "</script>"
        + "</body></html>"
    )


# ── MAIN ──────────────────────────────────────────────────────────────────────

def generate_dashboard():
    now = datetime.now()
    print("\n" + "="*55)
    print("  PORTFOLIO CTO DASHBOARD - " + now.strftime("%d/%m/%Y %H:%M"))
    print("="*55 + "\n")

    all_data, errors = {}, []
    for key, cfg in TICKER_MAP.items():
        print("  -> " + key + " (" + cfg["primary"] + ")...")
        d = fetch_asset(
            cfg["primary"],
            isin_fallback=cfg.get("isin"),
            ticker_fallback=None,
            ticker_rt=cfg.get("ticker_rt"),
            fallbacks=cfg.get("fallbacks", []),
        )
        all_data[key] = d
        if d and not d.get("ok"):
            errors.append(key)

    signals    = {k: evaluate_signal(k, TICKER_MAP[k], all_data[k]) for k in TICKER_MAP}
    all_tiers  = {k: evaluate_tier(k, all_data[k]) for k in TICKER_MAP}
    all_exits  = {k: evaluate_exit_signal(k, all_data[k]) for k in TICKER_MAP}

    tier_counts = {t: sum(1 for k in TICKER_MAP if all_tiers[k]["tier"] == t) for t in range(4)}
    exit_count  = sum(1 for k in TICKER_MAP if all_exits[k]["status"] in ["SELL_50","SELL_100"])

    # ETF ranking (tri par RSI D croissant = le plus survendu en premier)
    etf_ranking = sorted(
        [{"ticker": k,
          "rsi_d": all_data[k]["daily"]["rsi"] if all_data[k] and all_data[k].get("ok") else None,
          "tier": all_tiers[k]["tier"]}
         for k in ETF_KEYS if all_data.get(k) and all_data[k].get("ok")],
        key=lambda x: x["rsi_d"] if x["rsi_d"] else 999
    )
    for i, item in enumerate(etf_ranking):
        item["rank"] = i + 1

    # Cross-asset signals
    gold_t  = all_tiers.get("GOLD", {}).get("tier", 0)
    phag_t  = all_tiers.get("PHAG", {}).get("tier", 0)
    btc_d   = all_data.get("BTC") or {}
    btc_death = btc_d.get("ma_cross") == "death" if btc_d.get("ok") else False
    etf_first = etf_ranking[0]["ticker"] if etf_ranking else "—"
    etf_t1    = sum(1 for k in ETF_KEYS if all_tiers.get(k, {}).get("tier", 0) >= 1)

    risk = "HIGH" if btc_death or exit_count > 0 else ("LOW" if tier_counts[3] > 0 else "MEDIUM")

    conds = {
        "t3": tier_counts[3], "t2": tier_counts[2], "t1": tier_counts[1], "t0": tier_counts[0],
        "exits": exit_count, "risk": risk,
        "etf_ranking": etf_ranking,
        "cross": {
            "metals_conviction": "high" if gold_t >= 2 and phag_t >= 2 else "normal",
            "btc_death_cross": btc_death,
            "etf_first": etf_first,
            "etf_t1_count": etf_t1,
        },
    }

    cards_by_cat = {"metaux": "", "crypto": "", "actions": ""}
    for key, cfg in TICKER_MAP.items():
        cards_by_cat[cfg["categorie"]] += build_card(key, cfg, all_data[key], signals[key])

    # Données chart par actif
    import json as _json
    charts_data = {}
    for key, d in all_data.items():
        if not d or not d.get("ok") or not d.get("ohlcv"):
            continue
        charts_data[key] = {
            "prix":        d["prix"],
            "ohlcv":       d["ohlcv"],
            "fibo_auto":   {str(r): v for r, v in d.get("fibo_auto", {}).items()},
            "zones":       d.get("sr_zones", []),
            "ma50_series":  d.get("ma50_series",  []),
            "ma200_series": d.get("ma200_series", []),
        }
    charts_json = _json.dumps(charts_data, ensure_ascii=False)

    html = build_html(now, cards_by_cat, conds, errors, charts_json)
    out  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    print("\n  Dashboard genere : " + out)
    print("\n  Signaux actifs :")
    for key, sig in signals.items():
        if sig["color"] in ["green", "teal"]:
            print("    [OK] " + key + " - " + sig["label"])
    print()
    if not os.environ.get("CI"):
        webbrowser.open("file://" + out)
    return out


# ── RÉSUMÉ CLAUDE ────────────────────────────────────────────────────────────

def generate_claude_summary():
    """
    Génère un bloc texte compact à coller dans Claude.ai pour mettre à jour
    les signaux techniques en mémoire et obtenir une analyse combinée technique+macro.
    """
    now = datetime.now()
    print("\n" + "="*55)
    print("  GENERATION RESUME CLAUDE - " + now.strftime("%d/%m/%Y %H:%M"))
    print("="*55 + "\n")

    all_data = {}
    for key, cfg in TICKER_MAP.items():
        print("  -> " + key + " (" + cfg["primary"] + ")...")
        all_data[key] = fetch_asset(
            cfg["primary"],
            isin_fallback=cfg.get("isin"),
            fallbacks=cfg.get("fallbacks", []),
        )

    signals   = {k: evaluate_signal(k, TICKER_MAP[k], all_data[k]) for k in TICKER_MAP}
    all_tiers = {k: evaluate_tier(k, all_data[k]) for k in TICKER_MAP}
    all_exits = {k: evaluate_exit_signal(k, all_data[k]) for k in TICKER_MAP}

    def g(key, field, tf="daily", digits=2):
        d = all_data.get(key)
        if not d or not d.get("ok"): return None
        val = d.get(tf, {}).get(field)
        if val is None: return None
        if isinstance(val, float): return round(val, digits)
        return val

    def px(key, digits=2):
        d = all_data.get(key)
        if not d or not d.get("ok") or not d["prix"]: return None
        return round(d["prix"], digits)

    def vr(key):
        d = all_data.get(key)
        if not d or not d.get("ok"): return None
        return d.get("variation")

    # Construction du JSON de snapshot
    snapshot = {
        "date": now.strftime("%d/%m/%Y %H:%M"),
        "portfolio": "CTO_AGGRESSIVE",
        "assets": {}
    }

    for key in TICKER_MAP:
        d   = all_data.get(key)
        ok    = d and d.get("ok")
        ma50  = round(d["ma50"],  2) if ok and d.get("ma50")  else None
        ma200 = round(d["ma200"], 2) if ok and d.get("ma200") else None
        n_sup = d.get("nearest_sup") if d else None
        n_res = d.get("nearest_res") if d else None
        # Zones S/R complètes (jusqu'à 5 niveaux triés par force)
        sr_zones = d.get("sr_zones", []) if d else []
        sr_detail = [
            {
                "prix":     round(z["price"], 4),
                "type":     z["type"],
                "force":    z["strength"],
                "touches":  z["touches"],
                "position": "below" if z["price"] < (d["prix"] or 0) else "above",
            }
            for z in sorted(sr_zones, key=lambda z: z["touches"], reverse=True)[:5]
        ]
        fib = d.get("fibonacci", {}) if ok else {}
        tier_info = all_tiers.get(key, {})
        exit_info = all_exits.get(key, {})
        snapshot["assets"][key] = {
            "prix":       px(key, 2),
            "prix_source": d.get("prix_source", "yahoo") if ok else None,
            "var_pct":    vr(key),
            "rsi_d":      g(key, "rsi",       "daily"),
            "rsi_w":      g(key, "rsi",       "weekly"),
            "macd_d":     g(key, "crossover", "daily",  0),
            "macd_w":     g(key, "crossover", "weekly", 0),
            "ma50":       ma50,
            "ma200":      ma200,
            "ma_cross":   d.get("ma_cross") if ok else None,
            "prix_vs_ma50":  ("above" if ok and d["prix"] and ma50 and d["prix"] > ma50 else "below") if ma50 else None,
            "prix_vs_ma200": ("above" if ok and d["prix"] and ma200 and d["prix"] > ma200 else "below") if ma200 else None,
            "support":    {"prix": round(n_sup["price"], 4), "force": n_sup["strength"], "touches": n_sup["touches"]} if n_sup else None,
            "resistance": {"prix": round(n_res["price"], 4), "force": n_res["strength"], "touches": n_res["touches"]} if n_res else None,
            "zones_sr":   sr_detail,
            "fibonacci":  fib,
            "tier":       {"level": tier_info.get("tier",0), "pct": tier_info.get("pct",0), "label": tier_info.get("label",""), "next_missing": tier_info.get("next_missing")},
            "exit_signal": {"status": exit_info.get("status","UNKNOWN"), "rsi_w": exit_info.get("rsi_w"), "dist_sell50": exit_info.get("dist_sell50")},
            "signal":     signals[key]["label"],
            "color":      signals[key]["color"],
        }

    snapshot["summary"] = {
        "tier_3": sum(1 for k in TICKER_MAP if all_tiers[k]["tier"]==3),
        "tier_2": sum(1 for k in TICKER_MAP if all_tiers[k]["tier"]==2),
        "tier_1": sum(1 for k in TICKER_MAP if all_tiers[k]["tier"]==1),
        "tier_0": sum(1 for k in TICKER_MAP if all_tiers[k]["tier"]==0),
        "exit_signals_active": sum(1 for k in TICKER_MAP if all_exits[k]["status"] in ["SELL_50","SELL_100"]),
    }

    json_str = json.dumps(snapshot, ensure_ascii=False, indent=2)

    # Bloc à coller dans Claude
    bloc = (
        "\n" + "="*60 + "\n"
        + "  COLLE CE BLOC DANS CLAUDE.AI POUR MISE A JOUR\n"
        + "="*60 + "\n\n"
        + "[CLAUDE UPDATE]\n"
        + json_str
        + "\n[/CLAUDE UPDATE]\n\n"
        + "Message suggéré :\n"
        + "  \"Voici le snapshot du jour. Mets à jour tes données techniques\n"
        + "   et donne-moi une analyse combinée technique + macro.\"\n"
        + "="*60 + "\n"
    )

    print(bloc)

    # Sauvegarde dans un fichier texte à côté du script
    summary_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_update.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(bloc)
    print("  Fichier sauvegarde : " + summary_path + "\n")

    return snapshot


if __name__ == "__main__":
    import sys
    if "--claude" in sys.argv:
        # Mode résumé Claude uniquement : python dashboard_claude.py --claude
        generate_claude_summary()
    else:
        # Mode normal : génère le dashboard HTML + résumé Claude
        generate_dashboard()
        generate_claude_summary()
