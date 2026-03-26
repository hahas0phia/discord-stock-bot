import discord
from discord import app_commands
from discord.ext import commands
import yfinance as yf
import pandas as pd
import numpy as np
import asyncio
import io
import os
import threading
import sqlite3
import json
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from flask import Flask

# ─── Flask Keep-Alive (24/7) ──────────────────────────────────────────────────

_flask_app = Flask(__name__)

@_flask_app.route("/")
def _home():
    return "EMA Bot 24/7 ✅"

def _run_flask():
    # This tells the bot to listen on the port Render provides
    port = int(os.environ.get("PORT", 10000))
    _flask_app.run(host="0.0.0.0", port=port, use_reloader=False)

# ─── Alerts Database ──────────────────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alerts.db")

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                alert_type TEXT    NOT NULL,
                params     TEXT    NOT NULL,
                created_at TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL,
                ticker       TEXT    NOT NULL,
                shares       INTEGER NOT NULL,
                entry        REAL    NOT NULL,
                stop         REAL    NOT NULL,
                target       REAL    NOT NULL,
                risk_dollars REAL    NOT NULL,
                status       TEXT    NOT NULL DEFAULT 'ACTIVE',
                created_at   TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                ticker      TEXT    NOT NULL,
                shares      REAL    NOT NULL,
                entry_price REAL    NOT NULL,
                added_at    TEXT    NOT NULL,
                UNIQUE(user_id, ticker)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS command_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL,
                username  TEXT    NOT NULL,
                command   TEXT    NOT NULL,
                args_json TEXT    NOT NULL DEFAULT '{}',
                timestamp TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_watchlists (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id  INTEGER NOT NULL,
                ticker   TEXT    NOT NULL,
                added_at TEXT    NOT NULL,
                UNIQUE(user_id, ticker)
            )
        """)
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN exit_price REAL")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN closed_at TEXT")
        except Exception:
            pass
        conn.commit()

def _update_trade_status(trade_id: int, status: str):
    with _db() as conn:
        conn.execute("UPDATE trades SET status = ? WHERE id = ?", (status, trade_id))
        conn.commit()

def _close_trade(trade_id: int, status: str, exit_price: float):
    """Close a trade, recording exit price and close timestamp."""
    with _db() as conn:
        conn.execute(
            "UPDATE trades SET status = ?, exit_price = ?, closed_at = ? WHERE id = ?",
            (status, round(exit_price, 4), datetime.utcnow().isoformat(), trade_id),
        )
        conn.commit()

init_db()

# ─── Bot Setup ────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ─── Bot Start Time (for /ping uptime) ────────────────────────────────────────

BOT_START_TIME = datetime.now(timezone.utc)

def _format_uptime() -> str:
    delta = datetime.now(timezone.utc) - BOT_START_TIME
    total_seconds = int(delta.total_seconds())
    days    = total_seconds // 86400
    hours   = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)

# ─── Rate Limiter (10 scan commands/min per user) ─────────────────────────────

from collections import defaultdict
_rate_limit_store: dict[int, list[float]] = defaultdict(list)
RATE_LIMIT_MAX    = 10
RATE_LIMIT_WINDOW = 60.0

def _check_rate_limit(user_id: int) -> bool:
    """Return True if user is within rate limit, False if exceeded."""
    import time
    now = time.monotonic()
    timestamps = _rate_limit_store[user_id]
    cutoff = now - RATE_LIMIT_WINDOW
    _rate_limit_store[user_id] = [t for t in timestamps if t > cutoff]
    if len(_rate_limit_store[user_id]) >= RATE_LIMIT_MAX:
        return False
    _rate_limit_store[user_id].append(now)
    return True

# ─── Full Ticker Watchlist ────────────────────────────────────────────────────

ALL_TICKERS = [
    # S&P 500 / Large-cap core
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "BRK-B",
    "UNH", "XOM", "JPM", "JNJ", "V", "AVGO", "PG", "MA", "HD", "CVX",
    "MRK", "LLY", "ABBV", "PEP", "KO", "COST", "ADBE", "WMT", "BAC", "CRM",
    "TMO", "ACN", "NFLX", "AMD", "MCD", "CSCO", "ABT", "NKE", "ORCL", "TXN",
    "DHR", "PM", "WFC", "CAT", "INTU", "AMGN", "QCOM", "SPGI", "RTX", "GS",
    "HON", "IBM", "AMAT", "ISRG", "BKNG", "LOW", "MDT", "AXP", "ELV", "NOW",
    "NEE", "SBUX", "UNP", "LMT", "DE", "GILD", "REGN", "CI", "MO", "SYK",
    "MMC", "PLD", "MDLZ", "BLK", "ADI", "PYPL", "VRTX", "ETN", "ZTS", "CB",
    "LRCX", "TJX", "PANW", "KLAC", "SO", "DUK", "PGR", "CME", "AON", "BSX",
    "MU", "SNPS", "ICE", "CL", "CDNS", "GD", "F", "GM", "UBER", "ABNB",
    "COIN", "PLTR", "SOFI", "RIVN", "NIO", "SNOW", "RBLX", "HOOD",
    "ASML", "ARM", "NET", "MPC", "OXY", "PSX", "DVN", "COP", "EOG",
    "HAL", "ROST", "MGM", "APD", "LIN", "SLB", "EXPE", "DDOG", "VLO",
    # ETF / Macro
    "SPY", "QQQ", "IWM", "VTI", "VWO", "HYG", "TLT", "GLD",
    # Young IPO / Fintech
    "UPST", "AFRM", "SQ", "HOOD",
    # AI Datacenter / Semis
    "SMCI", "MRVL",
    # Apparel & Footwear
    "LULU", "ONON", "DECK",
    # AI names
    "PATH", "SOUN", "BBAI",
    # AR / Social
    "SNAP",
    # Batteries / Materials
    "ALB", "LTHM",
    # Crypto Mining
    "MARA", "RIOT", "CIFR", "BITF",
    # EVs
    "LI", "XPEV",
    # Chemicals
    "DOW", "EPD",
    # China ADRs
    "BABA", "PDD", "BIDU",
    # Telecom
    "VZ", "T", "DISH",
    # Crypto vehicles
    "MSTR", "BITO", "GBTC",
    # Data Networking
    "ANET", "CIEN", "JNPR",
    # Disk Drive
    "STX", "WDC",
    # Drones
    "AVAV", "KTOS",
    # eVTOL
    "JOBY", "ACHR",
    # Gold & Silver
    "NEM", "GOLD", "WPM",
    # Home Builders
    "DHI", "PHM", "LEN",
    # Banks (extra)
    "C",
]
# Deduplicate while preserving order
ALL_TICKERS = list(dict.fromkeys(ALL_TICKERS))

MKTCAP_B = {
    "AAPL": 3000, "MSFT": 3000, "NVDA": 2900, "GOOGL": 2100, "GOOG": 2100,
    "AMZN": 2100, "META": 1400, "TSLA": 700,  "BRK-B": 900,  "UNH": 500,
    "XOM": 550,   "JPM": 600,   "JNJ": 380,   "V": 550,      "AVGO": 800,
    "PG": 370,    "MA": 470,    "HD": 360,    "CVX": 280,    "MRK": 250,
    "LLY": 700,   "ABBV": 330,  "PEP": 220,   "KO": 270,     "COST": 380,
    "ADBE": 200,  "WMT": 700,   "BAC": 340,   "CRM": 280,    "TMO": 200,
    "ACN": 210,   "NFLX": 350,  "AMD": 230,   "MCD": 200,    "CSCO": 200,
    "ABT": 180,   "NKE": 100,   "ORCL": 400,  "TXN": 180,    "DHR": 160,
    "PM": 200,    "WFC": 230,   "CAT": 170,   "INTU": 170,   "AMGN": 170,
    "QCOM": 150,  "SPGI": 140,  "RTX": 130,   "GS": 160,     "HON": 130,
    "IBM": 190,   "AMAT": 160,  "ISRG": 150,  "BKNG": 130,   "LOW": 130,
    "MDT": 100,   "AXP": 180,   "ELV": 90,    "NOW": 200,    "NEE": 130,
    "SBUX": 90,   "UNP": 130,   "LMT": 130,   "DE": 100,     "GILD": 110,
    "REGN": 100,  "CI": 80,     "MO": 90,     "SYK": 120,    "MMC": 100,
    "PLD": 100,   "MDLZ": 80,   "BLK": 130,   "ADI": 90,     "PYPL": 70,
    "VRTX": 110,  "ETN": 130,   "ZTS": 80,    "CB": 90,      "LRCX": 90,
    "TJX": 120,   "PANW": 100,  "KLAC": 90,   "SO": 80,      "DUK": 70,
    "PGR": 130,   "CME": 80,    "AON": 70,    "BSX": 110,    "MU": 90,
    "SNPS": 70,   "ICE": 80,    "CL": 60,     "CDNS": 70,    "GD": 70,
    "F": 40,      "GM": 50,     "UBER": 150,  "ABNB": 80,    "COIN": 60,
    "PLTR": 200,  "SOFI": 15,   "RIVN": 10,   "NIO": 10,     "SNOW": 40,
    "RBLX": 20,   "HOOD": 10,   "ASML": 300,  "ARM": 150,    "NET": 50,
    "MPC": 50,    "OXY": 50,    "PSX": 50,    "DVN": 20,     "COP": 150,
    "EOG": 80,    "HAL": 25,    "ROST": 50,   "MGM": 15,     "APD": 50,
    "LIN": 200,   "SLB": 60,    "EXPE": 20,   "DDOG": 35,    "VLO": 40,
    # ETFs / Macro
    "SPY": 500,   "QQQ": 200,   "IWM": 50,    "VTI": 400,    "VWO": 100,
    "HYG": 20,    "TLT": 30,    "GLD": 70,
    # Young IPO / Fintech
    "UPST": 5,    "AFRM": 4,    "SQ": 45,
    # AI Datacenter
    "SMCI": 30,   "MRVL": 60,
    # Apparel
    "LULU": 30,   "ONON": 20,   "DECK": 20,
    # AI
    "PATH": 10,   "SOUN": 3,    "BBAI": 1,
    # AR / Social
    "SNAP": 20,
    # Batteries
    "ALB": 10,    "LTHM": 2,
    # Crypto Mining
    "MARA": 5,    "RIOT": 3,    "CIFR": 1,    "BITF": 1,
    # EVs
    "LI": 20,     "XPEV": 10,
    # Chemicals
    "DOW": 30,    "EPD": 60,
    # China ADRs
    "BABA": 200,  "PDD": 200,   "BIDU": 30,
    # Telecom
    "VZ": 160,    "T": 130,     "DISH": 3,
    # Crypto vehicles
    "MSTR": 80,   "BITO": 5,    "GBTC": 30,
    # Data Networking
    "ANET": 100,  "CIEN": 10,   "JNPR": 12,
    # Disk Drive
    "STX": 20,    "WDC": 15,
    # Drones
    "AVAV": 8,    "KTOS": 4,
    # eVTOL
    "JOBY": 5,    "ACHR": 2,
    # Gold & Silver
    "NEM": 50,    "GOLD": 20,   "WPM": 25,
    # Home Builders
    "DHI": 50,    "PHM": 25,    "LEN": 40,
    # Banks
    "C": 120,
}

SECTOR_MAP = {
    "AAPL": "Technology",    "MSFT": "Technology",    "NVDA": "Technology",
    "GOOGL": "Technology",   "GOOG": "Technology",    "AMZN": "Consumer Disc",
    "META": "Technology",    "TSLA": "Consumer Disc", "BRK-B": "Financials",
    "UNH": "Healthcare",     "XOM": "Energy",         "JPM": "Financials",
    "JNJ": "Healthcare",     "V": "Financials",       "AVGO": "Technology",
    "PG": "Consumer Staples","MA": "Financials",      "HD": "Consumer Disc",
    "CVX": "Energy",         "MRK": "Healthcare",     "LLY": "Healthcare",
    "ABBV": "Healthcare",    "PEP": "Consumer Staples","KO": "Consumer Staples",
    "COST": "Consumer Staples","ADBE": "Technology",  "WMT": "Consumer Staples",
    "BAC": "Financials",     "CRM": "Technology",     "TMO": "Healthcare",
    "ACN": "Technology",     "NFLX": "Communication", "AMD": "Technology",
    "MCD": "Consumer Disc",  "CSCO": "Technology",    "ABT": "Healthcare",
    "NKE": "Consumer Disc",  "ORCL": "Technology",    "TXN": "Technology",
    "DHR": "Healthcare",     "PM": "Consumer Staples","WFC": "Financials",
    "CAT": "Industrials",    "INTU": "Technology",    "AMGN": "Healthcare",
    "QCOM": "Technology",    "SPGI": "Financials",    "RTX": "Industrials",
    "GS": "Financials",      "HON": "Industrials",    "IBM": "Technology",
    "AMAT": "Technology",    "ISRG": "Healthcare",    "BKNG": "Consumer Disc",
    "LOW": "Consumer Disc",  "MDT": "Healthcare",     "AXP": "Financials",
    "ELV": "Healthcare",     "NOW": "Technology",     "NEE": "Utilities",
    "SBUX": "Consumer Disc", "UNP": "Industrials",    "LMT": "Industrials",
    "DE": "Industrials",     "GILD": "Healthcare",    "REGN": "Healthcare",
    "CI": "Healthcare",      "MO": "Consumer Staples","SYK": "Healthcare",
    "MMC": "Financials",     "PLD": "Real Estate",    "MDLZ": "Consumer Staples",
    "BLK": "Financials",     "ADI": "Technology",     "PYPL": "Financials",
    "VRTX": "Healthcare",    "ETN": "Industrials",    "ZTS": "Healthcare",
    "CB": "Financials",      "LRCX": "Technology",    "TJX": "Consumer Disc",
    "PANW": "Technology",    "KLAC": "Technology",    "SO": "Utilities",
    "DUK": "Utilities",      "PGR": "Financials",     "CME": "Financials",
    "AON": "Financials",     "BSX": "Healthcare",     "MU": "Technology",
    "SNPS": "Technology",    "ICE": "Financials",     "CL": "Consumer Staples",
    "CDNS": "Technology",    "GD": "Industrials",     "F": "Consumer Disc",
    "GM": "Consumer Disc",   "UBER": "Industrials",   "ABNB": "Consumer Disc",
    "COIN": "Financials",    "PLTR": "Technology",    "SOFI": "Financials",
    "RIVN": "Consumer Disc", "NIO": "Consumer Disc",  "SNOW": "Technology",
    "RBLX": "Communication", "HOOD": "Financials",    "ASML": "Technology",
    "ARM": "Technology",     "NET": "Technology",     "MPC": "Energy",
    "OXY": "Energy",         "PSX": "Energy",         "DVN": "Energy",
    "COP": "Energy",         "EOG": "Energy",         "HAL": "Energy",
    "ROST": "Consumer Disc", "MGM": "Consumer Disc",  "APD": "Materials",
    "LIN": "Materials",      "SLB": "Energy",         "EXPE": "Consumer Disc",
    "DDOG": "Technology",    "VLO": "Energy",
    # ETFs
    "SPY": "ETF",            "QQQ": "ETF",            "IWM": "ETF",
    "VTI": "ETF",            "VWO": "ETF",            "HYG": "ETF",
    "TLT": "ETF",            "GLD": "ETF",
    # Young IPO / Fintech
    "UPST": "Financials",    "AFRM": "Financials",    "SQ": "Financials",
    # AI Datacenter
    "SMCI": "Technology",    "MRVL": "Technology",
    # Apparel
    "LULU": "Consumer Disc", "ONON": "Consumer Disc", "DECK": "Consumer Disc",
    # AI
    "PATH": "Technology",    "SOUN": "Technology",    "BBAI": "Technology",
    # AR / Social
    "SNAP": "Communication",
    # Batteries / Materials
    "ALB": "Materials",      "LTHM": "Materials",
    # Crypto Mining
    "MARA": "Financials",    "RIOT": "Financials",    "CIFR": "Financials",
    "BITF": "Financials",
    # EVs
    "LI": "Consumer Disc",   "XPEV": "Consumer Disc",
    # Chemicals
    "DOW": "Materials",      "EPD": "Energy",
    # China ADRs
    "BABA": "Consumer Disc", "PDD": "Consumer Disc",  "BIDU": "Technology",
    # Telecom
    "VZ": "Communication",   "T": "Communication",    "DISH": "Communication",
    # Crypto vehicles
    "MSTR": "Technology",    "BITO": "ETF",           "GBTC": "ETF",
    # Data Networking
    "ANET": "Technology",    "CIEN": "Technology",    "JNPR": "Technology",
    # Disk Drive
    "STX": "Technology",     "WDC": "Technology",
    # Drones
    "AVAV": "Industrials",   "KTOS": "Industrials",
    # eVTOL
    "JOBY": "Industrials",   "ACHR": "Industrials",
    # Gold & Silver
    "NEM": "Materials",      "GOLD": "Materials",     "WPM": "Materials",
    # Home Builders
    "DHI": "Consumer Disc",  "PHM": "Consumer Disc",  "LEN": "Consumer Disc",
    # Banks
    "C": "Financials",
}

# ─── 25 Themed Watchlists ─────────────────────────────────────────────────────

WATCHLISTS: dict[str, list[str]] = {
    # ── Your 14 themed sectors + SpaceX ─────────────────────────────────────
    "Media":             ["NFLX", "DIS", "PARA", "FOXA", "WBD", "ROKU", "SPOT", "TTWO"],
    "Mining/Rare Earth": ["MP", "UUUU", "NEM", "GOLD", "FCX", "CLF", "AA", "RGLD", "WPM"],
    "Network Hardware":  ["ANET", "CSCO", "JNPR", "CIEN", "INFN", "COMM", "CALX", "NET"],
    "Nuclear":           ["CEG", "CCJ", "VST", "NNE", "SMR", "OKLO", "BWXT", "LEU"],
    "Oil & Gas":         ["XOM", "CVX", "COP", "SLB", "OXY", "HAL", "VLO", "MPC", "PSX"],
    "Quantum":           ["IONQ", "RGTI", "QUBT", "IBM", "GOOGL", "MSFT", "QBTS", "ARQQ"],
    "Real Estate":       ["AMT", "PLD", "EQIX", "CCI", "WELL", "SPG", "O", "DLR"],
    "Robotics":          ["ISRG", "ABB", "ROK", "TER", "FANUY", "IRBT", "NVDA", "PATH"],
    "Self Driving":      ["TSLA", "GOOGL", "MBLY", "LAZR", "LIDR", "INVZ", "OUST", "UBER"],
    "Semiconductor":     ["NVDA", "AMD", "AVGO", "QCOM", "AMAT", "LRCX", "KLAC", "MRVL", "SMCI"],
    "Smart Glasses":     ["META", "SNAP", "GOOGL", "AAPL", "MVIS", "VUZI", "KOPIN"],
    "Solar":             ["ENPH", "SEDG", "FSLR", "SPWR", "RUN", "ARRY", "NOVA", "CSIQ"],
    "Space":             ["RKLB", "ASTS", "LUNR", "BKSY", "PL", "SPCE", "ASTR", "LMT", "RTX"],
    "Tele Health":       ["TDOC", "AMWL", "HIMS", "DOCS", "ACCD", "ONEM", "PHR", "WDFC"],
    "SpaceX Plays":      ["RKLB", "ASTS", "LUNR", "BKSY", "BA", "LMT", "RTX", "HII", "NOC"],
    # ── Original themed watchlists ───────────────────────────────────────────
    "AI":                ["PLTR", "PATH", "SOUN", "BBAI", "NVDA", "AMD", "IONQ", "GFAI"],
    "AI Datacenter":     ["NVDA", "AMD", "SMCI", "AVGO", "MRVL", "AMAT", "LRCX"],
    "Augmented Reality": ["META", "SNAP", "GOOGL", "AAPL", "MVIS", "VUZI"],
    "Banks":             ["JPM", "BAC", "WFC", "GS", "C", "MS", "USB", "PNC"],
    "Batteries":         ["ALB", "LTHM", "LAC", "SQM", "LTUM"],
    "Cars & EV":         ["TSLA", "RIVN", "LI", "XPEV", "NIO", "F", "GM", "LCID"],
    "Chemicals":         ["DOW", "EPD", "APD", "LIN", "ECL", "PPG"],
    "China":             ["BABA", "PDD", "BIDU", "NIO", "XPEV", "LI", "JD"],
    "Communication":     ["VZ", "T", "META", "NFLX", "SNAP", "GOOGL"],
    "Crypto":            ["MSTR", "COIN", "MARA", "RIOT", "CIFR", "BITF", "BITO", "HOOD"],
    "Data Networking":   ["ANET", "CIEN", "JNPR", "CSCO", "NET", "ZS"],
    "Disk Drive":        ["STX", "WDC", "MU", "NVDA", "NAND"],
    "Drones":            ["AVAV", "KTOS", "LMT", "RTX", "JOBY", "ACHR", "RKLB"],
    "Energy":            ["XOM", "CVX", "COP", "SLB", "OXY", "HAL", "VLO", "MPC"],
    "ETF Basket":        ["SPY", "QQQ", "IWM", "VTI", "GLD", "TLT", "HYG", "ARKK"],
    "eVTOL":             ["JOBY", "ACHR", "LILM", "EVTL"],
    "Finance & Loans":   ["SOFI", "UPST", "AFRM", "SQ", "PYPL", "NU"],
    "Fintech":           ["PYPL", "SQ", "AFRM", "SOFI", "UPST", "HOOD", "NU", "DAVE"],
    "Gold & Silver":     ["NEM", "GOLD", "WPM", "GLD", "PAAS", "CDE", "HL", "AG"],
    "Home Builder":      ["DHI", "PHM", "LEN", "TOL", "MTH"],
    "Young IPO":         ["PLTR", "SOFI", "UPST", "AFRM", "HOOD", "RIVN", "ACHR", "JOBY"],
    "Market Indicators": ["SPY", "QQQ", "IWM", "HYG", "TLT", "GLD", "VIX"],
}

async def watchlist_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    matches = [
        app_commands.Choice(name=name, value=name)
        for name in WATCHLISTS
        if current.lower() in name.lower()
    ]
    return matches[:25]

# ─── Core Data Functions ──────────────────────────────────────────────────────

def compute_emas(closes: pd.Series) -> dict:
    return {
        "ema9":  closes.ewm(span=9,  adjust=False).mean().iloc[-1],
        "ema21": closes.ewm(span=21, adjust=False).mean().iloc[-1],
        "ema50": closes.ewm(span=50, adjust=False).mean().iloc[-1],
    }

def assign_watchlist(price: float, emas: dict) -> str:
    if price > emas["ema9"] and price > emas["ema21"] and price > emas["ema50"]:
        return "Leading"
    elif price > emas["ema21"] and price > emas["ema50"]:
        return "Mediocre"
    else:
        return "Lagging"

def get_tier_from_row(row) -> str:
    """For CSV upload: assign tier from EMA columns in a DataFrame row."""
    try:
        price = float(row.get("Close", 0))
        e9  = float(row.get("EMA9",  row.get("Ema9",  0)))
        e21 = float(row.get("EMA21", row.get("Ema21", 0)))
        e50 = float(row.get("EMA50", row.get("Ema50", 0)))
        if price > e9 and price > e21 and price > e50:
            return "Leading"
        elif price > e21 and price > e50:
            return "Mediocre"
        else:
            return "Lagging"
    except Exception:
        return "Unknown"

def fetch_data(tickers: list = None) -> pd.DataFrame:
    """
    Download ~3 months of OHLCV for every ticker and compute all metrics.
    Column order matches Martin Luk template exactly:
    Ticker, Sector, Close, EMA9, EMA21, EMA50, Perf1D, Perf1W, Perf1M,
    RelVol, DollarVol_M, ADR, Gap, MktCap, Watchlist
    Sorted by Perf1M descending.
    """
    if tickers is None:
        tickers = ALL_TICKERS

    rows = []
    try:
        download_arg = tickers[0] if len(tickers) == 1 else tickers
        raw = yf.download(
            download_arg,
            period="3mo",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception:
        return pd.DataFrame()

    for ticker in tickers:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                df = raw.xs(ticker, level=1, axis=1)
            else:
                df = raw

            df = df.dropna(how="all")
            if len(df) < 22:
                continue

            closes  = df["Close"].dropna()
            opens   = df["Open"].dropna()
            highs   = df["High"].dropna()
            lows    = df["Low"].dropna()
            volumes = df["Volume"].dropna()

            price      = float(closes.iloc[-1])
            prev_close = float(closes.iloc[-2])

            # Gap = today's open vs yesterday's close
            gap_pct = (float(opens.iloc[-1]) - prev_close) / prev_close * 100

            # Relative volume vs 20-day avg
            avg_vol_20 = volumes.iloc[-21:-1].mean()
            rel_vol    = float(volumes.iloc[-1]) / avg_vol_20 if avg_vol_20 > 0 else 1.0

            # Perf1D
            perf_1d = (price - prev_close) / prev_close * 100

            # Perf1W — 5 trading days back
            w_idx      = max(0, len(closes) - 6)
            start_1w   = float(closes.iloc[w_idx])
            perf_1w    = (price - start_1w) / start_1w * 100

            # Perf1M — 22 trading days back
            m_idx      = max(0, len(closes) - 22)
            start_1m   = float(closes.iloc[m_idx])
            perf_1m    = (price - start_1m) / start_1m * 100

            # Dollar volume
            dol_vol = price * float(volumes.iloc[-1]) / 1_000_000

            # ADR — 14-day average true range as % of close
            adr_14 = ((highs.iloc[-15:-1] - lows.iloc[-15:-1]) / closes.iloc[-15:-1] * 100).mean()

            emas      = compute_emas(closes)
            watchlist = assign_watchlist(price, emas)
            sector    = SECTOR_MAP.get(ticker, "Other")
            mktcap    = MKTCAP_B.get(ticker, 0)

            rows.append({
                "Ticker":      ticker,
                "Sector":      sector,
                "Close":       round(price, 2),
                "EMA9":        round(emas["ema9"], 2),
                "EMA21":       round(emas["ema21"], 2),
                "EMA50":       round(emas["ema50"], 2),
                "Perf1D":      round(perf_1d, 2),
                "Perf1W":      round(perf_1w, 2),
                "Perf1M":      round(perf_1m, 2),
                "RelVol":      round(rel_vol, 2),
                "DollarVol_M": round(dol_vol, 1),
                "ADR":         round(adr_14, 2),
                "Gap":         round(gap_pct, 2),
                "MktCap":      f"{mktcap}B" if mktcap else "N/A",
                "Watchlist":   watchlist,
            })
        except Exception:
            pass

    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        df_out = df_out.sort_values("Perf1M", ascending=False).reset_index(drop=True)
    return df_out

def df_to_file(df: pd.DataFrame, filename: str) -> discord.File:
    buf = io.BytesIO(df.to_csv(index=False).encode())
    return discord.File(buf, filename=filename)

def build_tv_watchlist_file(tickers: list[str], price_map: dict | None = None) -> discord.File:
    """
    Build a TradingView watchlist-import CSV (Symbol, Price, Exchange).
    If price_map is provided, uses those prices; otherwise fetches the latest close.
    """
    rows = []
    for ticker in tickers:
        price = (price_map or {}).get(ticker, 0)
        if not price:
            try:
                raw = yf.download(ticker, period="1d", auto_adjust=True, progress=False)
                price = float(raw["Close"].iloc[-1]) if not raw.empty else 0
            except Exception:
                price = 0
        rows.append({"Symbol": ticker, "Price": f"{price:.2f}", "Exchange": "NASDAQ"})
    df_wl = pd.DataFrame(rows)
    buf = io.BytesIO(df_wl.to_csv(index=False).encode())
    return discord.File(buf, "tradingview_watchlist.csv")

# ─── UI Components ────────────────────────────────────────────────────────────

class DownloadCSV(discord.ui.View):
    def __init__(self, csv_bytes: bytes, filename: str, tickers: list[str] | None = None):
        super().__init__(timeout=300)
        self.csv_bytes = csv_bytes
        self.filename  = filename
        self.tickers   = tickers or []
        if not self.tickers:
            self.remove_item(self.tv_btn)

    @discord.ui.button(label="📥 Download CSV", style=discord.ButtonStyle.green, row=0)
    async def download_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        file = discord.File(io.BytesIO(self.csv_bytes), self.filename)
        await interaction.response.send_message(file=file, ephemeral=True)

    @discord.ui.button(label="📈 TradingView Watchlist", style=discord.ButtonStyle.green, row=0)
    async def tv_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        wl_file = build_tv_watchlist_file(self.tickers)
        tickers_str = ", ".join(self.tickers)
        embed = discord.Embed(
            title="📊 TradingView Watchlist",
            description=(
                f"**{len(self.tickers)} stocks** — `{tickers_str}`\n\n"
                "**How to import:**\n"
                "1. TradingView → Watchlist\n"
                "2. Click `...` → Import\n"
                "3. Upload `tradingview_watchlist.csv`\n"
                "4. All stocks added instantly!"
            ),
            color=0x1A6EBD,
            timestamp=datetime.utcnow(),
        )
        await interaction.followup.send(embed=embed, file=wl_file, ephemeral=True)


class TierDownloadView(discord.ui.View):
    """
    4 buttons: Full CSV ↓ (all results) + Leading/Mediocre/Lagging tier CSVs.
    Used by /premarket, /potent, /leaders, /generatecsv, /sector, /watchlists, /tier.
    """

    def __init__(self, df: pd.DataFrame, prefix: str = "scan"):
        super().__init__(timeout=1800)   # 30 min
        self.df      = df
        self.prefix  = prefix
        self.date_str = datetime.utcnow().strftime("%m-%d-%y")

    def _csv_file_and_subset(self, tier: str):
        subset = self.df[self.df["Watchlist"] == tier]
        buf    = io.BytesIO(subset.to_csv(index=False).encode())
        return discord.File(buf, f"{self.prefix}-{tier}-{self.date_str}.csv"), subset

    @discord.ui.button(label="📥 Full CSV ↓", style=discord.ButtonStyle.green, row=0)
    async def full_csv_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        buf  = io.BytesIO(self.df.to_csv(index=False).encode())
        file = discord.File(buf, f"{self.prefix}-full-{self.date_str}.csv")
        await interaction.response.send_message(file=file, ephemeral=True)

    @discord.ui.button(label="🟢 Leading CSV", style=discord.ButtonStyle.success, row=0)
    async def leading_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        f, subset = self._csv_file_and_subset("Leading")
        await interaction.response.send_message(file=f, view=TVWatchlistView(subset))

    @discord.ui.button(label="🟡 Mediocre CSV", style=discord.ButtonStyle.secondary, row=0)
    async def mediocre_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        f, subset = self._csv_file_and_subset("Mediocre")
        await interaction.response.send_message(file=f, view=TVWatchlistView(subset))

    @discord.ui.button(label="🔴 Lagging CSV", style=discord.ButtonStyle.danger, row=0)
    async def lagging_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        f, subset = self._csv_file_and_subset("Lagging")
        await interaction.response.send_message(file=f, view=TVWatchlistView(subset))

    @discord.ui.button(label="📈 TradingView Watchlist", style=discord.ButtonStyle.green, row=1)
    async def tv_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        leading = self.df[self.df["Watchlist"] == "Leading"]["Ticker"].tolist()[:5]
        tickers = leading if leading else self.df["Ticker"].tolist()[:5]
        price_map = self.df.set_index("Ticker")["Close"].to_dict()
        wl_file = build_tv_watchlist_file(tickers, price_map=price_map)
        tickers_str = ", ".join(tickers)
        embed = discord.Embed(
            title="📊 TradingView Watchlist",
            description=(
                f"**{len(tickers)} stocks** — `{tickers_str}`\n\n"
                "**How to import:**\n"
                "1. TradingView → Watchlist\n"
                "2. Click `...` → Import\n"
                "3. Upload `tradingview_watchlist.csv`\n"
                "4. All stocks added instantly!"
            ),
            color=0x1A6EBD,
            timestamp=datetime.utcnow(),
        )
        await interaction.followup.send(embed=embed, file=wl_file, ephemeral=True)


class TVWatchlistView(discord.ui.View):
    """Single-button view that sends a TradingView watchlist CSV for a given df subset."""

    def __init__(self, df: pd.DataFrame):
        super().__init__(timeout=1800)
        self.df = df

    @discord.ui.button(label="📈 TradingView Watchlist", style=discord.ButtonStyle.green)
    async def tv_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        tickers   = self.df["Ticker"].tolist()[:5]
        price_map = self.df.set_index("Ticker")["Close"].to_dict()
        wl_file   = build_tv_watchlist_file(tickers, price_map=price_map)
        tickers_str = ", ".join(tickers)
        embed = discord.Embed(
            title="📊 TradingView Watchlist",
            description=(
                f"**{len(tickers)} stocks** — `{tickers_str}`\n\n"
                "**How to import:**\n"
                "1. TradingView → Watchlist\n"
                "2. Click `...` → Import\n"
                "3. Upload `tradingview_watchlist.csv`\n"
                "4. All stocks added instantly!"
            ),
            color=0x1A6EBD,
            timestamp=datetime.utcnow(),
        )
        await interaction.followup.send(embed=embed, file=wl_file, ephemeral=True)


class ScanTierView(discord.ui.View):
    """
    2-button view attached to /scan tier results: Full CSV ↓ + TradingView Watchlist.
    Ensures a guaranteed full-CSV download is always available on mobile.
    """

    def __init__(self, csv_bytes: bytes, filename: str, df: pd.DataFrame):
        super().__init__(timeout=1800)
        self.csv_bytes = csv_bytes
        self.filename  = filename
        self.df        = df

    @discord.ui.button(label="📥 Full CSV ↓", style=discord.ButtonStyle.green, row=0)
    async def full_csv_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        file = discord.File(io.BytesIO(self.csv_bytes), self.filename)
        await interaction.response.send_message(file=file, ephemeral=True)

    @discord.ui.button(label="📈 TradingView Watchlist", style=discord.ButtonStyle.blurple, row=0)
    async def tv_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        tickers   = self.df["Ticker"].tolist()[:5]
        price_map = self.df.set_index("Ticker")["Close"].to_dict() if "Close" in self.df.columns else None
        wl_file   = build_tv_watchlist_file(tickers, price_map=price_map)
        tickers_str = ", ".join(tickers)
        embed = discord.Embed(
            title="📊 TradingView Watchlist",
            description=(
                f"**{len(tickers)} stocks** — `{tickers_str}`\n\n"
                "**How to import:**\n"
                "1. TradingView → Watchlist\n"
                "2. Click `...` → Import\n"
                "3. Upload `tradingview_watchlist.csv`\n"
                "4. All stocks added instantly!"
            ),
            color=0x1A6EBD,
            timestamp=datetime.utcnow(),
        )
        await interaction.followup.send(embed=embed, file=wl_file, ephemeral=True)


class ScanView(discord.ui.View):
    """
    3-button view for /scan — posts a visible message with stock count + CSV
    when a tier button is clicked (not ephemeral, so the channel sees it).
    """

    LABELS = {
        "Leading":  ("🟢 Leading (LONG-ONLY)",  discord.ButtonStyle.success,   0x2DC653),
        "Mediocre": ("🟡 Mediocre (LONG/SHORT)", discord.ButtonStyle.secondary,  0xF77F00),
        "Lagging":  ("🔴 Lagging (SHORT-ONLY)",  discord.ButtonStyle.danger,     0xE63946),
    }

    def __init__(self, df: pd.DataFrame):
        super().__init__(timeout=1800)
        self.df       = df
        self.date_str = datetime.utcnow().strftime("%m-%d-%y")

    async def _send_tier(self, interaction: discord.Interaction, tier: str):
        label, _, color = self.LABELS[tier]
        subset = self.df[self.df["Watchlist"] == tier]
        csv_bytes = subset.to_csv(index=False).encode()
        embed  = discord.Embed(
            title=f"{label}",
            description=f"**{len(subset)} stocks** — full list via Full CSV ↓ button",
            color=color,
            timestamp=datetime.utcnow(),
        )
        lines = []
        for _, row in subset.head(5).iterrows():
            arrow = "🟢" if row["Perf1D"] >= 0 else "🔴"
            lines.append(
                f"{arrow} **{row['Ticker']}** `{row['Perf1D']:+.1f}%` 1D "
                f"`{row['Perf1M']:+.1f}%` 1M · {row['Sector']}"
            )
        preview_label = f"Top 5 of {len(subset)}" if len(subset) > 5 else f"All {len(subset)}"
        embed.add_field(name=preview_label, value="\n".join(lines) or "_None_", inline=False)
        embed.set_footer(text=f"Showing 5/{len(subset)} — click Full CSV ↓ for complete list")
        filename = f"watchlist_scan-{self.date_str}-{tier}.csv"
        view = ScanTierView(csv_bytes, filename, subset)
        await interaction.response.send_message(embed=embed, view=view)

    @discord.ui.button(label="🟢 Leading", style=discord.ButtonStyle.success)
    async def leading_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send_tier(interaction, "Leading")

    @discord.ui.button(label="🟡 Mediocre", style=discord.ButtonStyle.secondary)
    async def mediocre_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send_tier(interaction, "Mediocre")

    @discord.ui.button(label="🔴 Lagging", style=discord.ButtonStyle.danger)
    async def lagging_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send_tier(interaction, "Lagging")

    @discord.ui.button(label="📈 TradingView Watchlist", style=discord.ButtonStyle.green)
    async def tv_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        leading = self.df[self.df["Watchlist"] == "Leading"]["Ticker"].tolist()[:5]
        if not leading:
            await interaction.followup.send("No Leading stocks found.", ephemeral=True)
            return
        price_map = self.df.set_index("Ticker")["Close"].to_dict()
        wl_file = build_tv_watchlist_file(leading, price_map=price_map)
        tickers_str = ", ".join(leading)
        embed = discord.Embed(
            title="📊 TradingView Watchlist",
            description=(
                f"**{len(leading)} stocks** — `{tickers_str}`\n\n"
                "**How to import:**\n"
                "1. TradingView → Watchlist\n"
                "2. Click `...` → Import\n"
                "3. Upload `tradingview_watchlist.csv`\n"
                "4. All stocks added instantly!"
            ),
            color=0x1A6EBD,
            timestamp=datetime.utcnow(),
        )
        await interaction.followup.send(embed=embed, file=wl_file, ephemeral=True)


class PaginatedView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed], timeout: int = 120,
                 df: pd.DataFrame | None = None):
        super().__init__(timeout=timeout)
        self.pages   = pages
        self.current = 0
        self.df      = df
        self._sync()
        if df is None:
            self.remove_item(self.tv_btn)

    def _sync(self):
        self.prev_btn.disabled    = self.current == 0
        self.next_btn.disabled    = self.current >= len(self.pages) - 1
        self.counter_btn.label    = f"{self.current + 1}/{len(self.pages)}"

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current -= 1; self._sync()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True)
    async def counter_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current += 1; self._sync()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="📈 TradingView Watchlist", style=discord.ButtonStyle.green)
    async def tv_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        tickers   = self.df["Ticker"].tolist()[:5]
        price_map = self.df.set_index("Ticker")["Close"].to_dict() if "Close" in self.df.columns else None
        wl_file   = build_tv_watchlist_file(tickers, price_map=price_map)
        tickers_str = ", ".join(tickers)
        embed = discord.Embed(
            title="📊 TradingView Watchlist",
            description=(
                f"**{len(tickers)} stocks** — `{tickers_str}`\n\n"
                "**How to import:**\n"
                "1. TradingView → Watchlist\n"
                "2. Click `...` → Import\n"
                "3. Upload `tradingview_watchlist.csv`\n"
                "4. All stocks added instantly!"
            ),
            color=0x1A6EBD,
            timestamp=datetime.utcnow(),
        )
        await interaction.followup.send(embed=embed, file=wl_file, ephemeral=True)

# ─── /recommend UI classes ────────────────────────────────────────────────────

class TradeView(discord.ui.View):
    """3-button view shown after a trade is logged: Stop Hit / 3R Hit / Breakeven."""

    def __init__(self, trade_id: int, owner_id: int):
        super().__init__(timeout=86400)
        self.trade_id = trade_id
        self.owner_id = owner_id

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This trade belongs to someone else.", ephemeral=True
            )
            return False
        return True

    async def _check_not_closed(self, interaction: discord.Interaction) -> bool:
        """Returns False (and replies) if the trade is already in a terminal state."""
        with _db() as conn:
            row = conn.execute(
                "SELECT status FROM trades WHERE id = ?", (self.trade_id,)
            ).fetchone()
        if row and row["status"] not in ("ACTIVE",):
            await interaction.response.send_message(
                f"This trade is already **{row['status']}** — no changes made.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="❌ Hit Stop", style=discord.ButtonStyle.danger, row=0)
    async def stop_hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        if not await self._check_not_closed(interaction):
            return
        with _db() as conn:
            row = conn.execute("SELECT stop FROM trades WHERE id = ?", (self.trade_id,)).fetchone()
        exit_price = row["stop"] if row else 0.0
        _close_trade(self.trade_id, "STOP_HIT", exit_price)
        embed = discord.Embed(
            title="💥 Stop Logged",
            description="Trade marked as **STOP_HIT**. Risk managed — well done for sticking to the plan. 💪",
            color=0xFF1744,
            timestamp=datetime.utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="✅ Hit 3R", style=discord.ButtonStyle.success, row=0)
    async def target_hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        if not await self._check_not_closed(interaction):
            return
        with _db() as conn:
            row = conn.execute("SELECT target FROM trades WHERE id = ?", (self.trade_id,)).fetchone()
        exit_price = row["target"] if row else 0.0
        _close_trade(self.trade_id, "3R_HIT", exit_price)
        embed = discord.Embed(
            title="🎉 3R Win Logged",
            description="Trade marked as **3R_HIT**. Outstanding execution! 🚀",
            color=0x00C853,
            timestamp=datetime.utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="➡️ Move to Breakeven", style=discord.ButtonStyle.primary, row=0)
    async def breakeven(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        with _db() as conn:
            row = conn.execute(
                "SELECT entry, status FROM trades WHERE id = ?", (self.trade_id,)
            ).fetchone()
            if row:
                if row["status"] != "ACTIVE":
                    await interaction.response.send_message(
                        f"This trade is already **{row['status']}** — no changes made.", ephemeral=True
                    )
                    return
                conn.execute(
                    "UPDATE trades SET stop = ? WHERE id = ?",
                    (row["entry"], self.trade_id),
                )
                conn.commit()
        embed = discord.Embed(
            title="🔒 Stop Moved to Breakeven",
            description=(
                "Stop price updated to your **entry price** — trade is now risk-free.\n"
                "The bot will continue monitoring this trade."
            ),
            color=0x7289DA,
            timestamp=datetime.utcnow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class BuyModal(discord.ui.Modal):
    """Modal for entering trade size and stop % when a BUY button is clicked."""

    shares   = discord.ui.TextInput(
        label="Number of Shares",
        placeholder="e.g. 10",
        default="10",
        required=True,
        max_length=10,
    )
    stop_pct = discord.ui.TextInput(
        label="Stop % below entry (e.g. 10 for 10%)",
        placeholder="e.g. 10",
        default="10",
        required=True,
        max_length=6,
    )

    def __init__(self, ticker: str):
        super().__init__(title=f"🛒 Log Trade: {ticker}")
        self.ticker = ticker

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            shares   = int(self.shares.value.strip())
            stop_pct = float(self.stop_pct.value.strip().replace("%", "")) / 100
            if shares <= 0 or stop_pct <= 0 or stop_pct >= 1:
                raise ValueError("out of range")
        except (ValueError, ZeroDivisionError):
            await interaction.followup.send(
                "Invalid input — shares must be a positive integer and stop % between 1–99.",
                ephemeral=True,
            )
            return

        raw = await asyncio.to_thread(
            yf.download, self.ticker, period="1d", auto_adjust=True, progress=False
        )
        if raw.empty:
            await interaction.followup.send("Could not fetch live price. Please try again.", ephemeral=True)
            return

        if isinstance(raw.columns, pd.MultiIndex):
            raw = raw.xs(self.ticker, level=1, axis=1)

        try:
            entry = float(raw["Close"].iloc[-1])
        except Exception:
            await interaction.followup.send("Price data unavailable. Please try again.", ephemeral=True)
            return

        stop         = entry * (1 - stop_pct)
        risk_per_sh  = entry - stop
        target       = entry + 3 * risk_per_sh
        risk_dollars = shares * risk_per_sh

        with _db() as conn:
            cur = conn.execute(
                """INSERT INTO trades
                   (user_id, ticker, shares, entry, stop, target, risk_dollars, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    interaction.user.id, self.ticker, shares,
                    round(entry, 4), round(stop, 4), round(target, 4),
                    round(risk_dollars, 2), "ACTIVE", datetime.utcnow().isoformat(),
                ),
            )
            trade_id = cur.lastrowid
            conn.commit()

        embed = discord.Embed(
            title=f"✅ {self.ticker} Trade Logged",
            description=(
                f"Your trade is now **ACTIVE** — the bot will DM you if price hits your target or stop."
            ),
            color=0x00C853,
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="💰 Entry",      value=f"${entry:.2f}",                inline=True)
        embed.add_field(name="🛑 Stop",       value=f"${stop:.2f} (-{stop_pct*100:.0f}%)", inline=True)
        embed.add_field(name="🎯 Target 3R",  value=f"${target:.2f}",               inline=True)
        embed.add_field(name="📉 Risk $",     value=f"${risk_dollars:.2f}",         inline=True)
        embed.add_field(name="📦 Shares",     value=str(shares),                    inline=True)
        embed.set_footer(text=f"Trade ID #{trade_id} • Use buttons below when trade closes")

        await interaction.followup.send(embed=embed, view=TradeView(trade_id, interaction.user.id), ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await interaction.followup.send("An error occurred processing your trade. Please try again.", ephemeral=True)


class StockBuyButton(discord.ui.Button):
    """A single green BUY button for one ticker in the /recommend view."""

    def __init__(self, ticker: str, row: int):
        super().__init__(
            label=f"🛒 BUY {ticker}",
            style=discord.ButtonStyle.success,
            row=row,
        )
        self.ticker = ticker

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BuyModal(self.ticker))


