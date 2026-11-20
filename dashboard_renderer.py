"""
Rendu HTML : liste compacte des actifs + grand graphique (TradingView Lightweight Charts).

Layout :
  - Bandeau résumé (tiers, sorties actives, risque)
  - Gauche : tableau watchlist groupé par catégorie (prix, var, RSI, tendance, MACD, signal)
  - Droite : graphique de l'actif sélectionné (journalier 2 ans / hebdo 5 ans) + RSI + détail

Génération HTML : jamais de .format() sur le template (accolades CSS/JS) — concaténation uniquement.
"""

import html as _html

from dashboard_signals import evaluate_tier, evaluate_exit_signal

# ── HELPERS ───────────────────────────────────────────────────────────────────

MACD_SHORT = {
    "bullish_cross": ("Croise ↑", "up"),
    "bullish":       ("Haussier", "up"),
    "bearish_cross": ("Croise ↓", "down"),
    "bearish":       ("Baissier", "down"),
    "neutral":       ("Neutre",   "dim"),
}

CAT_TITLES = {
    "metaux":  "Métaux précieux",
    "crypto":  "Crypto",
    "actions": "ETF",
    "titres":  "Actions",
}
CAT_ORDER = ["metaux", "crypto", "actions", "titres"]


def esc(s):
    return _html.escape(str(s), quote=True)


def rc(rsi):
    """Classe couleur RSI (utilisée aussi par dashboard_claude)."""
    if rsi is None: return "dim"
    if rsi > 70:    return "warn"
    if rsi < 30:    return "cold"
    return ""


def fmt_price(p):
    if p is None: return "—"
    if p >= 10000: return "{:,.0f}".format(p).replace(",", " ")
    if p >= 100:   return "{:,.2f}".format(p).replace(",", " ")
    return "{:,.3f}".format(p)


def fmt_var(v):
    if v is None: return "—", "dim"
    return ("+" if v > 0 else "") + "{:.2f}".format(v) + "%", ("up" if v > 0 else "down" if v < 0 else "dim")


def _signal_badge(sig, tier_info, exit_s):
    """Badge court : sortie prioritaire, sinon tier d'entrée."""
    es = exit_s["status"]
    if es == "SELL_100": return "Vendre 100%", "red"
    if es == "SELL_50":  return "Vendre 50%", "orange"
    t = tier_info["tier"]
    if t > 0:
        return "T" + str(t), {3: "green", 2: "yellow", 1: "teal"}[t]
    if sig["color"] == "gray" and sig["label"].startswith("DONNEES"):
        return "N/D", "gray"
    return "—", "none"


# ── LIGNE DU TABLEAU ──────────────────────────────────────────────────────────

def build_row(key, cfg, d, sig, swing=None):
    ok     = bool(d and d.get("ok"))
    prix   = d.get("prix") if ok else None
    var, var_cls = fmt_var(d.get("variation") if ok else None)
    rsi_d  = d["daily"]["rsi"]  if ok else None
    rsi_w  = d["weekly"]["rsi"] if ok else None
    macd   = d["daily"]["macd"].get("signal", "neutral") if ok else "neutral"
    ma200  = d.get("ma200") if ok else None
    ath    = (d.get("ath") or {}) if ok else {}
    dd     = ath.get("drawdown_pct")
    if dd is None:
        dd_html = "<span class='dim'>—</span>"
    else:
        dd_cls  = "cold" if dd <= -20 else ("dim" if dd > -3 else "")
        dd_html = ("<span class='" + dd_cls + "' title='ATH " + fmt_price(ath.get("price")) + " le "
                   + esc(ath.get("date", "")) + "'>" + ("{:.0f}".format(dd) if dd <= -0.5 else "0") + "%</span>")

    tier_info = evaluate_tier(key, d)
    exit_s    = evaluate_exit_signal(key, d)
    badge, badge_cls = _signal_badge(sig, tier_info, exit_s)

    if prix and ma200:
        above = prix > ma200
        trend = ("<span class='" + ("up" if above else "down") + "' title='Prix "
                 + ("au-dessus" if above else "sous") + " la MA200 (" + fmt_price(ma200) + ")'>"
                 + ("▲" if above else "▼") + "</span>")
    else:
        trend = "<span class='dim'>—</span>"

    macd_txt, macd_cls = MACD_SHORT.get(macd, MACD_SHORT["neutral"])

    swing_html = ""
    if swing:
        swing_html = ("<span class='swing' title='Score swing " + str(swing["score"]) + "/"
                      + str(swing["max_score"]) + "'>S " + str(swing["score"]) + "</span>")

    return (
        "<tr data-key='" + esc(key) + "' tabindex='0'>"
        + "<td class='c-name'><div class='tk'>" + esc(key) + "</div><div class='nm'>" + esc(cfg["nom"]) + "</div></td>"
        + "<td class='num'>" + fmt_price(prix) + "</td>"
        + "<td class='num " + var_cls + "'>" + var + "</td>"
        + "<td class='num'>" + dd_html + "</td>"
        + "<td class='num'><span class='" + rc(rsi_d) + "'>" + (str(round(rsi_d)) if rsi_d is not None else "—") + "</span>"
        + "<span class='rw " + rc(rsi_w) + "'>" + (str(round(rsi_w)) if rsi_w is not None else "—") + "</span></td>"
        + "<td class='ctr'>" + trend + "</td>"
        + "<td class='" + macd_cls + " c-macd'>" + macd_txt + "</td>"
        + "<td><span class='badge b-" + badge_cls + "' title='" + esc(sig["label"]) + "'>" + badge + "</span>" + swing_html + "</td>"
        + "</tr>"
    )


