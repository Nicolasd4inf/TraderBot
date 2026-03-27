"""
Logique de signaux : tier, exit, signal combiné, swing stock picking.
"""

from dashboard_config import ASSET_CATEGORY, EXIT_RSI_THRESHOLDS


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
    macd_d = d["daily"]["macd"]["signal"]
    macd_w = d["weekly"]["macd"]["signal"]
    prix   = d["prix"]
    ma_cross = d.get("ma_cross")
    fib    = d.get("fibonacci", {})
    fib_382 = fib.get("fib_382")

    # Condition S/R zone-based : le tier ne redescend jamais à cause d'une cassure de support.
    # Les flags support_broken / days_below_zone ajoutent uniquement des avertissements au label.
    nearest_zone   = d.get("nearest_zone")
    days_below     = nearest_zone.get("days_below_zone", 0) if nearest_zone else 0
    support_broken = nearest_zone.get("support_broken", False) if nearest_zone else False
    if nearest_zone:
        above_sup = True  # le tier est toujours calculé normalement
    else:
        sr        = d.get("sr_zones", [])
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

    # Avertissements zone S/R (n'abaissent jamais le tier)
    if tier > 0 and support_broken:
        if days_below >= 2:
            label = label + " \u26d4 support cass\u00e9 " + str(days_below) + "j+"
        else:
            label = label + " \u26a0 sous support"

    next_missing = None
    if tier < 3:
        for k, v in conds.get("tier_" + str(tier+1), {}).items():
            if not v:
                next_missing = k.replace("_", " ")
                break
    return {"tier": tier, "pct": pct, "label": label, "next_missing": next_missing, "conditions": conds}


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


def _find_nearest_strong_support(prix, sr_zones):
    cands = [z for z in sr_zones if z["price"] < prix
             and z["type"] in ["support", "both"]
             and z["strength"] in ["strong", "medium"]]
    if cands:
        return max(cands, key=lambda z: z["price"])["price"]
    return None


def compute_swing_signal(data):
    """Score composite pour le swing trading d'une action."""
    score = 0.0
    reasons = []
    rsi_d  = data.get("rsi_d") or 50
    macd   = data.get("macd_d") or {}
    macd_w = data.get("macd_w") or {}
    volume = data.get("volume") or {}
    boll   = data.get("bollinger") or {}
    prix   = data.get("prix") or 0
    sr     = data.get("zones_sr") or []

    if rsi_d < 30:
        score += 2; reasons.append("RSI_D très survendu (<30)")
    elif rsi_d < 40:
        score += 1; reasons.append("RSI_D survendu (<40)")
    elif rsi_d > 70:
        score -= 2; reasons.append("RSI_D surachat (>70)")

    ms = macd.get("signal", "neutral")
    if ms in ["bullish", "bullish_cross"]:
        score += 2; reasons.append("MACD_D haussier")
    elif macd.get("cross_imminent") and macd.get("hist_trend") == "converging":
        est = macd.get("est_days_to_cross")
        score += 1; reasons.append("MACD_D croisement imminent" + ((" (~" + str(est) + "j)") if est else ""))

    mws = macd_w.get("signal", "neutral") if macd_w else "neutral"
    if mws in ["bullish", "bullish_cross"]:
        score += 1; reasons.append("MACD_W haussier (confirmation)")
    elif macd_w and macd_w.get("cross_imminent") and macd_w.get("hist_trend") == "converging":
        score += 0.5; reasons.append("MACD_W converge")

    if volume.get("surge") and (data.get("variation") or 0) > 0:
        score += 1; reasons.append("Volume surge sur hausse")

    ns = _find_nearest_strong_support(prix, sr)
    if ns and prix > ns:
        score += 1; reasons.append("Au-dessus support " + str(round(ns, 2)))

    if boll.get("squeeze"):
        score += 0.5; reasons.append("Bollinger squeeze (breakout imminent)")

    if boll.get("price_position") == "below_lower":
        score += 1; reasons.append("Prix sous Bollinger basse")

    if score >= 5:   signal = "SWING_BUY"
    elif score >= 3: signal = "PREPARING"
    elif score >= 1: signal = "WATCHING"
    elif score <= -1: signal = "OVERBOUGHT"
    else:            signal = "NEUTRAL"

    return {
        "signal":        signal,
        "score":         round(score, 1),
        "max_score":     8.5,
        "reasons":       reasons,
        "entry_quality": str(round(score / 8.5 * 100)) + "%",
    }
