"""
Stock Sentinel — Storage Layer
SQLite 기반 시계열 데이터, 뉴스, 점수, 알림 저장
"""
import sqlite3
import json
import os
from datetime import datetime, timedelta
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "sentinel.db")


@contextmanager
def get_db():
    """DB 연결 컨텍스트 매니저"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """데이터베이스 초기화 — 모든 테이블 생성"""
    with get_db() as conn:
        conn.executescript("""
        -- 1. 가격 시계열
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            source TEXT DEFAULT 'yfinance',
            UNIQUE(ticker, timestamp)
        );
        CREATE INDEX IF NOT EXISTS idx_prices_ticker_ts 
            ON prices(ticker, timestamp DESC);

        -- 2. 옵션 스냅샷
        CREATE TABLE IF NOT EXISTS options_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            expiration TEXT,
            total_call_volume INTEGER,
            total_put_volume INTEGER,
            pc_ratio REAL,
            top_calls_json TEXT,  -- JSON: [{strike, volume, oi, iv}, ...]
            top_puts_json TEXT,
            otm_call_volume_ratio REAL,  -- 당일/20일평균
            short_expiry_pct REAL,       -- 7일내 만기 비중
            oi_change_pct REAL,
            raw_json TEXT,
            UNIQUE(ticker, timestamp, expiration)
        );
        CREATE INDEX IF NOT EXISTS idx_options_ticker_ts 
            ON options_snapshots(ticker, timestamp DESC);

        -- 3. 뉴스/공시
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            timestamp TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT,
            url TEXT UNIQUE,
            source TEXT,          -- google_news, sec_edgar, finnhub, etc.
            source_type TEXT,     -- news, filing, analysis, social
            sentiment TEXT,       -- positive, negative, neutral
            keywords_matched TEXT, -- JSON array
            collected_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_news_ticker_ts 
            ON news(ticker, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_news_url ON news(url);

        -- 4. 소셜 언급량
        CREATE TABLE IF NOT EXISTS social_mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            platform TEXT,        -- reddit, stocktwits, google_trends
            mention_count INTEGER DEFAULT 0,
            sentiment_score REAL, -- -1.0 ~ 1.0
            breaking_keyword_found INTEGER DEFAULT 0,
            raw_json TEXT,
            UNIQUE(ticker, timestamp, platform)
        );
        CREATE INDEX IF NOT EXISTS idx_social_ticker_ts 
            ON social_mentions(ticker, timestamp DESC);

        -- 5. Pre-signal Index 점수 이력
        CREATE TABLE IF NOT EXISTS psi_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            options_score REAL DEFAULT 0,
            attention_score REAL DEFAULT 0,
            fact_score REAL DEFAULT 0,
            confluence_bonus REAL DEFAULT 0,
            noise_penalty REAL DEFAULT 0,
            psi_total REAL DEFAULT 0,
            level TEXT,           -- normal, watch, alert, critical
            details_json TEXT,    -- 점수 산출 상세 근거
            UNIQUE(ticker, timestamp)
        );
        CREATE INDEX IF NOT EXISTS idx_psi_ticker_ts 
            ON psi_scores(ticker, timestamp DESC);

        -- 6. 알림 이력
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id TEXT UNIQUE NOT NULL,
            ticker TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            trigger_type TEXT,     -- price_surge, price_drop, psi_critical, confluence
            psi_total REAL,
            classification TEXT,   -- Noise, Fracture, Catalyst, Unknown
            confidence REAL,
            reason_candidates_json TEXT,  -- JSON: Top-3
            playbook_id TEXT,
            playbook_actions_json TEXT,
            sent_via TEXT,         -- telegram, console, both
            
            -- 사후 평가
            actual_outcome TEXT,   -- 사후 라벨링
            accuracy_label TEXT,   -- correct, partially, wrong
            reviewed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_alerts_ticker_ts 
            ON alerts(ticker, timestamp DESC);

        -- 7. 이벤트 캘린더
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            event_date TEXT NOT NULL,
            event_type TEXT,       -- earnings, fomc, cpi, regulatory, etc.
            description TEXT,
            importance TEXT DEFAULT 'medium'  -- low, medium, high
        );
        CREATE INDEX IF NOT EXISTS idx_events_date 
            ON events(event_date);
        """)
    print("✅ Database initialized:", DB_PATH)


# ============================================================
# CRUD 헬퍼
# ============================================================

def save_price(ticker: str, timestamp: str, open_: float, high: float, 
               low: float, close: float, volume: int, source: str = "yfinance"):
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO prices (ticker, timestamp, open, high, low, close, volume, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (ticker, timestamp, open_, high, low, close, volume, source))


def save_news(ticker: str, timestamp: str, title: str, url: str,
              summary: str = "", source: str = "", source_type: str = "news",
              sentiment: str = "neutral", keywords_matched: list = None):
    with get_db() as conn:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO news 
                (ticker, timestamp, title, summary, url, source, source_type, sentiment, keywords_matched)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ticker, timestamp, title, summary, url, source, source_type,
                  sentiment, json.dumps(keywords_matched or [])))
            return True
        except sqlite3.IntegrityError:
            return False  # 이미 존재하는 URL


def save_social(ticker: str, timestamp: str, platform: str,
                mention_count: int, sentiment_score: float = 0,
                breaking_keyword_found: bool = False, raw_json: str = ""):
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO social_mentions
            (ticker, timestamp, platform, mention_count, sentiment_score, breaking_keyword_found, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (ticker, timestamp, platform, mention_count, sentiment_score,
              int(breaking_keyword_found), raw_json))


def save_psi_score(ticker: str, timestamp: str, options_score: float,
                   attention_score: float, fact_score: float,
                   confluence_bonus: float, noise_penalty: float,
                   psi_total: float, level: str, details: dict = None):
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO psi_scores
            (ticker, timestamp, options_score, attention_score, fact_score,
             confluence_bonus, noise_penalty, psi_total, level, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ticker, timestamp, options_score, attention_score, fact_score,
              confluence_bonus, noise_penalty, psi_total, level,
              json.dumps(details or {})))


def save_alert(alert_id: str, ticker: str, timestamp: str,
               trigger_type: str, psi_total: float, classification: str,
               confidence: float, reason_candidates: list,
               playbook_id: str = "", playbook_actions: list = None,
               sent_via: str = "console"):
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO alerts
            (alert_id, ticker, timestamp, trigger_type, psi_total,
             classification, confidence, reason_candidates_json,
             playbook_id, playbook_actions_json, sent_via)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (alert_id, ticker, timestamp, trigger_type, psi_total,
              classification, confidence, json.dumps(reason_candidates),
              playbook_id, json.dumps(playbook_actions or []), sent_via))


# ============================================================
# 조회 헬퍼
# ============================================================

def get_recent_prices(ticker: str, limit: int = 100) -> list:
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM prices WHERE ticker = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (ticker, limit)).fetchall()
        return [dict(r) for r in rows]


def get_recent_news(ticker: str, hours: int = 24, limit: int = 50) -> list:
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM news WHERE ticker = ? AND timestamp >= ?
            ORDER BY timestamp DESC LIMIT ?
        """, (ticker, cutoff, limit)).fetchall()
        return [dict(r) for r in rows]


