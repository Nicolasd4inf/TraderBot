#!/usr/bin/env python3
"""
Portfolio Signal Dashboard Generator
=====================================
Génère un dashboard HTML avec les signaux techniques de tous les actifs du portefeuille.

Installation :
    pip install yfinance pandas numpy

Usage :
    python dashboard_generator.py
    -> Ouvre automatiquement dashboard.html dans le navigateur

Planification automatique :
    Windows : Planificateur de taches -> executer chaque matin a 9h
    Mac/Linux : crontab -e -> 0 9 * * 1-5 python /chemin/dashboard_generator.py
"""

import yfinance as yf
import pandas as pd
import numpy as np
import webbrowser
import os
import requests
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────

ASSETS = {
    "PPFB":  {"ticker": "PPFB.PA",   "nom": "Or — iShares Physical Gold",    "categorie": "metaux",  "devise": "€", "fibo_zones": [84, 78.5, 72],         "stop": 68,  "ticker_fallback": "PPFB.DE", "isin": "IE00B4ND3602"},
    "XAD6":  {"ticker": "XAD6.DE",   "nom": "Argent — Xtrackers Silver",     "categorie": "metaux",  "devise": "€", "fibo_zones": [660, 555, 480],        "stop": 400},
    "BTC":   {"ticker": "BTC-USD",   "nom": "Bitcoin",                        "categorie": "crypto",  "devise": "$", "fibo_zones": [70750, 57800, 39200],  "stop": 32000},
    "EURUSD":{"ticker": "EURUSD=X",  "nom": "EUR/USD",                        "categorie": "macro",   "devise": "",  "fibo_zones": [1.145, 1.108, 1.081],  "stop": None},
    "BRENT": {"ticker": "BZ=F",      "nom": "Brent Crude",                    "categorie": "macro",   "devise": "$", "fibo_zones": [90, 85],               "stop": None},
    "PUST":  {"ticker": "PUST.PA",   "nom": "Nasdaq 100 — Amundi PEA",       "categorie": "actions", "devise": "€", "fibo_zones": [84, 78.5, 74],         "stop": 61},
    "PSP5":  {"ticker": "PSP5.PA",   "nom": "S&P 500 — Amundi PEA",          "categorie": "actions", "devise": "€", "fibo_zones": [49.75, 47.12, 45],     "stop": 39},
    "PTPXE": {"ticker": "PTPXE.PA",  "nom": "Japon TOPIX — Amundi PEA",      "categorie": "actions", "devise": "€", "fibo_zones": [32.99, 30.5, 28.5],   "stop": 20},
    "PAASI": {"ticker": "PAASI.PA",  "nom": "Asia Emergente — Amundi PEA",   "categorie": "actions", "devise": "€", "fibo_zones": [30.61, 28.19, 26.25], "stop": 18},
}

TRIGGERS = {
    "eurusd_seuil":    1.15,
    "brent_actions":  90.0,
    "brent_japon":    85.0,
    "brent_critique": 110.0,
    "ppfb_zone1":     84.0,
    "xad6_zone1":     660.0,
    "btc_fibo50":     70750.0,
    "btc_fibo618":    57800.0,
}

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
        base_url = f"https://www.tradegate.de/orderbuch.php?isin={isin}"
        session.get(base_url, timeout=10)
        # 2. Appel de l'API JSON avec Referer
        session.headers["Referer"] = base_url
        r = session.get(f"https://www.tradegate.de/json/?isin={isin}", timeout=10)
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
        print(f"  [ERR Tradegate] {isin}: {e}")
    return None


