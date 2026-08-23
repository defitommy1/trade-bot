"""
Handles all database operations for the trade journal.
Every function is scoped to a specific telegram_user_id so users
can never see each other's data.
"""

import sqlite3
import os
from datetime import datetime, timezone

# On Railway, set DB_PATH=/data/trades.db to match your mounted volume
# (so the database survives restarts/redeploys). Locally, it just
# creates a file in the project folder.
DB_PATH = os.environ.get("DB_PATH", "trades.db")


def init_db():
    """Creates all tables if they don't already exist. Call once on startup."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            pair TEXT NOT NULL,
            session TEXT NOT NULL,
            setup TEXT NOT NULL,
            planned_rr REAL NOT NULL,
            confidence INTEGER NOT NULL,
            result TEXT NOT NULL,
            actual_rr REAL NOT NULL,
            logged_at TEXT NOT NULL
        )
    """)
    # Tracks every user who has ever started the bot, so scheduled jobs
    # (weekly/monthly reports, future alerts) know who to message.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_user_id INTEGER PRIMARY KEY,
            joined_at TEXT NOT NULL
        )
    """)
    # Per-user, per-alert-type on/off switch. Missing row = enabled by default.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alert_prefs (
            telegram_user_id INTEGER NOT NULL,
            alert_type TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            PRIMARY KEY (telegram_user_id, alert_type)
        )
    """)
    # Pairs each user wants scanned for opportunities.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            telegram_user_id INTEGER NOT NULL,
            pair TEXT NOT NULL,
            added_at TEXT NOT NULL,
            PRIMARY KEY (telegram_user_id, pair)
        )
    """)
    # Tracks the last candle we already alerted a user about for a given
    # pair+signal, so we don't spam the same setup every hour.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scan_alerts_sent (
            telegram_user_id INTEGER NOT NULL,
            pair TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            last_candle_time TEXT NOT NULL,
            PRIMARY KEY (telegram_user_id, pair, signal_type)
        )
    """)
    conn.commit()
    conn.close()


def register_user(user_id: int):
    """Records that this user has started the bot. Safe to call every /start."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO users (telegram_user_id, joined_at)
        VALUES (?, ?)
    """, (user_id, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def get_all_user_ids():
    """Returns every user who has ever started the bot — used by scheduled jobs."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_user_id FROM users")
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]


def is_alert_enabled(user_id: int, alert_type: str) -> bool:
    """Checks if a given alert type is enabled for a user. Defaults to True if never set."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT enabled FROM alert_prefs WHERE telegram_user_id = ? AND alert_type = ?
    """, (user_id, alert_type))
    row = cursor.fetchone()
    conn.close()
    if row is None:
        return True  # default: on
    return bool(row[0])


def set_alert_enabled(user_id: int, alert_type: str, enabled: bool):
    """Turns a specific alert type on/off for a user."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO alert_prefs (telegram_user_id, alert_type, enabled)
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_user_id, alert_type) DO UPDATE SET enabled = excluded.enabled
    """, (user_id, alert_type, int(enabled)))
    conn.commit()
    conn.close()


def log_trade(user_id: int, pair: str, session: str, setup: str,
              planned_rr: float, confidence: int, result: str, actual_rr: float):
    """Saves a completed trade log entry for a specific user."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO trades (telegram_user_id, pair, session, setup, planned_rr, confidence, result, actual_rr, logged_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, pair.upper(), session, setup, planned_rr, confidence, result, actual_rr,
          datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def get_history(user_id: int, limit: int = 10):
    """Returns the most recent trades for a specific user."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pair, session, setup, planned_rr, confidence, result, actual_rr, logged_at
        FROM trades
        WHERE telegram_user_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_stats(user_id: int, since: str = None):
    """
    Returns summary stats for a specific user's trade history.
    If 'since' (an ISO date string) is given, only includes trades logged on or after it —
    used for weekly/monthly reports.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if since:
        cursor.execute("""
            SELECT result, actual_rr, confidence, session, setup FROM trades
            WHERE telegram_user_id = ? AND logged_at >= ?
        """, (user_id, since))
    else:
        cursor.execute("""
            SELECT result, actual_rr, confidence, session, setup FROM trades
            WHERE telegram_user_id = ?
        """, (user_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return None

    total_trades = len(rows)
    wins = len([r for r in rows if r[0] == "win"])
    losses = len([r for r in rows if r[0] == "loss"])
    breakeven = len([r for r in rows if r[0] == "breakeven"])
    win_rate = round((wins / total_trades) * 100, 1) if total_trades else 0
    total_rr = round(sum(r[1] for r in rows), 2)
    avg_rr = round(total_rr / total_trades, 2) if total_trades else 0
    avg_confidence = round(sum(r[2] for r in rows) / total_trades, 1) if total_trades else 0

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "win_rate": win_rate,
        "total_rr": total_rr,
        "avg_rr": avg_rr,
        "avg_confidence": avg_confidence,
    }



# ---------- watchlist ----------

def add_to_watchlist(user_id: int, pair: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO watchlist (telegram_user_id, pair, added_at)
        VALUES (?, ?, ?)
    """, (user_id, pair.upper(), datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def remove_from_watchlist(user_id: int, pair: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM watchlist WHERE telegram_user_id = ? AND pair = ?
    """, (user_id, pair.upper()))
    conn.commit()
    conn.close()


def get_watchlist(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pair FROM watchlist WHERE telegram_user_id = ? ORDER BY pair
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]


def get_all_watchlist_pairs():
    """Every unique pair being watched by anyone — used to fetch each pair's data only once per scan."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT pair FROM watchlist")
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]


def get_users_watching(pair: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT telegram_user_id FROM watchlist WHERE pair = ?
    """, (pair.upper(),))
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]


# ---------- scan alert dedupe ----------

def already_alerted(user_id: int, pair: str, signal_type: str, candle_time: str) -> bool:
    """Checks if we've already alerted this user about this exact candle's signal."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT last_candle_time FROM scan_alerts_sent
        WHERE telegram_user_id = ? AND pair = ? AND signal_type = ?
    """, (user_id, pair.upper(), signal_type))
    row = cursor.fetchone()
    conn.close()
    return row is not None and row[0] == candle_time


def mark_alerted(user_id: int, pair: str, signal_type: str, candle_time: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO scan_alerts_sent (telegram_user_id, pair, signal_type, last_candle_time)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(telegram_user_id, pair, signal_type) DO UPDATE SET last_candle_time = excluded.last_candle_time
    """, (user_id, pair.upper(), signal_type, candle_time))
    conn.commit()
    conn.close()