def get_recent_social(ticker: str, hours: int = 48) -> list:
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM social_mentions WHERE ticker = ? AND timestamp >= ?
            ORDER BY timestamp DESC
        """, (ticker, cutoff)).fetchall()
        return [dict(r) for r in rows]


def get_latest_psi(ticker: str) -> dict:
    with get_db() as conn:
        row = conn.execute("""
            SELECT * FROM psi_scores WHERE ticker = ?
            ORDER BY timestamp DESC LIMIT 1
        """, (ticker,)).fetchone()
        return dict(row) if row else None


def get_psi_history(ticker: str, hours: int = 24) -> list:
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM psi_scores WHERE ticker = ? AND timestamp >= ?
            ORDER BY timestamp ASC
        """, (ticker, cutoff)).fetchall()
        return [dict(r) for r in rows]


def get_recent_alerts(ticker: str = None, hours: int = 24) -> list:
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as conn:
        if ticker:
            rows = conn.execute("""
                SELECT * FROM alerts WHERE ticker = ? AND timestamp >= ?
                ORDER BY timestamp DESC
            """, (ticker, cutoff)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM alerts WHERE timestamp >= ?
                ORDER BY timestamp DESC
            """, (cutoff,)).fetchall()
        return [dict(r) for r in rows]


def get_last_alert_time(ticker: str) -> str:
    """쿨다운 체크용: 마지막 알림 시각"""
    with get_db() as conn:
        row = conn.execute("""
            SELECT timestamp FROM alerts WHERE ticker = ?
            ORDER BY timestamp DESC LIMIT 1
        """, (ticker,)).fetchone()
        return row['timestamp'] if row else None


def get_last_alert_psi(ticker: str) -> float:
    """마지막 알림의 PSI 점수"""
    with get_db() as conn:
        row = conn.execute("""
            SELECT psi_total FROM alerts WHERE ticker = ?
            ORDER BY timestamp DESC LIMIT 1
        """, (ticker,)).fetchone()
        return row['psi_total'] if row else 0.0


def count_noise_alerts_today(ticker: str) -> int:
    """오늘 Noise 알림 횟수"""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with get_db() as conn:
        row = conn.execute("""
            SELECT COUNT(*) as cnt FROM alerts 
            WHERE ticker = ? AND classification = 'Noise'
            AND timestamp >= ?
        """, (ticker, today)).fetchone()
        return row['cnt']


# ============================================================
# 초기화 실행
# ============================================================
if __name__ == "__main__":
    init_db()
