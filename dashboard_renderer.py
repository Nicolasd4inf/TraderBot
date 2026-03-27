"""
Rendu HTML : helpers, CSS, build_card, build_stock_picking_section, build_html.
"""

from dashboard_config import STOCK_PICKING_MAP
from dashboard_signals import evaluate_tier, evaluate_exit_signal

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

def _macd_cross_label(macd_dict):
    if not macd_dict or macd_dict.get("signal") == "neutral":
        return "—"
    sig = macd_dict.get("signal", "neutral")
    if sig in ["bullish_cross", "bullish"]:
        return "Bullish"
    if macd_dict.get("cross_imminent"):
        est = macd_dict.get("est_days_to_cross")
        return ("~" + str(est) + "j") if est else "Imminent"
    ht = macd_dict.get("hist_trend")
    if ht == "converging":
        return "Converge"
    return "Diverge"

def _macd_cross_cls(macd_dict):
    if not macd_dict:
        return "neutral"
    sig = macd_dict.get("signal", "neutral")
    if sig in ["bullish_cross", "bullish"]:
        return "bullish"
    if macd_dict.get("cross_imminent"):
        return "overbought"  # orange
    if macd_dict.get("hist_trend") == "converging":
        return "bearish"    # yellow → use bearish for warm tone
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

def _zone_badge(d):
    """Badge textuel si le prix est dans une zone S/R (support ou résistance)."""
    nz = d.get("nearest_zone") if d else None
    if not nz or nz.get("price_position") != "in_zone":
        return ""
    t = nz.get("type", "")
    if t in ("support", "both"):
        return "<span class='zone-badge zone-sup'>\U0001f7e2 IN_ZONE_SUP</span>"
    if t == "resistance":
        return "<span class='zone-badge zone-res'>\U0001f534 IN_ZONE_RES</span>"
    return ""


def _sr_row(zone, devise):
    """Ligne texte pour une zone S/R."""
    if zone is None: return "—"
    sym = "▲" if zone["type"] == "resistance" else ("▼" if zone["type"] == "support" else "◆")
    strength_map = {"strong": "●●●", "medium": "●●○", "weak": "●○○"}
    return sym + " " + _fmt_level(zone["price"], devise) + " " + strength_map.get(zone["strength"], "")


# ── STOCK PICKING ─────────────────────────────────────────────────────────────

