"""
Configuration Management
Loads from environment variables (Railway) or .env file
"""

import os
import json
from dotenv import load_dotenv

load_dotenv()

class Config:
    # ─── API Keys ────────────────────────────────────────────────────────────
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
    TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY", "")
    FINNHUB_KEY    = os.getenv("FINNHUB_KEY", "")
    ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")

    # ─── Scoring ─────────────────────────────────────────────────────────────
    MIN_SCORE = int(os.getenv("MIN_SCORE", "70"))       # Higher = fewer but better signals
    MIN_CONFIRMATIONS = int(os.getenv("MIN_CONFIRMATIONS", "5"))  # Minimum confirmations

    # ─── Trade Parameters ────────────────────────────────────────────────────
    TP1_PCT = float(os.getenv("TP1_PCT", "2.0"))        # 2%
    TP2_PCT = float(os.getenv("TP2_PCT", "4.0"))        # 4%
    SL_PCT  = float(os.getenv("SL_PCT",  "1.5"))        # 1.5% (tight stop)
    MAX_HOLD_DAYS = int(os.getenv("MAX_HOLD_DAYS", "7"))

    # ─── Filters ─────────────────────────────────────────────────────────────
    MIN_PRICE  = float(os.getenv("MIN_PRICE", "5.0"))
    MAX_PRICE  = float(os.getenv("MAX_PRICE", "500.0"))
    MIN_VOLUME = int(os.getenv("MIN_VOLUME", "500000"))   # 500K avg daily vol
    MIN_MKTCAP = float(os.getenv("MIN_MKTCAP", "500e6")) # $500M market cap

    # ─── Scan Settings ───────────────────────────────────────────────────────
    SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "180"))  # 3 minutes
    COOLDOWN_SEC  = int(os.getenv("COOLDOWN_SEC", "3600"))  # 1 hour per symbol

    # ─── Storage ─────────────────────────────────────────────────────────────
    _CHATS_FILE     = "chats.json"
    _WATCHLIST_FILE = "watchlist.json"
    _COOLDOWN_FILE  = "cooldowns.json"

    # ─── Default Watchlist ───────────────────────────────────────────────────
    DEFAULT_WATCHLIST = [
        "AAPL", "NVDA", "TSLA", "AMD", "AVGO", "QCOM", "MU", "ORCL", "ADBE", "CRM",
        "NOW", "PANW", "CRWD", "SNOW", "ZS", "OKTA", "AMAT", "LRCX", "KLAC", "NXPI",
        "ON", "GFS", "MPWR", "TER", "TXN", "SMCI", "ARM", "ASML", "ISRG", "SYK",
        "ABT", "JNJ", "TMO", "DHR", "BSX", "MDT", "ZTS", "PG", "HD", "SBUX",
        "NKE", "LULU", "TJX", "AME", "ETN", "EMR", "ITW", "UNP", "UPS", "XPO",
        "JBHT", "CHRW", "ODFL", "EXPD", "ROK", "DOV", "PH", "V", "MA", "SPGI",
        "MSCI", "MCO", "FICO", "CDNS", "SNPS", "ANET", "CSCO", "NTAP", "VRSN",
        "FFIV", "GLW", "TEL", "APH", "KEYS", "GRMN", "MSI", "EQIX", "WELL", "WM",
        "RSG", "GWW", "FAST", "CARR", "OTIS", "TT", "PWR", "PPG", "SHW", "ECL",
        "CL", "CLX", "HSY", "KMB", "MCK", "CIEN", "LLY", "MRK", "GILD", "VRTX",
        "ALNY", "NBIX", "INCY", "DXCM", "IDXX", "ZBRA", "WST", "WAT", "BDX",
        "EW", "A", "APD", "LIN", "XOM", "CVX", "SLB",
        "ALB", "ALGN", "AOS", "APOG", "AR", "ARHS", "ARWR", "ASLE", "ASPN",
        "AUDC", "AVNS", "AVO", "AWI", "AXSM", "AYI", "AZTA", "AZO", "BBY",
        "BIO", "BIIB", "BIRK", "BKTI", "BLD", "BLDR",
        "SPY", "QQQ",
    ]

    def __init__(self):
        self._load_chats()
        self._load_watchlist()
        self._load_cooldowns()

    # ─── Chat Management ─────────────────────────────────────────────────────
    def _load_chats(self):
        try:
            with open(self._CHATS_FILE) as f:
                self._chats = set(json.load(f))
        except:
            self._chats = set()

    def _save_chats(self):
        with open(self._CHATS_FILE, 'w') as f:
            json.dump(list(self._chats), f)

    def add_chat(self, chat_id: int):
        self._chats.add(chat_id)
        self._save_chats()

    def remove_chat(self, chat_id: int):
        self._chats.discard(chat_id)
        self._save_chats()

    def get_chats(self) -> list:
        return list(self._chats)

    # ─── Watchlist Management ────────────────────────────────────────────────
    def _load_watchlist(self):
        try:
            with open(self._WATCHLIST_FILE) as f:
                self._watchlist = set(json.load(f))
        except:
            self._watchlist = set(self.DEFAULT_WATCHLIST)
            self._save_watchlist()

    def _save_watchlist(self):
        with open(self._WATCHLIST_FILE, 'w') as f:
            json.dump(list(self._watchlist), f)

    def add_to_watchlist(self, symbol: str) -> bool:
        if symbol in self._watchlist:
            return False
        self._watchlist.add(symbol)
        self._save_watchlist()
        return True

    def remove_from_watchlist(self, symbol: str) -> bool:
        if symbol not in self._watchlist:
            return False
        self._watchlist.discard(symbol)
        self._save_watchlist()
        return True

    def get_watchlist(self) -> list:
        return sorted(list(self._watchlist))

    # ─── Cooldown Management ─────────────────────────────────────────────────
    def _load_cooldowns(self):
        try:
            with open(self._COOLDOWN_FILE) as f:
                self._cooldowns = json.load(f)
        except:
            self._cooldowns = {}

    def _save_cooldowns(self):
        with open(self._COOLDOWN_FILE, 'w') as f:
            json.dump(self._cooldowns, f)

    def is_on_cooldown(self, symbol: str) -> bool:
        if symbol not in self._cooldowns:
            return False
        last = self._cooldowns[symbol]
        from datetime import datetime
        elapsed = (datetime.utcnow() - datetime.fromisoformat(last)).total_seconds()
        return elapsed < self.COOLDOWN_SEC

    def set_cooldown(self, symbol: str):
        from datetime import datetime
        self._cooldowns[symbol] = datetime.utcnow().isoformat()
        self._save_cooldowns()
