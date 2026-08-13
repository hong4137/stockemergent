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


# 스키마 변경 시 여기에 (컬럼명, 타입+기본값)을 추가하면 ALTER TABLE로 자동 반영된다.
# 절대 DROP 하지 말 것 — alerts 테이블은 쿨다운 판정과 알림 이력의 유일한 근거다.
ALERTS_COLUMNS = [
    ("alert_id", "TEXT PRIMARY KEY"),
    ("ticker", "TEXT NOT NULL"),
    ("timestamp", "TEXT NOT NULL"),
    ("trigger_type", "TEXT"),
    ("psi_total", "REAL"),
    ("classification", "TEXT"),
    ("confidence", "REAL"),
    ("reason_candidates", "TEXT"),
    ("playbook_id", "TEXT"),
    ("playbook_actions", "TEXT"),
    ("sent_via", "TEXT DEFAULT 'console'"),
    ("change_pct", "REAL DEFAULT 0"),
    # ── 관측성: 실제로 발송된 내용을 남긴다 ──
    ("headline", "TEXT DEFAULT ''"),
    ("detail", "TEXT DEFAULT ''"),
    ("event_type", "TEXT DEFAULT ''"),
    ("ai_generated", "INTEGER DEFAULT 0"),
    ("key_source", "TEXT DEFAULT ''"),
    ("model", "TEXT DEFAULT ''"),
]


def init_db():
    conn = _connect()
    c = conn.cursor()

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

    # 누락 컬럼은 ALTER TABLE로 추가 (이력 보존)
    c.execute("PRAGMA table_info(alerts)")
    existing = {row[1] for row in c.fetchall()}
    for name, decl in ALERTS_COLUMNS:
        if name in existing:
            continue
        # PRIMARY KEY / NOT NULL 은 ALTER TABLE ADD COLUMN 으로 붙일 수 없다.
        # 해당 컬럼들은 위 CREATE TABLE 에 이미 포함돼 있으므로 여기 도달하지 않는다.
        safe_decl = decl.replace("PRIMARY KEY", "").replace("NOT NULL", "").strip()
        c.execute(f"ALTER TABLE alerts ADD COLUMN {name} {safe_decl}")
        print(f"  🔧 alerts.{name} 컬럼 추가")

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
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
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
    headline: str = "",
    detail: str = "",
    event_type: str = "",
    ai_generated: bool = False,
    key_source: str = "",
    model: str = "",
):
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """INSERT OR REPLACE INTO alerts
           (alert_id, ticker, timestamp, trigger_type, psi_total,
            classification, confidence, reason_candidates,
            playbook_id, playbook_actions, sent_via, change_pct,
            headline, detail, event_type, ai_generated, key_source, model)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            alert_id, ticker, timestamp, trigger_type, psi_total,
            classification, confidence, json.dumps(reason_candidates),
            playbook_id, json.dumps(playbook_actions), sent_via, change_pct,
            headline, detail, event_type, int(bool(ai_generated)), key_source, model,
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


def get_meta(key: str) -> Optional[str]:
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT value FROM meta WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row["value"] if row else None


def set_meta(key: str, value: str):
    conn = _connect()
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()
    conn.close()


def claim_once_per_day(key: str, day: str) -> bool:
    """오늘 아직 안 한 작업이면 True를 주고 즉시 잠근다.

    cron 스케줄이 겹쳐 같은 시각에 워크플로가 두 번 돌아도
    일일 요약이 중복 발송되지 않게 한다.
    """
    if get_meta(key) == day:
        return False
    set_meta(key, day)
    return True


SCAN_LOG_RETENTION_DAYS = 30


def prune_scan_log(days: int = SCAN_LOG_RETENTION_DAYS):
    """scan_log 보존기간 초과분 삭제.

    sentinel.db는 매 스캔마다 git에 커밋되므로 무한 증가하면 레포가 부푼다.
    PSI baseline 계산에는 최근 30일이면 충분하다.
    """
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM scan_log WHERE timestamp < ?", (cutoff,))
    removed = c.rowcount
    conn.commit()
    conn.close()
    if removed > 0:
        print(f"  🧹 scan_log {removed}행 정리 ({days}일 초과)")
    return removed


def get_news_baseline(ticker: str, days: int = 14) -> Optional[float]:
    """평소 뉴스 건수(중앙값). PSI의 '평소 대비' 판정에 쓴다.

    이력이 부족하면 None을 반환하고, 호출측이 절대 건수 방식으로 폴백한다.
    """
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """SELECT news_count FROM scan_log
           WHERE ticker = ? AND timestamp >= ? AND news_count IS NOT NULL
           ORDER BY news_count""",
        (ticker, cutoff),
    )
    counts = [r[0] for r in c.fetchall()]
    conn.close()

    if len(counts) < 20:  # 표본 부족 — 신뢰할 수 없음
        return None

    mid = len(counts) // 2
    if len(counts) % 2:
        return float(counts[mid])
    return (counts[mid - 1] + counts[mid]) / 2


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
