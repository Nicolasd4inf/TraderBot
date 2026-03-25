"""
Configuration des actifs pour le dashboard Portfolio CTO.
"""

TICKER_MAP = {
    "GOLD":  {"primary": "GOLD.PA",  "fallbacks": ["GLDA.PA"],          "nom": "Or — Amundi Physical Gold",      "categorie": "metaux",  "devise": "€", "isin": "FR0013416716", "euronext_mic": "ETFP"},
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

STOCK_PICKING_MAP = {
    "TE":    {"primary": "TE.PA",     "fallbacks": [], "nom": "Technip Energies",           "sector": "energy_services",    "market_cap": "mid",   "devise": "€"},
    "AL2SI": {"primary": "AL2SI.PA",  "fallbacks": [], "nom": "2CRSI",                      "sector": "tech_ai_servers",    "market_cap": "small", "devise": "€"},
    "ALSEM": {"primary": "ALSEM.PA",  "fallbacks": [], "nom": "SEMCO Technologies",          "sector": "semiconductors",     "market_cap": "small", "devise": "€"},
    "AIR":   {"primary": "AIR.PA",    "fallbacks": [], "nom": "Airbus",                      "sector": "aerospace_defense",  "market_cap": "large", "devise": "€"},
    "AI":    {"primary": "AI.PA",     "fallbacks": [], "nom": "Air Liquide",                 "sector": "chemicals",          "market_cap": "large", "devise": "€"},
    "SU":    {"primary": "SU.PA",     "fallbacks": [], "nom": "Schneider Electric",          "sector": "industrial_tech",    "market_cap": "large", "devise": "€"},
    "STM":   {"primary": "STMPA.PA",  "fallbacks": ["STM.PA"], "nom": "STMicroelectronics", "sector": "semiconductors",     "market_cap": "large", "devise": "€"},
    "BESI":  {"primary": "BESI.AS",   "fallbacks": [], "nom": "BE Semiconductor Industries","sector": "semiconductors",     "market_cap": "mid",   "devise": "€"},
}