# ── PANNEAU DÉTAIL (sous le graphique) ────────────────────────────────────────

def _zone_txt(z):
    if not z: return "—"
    strength = {"strong": "forte", "medium": "moyenne", "weak": "faible"}.get(z.get("strength"), "")
    return fmt_price(z["price"]) + " <span class='dim'>(" + strength + ", " + str(z.get("touches", 0)) + " touches)</span>"


def build_detail(key, cfg, d, sig, swing=None):
    ok = bool(d and d.get("ok"))
    if not ok:
        return "<div class='detail' id='det-" + esc(key) + "' hidden><div class='dim'>Données indisponibles</div></div>"

    exit_s = evaluate_exit_signal(key, d)
    ma50, ma200, cross = d.get("ma50"), d.get("ma200"), d.get("ma_cross")
    cross_txt = {"golden": "<span class='up'>golden cross</span>", "death": "<span class='down'>death cross</span>"}.get(cross, "")
    fib_zone  = (d.get("fibonacci") or {}).get("current_zone")
    rsi_w     = exit_s.get("rsi_w")

    items = [
        ("Signal", esc(sig["label"]) + "<div class='sub'>" + esc(sig["action"]) + "</div>"),
        ("Sortie (RSI W)", esc(exit_s["status"]) + (" · RSI W " + str(rsi_w) + " · vente 50% à " + str(exit_s.get("sell_50")) if rsi_w is not None else "")),
        ("Support", _zone_txt(d.get("nearest_sup"))),
        ("Résistance", _zone_txt(d.get("nearest_res"))),
        ("MA50 / MA200", fmt_price(ma50) + " / " + fmt_price(ma200) + (" · " + cross_txt if cross_txt else "")),
    ]
    ath = d.get("ath") or {}
    if ath.get("price"):
        items.append(("Plus haut historique", fmt_price(ath["price"]) + " <span class='dim'>(" + esc(ath.get("date", ""))
                      + ")</span> · " + ("{:+.1f}".format(ath["drawdown_pct"]) + "%" if ath.get("drawdown_pct") is not None else "—")
                      + "<div class='sub'>historique depuis " + esc(ath.get("since", "")) + "</div>"))
    if fib_zone:
        items.append(("Zone Fibonacci", esc(fib_zone)))
    if swing:
        reasons = ", ".join(esc(r) for r in swing.get("reasons", [])) or "aucun critère rempli"
        items.append(("Swing " + str(swing["score"]) + "/" + str(swing["max_score"]),
                      esc(swing["signal"]) + "<div class='sub'>" + reasons + "</div>"))

    return (
        "<div class='detail' id='det-" + esc(key) + "' hidden>"
        + "".join("<div class='di'><div class='dl'>" + k + "</div><div class='dv'>" + v + "</div></div>" for k, v in items)
        + "</div>"
    )


# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """\
:root{
  --bg:#0a0e16;--panel:#111723;--panel2:#161e2d;--border:#1f2a3c;
  --text:#c9d4e5;--dim:#5d6f8a;--bright:#eef3fb;
  --up:#26a69a;--down:#ef5350;--warn:#ffa726;--cold:#4fc3f7;
  --green:#26a69a;--yellow:#e6c84f;--teal:#4fc3f7;--orange:#ffa726;--red:#ef5350;--gray:#5d6f8a;
  --accent:#5b8def;
}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font:13px/1.4 'Inter',system-ui,sans-serif;padding:20px}
.wrap{max-width:1500px;margin:0 auto}
.up{color:var(--up)}.down{color:var(--down)}.dim{color:var(--dim)}.warn{color:var(--warn)}.cold{color:var(--cold)}
header{display:flex;justify-content:space-between;align-items:baseline;gap:16px;margin-bottom:14px;flex-wrap:wrap}
h1{font-size:18px;font-weight:700;color:var(--bright)}
.ts{color:var(--dim);font-size:12px}
.summary{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.pill{padding:4px 10px;border-radius:4px;background:var(--panel);border:1px solid var(--border);font-size:12px}
.pill b{color:var(--bright)}
.pill.risk-HIGH{border-color:var(--red);color:var(--red)}
.pill.risk-MEDIUM{border-color:var(--orange);color:var(--orange)}
.pill.risk-LOW{border-color:var(--green);color:var(--green)}
.err{background:rgba(239,83,80,.1);border:1px solid rgba(239,83,80,.4);color:var(--red);padding:8px 12px;border-radius:4px;margin-bottom:12px;font-size:12px}
.layout{display:grid;grid-template-columns:minmax(0,680px) minmax(0,1fr);gap:16px;align-items:start}
.list{background:var(--panel);border:1px solid var(--border);border-radius:6px;overflow-x:auto}
table{width:100%;border-collapse:collapse}
th{white-space:nowrap;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:var(--dim);text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);background:var(--panel)}
th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
th.ctr,td.ctr{text-align:center}
td{padding:7px 10px;border-bottom:1px solid var(--border);white-space:nowrap}
tr.grp td{background:var(--panel2);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--dim);padding:5px 10px}
tbody tr[data-key]{cursor:pointer}
tbody tr[data-key]:hover td{background:rgba(91,141,239,.06)}
tbody tr.sel td{background:rgba(91,141,239,.14)}
tbody tr.sel td:first-child{box-shadow:inset 3px 0 0 var(--accent)}
.c-name .tk{font-weight:700;color:var(--bright)}
.c-name .nm{font-size:11px;color:var(--dim);max-width:150px;overflow:hidden;text-overflow:ellipsis}
.rw{font-size:10px;margin-left:5px;opacity:.75}
.rw::before{content:'/ '}
td.c-macd{font-size:12px}
.badge{display:inline-block;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:600}
.b-none{color:var(--dim)}
.b-gray{color:var(--gray);border:1px solid var(--border)}
.b-teal{color:var(--teal);background:rgba(79,195,247,.1)}
.b-yellow{color:var(--yellow);background:rgba(230,200,79,.1)}
.b-green{color:var(--green);background:rgba(38,166,154,.15)}
.b-orange{color:var(--orange);background:rgba(255,167,38,.12)}
.b-red{color:var(--red);background:rgba(239,83,80,.15)}
.swing{font-size:10px;color:var(--dim);margin-left:6px}
.chart-panel{background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:14px;position:sticky;top:12px}
.cp-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;margin-bottom:10px}
.cp-title{font-size:16px;font-weight:700;color:var(--bright)}
.cp-sub{font-size:12px;color:var(--dim)}
.cp-price{font-size:20px;font-weight:700;color:var(--bright);text-align:right;font-variant-numeric:tabular-nums}
.controls{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.controls button{background:var(--panel2);border:1px solid var(--border);color:var(--dim);font:inherit;font-size:12px;padding:4px 10px;border-radius:4px;cursor:pointer}
.controls button.on{color:var(--bright);border-color:var(--accent);background:rgba(91,141,239,.15)}
.controls .sep{width:1px;background:var(--border);margin:0 4px}
#chart{height:460px}
#rsi{height:110px;margin-top:4px}
.legend{font-size:11px;color:var(--dim);margin-top:6px;display:flex;gap:14px;flex-wrap:wrap}
.legend i{display:inline-block;width:12px;height:2px;vertical-align:middle;margin-right:4px}
.detail[hidden]{display:none}
.detail{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px 18px;margin-top:14px;padding-top:12px;border-top:1px solid var(--border)}
.dl{font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--dim);margin-bottom:2px}
.dv{font-size:12px;color:var(--text)}
.dv .sub{font-size:11px;color:var(--dim);margin-top:2px}
footer{margin-top:20px;color:var(--dim);font-size:11px;text-align:center}
@media(max-width:1000px){
  .layout{grid-template-columns:1fr}
  .chart-panel{position:static}
  #chart{height:360px}
}
@media(max-width:560px){
  body{padding:10px}
  .c-name .nm,.c-macd,.swing,.rw{display:none}
  .layout{gap:10px}
  .chart-panel{padding:10px}
  td,th{padding:6px}
}
"""

# ── JS ────────────────────────────────────────────────────────────────────────

JS = """
const LC=LightweightCharts;
const state={key:null,mode:'d',sr:true,ma:true,fib:false};
let main=null,rsiChart=null;

