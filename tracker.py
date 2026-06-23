"""
Trade Tracker - SQLite-based trade tracking
Auto-tracks all signals, updates TP/SL hits, calculates performance
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from typing import List, dict

logger = logging.getLogger(__name__)

DB_FILE = "trades.db"

class TradeTracker:
    def __init__(self):
        self._init_db()

    def _init_db(self):
        """Create tables if not exist"""
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT NOT NULL,
                direction   TEXT NOT NULL,
                entry       REAL NOT NULL,
                tp1         REAL NOT NULL,
                tp2         REAL NOT NULL,
                sl          REAL NOT NULL,
                score       INTEGER,
                session     TEXT,
                hold_time   TEXT,
                entry_time  TEXT NOT NULL,
                close_time  TEXT,
                close_price REAL,
                close_type  TEXT,
                pnl_pct     REAL,
                tp1_hit     INTEGER DEFAULT 0,
                status      TEXT DEFAULT 'open',
                ai_comment  TEXT,
                reasons     TEXT
            )
        """)
        conn.commit()
        conn.close()

    def add_signal(self, signal: dict) -> int:
        """Record a new signal"""
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Check if already open for this symbol
        c.execute("SELECT id FROM trades WHERE symbol=? AND status='open'", (signal['symbol'],))
        if c.fetchone():
            conn.close()
            return -1  # Already tracking
        
        import json
        c.execute("""
            INSERT INTO trades
            (symbol, direction, entry, tp1, tp2, sl, score, session, hold_time,
             entry_time, status, ai_comment, reasons)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            signal['symbol'],
            signal.get('direction', 'LONG'),
            signal['entry'],
            signal['tp1'],
            signal['tp2'],
            signal['stop_loss'],
            signal.get('score', 0),
            signal.get('session', 'open'),
            signal.get('hold_time', ''),
            datetime.utcnow().isoformat(),
            'open',
            signal.get('ai_comment', ''),
            json.dumps(signal.get('reasons', [])),
        ))
        trade_id = c.lastrowid
        conn.commit()
        conn.close()
        logger.info(f"📝 Tracked signal: {signal['symbol']} (id={trade_id})")
        return trade_id

    def mark_tp1(self, trade_id: int):
        """Mark TP1 as hit"""
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE trades SET tp1_hit=1 WHERE id=?", (trade_id,))
        conn.commit()
        conn.close()

    def close_position(self, trade_id: int, close_price: float, close_type: str):
        """Close a position with result"""
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Get entry to calculate P&L
        c.execute("SELECT entry, direction FROM trades WHERE id=?", (trade_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return
        
        entry, direction = row
        if direction == 'LONG':
            pnl = (close_price - entry) / entry * 100
        else:
            pnl = (entry - close_price) / entry * 100
        
        c.execute("""
            UPDATE trades
            SET close_time=?, close_price=?, close_type=?, pnl_pct=?, status='closed'
            WHERE id=?
        """, (
            datetime.utcnow().isoformat(),
            close_price,
            close_type,
            pnl,
            trade_id,
        ))
        conn.commit()
        conn.close()
        logger.info(f"✅ Closed trade {trade_id}: {close_type} | P&L: {pnl:+.2f}%")

    def get_open_positions(self) -> List[dict]:
        """Get all open positions"""
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            SELECT id, symbol, direction, entry, tp1, tp2, sl, entry_time, tp1_hit
            FROM trades WHERE status='open'
            ORDER BY entry_time DESC
        """)
        rows = c.fetchall()
        conn.close()
        
        return [
            {
                "id":         row[0],
                "symbol":     row[1],
                "direction":  row[2],
                "entry":      row[3],
                "tp1":        row[4],
                "tp2":        row[5],
                "sl":         row[6],
                "entry_time": row[7],
                "tp1_hit":    bool(row[8]),
            }
            for row in rows
        ]

    def get_stats(self) -> dict:
        """Today's stats"""
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        today = datetime.utcnow().strftime('%Y-%m-%d')
        
        # Today's signals
        c.execute("SELECT COUNT(*) FROM trades WHERE entry_time LIKE ?", (f"{today}%",))
        today_signals = c.fetchone()[0]
        
        # Today's closed
        c.execute("""
            SELECT COUNT(*), AVG(pnl_pct)
            FROM trades WHERE close_time LIKE ? AND status='closed'
        """, (f"{today}%",))
        row = c.fetchone()
        closed = row[0] or 0
        
        c.execute("SELECT COUNT(*) FROM trades WHERE close_time LIKE ? AND pnl_pct > 0", (f"{today}%",))
        wins = c.fetchone()[0] or 0
        
        losses = closed - wins
        win_rate = (wins / closed * 100) if closed > 0 else 0
        avg_profit = row[1] or 0
        
        conn.close()
        return {
            "today_signals": today_signals,
            "today_wins":    wins,
            "today_losses":  losses,
            "win_rate":      win_rate,
            "avg_profit":    avg_profit,
        }

    def get_full_stats(self) -> dict:
        """All-time stats"""
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM trades WHERE status='closed'")
        total = c.fetchone()[0] or 0
        
        c.execute("SELECT COUNT(*), AVG(pnl_pct) FROM trades WHERE pnl_pct > 0 AND status='closed'")
        win_row = c.fetchone()
        wins = win_row[0] or 0
        avg_win = win_row[1] or 0
        
        c.execute("SELECT COUNT(*), AVG(pnl_pct) FROM trades WHERE pnl_pct <= 0 AND status='closed'")
        loss_row = c.fetchone()
        losses = loss_row[0] or 0
        avg_loss = abs(loss_row[1] or 0)
        
        c.execute("SELECT MAX(pnl_pct) FROM trades WHERE status='closed'")
        best = c.fetchone()[0] or 0
        
        # Profit factor
        c.execute("SELECT SUM(pnl_pct) FROM trades WHERE pnl_pct > 0 AND status='closed'")
        gross_win = c.fetchone()[0] or 0
        c.execute("SELECT SUM(ABS(pnl_pct)) FROM trades WHERE pnl_pct < 0 AND status='closed'")
        gross_loss = c.fetchone()[0] or 1
        profit_factor = gross_win / gross_loss if gross_loss > 0 else 0
        
        # Last 7 days
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        c.execute("SELECT COUNT(*) FROM trades WHERE entry_time > ?", (week_ago,))
        week_signals = c.fetchone()[0] or 0
        
        c.execute("SELECT COUNT(*) FROM trades WHERE entry_time > ? AND pnl_pct > 0 AND status='closed'", (week_ago,))
        week_wins = c.fetchone()[0] or 0
        
        c.execute("SELECT COUNT(*) FROM trades WHERE entry_time > ? AND status='closed'", (week_ago,))
        week_closed = c.fetchone()[0] or 0
        
        c.execute("SELECT SUM(pnl_pct) FROM trades WHERE entry_time > ? AND status='closed'", (week_ago,))
        week_return = c.fetchone()[0] or 0
        
        conn.close()
        
        win_rate = (wins / total * 100) if total > 0 else 0
        week_win_rate = (week_wins / week_closed * 100) if week_closed > 0 else 0
        
        return {
            "total":          total,
            "wins":           wins,
            "losses":         losses,
            "win_rate":       win_rate,
            "avg_win":        avg_win,
            "avg_loss":       avg_loss,
            "best":           best,
            "profit_factor":  profit_factor,
            "week_signals":   week_signals,
            "week_win_rate":  week_win_rate,
            "week_return":    week_return,
        }
