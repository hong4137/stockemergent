"""
Stock Sentinel — Configuration
워치리스트는 watchlist.json에서 로드. 점수 가중치, 임계치, API 키 관리.
"""
import os
import json
from dataclasses import dataclass, field
from typing import Optional, List

# ============================================================
# API Keys (GitHub Secrets → 환경변수)
# ============================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

# ============================================================
# 워치리스트 (watchlist.json에서 로드)
# ============================================================
@dataclass
class WatchItem:
    ticker: str
    name: str
    sector: str = ""
    related: list = field(default_factory=list)
    keywords: list = field(default_factory=list)
    china_exposure: str = "low"
    notes: str = ""


def _load_watchlist() -> List[WatchItem]:
    """watchlist.json에서 active 종목만 로드"""
    json_path = os.path.join(os.path.dirname(__file__), "..", "..", "watchlist.json")
    json_path = os.path.normpath(json_path)
    
    if not os.path.exists(json_path):
        print(f"⚠️ watchlist.json 없음: {json_path}")
        return []
    
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    items = []
    for entry in data.get("watchlist", []):
        if not entry.get("active", False):
            continue
        items.append(WatchItem(
            ticker=entry["ticker"],
            name=entry["name"],
            sector=entry.get("sector", ""),
            related=entry.get("related", []),
            keywords=entry.get("keywords", []),
            china_exposure=entry.get("china_exposure", "low"),
            notes=entry.get("notes", ""),
        ))
    
    print(f"📋 워치리스트: {len(items)}개 활성 — {', '.join(w.ticker for w in items)}")
    return items


WATCHLIST = _load_watchlist()
WATCHMAP = {item.ticker: item for item in WATCHLIST}

# ============================================================
# Pre-signal Index 가중치
# ============================================================
SCORE_WEIGHTS = {
    "options": 0.35,
    "attention": 0.30,
    "fact": 0.35,
}

CONFLUENCE_BONUS = 1.0
NOISE_PENALTY_MAX = 2.0

# ============================================================
# 트리거 임계치
# ============================================================
PSI_LEVELS = {
    "normal": (0, 3),
    "watch": (3, 5),
    "alert": (5, 7),
    "critical": (7, 10),
}

TRIGGER_PSI_THRESHOLD = 7.0
TRIGGER_PRICE_CHANGE_5MIN = 2.0
TRIGGER_VOLUME_RATIO = 3.0
TRIGGER_PREMARKET_CHANGE = 3.0

# ============================================================
# 옵션 이상 점수 기준
# ============================================================
OPTIONS_SCORING = {
    "otm_volume_3x": 3,
    "otm_volume_5x": 5,
    "short_expiry_60pct": 2,
    "oi_change_50pct": 2,
    "iv_skew_2sigma": 1,
    "large_trade_100k": 1,
}

# ============================================================
# 관심도 가속도 점수 기준
# ============================================================
ATTENTION_SCORING = {
    "mention_accel_100pct": 3,
    "mention_accel_300pct": 5,
    "breaking_keywords": 2,
    "google_trends_2x": 2,
    "multi_platform": 1,
}

BREAKING_KEYWORDS = [
    "breaking", "just announced", "just reported",
    "urgent", "alert", "soars", "plunges", "surges",
    "crashes", "halted", "FDA approved", "settlement",
    "acquisition", "merger", "buyout", "recall",
    "속보", "긴급", "급등", "급락", "폭등", "폭락",
]

# ============================================================
# 팩트/공시 점수 기준
# ============================================================
FACT_SCORING = {
    "sec_8k": 4,
    "sec_other": 2,
    "regulatory": 3,
    "earnings_window": 2,
    "multi_source": 1,
}

# ============================================================
# 분류 키워드
# ============================================================
NEGATIVE_KEYWORDS = [
    "lawsuit", "sued", "recall", "fraud", "investigation",
    "downgrade", "ban", "sanction", "penalty", "fine",
    "layoff", "cut", "miss", "disappointing", "weak",
    "소송", "리콜", "사기", "조사", "제재", "벌금",
]

POSITIVE_KEYWORDS = [
    "beat", "raise", "upgrade", "approved", "deal",
    "contract", "partnership", "record", "strong",
    "guidance above", "upside", "outperform",
    "상향", "호실적", "계약", "승인", "신고가",
]

# ============================================================
# 알림 설정
# ============================================================
ALERT_COOLDOWN_MINUTES = 30
NOISE_ALERTS_MAX_PER_DAY = 3
VIX_SUPPRESS_THRESHOLD = 30

# ============================================================
# 수집 주기 (초)
# ============================================================
INTERVALS = {
    "price": 60,
    "news": 300,
    "social": 600,
    "options": 900,
    "score_calc": 900,
    "google_trends": 3600,
}

# ============================================================
# 뉴스 RSS 피드
# ============================================================
NEWS_RSS_FEEDS = {
    "google_news": "https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en",
    "seeking_alpha": "https://seekingalpha.com/api/sa/combined/{ticker}.xml",
    "yahoo_finance": "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US",
}

SEC_EDGAR_RSS = "https://efts.sec.gov/LATEST/search-index?q=%22{company}%22&dateRange=custom&startdt={start_date}&enddt={end_date}&forms=8-K,10-Q,10-K"
SEC_EDGAR_FULL_TEXT = "https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&forms=8-K"

# ============================================================
# 데이터베이스
# ============================================================
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "storage", "sentinel.db")

# ============================================================
# 로깅
# ============================================================
LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
LOG_LEVEL = "INFO"