def build_stock_picking_section(sp_data):
    """Génère le HTML de la section stock picking."""
    buy_count  = sum(1 for d in sp_data.values() if d and d.get("swing", {}).get("signal") == "SWING_BUY")
    prep_count = sum(1 for d in sp_data.values() if d and d.get("swing", {}).get("signal") == "PREPARING")

    counter_html = "<div class='sp-counter'>"
    if buy_count > 0:
        counter_html += "<div class='sp-pill sp-buy blink'>Swing BUY : " + str(buy_count) + "</div>"
    if prep_count > 0:
        counter_html += "<div class='sp-pill sp-prep'>PREPARING : " + str(prep_count) + "</div>"
    if buy_count == 0 and prep_count == 0:
        counter_html += "<div class='sp-pill' style='border:1px solid var(--border);color:var(--text-dim)'>Aucun signal actif</div>"
    counter_html += "</div>"

    # Trier par score décroissant
    ranked = sorted(
        [(k, v) for k, v in sp_data.items() if v],
        key=lambda x: x[1].get("swing", {}).get("score", -99),
        reverse=True
    )

    SWING_CLS = {
        "SWING_BUY": "swing-buy",
        "PREPARING": "swing-prep",
        "WATCHING":  "swing-watch",
        "NEUTRAL":   "swing-neutral",
        "OVERBOUGHT":"swing-over",
    }

    table = (
        "<table class='sp-table'>"
        + "<thead><tr>"
        + "<th>Action</th><th>Prix</th><th>Var%</th><th>RSI D</th>"
        + "<th>MACD D</th><th>Cross ~j</th><th>Vol Rel</th><th>Bollinger</th>"
        + "<th>Signal Swing</th><th>Score</th>"
        + "</tr></thead><tbody>"
    )

    details_html = ""
    for i, (key, d) in enumerate(ranked):
        swing   = d.get("swing", {})
        sig     = swing.get("signal", "NEUTRAL")
        score   = swing.get("score", 0)
        max_s   = swing.get("max_score", 8.5)
        macd    = d.get("macd_d") or {}
        boll    = d.get("bollinger") or {}
        vol     = d.get("volume") or {}
        perf    = d.get("performance") or {}
        rng     = d.get("range_52w") or {}
        cfg     = STOCK_PICKING_MAP.get(key, {})
        devise  = cfg.get("devise", "€")
        nom     = cfg.get("nom", key)

        prix    = d.get("prix")
        var     = d.get("variation")
        rsi_d   = d.get("rsi_d")

        vol_rel = vol.get("relative", 0)
        vol_str = str(vol_rel) + "x" + ("<span class='sp-warning'>⚠ faibles</span>" if vol.get("low_liquidity") else "")

        bp = boll.get("price_position", "inside")
        bb_cls  = "above" if bp == "above_upper" else ("below" if bp == "below_lower" else "")
        bb_sq   = " squeeze" if boll.get("squeeze") else ""
        bb_str  = bp.replace("_", " ") + (" · SQUEEZE" if boll.get("squeeze") else "")

        cross_str = _macd_cross_label(macd)

        bar_w = round(score / max_s * 100)
        score_html = (
            str(score) + "/" + str(max_s)
            + "<span class='sp-score-bar'><span style='width:" + str(bar_w) + "%'></span></span>"
        )

        table += (
            "<tr onclick=\"document.getElementById('spd-" + str(i) + "').classList.toggle('open')\" style='cursor:pointer'>"
            + "<td><strong>" + key + "</strong><br><small style='color:var(--text-dim)'>" + nom + "</small></td>"
            + "<td>" + devise + (fmt_price(prix, devise) if prix else "—") + "</td>"
            + "<td class='" + ("up" if var and var > 0 else "down" if var and var < 0 else "") + "'>"
            + (("+" if var and var > 0 else "") + str(var) + "%" if var is not None else "—") + "</td>"
            + "<td class='" + rc(rsi_d) + "'>" + (str(round(rsi_d)) if rsi_d else "—") + "</td>"
            + "<td class='" + mc(macd.get("signal", "neutral")) + "'>" + ml(macd.get("signal", "neutral")) + "</td>"
            + "<td class='" + _macd_cross_cls(macd) + "'>" + cross_str + "</td>"
            + "<td>" + vol_str + "</td>"
            + "<td><span class='sp-bb-pill" + bb_cls + bb_sq + "'>" + bb_str + "</span></td>"
            + "<td><span class='" + SWING_CLS.get(sig, "swing-neutral") + "'>" + sig + "</span></td>"
            + "<td>" + score_html + "</td>"
            + "</tr>"
        )

        # Panneau de détail accordéon
        perf_pills = ""
        for period, val in [("1j", perf.get("1d")), ("5j", perf.get("5d")),
                            ("20j", perf.get("20d")), ("60j", perf.get("60d"))]:
            if val is not None:
                cls = "pos" if val > 0 else ("neg" if val < 0 else "")
                perf_pills += "<span class='sp-perf-pill " + cls + "'>" + period + " " + ("+" if val > 0 else "") + str(val) + "%</span>"

        rng_pos = 0
        if rng.get("high") and rng.get("low") and rng["high"] != rng["low"] and prix:
            rng_pos = round((prix - rng["low"]) / (rng["high"] - rng["low"]) * 100)
            rng_pos = max(0, min(100, rng_pos))

        reasons_html = "<ul class='sp-reason-list'>" + "".join(
            "<li>" + r + "</li>" for r in swing.get("reasons", [])
        ) + "</ul>" if swing.get("reasons") else "<span style='color:var(--text-dim)'>Aucun signal</span>"

        fib = d.get("fibonacci", {})
        fib_zone = fib.get("current_zone", "")

        details_html += (
            "<div class='sp-detail' id='spd-" + str(i) + "'>"
            + "<strong>" + key + " — " + nom + "</strong>"
            + " · Score " + str(score) + "/" + str(max_s)
            + " (" + swing.get("entry_quality", "0%") + ")"
            + (" · Zone Fib : " + fib_zone if fib_zone else "")
            + "<br>Raisons :" + reasons_html
            + "<div class='sp-perf-row'>" + perf_pills + "</div>"
            + "<div style='margin-top:6px;font-size:10px;color:var(--text-dim)'>Range 52 semaines</div>"
            + "<div class='sp-52w-bar'>"
            + "<div class='sp-52w-fill' style='width:" + str(rng_pos) + "%'></div>"
            + "<div class='sp-52w-marker' style='left:" + str(rng_pos) + "%'></div>"
            + "</div>"
            + "<div style='display:flex;justify-content:space-between;font-size:9px;color:var(--text-dim)'>"
            + "<span>Low " + devise + str(round(rng.get("low", 0), 2)) + " (" + str(rng.get("pct_from_low", 0)) + "% au-dessus)</span>"
            + "<span>High " + devise + str(round(rng.get("high", 0), 2)) + " (" + str(abs(rng.get("pct_from_high", 0))) + "% en dessous)</span>"
            + "</div>"
            + "</div>"
        )

    table += "</tbody></table>"

    return (
        counter_html
        + table
        + details_html
    )


