"""
Stock Sentinel — Database (SQLite)
알림 이력 + PSI 추적 + change_pct 저장
"""
import os
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict

DB_PATH = os.path.join(os.path.dirname(__file__), "sentinel.db")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    c = conn.cursor()

    # alerts 테이블 — 필요한 컬럼 체크 후 재생성
    required_cols = {"alert_id", "ticker", "timestamp", "trigger_type", "psi_total",
                     "classification", "confidence", "reason_candidates",
                     "playbook_id", "playbook_actions", "sent_via", "change_pct"}

    try:
        c.execute("PRAGMA table_info(alerts)")
        existing_cols = {row[1] for row in c.fetchall()}
    except Exception:
        existing_cols = set()

    missing = required_cols - existing_cols
    if missing and existing_cols:
        # 컬럼 누락 — 테이블 DROP 후 재생성 (이력 초기화)
        print(f"⚠️ alerts 테이블 마이그레이션: 누락 컬럼 {missing} → 재생성")
        c.execute("DROP TABLE IF EXISTS alerts")

    c.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            alert_id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            trigger_type TEXT,
            psi_total REAL,
            classification TEXT,
            confidence REAL,
            reason_candidates TEXT,
            playbook_id TEXT,
            playbook_actions TEXT,
            sent_via TEXT DEFAULT 'console',
            change_pct REAL DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS scan_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            psi_total REAL,
            level TEXT,
            news_count INTEGER,
            classification TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            timestamp TEXT,
            title TEXT,
            summary TEXT,
            url TEXT,
            source TEXT,
            source_type TEXT,
            sentiment TEXT,
            keywords_matched TEXT
        )
    """)

    conn.commit()
    conn.close()


def save_alert(
    alert_id: str,
    ticker: str,
    timestamp: str,
    trigger_type: str,
    psi_total: float,
    classification: str,
    confidence: float,
    reason_candidates: list,
    playbook_id: str,
    playbook_actions: list,
    sent_via: str = "console",
    change_pct: float = 0,
):
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """INSERT OR REPLACE INTO alerts
           (alert_id, ticker, timestamp, trigger_type, psi_total,
            classification, confidence, reason_candidates,
            playbook_id, playbook_actions, sent_via, change_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            alert_id, ticker, timestamp, trigger_type, psi_total,
            classification, confidence, json.dumps(reason_candidates),
            playbook_id, json.dumps(playbook_actions), sent_via, change_pct,
        ),
    )
    conn.commit()
    conn.close()


def save_scan(
    ticker: str,
    psi_total: float,
    level: str,
    news_count: int,
    classification: str = "N/A",
):
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """INSERT INTO scan_log
           (ticker, timestamp, psi_total, level, news_count, classification)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (ticker, datetime.utcnow().isoformat(), psi_total, level, news_count, classification),
    )
    conn.commit()
    conn.close()


def save_news(
    ticker: str,
    timestamp: str,
    title: str,
    url: str,
    summary: str = "",
    source: str = "",
    source_type: str = "news",
    sentiment: str = "neutral",
    keywords_matched: list = None,
    **kwargs,
):
    """뉴스 기사 DB 저장"""
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """INSERT INTO news
           (ticker, timestamp, title, summary, url, source,
            source_type, sentiment, keywords_matched)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ticker, timestamp, title, summary, url, source,
            source_type, sentiment,
            json.dumps(keywords_matched or []),
        ),
    )
    conn.commit()
    conn.close()


def get_last_alert_time(ticker: str) -> Optional[str]:
    conn = _connect()
    c = conn.cursor()
    c.execute(
        "SELECT timestamp FROM alerts WHERE ticker = ? ORDER BY timestamp DESC LIMIT 1",
        (ticker,),
    )
    row = c.fetchone()
    conn.close()
    return row["timestamp"] if row else None


def get_last_alert_psi(ticker: str) -> Optional[Dict]:
    """마지막 알림의 PSI와 change_pct 조회"""
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """SELECT psi_total, classification, change_pct
           FROM alerts WHERE ticker = ?
           ORDER BY timestamp DESC LIMIT 1""",
        (ticker,),
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "psi_total": row["psi_total"],
            "classification": row["classification"],
            "change_pct": row["change_pct"] or 0,
        }
    return None


def count_noise_alerts_today(ticker: str) -> int:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """SELECT COUNT(*) as cnt FROM alerts
           WHERE ticker = ? AND classification IN ('Noise', '노이즈')
           AND timestamp LIKE ?""",
        (ticker, f"{today}%"),
    )
    row = c.fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_recent_alerts(ticker: str = None, limit: int = 20) -> list:
    conn = _connect()
    c = conn.cursor()
    if ticker:
        c.execute(
            "SELECT * FROM alerts WHERE ticker = ? ORDER BY timestamp DESC LIMIT ?",
            (ticker, limit),
        )
    else:
        c.execute(
            "SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]