function sma(vals,n){const out=[];let s=0;for(let i=0;i<vals.length;i++){s+=vals[i];if(i>=n)s-=vals[i-n];out.push(i>=n-1?s/n:null);}return out;}
function toBars(arr){return arr.map(b=>({time:b[0],open:b[1],high:b[2],low:b[3],close:b[4],volume:b[5]}));}

function baseOpts(el,h,showTime){return{
  width:el.clientWidth,height:h,
  layout:{background:{color:'#111723'},textColor:'#8a9ab3',fontSize:11},
  grid:{vertLines:{color:'#182133'},horzLines:{color:'#182133'}},
  rightPriceScale:{borderColor:'#1f2a3c',minimumWidth:70},
  timeScale:{borderColor:'#1f2a3c',visible:showTime,rightOffset:4},
  crosshair:{mode:LC.CrosshairMode.Normal},
};}

function render(){
  const d=ASSETS[state.key];
  const elC=document.getElementById('chart'),elR=document.getElementById('rsi');
  if(main){main.remove();main=null;} if(rsiChart){rsiChart.remove();rsiChart=null;}
  elC.innerHTML='';elR.innerHTML='';
  if(!d||!d.d||!d.d.length){elC.innerHTML='<div class="dim" style="padding:20px">Pas de données graphiques</div>';return;}

  const weekly=state.mode==='w'&&d.w&&d.w.length;
  const bars=toBars(weekly?d.w:d.d);
  main=LC.createChart(elC,baseOpts(elC,elC.clientHeight,true));
  main.priceScale('right').applyOptions({scaleMargins:{top:0.06,bottom:0.2}});
  const candles=main.addCandlestickSeries({upColor:'#26a69a',downColor:'#ef5350',borderVisible:false,wickUpColor:'#26a69a',wickDownColor:'#ef5350'});
  candles.setData(bars);
  const vol=main.addHistogramSeries({priceFormat:{type:'volume'},priceScaleId:'vol',lastValueVisible:false,priceLineVisible:false});
  main.priceScale('vol').applyOptions({scaleMargins:{top:0.85,bottom:0}});
  vol.setData(bars.map(b=>({time:b.time,value:b.volume,color:b.close>=b.open?'rgba(38,166,154,.35)':'rgba(239,83,80,.35)'})));

  if(state.ma){
    let m50,m200;
    if(weekly){
      const closes=bars.map(b=>b.close);
      const s50=sma(closes,50),s200=sma(closes,200);
      m50=bars.map((b,i)=>s50[i]==null?null:{time:b.time,value:s50[i]}).filter(Boolean);
      m200=bars.map((b,i)=>s200[i]==null?null:{time:b.time,value:s200[i]}).filter(Boolean);
    }else{
      m50=d.ma50.map(p=>({time:p[0],value:p[1]}));
      m200=d.ma200.map(p=>({time:p[0],value:p[1]}));
    }
    const lo={lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false};
    if(m50.length) main.addLineSeries(Object.assign({color:'#e6c84f'},lo)).setData(m50);
    if(m200.length) main.addLineSeries(Object.assign({color:'#ab47bc'},lo)).setData(m200);
  }
  if(state.sr){
    for(const z of (weekly?d.zw:d.zd)){
      candles.createPriceLine({price:z.p,color:z.side==='s'?'#26a69a':'#ef5350',
        lineWidth:2,lineStyle:z.s==='strong'?LC.LineStyle.Solid:LC.LineStyle.Dashed,
        axisLabelVisible:true,title:(z.side==='s'?'Support':'Résistance')+(z.n>0?' · '+z.n+'×':'')+(z.ath?' · ATH':'')});
    }
  }
  if(state.fib){
    for(const [lbl,p] of d.fib){
      candles.createPriceLine({price:p,color:'rgba(91,141,239,.7)',lineWidth:1,lineStyle:LC.LineStyle.Dotted,axisLabelVisible:true,title:'Fib '+lbl});
    }
  }

  // RSI (même nombre de barres que le graphique principal -> plages logiques alignées)
  const rsiSrc=new Map((weekly?d.rw:d.rd).map(p=>[p[0],p[1]]));
  rsiChart=LC.createChart(elR,baseOpts(elR,elR.clientHeight,false));
  rsiChart.applyOptions({handleScroll:false,handleScale:false});
  const rs=rsiChart.addLineSeries({color:'#5b8def',lineWidth:1,priceLineVisible:false,lastValueVisible:true});
  rs.setData(bars.map(b=>rsiSrc.has(b.time)?{time:b.time,value:rsiSrc.get(b.time)}:{time:b.time}));
  for(const [v,c] of [[70,'#ef5350'],[30,'#26a69a']]) rs.createPriceLine({price:v,color:c,lineWidth:1,lineStyle:LC.LineStyle.Dashed,axisLabelVisible:false});
  rs.applyOptions({autoscaleInfoProvider:()=>({priceRange:{minValue:0,maxValue:100}})});

  main.timeScale().subscribeVisibleLogicalRangeChange(r=>{if(r&&rsiChart)rsiChart.timeScale().setVisibleLogicalRange(r);});
  main.timeScale().fitContent();
}

