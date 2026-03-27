"""
Récupération des données de marché : Euronext, Tradegate, yfinance.
"""

import yfinance as yf
import pandas as pd
import requests

from dashboard_indicators import (
    calc_rsi,
    compute_macd_detailed,
    calculate_fibonacci_levels,
    get_current_fib_zone,
    detect_sr_zones,
    calc_atr,
    enrich_sr_zones,
    compute_nearest_zone,
)
from dashboard_config import SR_ZONE_ATR_MULTIPLIER


def fetch_euronext_price(isin, mic="ETFP"):
    """
    Récupère le dernier prix depuis l'API intraday d'Euronext Live.
    Endpoint : /en/instruments_intraday_chart_data/{ISIN}-{MIC}/1D
    Retourne un float ou None.
    """
    try:
        url = ("https://live.euronext.com/en/instruments_intraday_chart_data/"
               + isin + "-" + mic + "/1D")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, */*",
            "Referer": "https://live.euronext.com/fr/product/etfs/" + isin + "-" + mic,
        }
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        # Format attendu : {"d": [{"time": "HH:MM", "price": 157.24}, ...]}
        # ou : {"d": [[timestamp_ms, price, volume], ...]}
        series = data.get("d", [])
        if not series:
            return None
        last = series[-1]
        if isinstance(last, dict):
            for field in ("price", "last", "value", "close"):
                if field in last:
                    val = last[field]
                    if isinstance(val, str):
                        val = val.replace(",", ".")
                    return round(float(val), 4)
        elif isinstance(last, (list, tuple)) and len(last) >= 2:
            return round(float(last[1]), 4)
    except Exception as e:
        print("  [ERR Euronext] " + isin + "-" + mic + ": " + str(e))
    return None


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


def fetch_asset(ticker, isin_fallback=None, ticker_fallback=None, ticker_rt=None, fallbacks=None, euronext_mic=None):
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
            # Dernier recours : prix Euronext ou Tradegate uniquement (pas d'indicateurs)
            if isin_fallback:
                if euronext_mic:
                    print("  [INFO] " + ticker + " -> tentative prix Euronext (" + isin_fallback + "-" + euronext_mic + ")")
                    prix_tg = fetch_euronext_price(isin_fallback, euronext_mic)
                else:
                    print("  [INFO] " + ticker + " -> tentative prix Tradegate (" + isin_fallback + ")")
                    prix_tg = fetch_tradegate_price(isin_fallback)
                if prix_tg:
                    _neutral_macd = {"signal": "neutral", "macd_line": None, "signal_line": None,
                                     "histogram": None, "prev_histogram": None, "hist_trend": None,
                                     "distance_to_cross": None, "est_days_to_cross": None, "cross_imminent": False}
                    _empty = {"rsi": None, "macd": _neutral_macd}
                    return {"ok": True, "prix": prix_tg, "variation": None,
                            "source": "tradegate", "daily": _empty.copy(), "weekly": dict(_empty),
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
        macd_d_detail = compute_macd_detailed(close_d)
        if not df_w.empty:
            df_w["RSI"]  = calc_rsi(close_w)
            macd_w_detail = compute_macd_detailed(close_w)
        else:
            macd_w_detail = {"signal": "neutral", "macd_line": None, "signal_line": None,
                             "histogram": None, "prev_histogram": None, "hist_trend": None,
                             "distance_to_cross": None, "est_days_to_cross": None, "cross_imminent": False}
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

        # Zones S/R — détection sur 2 ans (enrichissement ATR)
        df_2y = df_d.iloc[-504:]
        ohlcv_sr = []
        for i in range(len(df_2y)):
            try:
                t2 = df_2y.index[i]
                t2 = t2.date().isoformat() if hasattr(t2, "date") else str(t2)[:10]
                ohlcv_sr.append({
                    "time":   t2,
                    "high":   round(float(_col(df_2y, "High").iloc[i]), 4),
                    "low":    round(float(_col(df_2y, "Low").iloc[i]),  4),
                    "open":   round(float(_col(df_2y, "Open").iloc[i]), 4),
                    "close":  round(float(_col(df_2y, "Close").iloc[i]), 4),
                    "volume": int(float(_col(df_2y, "Volume").iloc[i])),
                })
            except Exception:
                pass
        atr_14   = calc_atr(df_d)
        sr_raw   = detect_sr_zones(ohlcv_sr, prix)
        sr_zones = enrich_sr_zones(sr_raw, atr_14, prix, fib_levels, SR_ZONE_ATR_MULTIPLIER)
        nearest_sup = next((z for z in sorted(sr_zones, key=lambda z: z["price"], reverse=True) if z["price"] < prix), None)
        nearest_res = next((z for z in sorted(sr_zones, key=lambda z: z["price"]) if z["price"] > prix), None)
        nearest_zone = compute_nearest_zone(sr_zones, prix, close_d)

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

        # 3. Euronext ou Tradegate (si fast_info absent)
        if prix_source == "yahoo" and isin_fallback:
            if euronext_mic:
                _update_prix(fetch_euronext_price(isin_fallback, euronext_mic), "euronext")
            else:
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
            "atr_14": atr_14,
            "ma50":  ma50_val, "ma200": ma200_val, "ma_cross": ma_cross,
            "ma50_series": ma50_data, "ma200_series": ma200_data,
            "sr_zones": sr_zones,
            "nearest_sup": nearest_sup, "nearest_res": nearest_res,
            "nearest_zone": nearest_zone,
            "daily": {
                "rsi":  round(float(df_d["RSI"].iloc[-1]), 1),
                "macd": macd_d_detail,
            },
            "weekly": {
                "rsi":  round(float(df_w["RSI"].iloc[-1]), 1) if not df_w.empty else None,
                "macd": macd_w_detail,
            },
        }
    except Exception as e:
        print("  [ERR] " + ticker + ": " + str(e))
        _neutral_macd = {"signal": "neutral", "macd_line": None, "signal_line": None,
                         "histogram": None, "prev_histogram": None, "hist_trend": None,
                         "distance_to_cross": None, "est_days_to_cross": None, "cross_imminent": False}
        _empty = {"rsi": None, "macd": _neutral_macd}
        return {"ok": False, "prix": None, "variation": None,
                "swing": {"high": None, "low": None}, "fibo_auto": {}, "fibonacci": {}, "ohlcv": [],
                "atr_14": None,
                "ma50": None, "ma200": None, "ma_cross": None,
                "ma50_series": [], "ma200_series": [], "sr_zones": [],
                "nearest_sup": None, "nearest_res": None, "nearest_zone": None,
                "daily": _empty.copy(), "weekly": dict(_empty)}


def fetch_stock_picking_asset(ticker, fallbacks=None):
    """Récupère les données pour une action de stock picking avec indicateurs swing."""
    try:
        all_tickers = [ticker] + (fallbacks or [])
        tk = None
        df_d = None
        df_w = None
        for t in all_tickers:
            tk_try   = yf.Ticker(t)
            df_d_try = tk_try.history(period="2y", interval="1d")
            df_w_try = tk_try.history(period="5y", interval="1wk")
            if not df_d_try.empty:
                tk  = tk_try
                df_d = df_d_try
                df_w = df_w_try
                break

        if df_d is None or df_d.empty:
            return None

        def _c(df, col):
            c = df[col]
            return c.iloc[:, 0] if hasattr(c, "columns") else c

        close_d = _c(df_d, "Close")
        close_w = _c(df_w, "Close") if not df_w.empty else None

        prix      = round(float(close_d.iloc[-1]), 4)
        variation = round(float((close_d.iloc[-1] / close_d.iloc[-2] - 1) * 100), 2)

        rsi_d = round(float(calc_rsi(close_d).iloc[-1]), 1)
        rsi_w = round(float(calc_rsi(close_w).iloc[-1]), 1) if close_w is not None else None

        macd_d_detail = compute_macd_detailed(close_d)
        macd_w_detail = compute_macd_detailed(close_w) if close_w is not None else None

        ma50_s  = close_d.rolling(50).mean()
        ma200_s = close_d.rolling(200).mean()
        ma50  = round(float(ma50_s.iloc[-1]),  4) if not pd.isna(ma50_s.iloc[-1])  else None
        ma200 = round(float(ma200_s.iloc[-1]), 4) if not pd.isna(ma200_s.iloc[-1]) else None
        ma_cross = ("golden" if ma50 and ma200 and ma50 > ma200 else
                    "death"  if ma50 and ma200 else None)

        # Fibonacci dynamique
        try:
            fib_levels = calculate_fibonacci_levels(df_d)
            fib_levels["current_zone"] = get_current_fib_zone(prix, fib_levels)
        except Exception:
            fib_levels = {}

        # OHLCV 2 ans pour S/R
        df_2y = df_d.iloc[-504:]
        ohlcv = []
        for i in range(len(df_2y)):
            try:
                t = df_2y.index[i]
                t = t.date().isoformat() if hasattr(t, "date") else str(t)[:10]
                o = round(float(_c(df_2y, "Open").iloc[i]),  4)
                c = round(float(_c(df_2y, "Close").iloc[i]), 4)
                ohlcv.append({"time": t, "open": o,
                              "high": round(float(_c(df_2y, "High").iloc[i]), 4),
                              "low":  round(float(_c(df_2y, "Low").iloc[i]),  4),
                              "close": c, "volume": int(float(_c(df_2y, "Volume").iloc[i])),
                              "up": c >= o})
            except Exception:
                pass

        sr_zones = detect_sr_zones(ohlcv, prix)

        # Volume relatif 20j
        vol_series   = _c(df_d, "Volume")
        avg_vol_20   = float(vol_series.tail(20).mean())
        curr_vol     = float(vol_series.iloc[-1])
        low_liquidity = avg_vol_20 < 5000
        volume = {
            "current":  int(curr_vol),
            "avg_20d":  int(avg_vol_20),
            "relative": round(curr_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 0,
            "surge":    curr_vol > avg_vol_20 * 1.5,
            "low_liquidity": low_liquidity,
        }

        # Bollinger Bands
        sma_20 = float(close_d.tail(20).mean())
        std_20 = float(close_d.tail(20).std())
        bw     = (4 * std_20) / sma_20 * 100 if sma_20 else 0
        bollinger = {
            "upper":     round(sma_20 + 2 * std_20, 4),
            "middle":    round(sma_20, 4),
            "lower":     round(sma_20 - 2 * std_20, 4),
            "bandwidth": round(bw, 2),
            "price_position": ("above_upper" if prix > sma_20 + 2 * std_20
                               else "below_lower" if prix < sma_20 - 2 * std_20
                               else "inside"),
            "squeeze": bw < 5,
        }

        # Performance multi-périodes
        def _perf(n):
            return round((float(close_d.iloc[-1]) / float(close_d.iloc[-n-1]) - 1) * 100, 2) if len(close_d) > n else None

        performance = {
            "1d":  round(variation, 2),
            "5d":  _perf(5),
            "20d": _perf(20),
            "60d": _perf(60),
        }

        # Range 52 semaines
        high_52w = float(_c(df_d, "High").tail(252).max())
        low_52w  = float(_c(df_d, "Low").tail(252).min())
        range_52w = {
            "high": round(high_52w, 4),
            "low":  round(low_52w,  4),
            "pct_from_high": round((prix / high_52w - 1) * 100, 2),
            "pct_from_low":  round((prix / low_52w  - 1) * 100, 2),
        }

        return {
            "ok": True, "prix": prix, "variation": variation,
            "rsi_d": rsi_d, "rsi_w": rsi_w,
            "macd_d": macd_d_detail, "macd_w": macd_w_detail,
            "ma50": ma50, "ma200": ma200, "ma_cross": ma_cross,
            "fibonacci": fib_levels,
            "zones_sr": sr_zones,
            "volume": volume,
            "bollinger": bollinger,
            "performance": performance,
            "range_52w": range_52w,
            "ohlcv": ohlcv,
        }
    except Exception as e:
        print("  [ERR SP] " + ticker + ": " + str(e))
        return None
