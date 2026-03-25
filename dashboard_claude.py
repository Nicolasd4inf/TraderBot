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
import os
import webbrowser
from datetime import datetime

from dashboard_config import TICKER_MAP, STOCK_PICKING_MAP, ETF_KEYS
from dashboard_fetcher import fetch_asset, fetch_stock_picking_asset
from dashboard_signals import evaluate_signal, evaluate_tier, evaluate_exit_signal, compute_swing_signal
from dashboard_renderer import build_card, build_stock_picking_section, build_html, rc


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
            euronext_mic=cfg.get("euronext_mic"),
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
    charts_json = json.dumps(charts_data, ensure_ascii=False)

    # Stock picking
    print("\n  Stock picking :")
    sp_raw = {}
    for key, cfg in STOCK_PICKING_MAP.items():
        print("  -> SP " + key + " (" + cfg["primary"] + ")...")
        d = fetch_stock_picking_asset(cfg["primary"], fallbacks=cfg.get("fallbacks", []))
        if d:
            d["swing"] = compute_swing_signal(d)
        sp_raw[key] = d

    sp_section = build_stock_picking_section(sp_raw)

    html = build_html(now, cards_by_cat, conds, errors, charts_json, sp_section=sp_section)
    out  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    print("\n  Dashboard genere : " + out)
    print("\n  Signaux actifs :")
    for key, sig in signals.items():
        if sig["color"] in ["green", "teal"]:
            print("    [OK] " + key + " - " + sig["label"])
    sp_buys = [k for k, d in sp_raw.items() if d and d.get("swing", {}).get("signal") in ["SWING_BUY", "PREPARING"]]
    if sp_buys:
        print("\n  Stock picking signaux :")
        for k in sp_buys:
            sw = sp_raw[k]["swing"]
            print("    [SP] " + k + " — " + sw["signal"] + " (score " + str(sw["score"]) + ")")
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
            euronext_mic=cfg.get("euronext_mic"),
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
            "rsi_d":      g(key, "rsi", "daily"),
            "rsi_w":      g(key, "rsi", "weekly"),
            "macd_d":     d["daily"]["macd"]  if ok else None,
            "macd_w":     d["weekly"]["macd"] if ok else None,
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

    # Stock picking dans le résumé Claude
    print("  Stock picking (résumé Claude)...")
    sp_snapshot = {}
    for key, cfg in STOCK_PICKING_MAP.items():
        d_sp = fetch_stock_picking_asset(cfg["primary"], fallbacks=cfg.get("fallbacks", []))
        if d_sp:
            d_sp["swing"] = compute_swing_signal(d_sp)
            sp_snapshot[key] = {
                "nom":    cfg["nom"],
                "prix":   d_sp["prix"],
                "var_pct": d_sp["variation"],
                "rsi_d":  d_sp["rsi_d"],
                "rsi_w":  d_sp["rsi_w"],
                "macd_d": d_sp["macd_d"],
                "macd_w": d_sp["macd_w"],
                "ma50":   d_sp["ma50"],
                "ma200":  d_sp["ma200"],
                "ma_cross": d_sp["ma_cross"],
                "volume":   d_sp["volume"],
                "bollinger": d_sp["bollinger"],
                "performance": d_sp["performance"],
                "range_52w":   d_sp["range_52w"],
                "fibonacci":   d_sp["fibonacci"],
                "swing":       d_sp["swing"],
                "sector":      cfg["sector"],
                "market_cap":  cfg["market_cap"],
            }
        else:
            sp_snapshot[key] = None

    sp_ranking = sorted(
        [{"ticker": k, "signal": v["swing"]["signal"], "score": v["swing"]["score"], "rank": 0}
         for k, v in sp_snapshot.items() if v],
        key=lambda x: x["score"], reverse=True
    )
    for i, item in enumerate(sp_ranking):
        item["rank"] = i + 1

    snapshot["stock_picking"]         = sp_snapshot
    snapshot["stock_picking_ranking"] = sp_ranking

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