# ── BUILD CARD ────────────────────────────────────────────────────────────────

def build_card(key, cfg, d, sig):
    prix_val  = d["prix"]      if d else None
    var_val   = d["variation"] if d else None
    rsi_d     = d["daily"]["rsi"]             if d else None
    rsi_w     = d["weekly"]["rsi"]            if d else None
    macd_d    = d["daily"]["macd"]            if d else {"signal": "neutral"}
    macd_w    = d["weekly"]["macd"]           if d else {"signal": "neutral"}
    cd        = macd_d.get("signal", "neutral")
    cw        = macd_w.get("signal", "neutral")
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
    _src_labels  = {"realtime": "RT", "tradegate": "TG", "euronext": "ENX", "yahoo_rt": "~RT"}
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
        + h("div","price-value", cfg["devise"] + fmt_price(prix_val, cfg["devise"]) + source_badge + _zone_badge(d))
        + h("div","price-change " + var_cls, var_str)
        + "</div></div>"
        + h("div","signal-badge badge-" + color, sig["label"])
        + h("div","signal-action", sig["action"])
        + "<div class='indicators'>"
        + "<div class='ind-block'>" + h("div","ind-label","RSI Daily")   + h("div","ind-value "+rc(rsi_d), str(round(rsi_d)) if rsi_d else "—") + "</div>"
        + "<div class='ind-block'>" + h("div","ind-label","MACD D")      + h("div","ind-value "+mc(cd), ml(cd)) + "</div>"
        + "<div class='ind-block'>" + h("div","ind-label","Cross D")     + h("div","ind-value "+_macd_cross_cls(macd_d), _macd_cross_label(macd_d)) + "</div>"
        + "<div class='ind-block'>" + h("div","ind-label","RSI Weekly")  + h("div","ind-value "+rc(rsi_w), str(round(rsi_w)) if rsi_w else "—") + "</div>"
        + "<div class='ind-block'>" + h("div","ind-label","MACD W")      + h("div","ind-value "+mc(cw), ml(cw)) + "</div>"
        + "<div class='ind-block'>" + h("div","ind-label","Cross W")     + h("div","ind-value "+_macd_cross_cls(macd_w), _macd_cross_label(macd_w)) + "</div>"
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
.indicators{display:grid;grid-template-columns:1fr 1fr 1fr 1fr 1fr 1fr;gap:6px;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)}
.ind-block{text-align:center}
.ind-label{font-size:9px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px}
.ind-value{font-size:12px;font-weight:600}
.ind-value.bullish{color:var(--green)}
.ind-value.bearish{color:var(--red)}
.ind-value.neutral{color:var(--text-dim)}
.ind-value.overbought{color:var(--orange)}
.ind-value.oversold{color:var(--teal)}
.source-tg{font-size:9px;font-weight:700;padding:1px 4px;border-radius:3px;background:rgba(38,198,218,.15);border:1px solid rgba(38,198,218,.4);color:var(--teal);margin-left:5px;vertical-align:middle;letter-spacing:.5px}
.zone-badge{font-size:9px;font-weight:700;padding:1px 5px;border-radius:3px;margin-left:6px;vertical-align:middle;letter-spacing:.4px}
.zone-sup{background:rgba(0,230,118,.12);border:1px solid rgba(0,230,118,.4);color:var(--green)}
.zone-res{background:rgba(255,71,87,.12);border:1px solid rgba(255,71,87,.4);color:var(--red)}
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
/* Stock picking */
.sp-counter{display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap;align-items:center}
.sp-pill{padding:5px 12px;border-radius:4px;font-size:12px;font-weight:700;font-family:'Syne',sans-serif}
.sp-buy{background:rgba(0,230,118,.1);border:1px solid var(--green);color:var(--green)}
.sp-buy.blink{animation:pulse-border 1.2s ease-in-out infinite}
.sp-prep{background:rgba(255,167,38,.1);border:1px solid var(--orange);color:var(--orange)}
.sp-table{width:100%;border-collapse:collapse;font-size:12px;margin-bottom:16px}
.sp-table th{text-align:left;padding:5px 8px;border-bottom:1px solid var(--border);font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px}
.sp-table td{padding:5px 8px;border-bottom:1px solid rgba(30,45,69,.6);vertical-align:middle}
.sp-table tr:last-child td{border-bottom:none}
.sp-table tr:hover td{background:rgba(61,122,237,.04)}
.swing-buy{color:var(--green);font-weight:700}
.swing-prep{color:var(--orange);font-weight:700}
.swing-watch{color:var(--teal)}
.swing-neutral{color:var(--text-dim)}
.swing-over{color:var(--red);font-weight:700}
.sp-score-bar{display:inline-block;width:50px;height:5px;background:var(--border);border-radius:2px;vertical-align:middle;margin-left:4px;position:relative;overflow:hidden}
.sp-score-bar span{position:absolute;left:0;top:0;height:100%;background:var(--accent);border-radius:2px}
.sp-detail{display:none;background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:10px 14px;margin-bottom:6px;font-size:11px}
.sp-detail.open{display:block}
.sp-reason-list{margin:4px 0 0 8px;color:var(--text);line-height:1.8}
.sp-perf-row{display:flex;gap:10px;margin-top:6px;flex-wrap:wrap}
.sp-perf-pill{padding:2px 7px;border-radius:3px;font-size:10px;background:var(--bg2);border:1px solid var(--border)}
.sp-perf-pill.pos{border-color:rgba(0,230,118,.3);color:var(--green)}
.sp-perf-pill.neg{border-color:rgba(255,71,87,.3);color:var(--red)}
.sp-52w-bar{position:relative;height:8px;background:var(--border);border-radius:2px;margin:6px 0 2px}
.sp-52w-fill{position:absolute;left:0;top:0;height:100%;background:var(--accent);border-radius:2px;opacity:.5}
.sp-52w-marker{position:absolute;top:-2px;width:4px;height:12px;background:var(--gold);border-radius:1px;transform:translateX(-50%)}
.sp-bb-pill{font-size:10px;padding:1px 5px;border-radius:3px;background:var(--bg2);border:1px solid var(--border);color:var(--text-dim)}
.sp-bb-pill.squeeze{border-color:var(--yellow);color:var(--yellow)}
.sp-bb-pill.above{border-color:var(--orange);color:var(--orange)}
.sp-bb-pill.below{border-color:var(--teal);color:var(--teal)}
.sp-warning{font-size:10px;color:var(--orange);display:inline-block;margin-left:4px}
@media(max-width:900px){
  .assets-grid{grid-template-columns:1fr}
  body{padding:12px}
  .sp-table{font-size:11px}
}
@media(max-width:520px){
  .header{flex-direction:column}
  .timestamp{text-align:left}
  .price-value{font-size:15px}
  body{padding:8px}
}
"""

# ── BUILD FULL HTML ───────────────────────────────────────────────────────────

def build_html(now, cards_by_cat, conds, errors, charts_json="{}", sp_section=""):

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
        + ("<div class='section-title'>Stock Picking — Swing Trading</div>" + sp_section if sp_section else "")

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
