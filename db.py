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
    """Creates the trades table if it doesn't already exist. Call once on startup."""
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