def fetch_asset(ticker, isin_fallback=None, ticker_fallback=None):
    try:
        tk   = yf.Ticker(ticker)
        df_d = tk.history(period="6mo",  interval="1d")
        df_w = tk.history(period="2y",   interval="1wk")
        # Fallback ticker Yahoo Finance si données vides
        if df_d.empty and ticker_fallback:
            print(f"  [INFO] {ticker} vide → essai {ticker_fallback}")
            tk   = yf.Ticker(ticker_fallback)
            df_d = tk.history(period="6mo", interval="1d")
            df_w = tk.history(period="2y",  interval="1wk")
        if df_d.empty:
            # Dernier recours : prix Tradegate uniquement (pas d'indicateurs)
            if isin_fallback:
                print(f"  [INFO] {ticker} → tentative prix Tradegate ({isin_fallback})")
                prix_tg = fetch_tradegate_price(isin_fallback)
                if prix_tg:
                    _empty = {"rsi": None, "hist": None, "crossover": "neutral"}
                    return {"ok": True, "prix": prix_tg, "variation": None,
                            "source": "tradegate", "daily": _empty.copy(), "weekly": _empty.copy()}
            return None
        # Compatibilité yfinance 0.2.x (colonnes MultiIndex → aplatir)
        def _close(df):
            c = df["Close"]
            return c.iloc[:, 0] if hasattr(c, "columns") else c
        close_d = _close(df_d)
        close_w = _close(df_w) if not df_w.empty else None
        df_d["RSI"]  = calc_rsi(close_d)
        df_d["MACD"], df_d["Sig"], df_d["Hist"] = calc_macd(close_d)
        if not df_w.empty:
            df_w["RSI"]  = calc_rsi(close_w)
            df_w["MACD"], df_w["Sig"], df_w["Hist"] = calc_macd(close_w)
        prix      = round(float(close_d.iloc[-1]), 4)
        variation = round(float((close_d.iloc[-1] / close_d.iloc[-2] - 1) * 100), 2)
        # Fibo auto depuis le swing 6 mois
        high_6m = float(df_d["High"].max() if not hasattr(df_d["High"], "columns") else df_d["High"].iloc[:, 0].max())
        low_6m  = float(df_d["Low"].min()  if not hasattr(df_d["Low"],  "columns") else df_d["Low"].iloc[:, 0].min())
        fibo_auto = {r: round(high_6m - (high_6m - low_6m) * r, 4) for r in [0.236, 0.382, 0.500, 0.618, 0.786]}
        return {
            "ok": True, "prix": prix, "variation": variation,
            "swing": {"high": round(high_6m, 4), "low": round(low_6m, 4)},
            "fibo_auto": fibo_auto,
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
        print(f"  [ERR] {ticker}: {e}")
        _empty = {"rsi": None, "hist": None, "crossover": "neutral"}
        return {"ok": False, "prix": None, "variation": None,
                "swing": {"high": None, "low": None}, "fibo_auto": {},
                "daily": _empty.copy(), "weekly": _empty.copy()}

# ── LOGIQUE SIGNAL ────────────────────────────────────────────────────────────

def evaluate_signal(key, cfg, d):
    if not d or not d.get("ok"):
        return {"label": "DONNEES INDISPONIBLES", "color": "gray", "action": "—"}
    p      = d["prix"]
    rsi_d  = d["daily"]["rsi"]
    rsi_w  = d["weekly"]["rsi"]
    cd     = d["daily"]["crossover"]
    cw     = d["weekly"]["crossover"]

    if key == "EURUSD":
        ok = p and p < TRIGGERS["eurusd_seuil"]
        return {"label": "TRIGGER ATTEINT" if ok else "EN ATTENTE",
                "color": "green" if ok else "yellow",
                "action": "Renforcer ETCs Or &amp; Argent — EUR/USD=" + str(round(p,4)) if ok
                          else "Surveiller passage sous 1.15 — actuel: " + (str(round(p,4)) if p else "—")}

    if key == "BRENT":
        if p and p < TRIGGERS["brent_actions"]:
            return {"label": "SIGNAL ACTIONS", "color": "green",
                    "action": "ETFs PEA debloqués — attendre 3 clotures consecutives"}
        if p and p > TRIGGERS["brent_critique"]:
            return {"label": "NIVEAU CRITIQUE", "color": "red",
                    "action": "Brent &gt; 110$ — allegier actions, renforcer Or"}
        return {"label": "EN ATTENTE", "color": "orange",
                "action": "Actions bloquées — Brent=" + (str(round(p,2)) if p else "—") + "$ (seuil 90$)"}

    if key == "PPFB":
        if cw in ["bearish_cross","bearish"] and rsi_w and rsi_w > 70:
            return {"label": "CORRECTION EN COURS", "color": "orange",
                    "action": "RSI weekly " + str(rsi_w) + " surachat — attendre zone 82-84€"}
        if cd in ["bullish","bullish_cross"] and p and p <= TRIGGERS["ppfb_zone1"]:
            return {"label": "ZONE D'ACHAT", "color": "green",
                    "action": "MACD daily haussier + prix en zone 1 (82-84€)"}
        if p and p <= TRIGGERS["ppfb_zone1"]:
            return {"label": "ZONE 1 ATTEINTE", "color": "teal",
                    "action": "Prix en zone 82-84€ — surveiller croisement MACD daily"}
        return {"label": "EN ATTENTE", "color": "yellow",
                "action": "Attendre repli vers 84€ — actuel: " + (str(round(p,2)) if p else "—") + "€"}

    if key == "XAD6":
        if cd in ["bullish_cross","bullish"] and p and p <= TRIGGERS["xad6_zone1"]:
            return {"label": "SIGNAL ACTIF", "color": "green",
                    "action": "MACD daily haussier + zone 1 — ENTRER"}
        if cd in ["bullish_cross","bullish"]:
            return {"label": "MACD HAUSSIER", "color": "teal",
                    "action": "Signal actif mais prix au-dessus zone 1 (660€) — attendre repli"}
        if cd == "bearish_cross":
            return {"label": "CROISEMENT BAISSIER", "color": "red",
                    "action": "Croisement MACD daily baissier — ne pas entrer"}
        return {"label": "ATTENTE SIGNAL", "color": "yellow",
                "action": "Surveiller croisement MACD daily haussier"}

    if key == "BTC":
        if cw in ["bullish","bullish_cross"] and cd in ["bullish","bullish_cross"]:
            return {"label": "SIGNAL LONG TERME", "color": "green",
                    "action": "MACD weekly ET daily haussiers — acheter selon Fibonacci"}
        if cw in ["bearish","bearish_cross"]:
            if p and p < TRIGGERS["btc_fibo618"]:
                return {"label": "ZONE FIBO 61.8%", "color": "teal",
                        "action": "Zone dorée atteinte — surveiller MACD weekly"}
            if p and p < TRIGGERS["btc_fibo50"]:
                return {"label": "ZONE FIBO 50%", "color": "yellow",
                        "action": "Sous Fibo 50% — signal weekly absent"}
            return {"label": "BEAR MARKET", "color": "red",
                    "action": "MACD weekly baissier — NE PAS ACHETER"}
        return {"label": "NEUTRE", "color": "yellow", "action": "Surveiller MACD weekly"}

    if cfg["categorie"] == "actions":
        z1, z2 = cfg["fibo_zones"][0], cfg["fibo_zones"][1]
        if p and p <= z2:
            return {"label": "ZONE 2 FIBO", "color": "teal",
                    "action": "Zone 2 atteinte — conditionnel Brent &lt; 90$"}
        if p and p <= z1:
            return {"label": "ZONE 1 FIBO", "color": "yellow",
                    "action": "Zone 1 atteinte — conditionnel Brent &lt; 90$"}
        return {"label": "EN ATTENTE", "color": "gray",
                "action": "Brent &gt; 90$ requis — prix: " + (str(round(p,2)) if p else "—") + "€"}

    return {"label": "—", "color": "gray", "action": "—"}

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

def fibo_pills(prix, zones, devise):
    out = ""
    for z in zones:
        active = prix is not None and prix <= z * 1.05
        cls    = 'fibo-pill active' if active else 'fibo-pill'
        label  = "{:,}".format(z) if z > 100 else str(z)
        out   += "<span class='" + cls + "'>" + devise + label + "</span>"
    return out

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
    # Alerte niveaux statiques obsolètes (>15% d'écart)
    if static_zones and fibo_auto:
        auto_levels = list(fibo_auto.values())
        for sz in static_zones:
            if sz <= 0: continue
            nearest = min(auto_levels, key=lambda x: abs(x - sz))
            if abs(nearest - sz) / sz > 0.15:
                sh = _fmt_level(swing["high"], devise) if swing and swing["high"] else "—"
                sl = _fmt_level(swing["low"],  devise) if swing and swing["low"]  else "—"
                out += "<div class='fibo-recalib-pill'>&#x1F504; Niveaux a recalibrer · swing " + sl + " → " + sh + "</div>"
                break
    return out

def build_card(key, cfg, d, sig):
    prix_val  = d["prix"]      if d else None
    var_val   = d["variation"] if d else None
    rsi_d     = d["daily"]["rsi"]       if d else None
    rsi_w     = d["weekly"]["rsi"]      if d else None
    cd        = d["daily"]["crossover"]  if d else "neutral"
    cw        = d["weekly"]["crossover"] if d else "neutral"
    fa        = d.get("fibo_auto", {})  if d else {}
    swing     = d.get("swing")          if d else None
    var_str   = ("+" if var_val and var_val > 0 else "") + (str(var_val) + "%" if var_val is not None else "—")
    var_cls   = "up" if var_val and var_val > 0 else ("down" if var_val and var_val < 0 else "flat")
    color     = sig["color"]

    return (
        "<div class='asset-card " + color + "'>"
        + "<div class='card-top'>"
        + "<div>" + h("div","asset-name",cfg["nom"]) + h("div","asset-ticker",cfg["ticker"]) + "</div>"
        + "<div class='price-block'>"
        + h("div","price-value", cfg["devise"] + fmt_price(prix_val, cfg["devise"]))
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
        + "<div class='fibo-zones'>" + fibo_pills(prix_val, cfg["fibo_zones"], cfg["devise"]) + "</div>"
        + fibo_auto_pills(prix_val, fa, cfg["devise"])
        + fibo_alert(prix_val, fa, cfg["fibo_zones"], cfg["devise"], swing)
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
.header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid var(--border)}
.header-left h1{font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:var(--text-bright);letter-spacing:-.5px}
.header-left h1 span{color:var(--accent)}
.subtitle{color:var(--text-dim);font-size:11px;margin-top:4px;letter-spacing:1px;text-transform:uppercase}
.timestamp{text-align:right;color:var(--text-dim);font-size:11px;line-height:1.8}
.timestamp .date{color:var(--gold);font-size:14px;font-weight:600}
.conditions-bar{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:24px}
.cond-pill{padding:10px 14px;border-radius:6px;border:1px solid}
.cond-label{font-size:10px;text-transform:uppercase;letter-spacing:1px;opacity:.7}
.cond-value{font-size:15px;font-weight:700;font-family:'Syne',sans-serif;margin:3px 0}
.cond-status{font-size:10px}
.cond-pill.green{background:var(--green-bg);border-color:var(--green)}
.cond-pill.green .cond-value{color:var(--green)}
.cond-pill.red{background:var(--red-bg);border-color:var(--red)}
.cond-pill.red .cond-value{color:var(--red)}
.cond-pill.orange{background:var(--orange-bg);border-color:var(--orange)}
.cond-pill.orange .cond-value{color:var(--orange)}
.cond-pill.yellow{background:var(--yellow-bg);border-color:var(--yellow)}
.cond-pill.yellow .cond-value{color:var(--yellow)}
.cond-pill.teal{background:var(--teal-bg);border-color:var(--teal)}
.cond-pill.teal .cond-value{color:var(--teal)}
.section-title{font-family:'Syne',sans-serif;font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--text-dim);margin:20px 0 10px;display:flex;align-items:center;gap:8px}
.section-title::after{content:'';flex:1;height:1px;background:var(--border)}
.scenario-bar{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:16px 20px;margin-bottom:20px;display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.scenario-item{text-align:center}
.scenario-name{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--text-dim);margin-bottom:6px}
.scenario-prob{font-family:'Syne',sans-serif;font-size:28px;font-weight:800;margin-bottom:4px}
.scenario-desc{font-size:11px;color:var(--text-dim)}
.prob-bar-container{height:4px;background:var(--border);border-radius:2px;margin-top:8px;overflow:hidden}
.prob-bar{height:100%;border-radius:2px}
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
.price-block{text-align:right}
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
.fibo-zones{margin-top:8px;display:flex;gap:6px;flex-wrap:wrap}
.fibo-pill{font-size:10px;padding:2px 7px;border-radius:3px;background:var(--bg3);border:1px solid var(--border);color:var(--text-dim)}
.fibo-pill.active{background:rgba(61,122,237,.12);border-color:rgba(61,122,237,.4);color:#7ab4ff}
.error-note{background:var(--red-bg);border:1px solid rgba(255,71,87,.3);border-radius:6px;padding:10px 14px;font-size:11px;color:var(--red);margin-bottom:16px}
.footer{margin-top:28px;padding-top:16px;border-top:1px solid var(--border);color:var(--text-dim);font-size:10px;text-align:center;line-height:2}
.fibo-auto-row{margin-top:6px;display:flex;gap:5px;flex-wrap:wrap;align-items:center}
.fibo-auto-label{font-size:9px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px;white-space:nowrap}
.fibo-alert-pill{display:block;padding:4px 10px;border-radius:4px;font-size:10px;font-weight:600;background:rgba(255,238,88,.12);border:1px solid rgba(255,238,88,.4);color:var(--yellow);margin-top:6px;text-align:center}
.fibo-alert-pill.close{background:rgba(255,167,38,.15);border-color:rgba(255,167,38,.6);color:var(--orange);animation:pulse-border 1.5s ease-in-out infinite}
@keyframes pulse-border{0%,100%{border-color:rgba(255,167,38,.6)}50%{border-color:rgba(255,167,38,1)}}
.fibo-recalib-pill{display:block;padding:3px 8px;border-radius:3px;font-size:10px;background:rgba(84,110,122,.12);border:1px dashed var(--gray);color:var(--gray);margin-top:4px;text-align:center}
"""

# ── BUILD FULL HTML ───────────────────────────────────────────────────────────

def build_html(now, cards_by_cat, conds, errors):

    def cond_pill(color, label_top, value, status):
        return (
            "<div class='cond-pill " + color + "'>"
            + "<div class='cond-label'>" + label_top + "</div>"
            + "<div class='cond-value'>"  + value     + "</div>"
            + "<div class='cond-status'>" + status    + "</div>"
            + "</div>"
        )

    conditions_bar = (
        "<div class='conditions-bar'>"
        + cond_pill(conds["eu_col"],  "EUR/USD · Seuil 1,15", conds["eu_p"],  conds["eu_s"])
        + cond_pill(conds["br_col"],  "Brent · Seuil 90$",   conds["br_p"]+"$", conds["br_s"])
        + cond_pill(conds["xd_col"],  "XAD6 · MACD Daily",   conds["xd_l"],  conds["xd_d"])
        + cond_pill(conds["bt_col"],  "BTC · MACD Weekly",   conds["bt_l"],  conds["bt_d"])
        + "</div>"
    )

    def scen(name, pct, desc, clr):
        return (
            "<div class='scenario-item'>"
            + "<div class='scenario-name'>"  + name + "</div>"
            + "<div class='scenario-prob' style='color:" + clr + "'>" + pct + "</div>"
            + "<div class='scenario-desc'>"  + desc + "</div>"
            + "<div class='prob-bar-container'><div class='prob-bar' style='width:" + pct + ";background:" + clr + "'></div></div>"
            + "</div>"
        )

    scenarios = (
        "<div class='section-title'>Scenarios Geopolitiques</div>"
        + "<div class='scenario-bar'>"
        + scen("Scenario A — Desescalade",    "15%", "Resolution rapide Iran · Brent &lt; 80$",         "var(--green)")
        + scen("Scenario B — Conflit prolonge","60%", "Hormuz partiellement bloque · Brent 90-110$",    "var(--orange)")
        + scen("Scenario C — Escalade",        "25%", "Hormuz ferme · Brent &gt; 110$ · Recession",    "var(--red)")
        + "</div>"
    )

    TITLES = {
        "metaux":  "ETCs Metaux Precieux",
        "macro":   "Referentiels Macro",
        "crypto":  "Crypto",
        "actions": "ETFs PEA Actions · Conditionnels (Brent &lt; 90$)",
    }
    ORDER = ["metaux", "macro", "crypto", "actions"]
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
        + "<title>Portfolio Signal Dashboard</title>"
        + "<link href='https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Syne:wght@400;600;700;800&display=swap' rel='stylesheet'>"
        + "<style>" + CSS + "</style>"
        + "</head><body><div class='wrapper'>"

        + "<div class='header'>"
        + "<div class='header-left'><h1>Portfolio <span>Signal</span> Dashboard</h1>"
        + "<div class='subtitle'>MACD 12/26/9 · RSI 14 · Fibonacci · Yahoo Finance</div></div>"
        + "<div class='timestamp'><div class='date'>" + now.strftime("%d/%m/%Y") + "</div>"
        + "<div>Mise a jour : " + now.strftime("%H:%M:%S") + "</div></div>"
        + "</div>"

        + conditions_bar + scenarios + err_html + cards_html

        + "<div class='footer'>Donnees : Yahoo Finance · MACD(12,26,9) + RSI(14) · Niveaux Fibonacci"
        + "<br>Analyse personnelle — Pas un conseil financier · Relancer le script pour actualiser</div>"
        + "</div></body></html>"
    )

# ── MAIN ──────────────────────────────────────────────────────────────────────

def generate_dashboard():
    now = datetime.now()
    print("\n" + "="*55)
    print("  PORTFOLIO SIGNAL DASHBOARD — " + now.strftime("%d/%m/%Y %H:%M"))
    print("="*55 + "\n")

    all_data, errors = {}, []
    for key, cfg in ASSETS.items():
        print("  -> " + key + " (" + cfg["ticker"] + ")...")
        d = fetch_asset(
            cfg["ticker"],
            isin_fallback=cfg.get("isin"),
            ticker_fallback=cfg.get("ticker_fallback"),
        )
        all_data[key] = d
        if d and not d.get("ok"):
            errors.append(key)

    signals = {k: evaluate_signal(k, ASSETS[k], all_data[k]) for k in ASSETS}

    cards_by_cat = {"metaux": "", "macro": "", "crypto": "", "actions": ""}
    for key, cfg in ASSETS.items():
        cards_by_cat[cfg["categorie"]] += build_card(key, cfg, all_data[key], signals[key])

    def safe_px(key, digits=4):
        d = all_data.get(key)
        p = d["prix"] if d and d.get("ok") and d["prix"] else None
        if p is None: return "—"
        fmt = "{:." + str(digits) + "f}"
        return fmt.format(p)

    def safe_cross(key, tf):
        d = all_data.get(key)
        if d and d.get("ok"): return d[tf]["crossover"]
        return "neutral"

    eu_p  = safe_px("EURUSD", 4)
    br_p  = safe_px("BRENT",  2)
    eu_ok = all_data.get("EURUSD") and all_data["EURUSD"].get("ok") and all_data["EURUSD"]["prix"] and all_data["EURUSD"]["prix"] < 1.15
    br_ok = all_data.get("BRENT")  and all_data["BRENT"].get("ok")  and all_data["BRENT"]["prix"]  and all_data["BRENT"]["prix"]  < 90
    br_hi = all_data.get("BRENT")  and all_data["BRENT"].get("ok")  and all_data["BRENT"]["prix"]  and all_data["BRENT"]["prix"]  > 110
    xd_c  = safe_cross("XAD6", "daily")
    bt_c  = safe_cross("BTC",  "weekly")

    conds = {
        "eu_p":  eu_p, "eu_col": "green" if eu_ok else "yellow",
        "eu_s":  "TRIGGER ATTEINT — Renforcer ETCs" if eu_ok else "Attendre passage sous 1.15",
        "br_p":  br_p, "br_col": "green" if br_ok else ("red" if br_hi else "orange"),
        "br_s":  "SIGNAL ACTIONS (attendre 3 clotures)" if br_ok else ("NIVEAU CRITIQUE &gt; 110$" if br_hi else "Actions bloquees — Brent &gt; 90$"),
        "xd_l":  ml(xd_c), "xd_col": "green" if xd_c in ["bullish","bullish_cross"] else ("red" if xd_c in ["bearish","bearish_cross"] else "yellow"),
        "xd_d":  "Signal d'entree actif" if xd_c in ["bullish","bullish_cross"] else "Attendre croisement haussier",
        "bt_l":  ml(bt_c), "bt_col": "green" if bt_c in ["bullish","bullish_cross"] else "red",
        "bt_d":  "Signal long terme actif" if bt_c in ["bullish","bullish_cross"] else "Signal absent — Ne pas acheter",
    }

    html = build_html(now, cards_by_cat, conds, errors)
    out  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    print("\n  Dashboard genere : " + out)
    print("\n  Signaux actifs :")
    for key, sig in signals.items():
        if sig["color"] in ["green", "teal"]:
            print("    [OK] " + key + " — " + sig["label"])
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
    print("  GENERATION RESUME CLAUDE — " + now.strftime("%d/%m/%Y %H:%M"))
    print("="*55 + "\n")

    all_data = {}
    for key, cfg in ASSETS.items():
        print("  -> " + key + " (" + cfg["ticker"] + ")...")
        all_data[key] = fetch_asset(
            cfg["ticker"],
            isin_fallback=cfg.get("isin"),
            ticker_fallback=cfg.get("ticker_fallback"),
        )

    signals = {k: evaluate_signal(k, ASSETS[k], all_data[k]) for k in ASSETS}

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
        "assets": {}
    }

    for key in ASSETS:
        snapshot["assets"][key] = {
            "prix":    px(key, 4 if key == "EURUSD" else 2),
            "var_pct": vr(key),
            "rsi_d":   g(key, "rsi",       "daily"),
            "rsi_w":   g(key, "rsi",       "weekly"),
            "macd_d":  g(key, "crossover", "daily",  0),
            "macd_w":  g(key, "crossover", "weekly", 0),
            "signal":  signals[key]["label"],
            "color":   signals[key]["color"],
        }

    # Triggers globaux
    eu = all_data.get("EURUSD")
    br = all_data.get("BRENT")
    snapshot["triggers"] = {
        "eurusd_ok":           bool(eu and eu.get("ok") and eu["prix"] and eu["prix"] < 1.15),
        "brent_actions_ok":    bool(br and br.get("ok") and br["prix"] and br["prix"] < 90),
        "brent_critique":      bool(br and br.get("ok") and br["prix"] and br["prix"] > 110),
        "xad6_macd_haussier":  g("XAD6", "crossover", "daily", 0) in ["bullish", "bullish_cross"],
        "btc_weekly_haussier": g("BTC",  "crossover", "weekly", 0) in ["bullish", "bullish_cross"],
    }

    # ATH connus pour alerte dépassement
    ATH = {"PPFB": 90.0, "XAD6": 1000.0, "BTC": 126000, "PUST": 93.0, "PSP5": 54.0, "PTPXE": 37.0, "PAASI": 34.5}
    ath_alerts = []
    for key, ath in ATH.items():
        p = px(key, 2)
        if p and p > ath * 0.97:
            ath_alerts.append(key + " a " + str(round(p/ath*100,1)) + "% de l'ATH -> verifier Fibonacci")
    if ath_alerts:
        snapshot["ath_alerts"] = ath_alerts

    import json
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
    print("  Fichier sauvegardé : " + summary_path + "\n")

    return snapshot


if __name__ == "__main__":
    import sys
    if "--claude" in sys.argv:
        # Mode résumé Claude uniquement : python dashboard_generator.py --claude
        generate_claude_summary()
    else:
        # Mode normal : génère le dashboard HTML + résumé Claude
        generate_dashboard()
        generate_claude_summary()
