"""
Configuration des actifs pour le dashboard Portfolio CTO.
"""

TICKER_MAP = {
    # ── Métaux précieux (ETC) ──
    "GOLD":  {"primary": "GOLD.PA",  "fallbacks": ["GLDA.PA"],           "nom": "Or — Amundi Physical Gold",             "categorie": "metaux",  "devise": "€", "isin": "FR0013416716", "euronext_mic": "ETFP"},
    "PHAG":  {"primary": "PHAG.AS",  "fallbacks": ["PHAG.L"],            "nom": "Argent — WisdomTree Physical Silver",   "categorie": "metaux",  "devise": "€", "isin": "JE00B1VS3333"},
    # ── Crypto ──
    "BTC":   {"primary": "BTC-USD",  "fallbacks": ["BTC-EUR"],           "nom": "Bitcoin",                               "categorie": "crypto",  "devise": "$"},
    # ── ETF actions ──
    "EQQQ":  {"primary": "EQQQ.PA",  "fallbacks": ["EQQQ.AS","EQQQ.L"],  "nom": "Nasdaq-100 — Invesco EQQQ",             "categorie": "actions", "devise": "€", "isin": "IE0032077012"},
    "SPEEU": {"primary": "SPEEU.PA", "fallbacks": [],                    "nom": "S&P 500 Scored — BNP Paribas Easy",     "categorie": "actions", "devise": "€", "isin": "IE0004J37T45", "euronext_mic": "ETFP"},
    "EEUE":  {"primary": "EEUE.PA",  "fallbacks": [],                    "nom": "MSCI Europe Min TE — BNP Paribas Easy", "categorie": "actions", "devise": "€", "isin": "LU1291099718", "euronext_mic": "ETFP"},
    "IJPA":  {"primary": "IJPA.AS",  "fallbacks": ["IJPA.L"],            "nom": "Core MSCI Japan IMI — iShares",         "categorie": "actions", "devise": "€", "isin": "IE00B4L5YX21"},
    "PAASI": {"primary": "PAASI.PA", "fallbacks": [],                    "nom": "PEA Asie Emergente — Amundi",           "categorie": "actions", "devise": "€", "isin": "FR0013412012", "euronext_mic": "ETFP"},
    "EMIM":  {"primary": "EMIM.AS",  "fallbacks": ["EIMI.AS","EMIM.L"],  "nom": "Core MSCI EM IMI — iShares",            "categorie": "actions", "devise": "€", "isin": "IE00BKM4GZ66"},
    # ── Actions individuelles ──
    "ASML":  {"primary": "ASML.AS",  "fallbacks": [],                    "nom": "ASML Holding",                          "categorie": "titres",  "devise": "€", "isin": "NL0010273215", "euronext_mic": "XAMS"},
    "SGO":   {"primary": "SGO.PA",   "fallbacks": [],                    "nom": "Saint-Gobain",                          "categorie": "titres",  "devise": "€", "isin": "FR0000125007", "euronext_mic": "XPAR"},
    "EL":    {"primary": "EL.PA",    "fallbacks": [],                    "nom": "EssilorLuxottica",                      "categorie": "titres",  "devise": "€", "isin": "FR0000121667", "euronext_mic": "XPAR"},
    "AI":    {"primary": "AI.PA",    "fallbacks": [],                    "nom": "Air Liquide",                           "categorie": "titres",  "devise": "€", "isin": "FR0000120073", "euronext_mic": "XPAR"},
    "FDJU":  {"primary": "FDJU.PA",  "fallbacks": [],                    "nom": "FDJ United (Française des Jeux)",       "categorie": "titres",  "devise": "€", "isin": "FR0013451333", "euronext_mic": "XPAR"},
    "MC":    {"primary": "MC.PA",    "fallbacks": [],                    "nom": "LVMH",                                  "categorie": "titres",  "devise": "€", "isin": "FR0000121014", "euronext_mic": "XPAR"},
    "SU":    {"primary": "SU.PA",    "fallbacks": [],                    "nom": "Schneider Electric",                    "categorie": "titres",  "devise": "€", "isin": "FR0000121972", "euronext_mic": "XPAR"},
    "ALSEM": {"primary": "ALSEM.PA", "fallbacks": [],                    "nom": "SEMCO Technologies",                    "categorie": "titres",  "devise": "€", "isin": "FR0014010H01", "euronext_mic": "ALXP"},
}
ASSETS = TICKER_MAP  # alias for backward compat

ASSET_CATEGORY = {k: v["categorie"] for k, v in TICKER_MAP.items()}

EXIT_RSI_THRESHOLDS = {
    "metaux":  {"sell_50": 78, "sell_100": 85, "rebuy": 50},
    "crypto":  {"sell_50": 80, "sell_100": 88, "rebuy": 45},
    "actions": {"sell_50": 75, "sell_100": 82, "rebuy": 55},
    "titres":  {"sell_50": 75, "sell_100": 82, "rebuy": 55},
}

ETF_KEYS = [k for k, v in TICKER_MAP.items() if v["categorie"] == "actions"]

SR_ZONE_ATR_MULTIPLIER = 0.5  # demi-largeur de chaque zone = 0.5 × ATR

# Swing scoring sur les actions individuelles détenues
STOCK_PICKING_MAP = {
    "ASML":  {"primary": "ASML.AS",  "fallbacks": [], "nom": "ASML Holding",       "sector": "semiconductors",    "market_cap": "large", "devise": "€"},
    "SGO":   {"primary": "SGO.PA",   "fallbacks": [], "nom": "Saint-Gobain",       "sector": "building_materials","market_cap": "large", "devise": "€"},
    "EL":    {"primary": "EL.PA",    "fallbacks": [], "nom": "EssilorLuxottica",   "sector": "healthcare_optics", "market_cap": "large", "devise": "€"},
    "AI":    {"primary": "AI.PA",    "fallbacks": [], "nom": "Air Liquide",        "sector": "chemicals",         "market_cap": "large", "devise": "€"},
    "FDJU":  {"primary": "FDJU.PA",  "fallbacks": [], "nom": "FDJ United",         "sector": "gaming",            "market_cap": "mid",   "devise": "€"},
    "MC":    {"primary": "MC.PA",    "fallbacks": [], "nom": "LVMH",               "sector": "luxury",            "market_cap": "large", "devise": "€"},
    "SU":    {"primary": "SU.PA",    "fallbacks": [], "nom": "Schneider Electric", "sector": "industrial_tech",   "market_cap": "large", "devise": "€"},
    "ALSEM": {"primary": "ALSEM.PA", "fallbacks": [], "nom": "SEMCO Technologies", "sector": "semiconductors",    "market_cap": "small", "devise": "€"},
}