function select(key,scroll){
  if(!ASSETS[key]) return;
  state.key=key;
  document.querySelectorAll('tr[data-key]').forEach(tr=>tr.classList.toggle('sel',tr.dataset.key===key));
  document.querySelectorAll('.detail').forEach(el=>el.hidden=el.id!=='det-'+key);
  const a=ASSETS[key];
  document.getElementById('cp-title').textContent=a.nom;
  document.getElementById('cp-sub').textContent=key+' · '+a.ticker;
  document.getElementById('cp-price').textContent=a.prix_txt;
  const v=document.getElementById('cp-var');v.textContent=a.var_txt;v.className=a.var_cls;
  try{localStorage.setItem('dash-key',key);}catch(e){}
  render();
  if(scroll&&window.innerWidth<=1000) document.getElementById('chart-panel').scrollIntoView({behavior:'smooth'});
}

function setBtn(){
  document.querySelectorAll('.controls button').forEach(b=>{
    const k=b.dataset.k,v=b.dataset.v;
    b.classList.toggle('on',v!==undefined?state[k]===v:!!state[k]);
  });
}

document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('tr[data-key]').forEach(tr=>{
    tr.addEventListener('click',()=>select(tr.dataset.key,true));
    tr.addEventListener('keydown',e=>{if(e.key==='Enter')select(tr.dataset.key,true);});
  });
  document.querySelectorAll('.controls button').forEach(b=>b.addEventListener('click',()=>{
    const k=b.dataset.k,v=b.dataset.v;
    state[k]=v!==undefined?v:!state[k];
    setBtn();render();
  }));
  setBtn();
  let start=null;try{start=localStorage.getItem('dash-key');}catch(e){}
  if(!start||!ASSETS[start]) start=document.querySelector('tr[data-key]')?.dataset.key;
  if(start) select(start,false);
  let t;window.addEventListener('resize',()=>{clearTimeout(t);t=setTimeout(render,150);});
});
"""

# ── PAGE COMPLÈTE ─────────────────────────────────────────────────────────────

def build_html(now, rows_by_cat, details_html, conds, errors, assets_json):
    summary = (
        "<div class='summary'>"
        + "<div class='pill'>T3 <b>" + str(conds["t3"]) + "</b></div>"
        + "<div class='pill'>T2 <b>" + str(conds["t2"]) + "</b></div>"
        + "<div class='pill'>T1 <b>" + str(conds["t1"]) + "</b></div>"
        + "<div class='pill'>Sorties actives <b>" + str(conds["exits"]) + "</b></div>"
        + "<div class='pill'>Death cross <b>" + str(len(conds.get("death_crosses", []))) + "</b>"
        + ((" <span class='dim'>" + esc(", ".join(conds["death_crosses"])) + "</span>") if conds.get("death_crosses") else "")
        + "</div>"
        + "<div class='pill risk-" + conds["risk"] + "'>Risque " + conds["risk"] + "</div>"
        + "</div>"
    )

    body_rows = ""
    for cat in CAT_ORDER:
        if rows_by_cat.get(cat):
            body_rows += "<tr class='grp'><td colspan='8'>" + CAT_TITLES[cat] + "</td></tr>" + rows_by_cat[cat]

    table = (
        "<div class='list'><table>"
        + "<thead><tr><th>Actif</th><th class='num'>Prix</th><th class='num'>Var</th><th class='num' title='Distance au plus haut historique'>ATH</th>"
        + "<th class='num' title='RSI journalier / hebdo'>RSI</th><th class='ctr' title='Prix vs MA200'>Tend.</th>"
        + "<th class='c-macd'>MACD</th><th>Signal</th></tr></thead>"
        + "<tbody>" + body_rows + "</tbody></table></div>"
    )

    chart_panel = (
        "<div class='chart-panel' id='chart-panel'>"
        + "<div class='cp-head'><div><div class='cp-title' id='cp-title'></div><div class='cp-sub' id='cp-sub'></div></div>"
        + "<div><div class='cp-price' id='cp-price'></div><div id='cp-var' style='text-align:right'></div></div></div>"
        + "<div class='controls'>"
        + "<button data-k='mode' data-v='d'>Journalier · 2 ans</button>"
        + "<button data-k='mode' data-v='w'>Hebdo · 5 ans</button>"
        + "<span class='sep'></span>"
        + "<button data-k='ma'>MA50/200</button><button data-k='sr'>Supports/Résistances</button><button data-k='fib'>Fibonacci</button>"
        + "</div>"
        + "<div id='chart'></div><div id='rsi'></div>"
        + "<div class='legend'><span><i style='background:#e6c84f'></i>MA50</span><span><i style='background:#ab47bc'></i>MA200</span>"
        + "<span><i style='background:#5b8def'></i>RSI 14 (30/70)</span></div>"
        + details_html
        + "</div>"
    )

    err_html = ("<div class='err'>Données indisponibles : " + esc(", ".join(errors)) + "</div>") if errors else ""

    return (
        "<!DOCTYPE html><html lang='fr'><head><meta charset='UTF-8'>"
        + "<meta name='viewport' content='width=device-width,initial-scale=1.0'>"
        + "<title>Portfolio CTO</title>"
        + "<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap' rel='stylesheet'>"
        + "<style>" + CSS + "</style></head><body><div class='wrap'>"
        + "<header><h1>Portfolio CTO</h1><div class='ts'>Mis à jour le " + now.strftime("%d/%m/%Y à %H:%M") + "</div></header>"
        + summary + err_html
        + "<div class='layout'>" + table + chart_panel + "</div>"
        + "<footer>Yahoo Finance · RSI 14 · MACD 12/26/9 · MA50/MA200 · Analyse personnelle, pas un conseil financier</footer>"
        + "</div>"
        + "<script src='https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js'></script>"
        + "<script>const ASSETS=" + assets_json.replace("</", "<\\/") + ";" + JS + "</script>"
        + "</body></html>"
    )