class RecommendView(discord.ui.View):
    """Dynamic view with one BUY button per recommended ticker (up to 10)."""

    def __init__(self, tickers: list[str]):
        super().__init__(timeout=600)
        for i, ticker in enumerate(tickers[:10]):
            self.add_item(StockBuyButton(ticker, row=i // 5))


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _apply_recommend_filter(
    df: pd.DataFrame,
    spy_perf1d: float,
    top_sectors: list[str],
) -> pd.DataFrame:
    """Apply Martin Luk buy-setup criteria and return filtered DataFrame sorted by Perf1D.

    Tier 1 is defined as the explicit EMA stack: Close > EMA9 > EMA21 > EMA50.
    This is stricter than Watchlist == 'Leading' which only requires price above all three
    but does not enforce that EMA9 > EMA21 > EMA50 themselves are stacked correctly.
    """
    mask = (
        (df["Close"] > df["EMA9"]) &
        (df["EMA9"]  > df["EMA21"]) &
        (df["EMA21"] > df["EMA50"]) &
        (df["RelVol"] >= 1.5) &
        (df["Close"] >= 10) &
        (df["Perf1D"] >= spy_perf1d) &
        (df["Sector"].isin(top_sectors))
    )
    return df[mask].sort_values("Perf1D", ascending=False).reset_index(drop=True)

def build_pages(title: str, color: int, rows: list[str], per_page: int = 20) -> list[discord.Embed]:
    pages = []
    for i in range(0, max(1, len(rows)), per_page):
        chunk = rows[i:i + per_page]
        embed = discord.Embed(title=title, color=color, timestamp=datetime.utcnow())
        embed.description = "\n".join(chunk) if chunk else "_No results found._"
        embed.set_footer(text=f"Data via yfinance • {datetime.utcnow().strftime('%Y-%m-%d')}")
        pages.append(embed)
    return pages

# ─── Alert Helper ─────────────────────────────────────────────────────────────

_ET = ZoneInfo("America/New_York")

def _et_now() -> datetime:
    """Return current time in US/Eastern (DST-aware via zoneinfo)."""
    return datetime.now(_ET)

def _is_trading_window() -> bool:
    """Return True during weekdays 4 AM – 6 PM ET (covers pre/market/AH)."""
    now = _et_now()
    if now.weekday() >= 5:
        return False
    return 4 <= now.hour < 18

async def _send_dm(user_id: int, embed: discord.Embed) -> bool:
    try:
        user = await bot.fetch_user(user_id)
        await user.send(embed=embed)
        return True
    except Exception:
        return False

_alert_checker_started = False

async def _check_alerts():
    """Background loop: check all active alerts every 10 minutes. Single-instance guard prevents duplicates on reconnect."""
    global _alert_checker_started
    if _alert_checker_started:
        return
    _alert_checker_started = True
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(600)
        if not _is_trading_window():
            continue
        try:
            with _db() as conn:
                rows = list(conn.execute("SELECT * FROM alerts").fetchall())
            if not rows:
                continue

            triggered_ids: list[int] = []

            tier_rows     = [r for r in rows if r["alert_type"] == "tier"]
            pre_rows      = [r for r in rows if r["alert_type"] == "premarket"]
            sector_rows   = [r for r in rows if r["alert_type"] == "hotsector"]
            target_rows   = [r for r in rows if r["alert_type"] == "price_target"]

            # ── Tier alerts ──────────────────────────────────────────────────
            if tier_rows:
                tickers = list({json.loads(r["params"])["ticker"] for r in tier_rows})
                df = await asyncio.to_thread(fetch_data, tickers)
                if not df.empty:
                    tier_map = df.set_index("Ticker")["Watchlist"].to_dict()
                    for row in tier_rows:
                        p = json.loads(row["params"])
                        current = tier_map.get(p["ticker"])
                        if current and current.lower() == p["tier"].lower():
                            embed = discord.Embed(
                                title=f"🔔 Tier Alert: {p['ticker']}",
                                description=(
                                    f"**{p['ticker']}** is now **{current}** — "
                                    f"matches your alert!"
                                ),
                                color={"Leading": 0x00C853, "Mediocre": 0xFFD600,
                                       "Lagging": 0xFF1744}.get(current, 0x7289DA),
                                timestamp=datetime.utcnow(),
                            )
                            if await _send_dm(row["user_id"], embed):
                                triggered_ids.append(row["id"])

            # ── Premarket gap alerts ─────────────────────────────────────────
            if pre_rows:
                df_pre = await asyncio.to_thread(fetch_data, ALL_TICKERS)
                if not df_pre.empty:
                    for row in pre_rows:
                        pct = json.loads(row["params"])["pct"]
                        hits = df_pre[df_pre["Gap"] >= pct][["Ticker", "Gap", "Watchlist"]]
                        if not hits.empty:
                            lines = "\n".join(
                                f"**{r['Ticker']}** +{r['Gap']:.1f}% ({r['Watchlist']})"
                                for _, r in hits.iterrows()
                            )
                            embed = discord.Embed(
                                title=f"🔔 Premarket Alert: Gap >{pct}%",
                                description=f"{len(hits)} stock(s) gapping:\n{lines}",
                                color=0x00B0F4,
                                timestamp=datetime.utcnow(),
                            )
                            if await _send_dm(row["user_id"], embed):
                                triggered_ids.append(row["id"])

            # ── Hot-sector alerts ────────────────────────────────────────────
            if sector_rows:
                df_sec = await asyncio.to_thread(fetch_data, ALL_TICKERS)
                if not df_sec.empty:
                    top_sectors = [
                        s.lower() for s in
                        df_sec[df_sec["Watchlist"] == "Leading"]["Sector"]
                        .value_counts()
                        .head(5)
                        .index.tolist()
                    ]
                    for row in sector_rows:
                        target = json.loads(row["params"])["sector"]
                        if target.lower() in top_sectors:
                            embed = discord.Embed(
                                title=f"🔔 Hot Sector Alert: {target}",
                                description=(
                                    f"**{target}** is now in the top hot sectors "
                                    f"by Leading stock count!"
                                ),
                                color=0xFF6B00,
                                timestamp=datetime.utcnow(),
                            )
                            if await _send_dm(row["user_id"], embed):
                                triggered_ids.append(row["id"])

            # ── Price-target alerts ──────────────────────────────────────────
            if target_rows:
                pt_tickers = list({json.loads(r["params"])["ticker"] for r in target_rows})
                pt_arg = pt_tickers[0] if len(pt_tickers) == 1 else pt_tickers
                try:
                    pt_raw = await asyncio.to_thread(
                        yf.download, pt_arg, period="1d", auto_adjust=True, progress=False
                    )
                    pt_price_map: dict[str, float] = {}
                    for t in pt_tickers:
                        try:
                            if isinstance(pt_raw.columns, pd.MultiIndex):
                                col = pt_raw.xs(t, level=1, axis=1)
                            else:
                                col = pt_raw
                            pt_price_map[t] = float(col["Close"].iloc[-1])
                        except Exception:
                            pass
                    for row in target_rows:
                        p = json.loads(row["params"])
                        current = pt_price_map.get(p["ticker"])
                        if current is None:
                            continue
                        direction = p.get("direction", "above")
                        hit = (direction == "above" and current >= p["target"]) or \
                              (direction == "below" and current <= p["target"])
                        if hit:
                            arrow = "📈" if direction == "above" else "📉"
                            embed = discord.Embed(
                                title=f"{arrow} Price Target Hit: {p['ticker']}",
                                description=(
                                    f"**{p['ticker']}** is at `${current:.2f}` — "
                                    f"your target of `${p['target']:.2f}` has been reached!"
                                ),
                                color=0x00C853 if direction == "above" else 0xFF1744,
                                timestamp=datetime.utcnow(),
                            )
                            if await _send_dm(row["user_id"], embed):
                                triggered_ids.append(row["id"])
                except Exception as e:
                    print(f"[Alerts] Price-target check error: {e}")

            # ── Remove triggered ─────────────────────────────────────────────
            if triggered_ids:
                with _db() as conn:
                    conn.executemany(
                        "DELETE FROM alerts WHERE id = ?",
                        [(i,) for i in triggered_ids],
                    )
                    conn.commit()
                print(f"[Alerts] Triggered and removed: {triggered_ids}")

        except Exception as e:
            print(f"[Alerts] Checker error: {e}")

# ─── Trade Monitor ────────────────────────────────────────────────────────────

_monitor_started = False

async def _monitor_trades():
    """Background loop: check ACTIVE trades every 5 minutes during market hours.
    DMs user and updates status when price hits target (3R) or stop."""
    global _monitor_started
    if _monitor_started:
        return
    _monitor_started = True
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(120)
        if not _is_trading_window():
            continue
        try:
            with _db() as conn:
                rows = list(conn.execute("SELECT * FROM trades WHERE status = 'ACTIVE'").fetchall())
            if not rows:
                continue

            tickers = list({r["ticker"] for r in rows})
            download_arg = tickers[0] if len(tickers) == 1 else tickers
            raw = await asyncio.to_thread(
                yf.download, download_arg,
                period="1d", auto_adjust=True, progress=False,
            )

            price_map: dict[str, float] = {}
            for ticker in tickers:
                try:
                    if isinstance(raw.columns, pd.MultiIndex):
                        col = raw.xs(ticker, level=1, axis=1)
                    else:
                        col = raw
                    price_map[ticker] = float(col["Close"].iloc[-1])
                except Exception:
                    pass

            updates: list[tuple[int, str]] = []
            for row in rows:
                price = price_map.get(row["ticker"])
                if price is None:
                    continue

                if price >= row["target"]:
                    profit = (price - row["entry"]) * row["shares"]
                    embed = discord.Embed(
                        title=f"🎉 {row['ticker']} Hit 3R Target!",
                        description=(
                            f"**{row['ticker']}** is trading at `${price:.2f}` — "
                            f"your 3R target was `${row['target']:.2f}`\n"
                            f"Estimated P&L: **+${profit:,.0f}** 🚀 Consider taking profit!"
                        ),
                        color=0x00C853,
                        timestamp=datetime.utcnow(),
                    )
                    dm_ok = await _send_dm(row["user_id"], embed)
                    if not dm_ok:
                        print(f"[Monitor] DM failed for user {row['user_id']} (3R hit on {row['ticker']})")
                    updates.append((row["id"], "3R_HIT", price))

                elif price <= row["stop"]:
                    loss = (row["entry"] - price) * row["shares"]
                    embed = discord.Embed(
                        title=f"💥 {row['ticker']} Hit Stop",
                        description=(
                            f"**{row['ticker']}** is trading at `${price:.2f}` — "
                            f"your stop was `${row['stop']:.2f}`\n"
                            f"Risk managed: -${loss:,.0f} · Good discipline sticking to the plan 💪"
                        ),
                        color=0xFF1744,
                        timestamp=datetime.utcnow(),
                    )
                    dm_ok = await _send_dm(row["user_id"], embed)
                    if not dm_ok:
                        print(f"[Monitor] DM failed for user {row['user_id']} (stop hit on {row['ticker']})")
                    updates.append((row["id"], "STOP_HIT", price))

            if updates:
                with _db() as conn:
                    for trade_id, status, exit_px in updates:
                        conn.execute(
                            "UPDATE trades SET status = ?, exit_price = ?, closed_at = ? WHERE id = ?",
                            (status, round(exit_px, 4), datetime.utcnow().isoformat(), trade_id),
                        )
                    conn.commit()
                print(f"[Monitor] Updated trades: {[(u[0], u[1]) for u in updates]}")

        except Exception as e:
            print(f"[Monitor] Error: {e}")

# ─── /alert command group ─────────────────────────────────────────────────────

_ALL_TICKERS_SET = set(ALL_TICKERS)

alert_group = app_commands.Group(name="alert", description="Set alerts — bot DMs you when triggered")

@alert_group.command(name="ticker", description="DM when a stock enters a specific tier (Leading/Mediocre/Lagging)")
@app_commands.describe(
    ticker="Stock ticker symbol, e.g. NVDA",
    tier="Tier to alert on",
)
@app_commands.choices(tier=[
    app_commands.Choice(name="Leading",  value="Leading"),
    app_commands.Choice(name="Mediocre", value="Mediocre"),
    app_commands.Choice(name="Lagging",  value="Lagging"),
])
async def alert_ticker(interaction: discord.Interaction, ticker: str, tier: app_commands.Choice[str]):
    ticker = ticker.upper().strip()
    if ticker not in _ALL_TICKERS_SET:
        await interaction.response.send_message(
            f"**{ticker}** is not in the supported ticker universe. "
            f"Try a major stock like `NVDA`, `AAPL`, or `TSLA`.",
            ephemeral=True,
        )
        return
    params = json.dumps({"ticker": ticker, "tier": tier.value})
    with _db() as conn:
        conn.execute(
            "INSERT INTO alerts (user_id, alert_type, params, created_at) VALUES (?, ?, ?, ?)",
            (interaction.user.id, "tier", params, datetime.utcnow().isoformat()),
        )
        conn.commit()
    embed = discord.Embed(
        title="✅ Tier Alert Set",
        description=f"You'll be DM'd when **{ticker}** enters **{tier.value}** tier.",
        color=0x00C853,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@alert_group.command(name="premarket", description="DM when any watchlist stock gaps up above a % threshold")
@app_commands.describe(pct="Gap % threshold, e.g. 5.0 means gap > 5%")
async def alert_premarket(interaction: discord.Interaction, pct: float):
    if pct <= 0 or pct > 100:
        await interaction.response.send_message("Gap % must be between 0 and 100.", ephemeral=True)
        return
    params = json.dumps({"pct": pct})
    with _db() as conn:
        conn.execute(
            "INSERT INTO alerts (user_id, alert_type, params, created_at) VALUES (?, ?, ?, ?)",
            (interaction.user.id, "premarket", params, datetime.utcnow().isoformat()),
        )
        conn.commit()
    embed = discord.Embed(
        title="✅ Premarket Alert Set",
        description=f"You'll be DM'd when any stock gaps up **>{pct}%** in premarket.",
        color=0x00B0F4,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

_KNOWN_SECTORS = [
    "Technology", "Financials", "Healthcare", "Consumer Disc", "Industrials",
    "Energy", "Materials", "Communication", "Consumer Staples", "Utilities",
    "Real Estate", "ETF", "Other",
]

async def _sector_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    return [
        app_commands.Choice(name=s, value=s)
        for s in _KNOWN_SECTORS
        if current.lower() in s.lower()
    ][:25]

@alert_group.command(name="hotsector", description="DM when a sector becomes a top leader")
@app_commands.describe(sector="Sector name, e.g. Technology, Financials, Energy")
@app_commands.autocomplete(sector=_sector_autocomplete)
async def alert_hotsector(interaction: discord.Interaction, sector: str):
    sector_normalized = next(
        (s for s in _KNOWN_SECTORS if s.lower() == sector.strip().lower()),
        None,
    )
    if sector_normalized is None:
        known = ", ".join(f"`{s}`" for s in _KNOWN_SECTORS)
        await interaction.response.send_message(
            f"**{sector.strip()}** is not a recognized sector.\nKnown sectors: {known}",
            ephemeral=True,
        )
        return
    params = json.dumps({"sector": sector_normalized})
    with _db() as conn:
        conn.execute(
            "INSERT INTO alerts (user_id, alert_type, params, created_at) VALUES (?, ?, ?, ?)",
            (interaction.user.id, "hotsector", params, datetime.utcnow().isoformat()),
        )
        conn.commit()
    embed = discord.Embed(
        title="✅ Hot Sector Alert Set",
        description=f"You'll be DM'd when **{sector.strip()}** is in the top hot sectors.",
        color=0xFF6B00,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@alert_group.command(name="target", description="DM when a stock hits a specific price")
@app_commands.describe(
    ticker="Stock ticker symbol, e.g. NVDA",
    price="Price to alert at, e.g. 150.00",
)
async def alert_target(interaction: discord.Interaction, ticker: str, price: float):
    ticker = ticker.upper().strip()
    if price <= 0:
        await interaction.response.send_message("Price must be greater than 0.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    raw = await asyncio.to_thread(yf.download, ticker, period="1d", auto_adjust=True, progress=False)
    if raw.empty:
        await interaction.followup.send(
            f"Could not fetch price for **{ticker}**. Check the symbol and try again.", ephemeral=True
        )
        return
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            raw = raw.xs(ticker, level=1, axis=1)
        current = float(raw["Close"].iloc[-1])
    except Exception:
        await interaction.followup.send("Price data unavailable. Please try again.", ephemeral=True)
        return

    direction = "above" if price > current else "below"
    params = json.dumps({"ticker": ticker, "target": price, "direction": direction})
    with _db() as conn:
        conn.execute(
            "INSERT INTO alerts (user_id, alert_type, params, created_at) VALUES (?, ?, ?, ?)",
            (interaction.user.id, "price_target", params, datetime.utcnow().isoformat()),
        )
        conn.commit()

    arrow = "📈" if direction == "above" else "📉"
    embed = discord.Embed(
        title="✅ Price Target Alert Set",
        description=(
            f"{arrow} You'll be DM'd when **{ticker}** "
            f"{'reaches' if direction == 'above' else 'falls to'} **${price:.2f}**.\n"
            f"Current price: `${current:.2f}`"
        ),
        color=0x00C853,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

bot.tree.add_command(alert_group)

# ─── /alerts ──────────────────────────────────────────────────────────────────

@bot.tree.command(name="alerts", description="Show all your active alerts")
async def slash_alerts(interaction: discord.Interaction):
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE user_id = ? ORDER BY id",
            (interaction.user.id,),
        ).fetchall()

    if not rows:
        await interaction.response.send_message(
            "You have no active alerts. Use `/alert ticker`, `/alert premarket`, or `/alert hotsector` to set one.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title="🔔 Your Active Alerts",
        color=0x7289DA,
        timestamp=datetime.utcnow(),
    )
    for row in rows:
        p = json.loads(row["params"])
        if row["alert_type"] == "tier":
            label = f"Tier — {p['ticker']} → {p['tier']}"
        elif row["alert_type"] == "premarket":
            label = f"Premarket — gap > {p['pct']}%"
        elif row["alert_type"] == "price_target":
            arrow = "📈" if p.get("direction") == "above" else "📉"
            label = f"Price Target — {arrow} {p['ticker']} @ ${p['target']:.2f}"
        else:
            label = f"Hot Sector — {p['sector']}"
        created = row["created_at"][:10]
        embed.add_field(name=f"ID #{row['id']}  •  {label}", value=f"Created {created}", inline=False)

    embed.set_footer(text="Use /removealert <id> to delete an alert")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ─── /removealert ─────────────────────────────────────────────────────────────

@bot.tree.command(name="removealert", description="Remove one of your active alerts by ID")
@app_commands.describe(id="Alert ID shown in /alerts")
async def slash_removealert(interaction: discord.Interaction, id: int):
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM alerts WHERE id = ? AND user_id = ?",
            (id, interaction.user.id),
        ).fetchone()
        if not row:
            await interaction.response.send_message(
                f"No alert with ID **#{id}** found for your account.", ephemeral=True
            )
            return
        conn.execute("DELETE FROM alerts WHERE id = ?", (id,))
        conn.commit()

    p = json.loads(row["params"])
    if row["alert_type"] == "tier":
        label = f"Tier alert for **{p['ticker']}** → {p['tier']}"
    elif row["alert_type"] == "premarket":
        label = f"Premarket gap alert > {p['pct']}%"
    elif row["alert_type"] == "price_target":
        arrow = "📈" if p.get("direction") == "above" else "📉"
        label = f"Price target alert — {arrow} **{p['ticker']}** @ ${p['target']:.2f}"
    else:
        label = f"Hot sector alert for **{p['sector']}**"

    embed = discord.Embed(
        title="🗑️ Alert Removed",
        description=f"Removed: {label}",
        color=0xFF1744,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ─── on_ready ─────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online!")
    try:
        synced = await bot.tree.sync()
        print(f"   Synced {len(synced)} slash command(s) globally.")
    except Exception as e:
        print(f"   Sync error: {e}")
    bot.loop.create_task(_check_alerts())
    bot.loop.create_task(_monitor_trades())

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"[AppCmd Error] {error}")

def _extract_cmd_args(options: list) -> dict:
    """Recursively extract args from interaction options, including subcommand groups."""
    result = {}
    for opt in options or []:
        opt_type = opt.get("type", 0)
        if opt_type in (1, 2):
            result.update(_extract_cmd_args(opt.get("options", [])))
        else:
            result[opt["name"]] = opt.get("value")
    return result

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.application_command:
        try:
            data = interaction.data or {}
            cmd  = data.get("name", "unknown")
            opts = data.get("options", [])
            args = json.dumps(_extract_cmd_args(opts))
            with _db() as conn:
                conn.execute(
                    "INSERT INTO command_log (user_id, username, command, args_json, timestamp) VALUES (?,?,?,?,?)",
                    (
                        interaction.user.id,
                        str(interaction.user),
                        cmd,
                        args,
                        datetime.utcnow().isoformat(),
                    ),
                )
                conn.commit()
        except Exception as e:
            print(f"[CmdLog] Error: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

# ─── /scan ────────────────────────────────────────────────────────────────────

@bot.tree.command(name="scan", description="Full 3-tier EMA scan with tier buttons + CSV download")
async def slash_scan(interaction: discord.Interaction):
    if not _check_rate_limit(interaction.user.id):
        await interaction.response.send_message(
            "⏳ You're running scans too fast! You can run up to 10 scan commands per minute. Please wait a moment.",
            ephemeral=True,
        )
        return
    await interaction.response.defer()
    df = fetch_data()
    if df.empty:
        await interaction.followup.send(
            "⚠️ No data returned. Markets may be closed or data is temporarily unavailable. "
            "Try `/stock NVDA` for a single ticker lookup."
        )
        return

    counts    = df["Watchlist"].value_counts()
    date_str  = datetime.utcnow().strftime("%m/%d/%y")
    hot       = df[df["Watchlist"] == "Leading"]["Sector"].value_counts().head(3)
    hot_str   = " | ".join(f"{s}({c})" for s, c in hot.items()) if not hot.empty else "N/A"

    embed = discord.Embed(
        title=f"📊 Watchlist Scan — {date_str}",
        color=0x00FF00,
        timestamp=datetime.utcnow(),
    )
    embed.add_field(
        name="Tiers",
        value=(
            f"🟢 Leading: **{counts.get('Leading', 0)}**\n"
            f"🟡 Mediocre: **{counts.get('Mediocre', 0)}**\n"
            f"🔴 Lagging: **{counts.get('Lagging', 0)}**"
        ),
        inline=True,
    )
    embed.add_field(name="🔥 Hot Sectors", value=hot_str, inline=True)
    embed.set_footer(text="Click a tier button → stock list + CSV posted in channel")

    full_file = discord.File(
        io.BytesIO(df.to_csv(index=False).encode()),
        f"watchlist_scan-{datetime.utcnow().strftime('%m-%d-%y')}-Full.csv",
    )
    await interaction.followup.send(embed=embed, view=ScanView(df), file=full_file)

# ─── /premarket ───────────────────────────────────────────────────────────────

@bot.tree.command(name="premarket", description="Pre-market gap scanner")
@app_commands.describe(
    min_gap="Minimum gap % (default 2.0)",
    watchlist="All / Leading / Mediocre / Lagging (default All)",
)
async def slash_premarket(
    interaction: discord.Interaction,
    min_gap: float = 2.0,
    watchlist: str = "All",
):
    if not _check_rate_limit(interaction.user.id):
        await interaction.response.send_message(
            "⏳ You're running scans too fast! You can run up to 10 scan commands per minute. Please wait a moment.",
            ephemeral=True,
        )
        return
    await interaction.response.defer()
    df = fetch_data()
    if df.empty:
        await interaction.followup.send(
            "⚠️ No data returned. Markets may be closed or data is temporarily unavailable. "
            "Try `/leaders` to see recent active movers."
        )
        return

    filtered = df.copy()
    if watchlist not in ("All", "all"):
        filtered = filtered[filtered["Watchlist"] == watchlist]
    gaps = filtered[filtered["Gap"].abs() >= min_gap].sort_values("Gap", ascending=False)

    embed = discord.Embed(
        title=f"🚀 Premarket Gaps (≥{min_gap}% | {watchlist})",
        color=0x00B4D8,
        timestamp=datetime.utcnow(),
    )
    if gaps.empty:
        embed.add_field(
            name="Top Gaps",
            value=f"_No stocks found gapping ≥{min_gap}%. Try lowering the threshold or use `/leaders` to see active movers._",
            inline=False,
        )
    else:
        lines = []
        for _, row in gaps.head(5).iterrows():
            arrow = "🟢" if row["Gap"] >= 0 else "🔴"
            lines.append(f"{arrow} **{row['Ticker']}** `{row['Gap']:+.2f}%` | RelVol `{row['RelVol']:.1f}x` | {row['Sector']}")
        embed.add_field(name=f"Top Gaps (showing {min(5, len(gaps))}/{len(gaps)})", value="\n".join(lines), inline=False)
    embed.add_field(name="Total",   value=str(len(gaps)), inline=True)
    embed.add_field(name="Leading", value=str(len(gaps[gaps["Watchlist"] == "Leading"])), inline=True)
    embed.set_footer(text="Full CSV attached • Tier CSVs via buttons")

    date_str  = datetime.utcnow().strftime("%m-%d-%y")
    full_file = discord.File(io.BytesIO(gaps.to_csv(index=False).encode()), f"premarket-{date_str}.csv")
    await interaction.followup.send(embed=embed, file=full_file, view=TierDownloadView(gaps, "premarket"))

# ─── /potent ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="potent", description="Top 1-day movers by % and dollar volume")
@app_commands.describe(
    perf="Min 1D gain % (default 5.0)",
    vol="Min dollar volume $M (default 50)",
    direction="up / down / both (default both)",
)
async def slash_potent(
    interaction: discord.Interaction,
    perf: float = 5.0,
    vol: float = 50.0,
    direction: str = "both",
):
    if not _check_rate_limit(interaction.user.id):
        await interaction.response.send_message(
            "⏳ You're running scans too fast! You can run up to 10 scan commands per minute. Please wait a moment.",
            ephemeral=True,
        )
        return
    await interaction.response.defer()
    df = fetch_data()
    if df.empty:
        await interaction.followup.send(
            "⚠️ No data returned. Markets may be closed or data is temporarily unavailable. "
            "Try `/leaders` to see recent active movers."
        )
        return

    mask = df["DollarVol_M"] >= vol
    if direction.lower() == "up":
        mask &= df["Perf1D"] >= perf
    elif direction.lower() == "down":
        mask &= df["Perf1D"] <= -perf
    else:
        mask &= df["Perf1D"].abs() >= perf

    movers = df[mask].sort_values("Perf1D", key=abs, ascending=False)

    embed = discord.Embed(
        title=f"🔥 Potent Movers (>{perf}% | >${vol:.0f}M vol)",
        color=0xF77F00,
        timestamp=datetime.utcnow(),
    )
    if movers.empty:
        embed.add_field(
            name="Top Movers",
            value=f"_No movers found matching your filters. Try lowering the gain% or volume threshold, or use `/leaders` to see active movers._",
            inline=False,
        )
    else:
        lines = []
        for _, row in movers.head(5).iterrows():
            arrow = "🟢" if row["Perf1D"] >= 0 else "🔴"
            lines.append(f"{arrow} **{row['Ticker']}** `{row['Perf1D']:+.1f}%` | Vol `${row['DollarVol_M']:.0f}M` | {row['Sector']}")
        embed.add_field(name=f"Top Movers (showing {min(5, len(movers))}/{len(movers)})", value="\n".join(lines), inline=False)
    embed.add_field(name="Total",   value=str(len(movers)), inline=True)
    embed.add_field(name="Leading", value=str(len(movers[movers["Watchlist"] == "Leading"])), inline=True)
    embed.set_footer(text="Full CSV attached • Tier CSVs via buttons")

    date_str  = datetime.utcnow().strftime("%m-%d-%y")
    full_file = discord.File(io.BytesIO(movers.to_csv(index=False).encode()), f"potent-{date_str}.csv")
    await interaction.followup.send(embed=embed, file=full_file, view=TierDownloadView(movers, "potent"))

# ─── /leaders ────────────────────────────────────────────────────────────────

@bot.tree.command(name="leaders", description="Top 1-month performance leaders")
@app_commands.describe(
    top="How many to show (default 30)",
    perf="Min 1M gain % (default 10)",
)
async def slash_leaders(
    interaction: discord.Interaction,
    top: int = 30,
    perf: float = 10.0,
):
    if not _check_rate_limit(interaction.user.id):
        await interaction.response.send_message(
            "⏳ You're running scans too fast! You can run up to 10 scan commands per minute. Please wait a moment.",
            ephemeral=True,
        )
        return
    await interaction.response.defer()
    df = fetch_data()
    if df.empty:
        await interaction.followup.send(
            "⚠️ No data returned. Markets may be closed or data is temporarily unavailable. "
            "Try `/stock NVDA` for a single ticker lookup."
        )
        return

    leaders = df[df["Perf1M"] >= perf].nlargest(top, "Perf1M")

    embed = discord.Embed(
        title=f"👑 Top Leaders (>{perf}% 1M | Top {top})",
        color=0x2DC653,
        timestamp=datetime.utcnow(),
    )
    if leaders.empty:
        embed.add_field(
            name="Ranked",
            value=f"_No leaders found above {perf}% 1M. Try lowering the `perf` threshold._",
            inline=False,
        )
    else:
        lines = []
        for idx, (_, row) in enumerate(leaders.head(5).iterrows(), 1):
            lines.append(f"**#{idx} {row['Ticker']}** `{row['Perf1M']:+.1f}%` 1M | `{row['Perf1D']:+.1f}%` 1D | {row['Sector']}")
        embed.add_field(name=f"Ranked (showing {min(5, len(leaders))}/{len(leaders)})", value="\n".join(lines), inline=False)
    embed.add_field(name="Total",   value=str(len(leaders)), inline=True)
    embed.add_field(name="Leading", value=str(len(leaders[leaders["Watchlist"] == "Leading"])), inline=True)
    embed.set_footer(text="Full CSV attached • Tier CSVs via buttons")

    date_str  = datetime.utcnow().strftime("%m-%d-%y")
    full_file = discord.File(io.BytesIO(leaders.to_csv(index=False).encode()), f"leaders-{date_str}.csv")
    await interaction.followup.send(embed=embed, file=full_file, view=TierDownloadView(leaders, "leaders"))

# ─── /tiers ──────────────────────────────────────────────────────────────────

@bot.tree.command(name="tiers", description="Show Leading / Mediocre / Lagging stocks by EMA tier")
@app_commands.describe(tier="Leading / Mediocre / Lagging / All (default All)")
async def slash_tiers(
    interaction: discord.Interaction,
    tier: str = "All",
):
    await interaction.response.defer()
    df = fetch_data()
    if df.empty:
        await interaction.followup.send("⚠️ Could not fetch data."); return

    tier_colors = {"Leading": 0x2DC653, "Mediocre": 0xF77F00, "Lagging": 0xE63946}

    def send_tier(name: str) -> discord.Embed:
        subset = df[df["Watchlist"] == name]
        embed = discord.Embed(
            title=f"{'🟢' if name=='Leading' else '🟡' if name=='Mediocre' else '🔴'} {name} ({len(subset)})",
            description=" ".join(f"`{t}`" for t in subset["Ticker"].tolist()) or "_None_",
            color=tier_colors[name],
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text=f"EMA9/21/50 positioning • Data via yfinance")
        return embed

    if tier in ("Leading", "Mediocre", "Lagging"):
        await interaction.followup.send(embed=send_tier(tier))
    else:
        for name in ("Leading", "Mediocre", "Lagging"):
            await interaction.followup.send(embed=send_tier(name))

# ─── /sectors ────────────────────────────────────────────────────────────────

@bot.tree.command(name="sectors", description="Hot sectors by average 1-month performance")
async def slash_sectors(interaction: discord.Interaction):
    await interaction.response.defer()
    df = fetch_data()
    if df.empty:
        await interaction.followup.send("⚠️ Could not fetch data."); return

    sector_stats = (
        df.groupby("Sector")
        .agg(AvgPerf1M=("Perf1M", "mean"), Count=("Ticker", "count"))
        .round(2)
        .reset_index()
    )
    sector_stats = sector_stats[sector_stats["Count"] >= 2].sort_values("AvgPerf1M", ascending=False)

    embed = discord.Embed(title="🔥 Hot Sectors", color=0xF77F00, timestamp=datetime.utcnow())
    for _, row in sector_stats.iterrows():
        perf = row["AvgPerf1M"]
        arrow = "📈" if perf > 0 else "📉"
        embed.add_field(
            name=f"{arrow} {row['Sector']}",
            value=f"`{perf:+.1f}%` avg 1M  ({int(row['Count'])} stocks)",
            inline=False,
        )
    embed.set_footer(text="Average 1-month performance by sector")

    top_tickers = df[df["Watchlist"] == "Leading"]["Ticker"].tolist()[:5]
    view = DownloadCSV(sector_stats.to_csv(index=False).encode(), "sectors.csv", tickers=top_tickers)
    await interaction.followup.send(embed=embed, view=view)

# ─── /after ──────────────────────────────────────────────────────────────────

@bot.tree.command(name="after", description="After-hours scan: ADR>5%, $100M+ vol, Leading only")
async def slash_after(interaction: discord.Interaction):
    if not _check_rate_limit(interaction.user.id):
        await interaction.response.send_message(
            "⏳ You're running scans too fast! You can run up to 10 scan commands per minute. Please wait a moment.",
            ephemeral=True,
        )
        return
    await interaction.response.defer()
    df = fetch_data()
    if df.empty:
        await interaction.followup.send(
            "⚠️ No data returned. Markets may be closed or data is temporarily unavailable. "
            "Try `/leaders` to see recent active movers."
        )
        return

    after = df[
        (df["ADR"] > 5) &
        (df["DollarVol_M"] > 100) &
        (df["Watchlist"] == "Leading")
    ].sort_values("ADR", ascending=False)

    if after.empty:
        await interaction.followup.send(
            "⚠️ No after-hours movers found (ADR>5%, $100M+ vol, Leading). "
            "Try `/potent` for broader mover scans or `/leaders` to see active movers."
        )
        return

    rows = []
    for _, row in after.iterrows():
        rows.append(
            f"⚡ **{row['Ticker']}** | ADR: `{row['ADR']:.1f}%` "
            f"| Vol: `${row['DollarVol_M']:.0f}M` | `{row['Sector']}`"
        )

    csv_bytes = after.to_csv(index=False).encode()
    date_fn   = datetime.utcnow().strftime("%m-%d-%y")
    view      = ScanTierView(csv_bytes, f"after-hours-{date_fn}.csv", after)
    rows_preview = rows[:5]
    if len(rows) > 5:
        rows_preview.append(f"_…and {len(rows) - 5} more — click Full CSV ↓_")
    embed = discord.Embed(
        title=f"🕒 After-Hours (ADR>5% | $100M+ | Leading) — {len(after)} stocks",
        description="\n".join(rows_preview),
        color=0x9B59B6,
        timestamp=datetime.utcnow(),
    )
    embed.set_footer(text=f"Showing 5/{len(after)} • Full CSV ↓ button for complete list")
    await interaction.followup.send(embed=embed, view=view)

# ─── /premarketreport ────────────────────────────────────────────────────────

@bot.tree.command(name="premarketreport", description="6:30AM-style daily market summary")
async def slash_premarketreport(interaction: discord.Interaction):
    await interaction.response.defer()
    df = fetch_data()
    if df.empty:
        await interaction.followup.send("⚠️ Could not fetch data."); return

    leaders_count  = len(df[df["Watchlist"] == "Leading"])
    gaps_count     = len(df[df["Gap"].abs() > 3])
    hot_sectors    = df[df["Watchlist"] == "Leading"]["Sector"].value_counts().head(3)

    try:
        spy_hist  = yf.Ticker("SPY").history(period="10d")
        spy_close = spy_hist["Close"]
        spy_ema9  = spy_close.ewm(span=9,  adjust=False).mean().iloc[-1]
        spy_ema21 = spy_close.ewm(span=21, adjust=False).mean().iloc[-1]
        spy_price = spy_close.iloc[-1]
        spy_status = "✅ Above 9 & 21 EMA" if spy_price > spy_ema9 > spy_ema21 else "⚠️ Mixed / Below EMAs"
        spy_1d = (spy_price - spy_close.iloc[-2]) / spy_close.iloc[-2] * 100
    except Exception:
        spy_status = "N/A"
        spy_1d = 0.0

    hot_str = "  ".join(f"{s}({c})" for s, c in hot_sectors.items()) or "N/A"

    embed = discord.Embed(
        title=f"📋 Premarket Report — {datetime.utcnow().strftime('%b %d, %Y')}",
        color=0x00B4D8,
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="🗂️ Leaders",     value=f"{leaders_count} stocks above EMA9/21/50", inline=True)
    embed.add_field(name="🚀 Gaps >3%",    value=f"{gaps_count} stocks",                      inline=True)
    embed.add_field(name="🔥 Hot Sectors", value=hot_str,                                      inline=False)
    embed.add_field(name="📊 SPY",         value=f"{spy_status}  (`{spy_1d:+.2f}%` 1D)",      inline=False)
    embed.set_footer(text="Data via yfinance")

    top_tickers = df[df["Watchlist"] == "Leading"]["Ticker"].tolist()[:5]
    view = DownloadCSV(df.head(20).to_csv(index=False).encode(), "report_sample.csv", tickers=top_tickers)
    await interaction.followup.send(embed=embed, view=view)

# ─── /portfolio ──────────────────────────────────────────────────────────────

portfolio_group = app_commands.Group(name="portfolio", description="Manage your personal stock portfolio")

@portfolio_group.command(name="add", description="Add a position to your portfolio")
@app_commands.describe(
    ticker="Stock ticker symbol (e.g. AAPL)",
    shares="Number of shares held",
    price="Your entry price per share",
)
async def portfolio_add(interaction: discord.Interaction, ticker: str, shares: float, price: float):
    ticker = ticker.upper().strip()
    if shares <= 0 or price <= 0:
        await interaction.response.send_message("❌ Shares and price must be positive.", ephemeral=True)
        return
    added_at = datetime.utcnow().isoformat()
    try:
        with _db() as conn:
            conn.execute(
                """
                INSERT INTO portfolio (user_id, ticker, shares, entry_price, added_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, ticker) DO UPDATE SET
                    shares      = excluded.shares,
                    entry_price = excluded.entry_price,
                    added_at    = excluded.added_at
                """,
                (interaction.user.id, ticker, shares, price, added_at),
            )
            conn.commit()
    except Exception as exc:
        await interaction.response.send_message(f"❌ DB error: `{exc}`", ephemeral=True)
        return

    embed = discord.Embed(
        title="✅ Position Added",
        description=(
            f"**{ticker}** — {shares:g} shares @ ${price:,.2f}\n"
            f"Cost basis: **${shares * price:,.2f}**"
        ),
        color=0x2DC653,
        timestamp=datetime.utcnow(),
    )
    embed.set_footer(text="Use /portfolio to view your full portfolio")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@portfolio_group.command(name="remove", description="Remove a position from your portfolio")
@app_commands.describe(ticker="Stock ticker to remove (e.g. AAPL)")
async def portfolio_remove(interaction: discord.Interaction, ticker: str):
    ticker = ticker.upper().strip()
    with _db() as conn:
        result = conn.execute(
            "DELETE FROM portfolio WHERE user_id = ? AND ticker = ?",
            (interaction.user.id, ticker),
        )
        conn.commit()
        deleted = result.rowcount
    if deleted:
        embed = discord.Embed(
            title="🗑️ Position Removed",
            description=f"**{ticker}** has been removed from your portfolio.",
            color=0xE63946,
            timestamp=datetime.utcnow(),
        )
    else:
        embed = discord.Embed(
            title="❌ Not Found",
            description=f"**{ticker}** was not in your portfolio.",
            color=0xF77F00,
            timestamp=datetime.utcnow(),
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@portfolio_group.command(name="view", description="View your portfolio with live P&L and EMA tier")
async def portfolio_view(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    with _db() as conn:
        rows = list(conn.execute(
            "SELECT ticker, shares, entry_price FROM portfolio WHERE user_id = ? ORDER BY ticker",
            (interaction.user.id,),
        ).fetchall())

    if not rows:
        await interaction.followup.send(
            "📭 Your portfolio is empty. Use `/portfolio add` to add positions.",
            ephemeral=True,
        )
        return

    tickers = [r["ticker"] for r in rows]

    prices: dict[str, float] = {}
    ema_tiers: dict[str, str] = {}
    try:
        download_arg = tickers[0] if len(tickers) == 1 else tickers
        raw = yf.download(download_arg, period="3mo", auto_adjust=True, progress=False, threads=True)
        for ticker in tickers:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    df_t = raw.xs(ticker, level=1, axis=1).dropna(how="all")
                else:
                    df_t = raw.dropna(how="all")
                closes = df_t["Close"].dropna()
                if len(closes) >= 50:
                    price_val = float(closes.iloc[-1])
                    emas = compute_emas(closes)
                    tier = assign_watchlist(price_val, emas)
                elif len(closes) > 0:
                    price_val = float(closes.iloc[-1])
                    tier = "N/A"
                else:
                    price_val = 0.0
                    tier = "N/A"
                prices[ticker] = price_val
                ema_tiers[ticker] = tier
            except Exception:
                prices[ticker] = 0.0
                ema_tiers[ticker] = "N/A"
    except Exception:
        for ticker in tickers:
            prices[ticker] = 0.0
            ema_tiers[ticker] = "N/A"

    total_cost   = 0.0
    total_value  = 0.0
    lines        = []

    tier_icons = {"Leading": "🟢", "Mediocre": "🟡", "Lagging": "🔴", "N/A": "⬜"}

    for r in rows:
        ticker      = r["ticker"]
        shares      = r["shares"]
        entry       = r["entry_price"]
        cur_price   = prices.get(ticker, 0.0)
        cost        = shares * entry
        value       = shares * cur_price
        pnl_amt     = value - cost
        pnl_pct     = (pnl_amt / cost * 100) if cost > 0 else 0.0
        tier        = ema_tiers.get(ticker, "N/A")
        tier_icon   = tier_icons.get(tier, "⬜")
        arrow       = "▲" if pnl_pct >= 0 else "▼"
        total_cost  += cost
        total_value += value
        lines.append(
            f"{tier_icon} **{ticker}** — {shares:g} sh @ ${entry:,.2f} → ${cur_price:,.2f}  "
            f"`{arrow}{abs(pnl_pct):.2f}%` (${pnl_amt:+,.2f})  _{tier}_"
        )

    total_pnl_amt = total_value - total_cost
    total_pnl_pct = (total_pnl_amt / total_cost * 100) if total_cost > 0 else 0.0

    embed_color = 0x2DC653 if total_pnl_pct >= 0 else 0xE63946
    embed = discord.Embed(
        title="📊 Your Portfolio",
        color=embed_color,
        timestamp=datetime.utcnow(),
    )
    embed.description = "\n".join(lines)
    embed.add_field(
        name="Portfolio Summary",
        value=(
            f"Cost basis: **${total_cost:,.2f}**  →  Current value: **${total_value:,.2f}**\n"
            f"Unrealized P&L: **${total_pnl_amt:+,.2f}  ({total_pnl_pct:+.2f}%)**"
        ),
        inline=False,
    )
    embed.set_footer(text="Tiers: 🟢 Leading · 🟡 Mediocre · 🔴 Lagging  |  Data via yfinance")
    await interaction.followup.send(embed=embed, ephemeral=True)


bot.tree.add_command(portfolio_group)

# ─── Trading Mode Helper ──────────────────────────────────────────────────────

def _derive_trading_mode(pnl: float) -> tuple[str, int, str]:
    """Return (mode_name, color, advice) based on P&L %."""
    if pnl >= 2.0:
        return "AGGRESSIVE 🚀", 0x2DC653, "Press winners. Add on breakouts. Run positions."
    elif pnl <= -1.5:
        return "DEFENSIVE 🛡️", 0xE63946, "Reduce size. Take profits quickly. Preserve capital."
    else:
        return "NEUTRAL ⚖️", 0xF77F00, "Standard sizing. Follow setups. No FOMO."

# ─── /mode ───────────────────────────────────────────────────────────────────

@bot.tree.command(name="mode", description="Set trading mode based on your P&L")
@app_commands.describe(pnl="P&L % e.g. +2.3 or -1.5")
async def slash_mode(interaction: discord.Interaction, pnl: float):
    mode_name, color, advice = _derive_trading_mode(pnl)
    embed = discord.Embed(
        title=f"⚙️ Trading Mode: {mode_name}",
        description=f"P&L: `{pnl:+.1f}%`\n\n{advice}",
        color=color,
        timestamp=datetime.utcnow(),
    )
    await interaction.response.send_message(embed=embed)

# ─── /equity ─────────────────────────────────────────────────────────────────


@bot.tree.command(name="equity", description="Log equity curve update or auto-sync from portfolio")
@app_commands.describe(pnl="P&L % e.g. +2.3 or -1.5 — omit to auto-calculate from your portfolio")
async def slash_equity(interaction: discord.Interaction, pnl: float | None = None):
    if pnl is None:
        await interaction.response.defer(ephemeral=True)
        with _db() as conn:
            rows = list(conn.execute(
                "SELECT ticker, shares, entry_price FROM portfolio WHERE user_id = ?",
                (interaction.user.id,),
            ).fetchall())

        if not rows:
            await interaction.followup.send(
                "📭 Your portfolio is empty. Add positions with `/portfolio add` first, "
                "or supply a manual P&L with `/equity [pnl]`.",
                ephemeral=True,
            )
            return

        tickers = [r["ticker"] for r in rows]
        prices: dict[str, float] = {}
        try:
            download_arg = tickers[0] if len(tickers) == 1 else tickers
            raw = yf.download(download_arg, period="3mo", auto_adjust=True, progress=False, threads=True)
            for ticker in tickers:
                try:
                    if isinstance(raw.columns, pd.MultiIndex):
                        df_t = raw.xs(ticker, level=1, axis=1).dropna(how="all")
                    else:
                        df_t = raw.dropna(how="all")
                    closes = df_t["Close"].dropna()
                    prices[ticker] = float(closes.iloc[-1]) if not closes.empty else 0.0
                except Exception:
                    prices[ticker] = 0.0
        except Exception:
            for t in tickers:
                prices[t] = 0.0

        total_cost  = sum(r["shares"] * r["entry_price"] for r in rows)
        total_value = sum(r["shares"] * prices.get(r["ticker"], 0.0) for r in rows)
        pnl = (total_value - total_cost) / total_cost * 100 if total_cost > 0 else 0.0

        mode, color, advice = _derive_trading_mode(pnl)
        embed = discord.Embed(
            title="📈 Equity Auto-Sync",
            description=(
                f"Portfolio P&L: `{pnl:+.2f}%`\n"
                f"Cost basis: ${total_cost:,.2f}  →  Value: ${total_value:,.2f}\n\n"
                f"Derived mode: **{mode}**\n{advice}"
            ),
            color=color,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text=f"Based on {len(rows)} position(s)  |  Data via yfinance")
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        mode, color, advice = _derive_trading_mode(pnl)
        embed = discord.Embed(
            title="📈 Equity Curve Updated",
            description=f"P&L logged: `{pnl:+.1f}%`\nDerived mode: **{mode}**\n\n{advice}",
            color=color,
            timestamp=datetime.utcnow(),
        )
        await interaction.response.send_message(embed=embed)

# ─── /csv ────────────────────────────────────────────────────────────────────

@bot.tree.command(name="csv", description="Upload a Finviz/TradingView CSV to get tiers added")
@app_commands.describe(file="Upload your CSV file")
async def slash_csv(interaction: discord.Interaction, file: discord.Attachment):
    if not file.filename.lower().endswith(".csv"):
        await interaction.response.send_message("❌ Please upload a `.csv` file.", ephemeral=True)
        return

    await interaction.response.defer()
    try:
        raw_bytes = await file.read()
        df = pd.read_csv(io.BytesIO(raw_bytes))
        df.columns = (
            df.columns.str.strip()
            .str.replace(r"[.\s]", "", regex=True)
            .str.replace("%", "Pct", regex=False)
        )
        df["Tier"] = df.apply(get_tier_from_row, axis=1)
        out_bytes = df.to_csv(index=False).encode()
        out_file  = discord.File(io.BytesIO(out_bytes), "processed_tiers.csv")

        counts = df["Tier"].value_counts()
        embed = discord.Embed(
            title="✅ CSV Processed — Tiers Added",
            color=0x2DC653,
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Rows",     value=str(len(df)),                      inline=True)
        embed.add_field(name="Leading",  value=str(counts.get("Leading",  0)),    inline=True)
        embed.add_field(name="Mediocre", value=str(counts.get("Mediocre", 0)),    inline=True)
        embed.add_field(name="Lagging",  value=str(counts.get("Lagging",  0)),    inline=True)
        embed.set_footer(text="Tier = EMA9/21/50 positioning (requires Close, EMA9, EMA21, EMA50 columns)")
        ticker_col = next((c for c in ["Ticker", "Symbol"] if c in df.columns), None)
        tickers = df[ticker_col].dropna().tolist()[:5] if ticker_col else []
        view = DownloadCSV(out_bytes, "processed_tiers.csv", tickers=tickers) if tickers else None
        await interaction.followup.send(embed=embed, file=out_file, view=view)
    except Exception as exc:
        await interaction.followup.send(f"❌ Error processing file: `{exc}`")

# ─── /hotsectors ─────────────────────────────────────────────────────────────

@bot.tree.command(name="hotsectors", description="Top sectors by avg 1M performance with tier breakdown")
@app_commands.describe(
    top="Number of top sectors to show (default 5)",
    min_stocks="Minimum stocks per sector (default 3)",
)
async def slash_hotsectors(
    interaction: discord.Interaction,
    top: int = 5,
    min_stocks: int = 3,
):
    await interaction.response.defer()
    df = fetch_data()
    if df.empty:
        await interaction.followup.send("⚠️ Could not fetch data."); return

    sector_stats = (
        df.groupby("Sector")
        .agg(AvgPerf1M=("Perf1M", "mean"), Count=("Ticker", "count"))
        .round(2)
        .reset_index()
    )
    hot_sectors_df = (
        sector_stats[sector_stats["Count"] >= min_stocks]
        .nlargest(top, "AvgPerf1M")
    )

    if hot_sectors_df.empty:
        await interaction.followup.send(f"No sectors found with ≥{min_stocks} stocks."); return

    hot_df      = df[df["Sector"].isin(hot_sectors_df["Sector"])]
    hot_leading  = hot_df[hot_df["Watchlist"] == "Leading"]
    hot_mediocre = hot_df[hot_df["Watchlist"] == "Mediocre"]
    hot_lagging  = hot_df[hot_df["Watchlist"] == "Lagging"]

    embed = discord.Embed(
        title=f"🔥 Top {top} Hot Sectors (≥{min_stocks} stocks)",
        color=0xF77F00,
        timestamp=datetime.utcnow(),
    )
    for idx, row in enumerate(hot_sectors_df.itertuples(), 1):
        perf = row.AvgPerf1M
        arrow = "📈" if perf > 0 else "📉"
        embed.add_field(
            name=f"#{idx} {arrow} {row.Sector}",
            value=f"`{perf:+.1f}%` avg 1M  ({int(row.Count)} stocks)",
            inline=False,
        )
    embed.add_field(
        name="Tier Breakdown (Hot Sectors)",
        value=f"🟢 Leading: {len(hot_leading)}  🟡 Mediocre: {len(hot_mediocre)}  🔴 Lagging: {len(hot_lagging)}",
        inline=False,
    )
    embed.set_footer(text="Click a button for tier-filtered CSV • Full CSV attached")

    class HotTierView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=600)

        @discord.ui.button(label="🟢 Leading (Hot)", style=discord.ButtonStyle.success)
        async def hot_leading_btn(self, i: discord.Interaction, b: discord.ui.Button):
            f = discord.File(io.BytesIO(hot_leading.to_csv(index=False).encode()), "hot_leading.csv")
            await i.response.send_message(file=f, view=TVWatchlistView(hot_leading), ephemeral=True)

        @discord.ui.button(label="🟡 Mediocre (Hot)", style=discord.ButtonStyle.secondary)
        async def hot_mediocre_btn(self, i: discord.Interaction, b: discord.ui.Button):
            f = discord.File(io.BytesIO(hot_mediocre.to_csv(index=False).encode()), "hot_mediocre.csv")
            await i.response.send_message(file=f, view=TVWatchlistView(hot_mediocre), ephemeral=True)

        @discord.ui.button(label="🔴 Lagging (Hot)", style=discord.ButtonStyle.danger)
        async def hot_lagging_btn(self, i: discord.Interaction, b: discord.ui.Button):
            f = discord.File(io.BytesIO(hot_lagging.to_csv(index=False).encode()), "hot_lagging.csv")
            await i.response.send_message(file=f, view=TVWatchlistView(hot_lagging), ephemeral=True)

        @discord.ui.button(label="📈 TradingView Watchlist", style=discord.ButtonStyle.green)
        async def tv_btn(self, i: discord.Interaction, b: discord.ui.Button):
            await i.response.defer(ephemeral=True)
            tickers   = hot_df["Ticker"].tolist()[:5]
            price_map = hot_df.set_index("Ticker")["Close"].to_dict()
            wl_file   = build_tv_watchlist_file(tickers, price_map=price_map)
            tickers_str = ", ".join(tickers)
            embed_tv = discord.Embed(
                title="📊 TradingView Watchlist",
                description=(
                    f"**{len(tickers)} stocks** — `{tickers_str}`\n\n"
                    "**How to import:**\n"
                    "1. TradingView → Watchlist\n"
                    "2. Click `...` → Import\n"
                    "3. Upload `tradingview_watchlist.csv`\n"
                    "4. All stocks added instantly!"
                ),
                color=0x1A6EBD,
                timestamp=datetime.utcnow(),
            )
            await i.followup.send(embed=embed_tv, file=wl_file, ephemeral=True)

    full_file = discord.File(io.BytesIO(hot_df.to_csv(index=False).encode()), f"hot_sectors_top{top}.csv")
    await interaction.followup.send(embed=embed, view=HotTierView(), file=full_file)

# ─── /tier ────────────────────────────────────────────────────────────────────

SECTOR_CHOICES = [
    app_commands.Choice(name=s, value=s)
    for s in ["Technology", "Healthcare", "Financials", "Energy", "Consumer Disc",
              "Consumer Staples", "Industrials", "Materials", "Utilities",
              "Real Estate", "Communication", "ETF", "Other"]
]

@bot.tree.command(name="tier", description="5-row preview table for a tier + CSV buttons")
@app_commands.describe(tier="Leading / Mediocre / Lagging")
@app_commands.choices(tier=[
    app_commands.Choice(name="🟢 Leading",  value="Leading"),
    app_commands.Choice(name="🟡 Mediocre", value="Mediocre"),
    app_commands.Choice(name="🔴 Lagging",  value="Lagging"),
])
async def slash_tier(interaction: discord.Interaction, tier: str = "Leading"):
    await interaction.response.defer()
    df = fetch_data()
    if df.empty:
        await interaction.followup.send("⚠️ Could not fetch data."); return

    subset = df[df["Watchlist"] == tier].head(5)
    color  = 0x00FF00 if tier == "Leading" else (0xFFCC00 if tier == "Mediocre" else 0xFF4444)
    icon   = "🟢" if tier == "Leading" else ("🟡" if tier == "Mediocre" else "🔴")
    date_s = datetime.utcnow().strftime("%m/%d/%y")

    embed = discord.Embed(
        title=f"{icon} {tier} Stocks — {date_s}",
        color=color,
        timestamp=datetime.utcnow(),
    )

    if subset.empty:
        embed.description = "_No stocks in this tier._"
    else:
        header = "`{:<6} {:>7} {:>6} {:>6} {:>6} {:>6} {:>6} {:>6}`".format(
            "Ticker","Close","EMA9","EMA21","EMA50","1D%","1W%","1M%")
        rows = [header]
        for _, r in subset.iterrows():
            rows.append("`{:<6} {:>7.2f} {:>6.2f} {:>6.2f} {:>6.2f} {:>+6.1f} {:>+6.1f} {:>+6.1f}`".format(
                r["Ticker"], r["Close"], r["EMA9"], r["EMA21"], r["EMA50"],
                r["Perf1D"], r["Perf1W"], r["Perf1M"]))
        embed.description = "\n".join(rows)

    total_in_tier = len(df[df["Watchlist"] == tier])
    embed.set_footer(text=f"Showing top 5 of {total_in_tier} • Full CSV ↓ via buttons")

    await interaction.followup.send(embed=embed, view=TierDownloadView(df, "tier"))

# ─── /generatecsv ─────────────────────────────────────────────────────────────

@bot.tree.command(name="generatecsv", description="Custom filter → instant CSV download")
@app_commands.describe(
    perf="Min 1M performance % (default 0)",
    vol="Min dollar volume $M (default 50)",
    tier="Filter by tier: All / Leading / Mediocre / Lagging (default All)",
)
async def slash_generatecsv(
    interaction: discord.Interaction,
    perf: float = 0.0,
    vol: float = 50.0,
    tier: str = "All",
):
    await interaction.response.defer()
    df = fetch_data()
    if df.empty:
        await interaction.followup.send("⚠️ Could not fetch data."); return

    filtered = df[df["DollarVol_M"] >= vol]
    filtered = filtered[filtered["Perf1M"] >= perf]
    if tier not in ("All", "all"):
        filtered = filtered[filtered["Watchlist"] == tier]
    filtered = filtered.sort_values("Perf1M", ascending=False)

    counts  = filtered["Watchlist"].value_counts()
    date_s  = datetime.utcnow().strftime("%m/%d/%y")
    date_fn = datetime.utcnow().strftime("%m-%d-%y")

    embed = discord.Embed(
        title=f"📥 Custom CSV — {date_s}",
        color=0x7289DA,
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="Filters",
        value=f"Perf1M ≥ `{perf}%` | Vol ≥ `${vol:.0f}M` | Tier `{tier}`",
        inline=False)
    embed.add_field(name="Results",
        value=(f"🟢 Leading: **{counts.get('Leading',0)}**\n"
               f"🟡 Mediocre: **{counts.get('Mediocre',0)}**\n"
               f"🔴 Lagging: **{counts.get('Lagging',0)}**"),
        inline=True)
    lines = []
    for _, r in filtered.head(5).iterrows():
        arrow = "🟢" if r["Watchlist"]=="Leading" else ("🟡" if r["Watchlist"]=="Mediocre" else "🔴")
        lines.append(f"{arrow} **{r['Ticker']}** `{r['Perf1M']:+.1f}%` 1M | `{r['Perf1D']:+.1f}%` 1D | {r['Sector']}")
    embed.add_field(name="Top 5", value="\n".join(lines) or "_No results_", inline=True)
    embed.add_field(name="Total", value=str(len(filtered)), inline=False)
    embed.set_footer(text="Full CSV ↓ attached • Tier CSVs via buttons")

    full_file = discord.File(
        io.BytesIO(filtered.to_csv(index=False).encode()),
        f"custom-scan-{date_fn}.csv",
    )
    await interaction.followup.send(embed=embed, file=full_file, view=TierDownloadView(filtered, "custom"))

# ─── /sector ──────────────────────────────────────────────────────────────────

@bot.tree.command(name="sector", description="Scan stocks in a specific sector with tier CSV")
@app_commands.describe(name="Choose a sector to scan")
@app_commands.choices(name=SECTOR_CHOICES)
async def slash_sector(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    df = fetch_data()
    if df.empty:
        await interaction.followup.send("⚠️ Could not fetch data."); return

    filtered = df[df["Sector"] == name].sort_values("Perf1M", ascending=False)
    if filtered.empty:
        await interaction.followup.send(f"⚠️ No stocks found for sector `{name}`."); return

    counts  = filtered["Watchlist"].value_counts()
    date_s  = datetime.utcnow().strftime("%m/%d/%y")
    date_fn = datetime.utcnow().strftime("%m-%d-%y")

    embed = discord.Embed(
        title=f"🏭 {name} — {date_s}",
        color=0xF4A261,
        timestamp=datetime.utcnow(),
    )
    embed.add_field(
        name="Tiers",
        value=(f"🟢 Leading: **{counts.get('Leading',0)}**\n"
               f"🟡 Mediocre: **{counts.get('Mediocre',0)}**\n"
               f"🔴 Lagging: **{counts.get('Lagging',0)}**"),
        inline=True,
    )
    lines = []
    for _, r in filtered.head(5).iterrows():
        arrow = "🟢" if r["Watchlist"]=="Leading" else ("🟡" if r["Watchlist"]=="Mediocre" else "🔴")
        lines.append(f"{arrow} **{r['Ticker']}** `{r['Perf1M']:+.1f}%` 1M | `{r['Perf1D']:+.1f}%` 1D")
    embed.add_field(name="Top 5 by 1M", value="\n".join(lines) or "_No data_", inline=True)
    embed.add_field(name="Total", value=str(len(filtered)), inline=False)
    embed.set_footer(text="Full CSV ↓ attached • Tier CSVs via buttons")

    full_file = discord.File(
        io.BytesIO(filtered.to_csv(index=False).encode()),
        f"sector-{name.lower().replace(' ','-')}-{date_fn}.csv",
    )
    await interaction.followup.send(embed=embed, file=full_file, view=TierDownloadView(filtered, f"sector-{name.lower().replace(' ','-')}"))

# ─── /watchlists ──────────────────────────────────────────────────────────────

@bot.tree.command(name="watchlists", description="Scan any themed watchlist — type to search all 40+")
@app_commands.describe(name="Type a theme name (Nuclear, Quantum, Solar, AI, Crypto...)")
@app_commands.autocomplete(name=watchlist_autocomplete)
async def slash_watchlists(interaction: discord.Interaction, name: str):
    await interaction.response.defer()

    tickers = WATCHLISTS.get(name, [])
    if not tickers:
        await interaction.followup.send(f"⚠️ Watchlist `{name}` not found.")
        return

    df = fetch_data(tickers=tickers)
    if df.empty:
        await interaction.followup.send("⚠️ Could not fetch data for that watchlist.")
        return

    counts   = df["Watchlist"].value_counts()
    date_str = datetime.utcnow().strftime("%m/%d/%y")

    embed = discord.Embed(
        title=f"📋 {name} — {date_str}",
        color=0x5865F2,
        timestamp=datetime.utcnow(),
    )
    embed.add_field(
        name="Tiers",
        value=(
            f"🟢 Leading: **{counts.get('Leading', 0)}**\n"
            f"🟡 Mediocre: **{counts.get('Mediocre', 0)}**\n"
            f"🔴 Lagging: **{counts.get('Lagging', 0)}**"
        ),
        inline=True,
    )
    lines = []
    for _, row in df.head(5).iterrows():
        arrow = "🟢" if row["Watchlist"] == "Leading" else ("🟡" if row["Watchlist"] == "Mediocre" else "🔴")
        lines.append(
            f"{arrow} **{row['Ticker']}** `{row['Perf1M']:+.1f}%` 1M | `{row['Perf1D']:+.1f}%` 1D"
        )
    embed.add_field(name="Top by 1M Perf", value="\n".join(lines) or "_No data_", inline=True)
    embed.add_field(name="Tickers Scanned", value=", ".join(df["Ticker"].tolist()), inline=False)
    embed.set_footer(text="Full CSV attached • Tier CSVs via buttons")

    slug      = name.lower().replace(" ", "-").replace("&", "and").replace("/", "-")
    date_fn   = datetime.utcnow().strftime("%m-%d-%y")
    full_file = discord.File(
        io.BytesIO(df.to_csv(index=False).encode()),
        f"{slug}-{date_fn}.csv",
    )
    await interaction.followup.send(embed=embed, file=full_file, view=TierDownloadView(df, slug))

# ─── /stock ───────────────────────────────────────────────────────────────────

@bot.tree.command(name="stock", description="Look up a single stock: price, EMAs, tier, performance, volume")
@app_commands.describe(ticker="Stock ticker symbol, e.g. NVDA")
async def slash_stock(interaction: discord.Interaction, ticker: str):
    await interaction.response.defer()
    ticker = ticker.upper().strip()

    df = await asyncio.to_thread(fetch_data, [ticker])

    if df.empty:
        embed = discord.Embed(
            title="❌ Not Found",
            description=f"`{ticker}` could not be fetched. Check the symbol and try again.",
            color=0xFF0000,
        )
        await interaction.followup.send(embed=embed)
        return

    row = df.iloc[0]

    price   = row["Close"]
    ema9    = row["EMA9"]
    ema21   = row["EMA21"]
    ema50   = row["EMA50"]
    tier    = row["Watchlist"]
    p1d     = row["Perf1D"]
    p1w     = row["Perf1W"]
    p1m     = row["Perf1M"]
    dvol    = row["DollarVol_M"]
    adr     = row["ADR"]
    gap     = row["Gap"]
    relvol  = row["RelVol"]
    sector  = row["Sector"]
    mktcap  = row["MktCap"]

    tier_badge = {"Leading": "🟢 Leading", "Mediocre": "🟡 Mediocre", "Lagging": "🔴 Lagging"}.get(tier, tier)
    color      = {"Leading": 0x00C853, "Mediocre": 0xFFD600, "Lagging": 0xFF1744}.get(tier, 0x7289DA)

    def fmt_pct(v: float) -> str:
        arrow = "▲" if v >= 0 else "▼"
        return f"{arrow} {v:+.2f}%"

    def ema_tag(price: float, ema: float) -> str:
        return "✅" if price > ema else "❌"

    embed = discord.Embed(
        title=f"📊 {ticker}",
        color=color,
        timestamp=datetime.utcnow(),
    )
    embed.add_field(
        name="Tier",
        value=tier_badge,
        inline=True,
    )
    embed.add_field(
        name="Sector",
        value=sector,
        inline=True,
    )
    embed.add_field(
        name="Mkt Cap",
        value=mktcap,
        inline=True,
    )
    embed.add_field(
        name="Price",
        value=f"**${price:.2f}**",
        inline=True,
    )
    embed.add_field(
        name="Gap",
        value=fmt_pct(gap),
        inline=True,
    )
    embed.add_field(
        name="Rel Vol",
        value=f"{relvol:.2f}x",
        inline=True,
    )
    embed.add_field(
        name="EMAs",
        value=(
            f"EMA9:  `${ema9:.2f}` {ema_tag(price, ema9)}\n"
            f"EMA21: `${ema21:.2f}` {ema_tag(price, ema21)}\n"
            f"EMA50: `${ema50:.2f}` {ema_tag(price, ema50)}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Performance",
        value=(
            f"1D:  {fmt_pct(p1d)}\n"
            f"1W:  {fmt_pct(p1w)}\n"
            f"1M:  {fmt_pct(p1m)}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Volume & Range",
        value=(
            f"Dollar Vol: ${dvol:.1f}M\n"
            f"ADR: {adr:.2f}%"
        ),
        inline=True,
    )
    embed.set_footer(text="Data via yfinance • EMA 9/21/50")

    await interaction.followup.send(embed=embed, view=TVWatchlistView(df))


# ─── /recommend ───────────────────────────────────────────────────────────────

@bot.tree.command(
    name="recommend",
    description="Top buy setups using Martin Luk criteria + per-stock BUY buttons to log trades",
)
@app_commands.describe(count="Number of stocks to show (1–10, default 10)")
async def slash_recommend(interaction: discord.Interaction, count: int = 10):
    await interaction.response.defer(ephemeral=True)
    count = max(1, min(count, 10))

    df = await asyncio.to_thread(fetch_data, ALL_TICKERS)
    if df.empty:
        await interaction.followup.send(
            "Could not fetch market data. Please try again in a moment.", ephemeral=True
        )
        return

    spy_row    = df[df["Ticker"] == "SPY"]
    spy_perf1d = float(spy_row["Perf1D"].iloc[0]) if not spy_row.empty else 0.0

    top_sectors = (
        df[df["Watchlist"] == "Leading"]["Sector"]
        .value_counts()
        .head(5)
        .index.tolist()
    )

    filtered = _apply_recommend_filter(df, spy_perf1d, top_sectors)
    results  = filtered.head(count)

    if results.empty:
        embed = discord.Embed(
            title="📈 No Recommendations Right Now",
            description=(
                "No stocks currently meet all five Martin Luk buy criteria:\n"
                "🟢 Tier 1 Leader · 📈 RelVol ≥ 1.5x · 💲 Price ≥ $10 · 🔥 Hot Sector · 🚀 Beats SPY\n\n"
                "Try `/scan` for a broader view of the market."
            ),
            color=0xFF6B00,
            timestamp=datetime.utcnow(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    lines = []
    for i, (_, row) in enumerate(results.iterrows(), 1):
        arrow = "🟢" if row["Perf1D"] >= 0 else "🔴"
        lines.append(
            f"`{i:>2}.` {arrow} **{row['Ticker']}** — "
            f"`{row['Perf1D']:+.1f}%` 1D · "
            f"RelVol `{row['RelVol']:.1f}x` · "
            f"${row['Close']:.2f} · "
            f"{row['Sector']}"
        )

    sectors_str = " · ".join(f"**{s}**" for s in top_sectors[:5])
    embed = discord.Embed(
        title=f"📈 Top {len(results)} Recommended Setups",
        description="\n".join(lines),
        color=0x00C853,
        timestamp=datetime.utcnow(),
    )
    embed.add_field(
        name="✅ Filter criteria (Martin Luk)",
        value=(
            "🟢 Tier 1 Leader (price > EMA9/21/50)\n"
            "📈 RelVol ≥ 1.5x · 💲 Price ≥ $10\n"
            f"🔥 Hot sector · 🚀 Beats SPY ({spy_perf1d:+.1f}% today)"
        ),
        inline=True,
    )
    embed.add_field(
        name="🔥 Hot sectors right now",
        value=sectors_str or "_None identified_",
        inline=True,
    )
    embed.set_footer(text="Click a BUY button to log your trade (private to you) · Bot DMs when target/stop hit")

    tickers = results["Ticker"].tolist()
    await interaction.followup.send(embed=embed, view=RecommendView(tickers), ephemeral=True)

# ─── /backtest ────────────────────────────────────────────────────────────────

def _run_ema_backtest(ticker: str) -> dict:
    """
    Download 3 months of daily OHLCV for ticker, simulate EMA 9/21 crossover
    strategy, and return performance metrics.
    """
    try:
        raw = yf.download(ticker, period="3mo", auto_adjust=True, progress=False)
        if raw.empty or len(raw) < 25:
            return {"error": "not_enough_data"}

        closes = raw["Close"].squeeze()
        if isinstance(closes, pd.DataFrame):
            closes = closes.iloc[:, 0]
        closes = closes.dropna()

        ema9  = closes.ewm(span=9,  adjust=False).mean()
        ema21 = closes.ewm(span=21, adjust=False).mean()

        trades = []
        in_trade    = False
        entry_price = 0.0
        peak_equity = 1.0
        equity      = 1.0
        max_drawdown = 0.0

        for i in range(1, len(closes)):
            prev_cross = ema9.iloc[i - 1] - ema21.iloc[i - 1]
            curr_cross = ema9.iloc[i]     - ema21.iloc[i]
            price      = float(closes.iloc[i])

            if not in_trade and prev_cross < 0 and curr_cross >= 0:
                in_trade    = True
                entry_price = price

            elif in_trade and prev_cross >= 0 and curr_cross < 0:
                in_trade = False
                ret      = (price - entry_price) / entry_price
                trades.append(ret)
                equity  *= (1 + ret)
                peak_equity = max(peak_equity, equity)
                dd = (peak_equity - equity) / peak_equity
                max_drawdown = max(max_drawdown, dd)

        if in_trade and len(closes) > 0:
            price = float(closes.iloc[-1])
            ret   = (price - entry_price) / entry_price
            trades.append(ret)
            equity *= (1 + ret)
            peak_equity = max(peak_equity, equity)
            dd = (peak_equity - equity) / peak_equity
            max_drawdown = max(max_drawdown, dd)

        if not trades:
            return {"error": "no_trades"}

        wins       = [t for t in trades if t > 0]
        losses     = [t for t in trades if t <= 0]
        win_rate   = len(wins) / len(trades) * 100
        avg_win    = float(np.mean(wins))  if wins   else 0.0
        avg_loss   = abs(float(np.mean(losses))) if losses else 0.0
        rr_ratio   = avg_win / avg_loss if avg_loss > 0 else float("inf")
        total_ret  = (equity - 1.0) * 100

        if win_rate >= 55 and rr_ratio >= 1.5:
            verdict = "✅ Strong edge — strategy shows consistent positive expectancy."
        elif win_rate >= 45 and rr_ratio >= 1.0:
            verdict = "⚠️ Moderate edge — works but requires discipline and good entries."
        elif win_rate < 40 or rr_ratio < 0.8:
            verdict = "❌ Weak edge — consider tighter entry criteria or a different setup."
        else:
            verdict = "⚖️ Mixed results — performance depends heavily on market conditions."

        return {
            "ticker":       ticker,
            "total_trades": len(trades),
            "win_rate":     round(win_rate, 1),
            "avg_rr":       round(rr_ratio, 2),
            "max_drawdown": round(max_drawdown * 100, 1),
            "total_return": round(total_ret, 1),
            "verdict":      verdict,
        }
    except Exception as exc:
        return {"error": str(exc)}


@bot.tree.command(name="backtest", description="Run 3-month EMA 9/21 crossover backtest on any ticker")
@app_commands.describe(ticker="Stock ticker symbol, e.g. NVDA")
async def slash_backtest(interaction: discord.Interaction, ticker: str):
    if not _check_rate_limit(interaction.user.id):
        await interaction.response.send_message(
            "⏳ You're running scans too fast! You can run up to 10 scan commands per minute. Please wait a moment.",
            ephemeral=True,
        )
        return

    ticker = ticker.upper().strip()
    await interaction.response.defer()

    result = await asyncio.to_thread(_run_ema_backtest, ticker)

    if "error" in result:
        if result["error"] == "not_enough_data":
            await interaction.followup.send(
                f"⚠️ Not enough historical data for `{ticker}` (need 25+ trading days). "
                f"Try a more liquid ticker like `NVDA`, `AAPL`, or `SPY`."
            )
        elif result["error"] == "no_trades":
            await interaction.followup.send(
                f"⚠️ No EMA 9/21 crossover trades were generated for `{ticker}` over the past 3 months. "
                f"The price may be trending without crossovers. Try `/stock {ticker}` to check the current setup."
            )
        else:
            await interaction.followup.send(
                f"⚠️ Could not fetch data for `{ticker}`. Check the symbol and try again, "
                f"or use `/leaders` to find active tickers."
            )
        return

    win_rate      = result["win_rate"]
    rr            = result["avg_rr"]
    max_dd        = result["max_drawdown"]
    total_trades  = result["total_trades"]
    total_return  = result["total_return"]
    verdict       = result["verdict"]

    if win_rate >= 55:
        color = 0x2DC653
    elif win_rate >= 45:
        color = 0xF77F00
    else:
        color = 0xE63946

    embed = discord.Embed(
        title=f"📈 Backtest: {ticker} — EMA 9/21 Crossover (3 Months)",
        color=color,
        timestamp=datetime.utcnow(),
    )
    rr_display = "∞" if rr == float("inf") else f"{rr:.2f}"
    embed.add_field(name="Total Trades", value=f"`{total_trades}`",    inline=True)
    embed.add_field(name="Win Rate",     value=f"`{win_rate}%`",        inline=True)
    embed.add_field(name="Avg R:R",      value=f"`{rr_display}`",       inline=True)
    embed.add_field(name="Max Drawdown", value=f"`{max_dd}%`",          inline=True)
    embed.add_field(name="Total Return", value=f"`{total_return:+.1f}%`", inline=True)
    embed.add_field(name="\u200b",       value="\u200b",                inline=True)
    embed.add_field(name="Verdict",      value=verdict,                 inline=False)
    embed.set_footer(text="Strategy: Buy on EMA9 crossing above EMA21, sell on EMA9 crossing below EMA21 • Data via yfinance")

    await interaction.followup.send(embed=embed)


# ─── /history ─────────────────────────────────────────────────────────────────

class HistoryView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed]):
        super().__init__(timeout=300)
        self.pages = pages
        self.page  = 0
        self._sync_buttons()

    def _sync_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.counter_btn.label = f"{self.page + 1}/{len(self.pages)}"
        self.next_btn.disabled = self.page >= len(self.pages) - 1

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.secondary, disabled=True)
    async def counter_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

@bot.tree.command(name="history", description="Your closed trade history with P&L")
async def slash_history(interaction: discord.Interaction):
    with _db() as conn:
        rows = conn.execute(
            """SELECT ticker, entry, exit_price, shares, status, created_at, closed_at
               FROM trades
               WHERE user_id = ? AND status != 'ACTIVE'
               ORDER BY COALESCE(closed_at, created_at) DESC""",
            (interaction.user.id,),
        ).fetchall()

    if not rows:
        await interaction.response.send_message(
            "No closed trades yet. Log a trade via `/recommend` and close it using the buttons to see your history here.",
            ephemeral=True,
        )
        return

    lines = []
    for r in rows:
        opened = r["created_at"][:10]
        closed = r["closed_at"][:10] if r["closed_at"] else "—"
        entry  = r["entry"]
        ex     = r["exit_price"]
        if ex and entry:
            pnl_d = (ex - entry) * r["shares"]
            pnl_p = (ex - entry) / entry * 100
            pnl_str = f"${pnl_d:+,.0f} ({pnl_p:+.1f}%)"
        else:
            pnl_str = "—"
        status_icon = {"3R_HIT": "✅", "STOP_HIT": "❌", "BREAKEVEN": "➡️"}.get(r["status"], "•")
        ex_str = f"${ex:.2f}" if ex else "—"
        lines.append(
            f"{status_icon} `{opened}` **{r['ticker']}**  "
            f"Buy: `${entry:.2f}` · Sell: `{ex_str}` · P&L: **{pnl_str}**"
            f"\n   ↳ Closed: `{closed}`"
        )

    pages: list[discord.Embed] = []
    per_page = 10
    for i in range(0, max(1, len(lines)), per_page):
        chunk = lines[i:i + per_page]
        embed = discord.Embed(
            title="📋 Trade History",
            description="\n".join(chunk),
            color=0x7289DA,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text=f"Showing {i+1}–{min(i+per_page, len(lines))} of {len(lines)} closed trades")
        pages.append(embed)

    view = HistoryView(pages) if len(pages) > 1 else None
    await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)

# ─── /commandlog ──────────────────────────────────────────────────────────────

@bot.tree.command(name="commandlog", description="Recent command activity across all users")
@app_commands.describe(limit="Number of entries to show (max 100, default 20)")
async def slash_commandlog(interaction: discord.Interaction, limit: int = 20):
    limit = max(1, min(limit, 100))
    with _db() as conn:
        rows = conn.execute(
            "SELECT username, command, args_json, timestamp FROM command_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    if not rows:
        await interaction.response.send_message(
            "No commands have been logged yet.", ephemeral=True
        )
        return

    lines = []
    for r in rows:
        ts   = r["timestamp"][:16].replace("T", " ")
        args = json.loads(r["args_json"])
        args_str = " ".join(f"{k}:{v}" for k, v in args.items()) if args else ""
        user_short = r["username"].split("#")[0][:15]
        lines.append(f"`{ts}` **{user_short}** `/{r['command']}` {args_str}".strip())

    pages: list[discord.Embed] = []
    per_page = 15
    for i in range(0, max(1, len(lines)), per_page):
        chunk = lines[i:i + per_page]
        embed = discord.Embed(
            title=f"📜 Command Log (last {len(rows)})",
            description="\n".join(chunk),
            color=0x5865F2,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text=f"Page {i//per_page + 1}/{(len(lines)-1)//per_page + 1} · All slash command activity · UTC timestamps")
        pages.append(embed)

    view = HistoryView(pages) if len(pages) > 1 else None
    await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)

# ─── /gapscanner ──────────────────────────────────────────────────────────────

@bot.tree.command(name="gapscanner", description="Live gap-up / gap-down scanner across 200+ stocks")
@app_commands.describe(
    min_gap="Minimum gap % to include (default 2.0)",
    direction="Filter direction: up, down, or both (default both)",
)
@app_commands.choices(direction=[
    app_commands.Choice(name="Both",     value="both"),
    app_commands.Choice(name="Gap Up",   value="up"),
    app_commands.Choice(name="Gap Down", value="down"),
])
async def slash_gapscanner(
    interaction: discord.Interaction,
    min_gap: float = 2.0,
    direction: str = "both",
):
    if not _check_rate_limit(interaction.user.id):
        await interaction.response.send_message(
            "⏳ Too many scan commands. Please wait a moment.", ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True)

    df = await asyncio.to_thread(fetch_data, ALL_TICKERS)
    if df.empty:
        await interaction.followup.send("Could not fetch market data. Try again shortly.", ephemeral=True)
        return

    if direction == "up":
        gapped = df[df["Gap"] >= min_gap].sort_values("Gap", ascending=False)
    elif direction == "down":
        gapped = df[df["Gap"] <= -min_gap].sort_values("Gap")
    else:
        gapped = df[df["Gap"].abs() >= min_gap].sort_values("Gap", ascending=False)

    top = gapped.head(15)
    if top.empty:
        await interaction.followup.send(
            f"No stocks found gapping ≥{min_gap}% in the **{direction}** direction. "
            f"Try lowering the threshold.", ephemeral=True
        )
        return

    lines = []
    for _, row in top.iterrows():
        gap   = row["Gap"]
        arrow = "🟢" if gap >= 0 else "🔴"
        tier  = {"Leading": "🟢", "Mediocre": "🟡", "Lagging": "🔴"}.get(row["Watchlist"], "⚪")
        lines.append(
            f"{arrow} **{row['Ticker']}**  `{gap:+.1f}%`  "
            f"${row['Close']:.2f}  Tier: {tier} {row['Watchlist']}"
        )

    dir_label = {"up": "Gap-Up", "down": "Gap-Down", "both": "Gaps"}.get(direction, "Gaps")
    embed = discord.Embed(
        title=f"🔎 {dir_label} Scanner (≥{min_gap}%) — Top {len(top)}",
        description="\n".join(lines),
        color=0x00B0F4,
        timestamp=datetime.utcnow(),
    )
    embed.set_footer(text=f"Scanned {len(df)} stocks · Data via yfinance")
    await interaction.followup.send(embed=embed, ephemeral=True)

# ─── /watchlist (personal list) ───────────────────────────────────────────────

mywl_group = app_commands.Group(name="watchlist", description="Your personal stock watchlist")

@mywl_group.command(name="add", description="Add a ticker to your personal watchlist (max 50)")
@app_commands.describe(ticker="Stock ticker symbol, e.g. NVDA")
async def mywl_add(interaction: discord.Interaction, ticker: str):
    ticker = ticker.upper().strip()
    with _db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM user_watchlists WHERE user_id = ?", (interaction.user.id,)
        ).fetchone()[0]
        if count >= 50:
            await interaction.response.send_message(
                "Your watchlist is full (50 tickers max). Use `/watchlist remove` to free up a slot.",
                ephemeral=True,
            )
            return
        try:
            conn.execute(
                "INSERT INTO user_watchlists (user_id, ticker, added_at) VALUES (?,?,?)",
                (interaction.user.id, ticker, datetime.utcnow().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            await interaction.response.send_message(
                f"**{ticker}** is already in your watchlist.", ephemeral=True
            )
            return
    await interaction.response.send_message(
        f"✅ **{ticker}** added to your watchlist.", ephemeral=True
    )

@mywl_group.command(name="remove", description="Remove a ticker from your personal watchlist")
@app_commands.describe(ticker="Stock ticker symbol to remove")
async def mywl_remove(interaction: discord.Interaction, ticker: str):
    ticker = ticker.upper().strip()
    with _db() as conn:
        result = conn.execute(
            "DELETE FROM user_watchlists WHERE user_id = ? AND ticker = ?",
            (interaction.user.id, ticker),
        )
        conn.commit()
    if result.rowcount == 0:
        await interaction.response.send_message(
            f"**{ticker}** was not found in your watchlist.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"🗑️ **{ticker}** removed from your watchlist.", ephemeral=True
        )

@mywl_group.command(name="view", description="Show all tickers in your personal watchlist")
async def mywl_view(interaction: discord.Interaction):
    with _db() as conn:
        rows = conn.execute(
            "SELECT ticker, added_at FROM user_watchlists WHERE user_id = ? ORDER BY added_at",
            (interaction.user.id,),
        ).fetchall()
    if not rows:
        await interaction.response.send_message(
            "Your watchlist is empty. Add tickers with `/watchlist add TICKER`.", ephemeral=True
        )
        return
    tickers_str = " · ".join(f"`{r['ticker']}`" for r in rows)
    embed = discord.Embed(
        title=f"📋 Your Watchlist ({len(rows)} tickers)",
        description=tickers_str,
        color=0x7289DA,
        timestamp=datetime.utcnow(),
    )
    embed.set_footer(text="Use /watchlist scan to run EMA analysis on these tickers")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@mywl_group.command(name="scan", description="Run EMA tier scan on your personal watchlist")
async def mywl_scan(interaction: discord.Interaction):
    if not _check_rate_limit(interaction.user.id):
        await interaction.response.send_message(
            "⏳ Too many scan commands. Please wait a moment.", ephemeral=True
        )
        return
    with _db() as conn:
        rows = conn.execute(
            "SELECT ticker FROM user_watchlists WHERE user_id = ? ORDER BY ticker",
            (interaction.user.id,),
        ).fetchall()
    if not rows:
        await interaction.response.send_message(
            "Your watchlist is empty. Add tickers with `/watchlist add TICKER`.", ephemeral=True
        )
        return

    tickers = [r["ticker"] for r in rows]
    await interaction.response.defer(ephemeral=True)

    df = await asyncio.to_thread(fetch_data, tickers)
    if df.empty:
        await interaction.followup.send(
            "Could not fetch data for your watchlist tickers. Check they are valid symbols.",
            ephemeral=True,
        )
        return

    leading  = df[df["Watchlist"] == "Leading"]
    mediocre = df[df["Watchlist"] == "Mediocre"]
    lagging  = df[df["Watchlist"] == "Lagging"]

    def fmt_rows(subset: pd.DataFrame) -> str:
        lines = []
        for _, r in subset.iterrows():
            lines.append(
                f"**{r['Ticker']}**  ${r['Close']:.2f}  "
                f"1D: `{r['Perf1D']:+.1f}%`  1M: `{r['Perf1M']:+.1f}%`"
            )
        return "\n".join(lines) if lines else "_None_"

    embed = discord.Embed(
        title=f"📊 My Watchlist Scan ({len(df)}/{len(tickers)} tickers)",
        color=0x00C853,
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name=f"🟢 Leading ({len(leading)})",  value=fmt_rows(leading)[:1024],  inline=False)
    embed.add_field(name=f"🟡 Mediocre ({len(mediocre)})", value=fmt_rows(mediocre)[:1024], inline=False)
    embed.add_field(name=f"🔴 Lagging ({len(lagging)})",  value=fmt_rows(lagging)[:1024],  inline=False)
    embed.set_footer(text="Data via yfinance · EMA 9/21/50 tiers · Click button to export TradingView list")

    price_map = dict(zip(df["Ticker"], df["Close"]))

    class _WlScanView(discord.ui.View):
        def __init__(self, _tickers: list[str], _price_map: dict):
            super().__init__(timeout=300)
            self._tickers   = _tickers
            self._price_map = _price_map

        @discord.ui.button(label="📊 TradingView Watchlist CSV", style=discord.ButtonStyle.primary)
        async def tv_btn(self, _interaction: discord.Interaction, _button: discord.ui.Button):
            wl_file = build_tv_watchlist_file(self._tickers, price_map=self._price_map)
            await _interaction.response.send_message(
                "Your TradingView watchlist CSV:", file=wl_file, ephemeral=True
            )

    await interaction.followup.send(embed=embed, view=_WlScanView(tickers, price_map), ephemeral=True)

bot.tree.add_command(mywl_group)

# ─── /ping ────────────────────────────────────────────────────────────────────

@bot.tree.command(name="ping", description="Check bot latency and uptime")
async def slash_ping(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🏓 Pong!",
        description=(
            f"Latency: `{round(bot.latency * 1000)}ms`\n"
            f"Uptime: `{_format_uptime()}`"
        ),
        color=0x7289DA,
    )
    await interaction.response.send_message(embed=embed)

# ─── /help ────────────────────────────────────────────────────────────────────

@bot.tree.command(name="help", description="Easy command guide")
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Cookie Monster — Command Guide",
        description="All commands are private (only you see the response).",
        color=0x00aa00,
    )

    embed.add_field(
        name="📊  Scanning",
        value=(
            "`/stock [ticker]`  Look up any single ticker — price, EMAs, tier, 1D/1W/1M perf\n"
            "`/scan`  Full scan of 200+ stocks — leaders, averages, laggards + CSV\n"
            "`/recommend`  Top buy setups (Tier 1 + RelVol ≥ 1.5x + hot sector) with BUY buttons to log trades\n"
            "`/premarket`  Stocks gapping up before market open\n"
            "`/premarketreport`  Morning briefing: leaders, gaps, SPY direction\n"
            "`/potent`  Strong movers — set min gain% and min volume\n"
            "`/leaders`  Top stocks by 1-month gain\n"
            "`/after`  After-hours big movers (>5% range, $100M+ vol)"
        ),
        inline=False,
    )

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    embed.add_field(
        name="🏷️  Tiers & Sectors",
        value=(
            "`/tiers`  All stocks sorted by tier: Leading / Mediocre / Lagging\n"
            "`/tier`  Quick 5-stock preview for one tier + CSV\n"
            "`/sectors`  All sectors ranked by 1-month average gain\n"
            "`/hotsectors`  Hot sectors with the most Leading stocks + CSV\n"
            "`/sector`  Deep scan of one specific sector"
        ),
        inline=False,
    )

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    embed.add_field(
        name="📋  Watchlists & Exports",
        value=(
            "`/watchlists`  40+ themed lists — AI, Crypto, Nuclear, Space, Solar and more\n"
            "`/watchlist add`  Add a ticker to your personal saved watchlist\n"
            "`/watchlist remove`  Remove a ticker from your personal watchlist\n"
            "`/watchlist view`  Show all tickers in your watchlist\n"
            "`/watchlist scan`  Run full EMA tier scan on your saved tickers\n"
            "`/gapscanner`  Live gap-up / gap-down scanner across 200+ stocks\n"
            "`/generatecsv`  Custom filtered CSV — set gain%, volume, tier\n"
            "`/csv`  Upload your own Finviz/TradingView CSV → auto tier scan"
        ),
        inline=False,
    )

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    embed.add_field(
        name="🔔  Alerts  (bot DMs you when triggered)",
        value=(
            "`/alert ticker`  DM when a stock enters Leading, Mediocre, or Lagging\n"
            "`/alert premarket`  DM when any stock gaps above your % threshold\n"
            "`/alert hotsector`  DM when a sector cracks the top hot list\n"
            "`/alert target`  DM when a stock hits a specific price\n"
            "`/alerts`  See all your active alerts\n"
            "`/removealert`  Delete an alert by ID"
        ),
        inline=False,
    )

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    embed.add_field(
        name="📈  Strategy",
        value=(
            "`/backtest [ticker]`  Run 3-month EMA 9/21 crossover backtest — win rate, R:R, drawdown"
        ),
        inline=False,
    )

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    embed.add_field(
        name="💼  Portfolio Tracker",
        value=(
            "`/portfolio add [ticker] [shares] [price]`  Add a position at your entry price\n"
            "`/portfolio view`  Show all positions with live P&L % and EMA tier\n"
            "`/portfolio remove [ticker]`  Remove a position from your portfolio"
        ),
        inline=False,
    )

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    embed.add_field(
        name="⚙️  Account",
        value=(
            "`/mode`  Set risk level based on account P&L (Aggressive / Neutral / Defensive)\n"
            "`/equity [pnl]`  Log a P&L % → risk mode auto-adjusts\n"
            "`/equity`  Auto-sync from your portfolio → calculates P&L and returns mode"
        ),
        inline=False,
    )

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    embed.add_field(
        name="📊  Trade Log & History",
        value=(
            "`/history`  Your closed trades with P&L — date, ticker, buy/sell price, profit\n"
            "`/commandlog`  Recent slash command activity across all users"
        ),
        inline=False,
    )

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    embed.add_field(
        name="🛠️  Utility",
        value="`/ping`  Check bot response speed and uptime",
        inline=False,
    )

    embed.set_footer(text="Tiers: 🟢 Leading = above EMA9/21/50 • 🟡 Mediocre = above EMA21/50 • 🔴 Lagging = below")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ─── Final Execution ──────────────────────────────────────────────────────────

# 1. Initialize Database
init_db()

# 2. Start Bot in the background as soon as the web server loads
@_flask_app.before_request
def start_bot_once():
    if not hasattr(bot, 'started'):
        bot.started = True
        print("🚀 Starting Discord Bot background task...")
        token = os.environ.get("DISCORD_TOKEN")
        if token:
            # Get the existing event loop from the main thread
            loop = asyncio.get_event_loop()
            loop.create_task(bot.start(token))
        else:
            print("❌ ERROR: DISCORD_TOKEN not found in Environment Variables")

# 3. Handle Running (Local vs Render)
if __name__ == "__main__":
    # This runs if you do 'python main.py' locally
    port = int(os.environ.get("PORT", 10000))
    _flask_app.run(host="0.0.0.0", port=port)