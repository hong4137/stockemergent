"""
Stock Sentinel — Configuration
워치리스트, 점수 가중치, 임계치, API 키 관리
"""
import os
from dataclasses import dataclass, field
from typing import Optional

# ============================================================
# API Keys (환경변수 또는 직접 입력)
# ============================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

# ============================================================
# 워치리스트
# ============================================================
@dataclass
class WatchItem:
    ticker: str
    name: str
    sector: str
    related: list = field(default_factory=list)
    keywords: list = field(default_factory=list)
    china_exposure: str = "low"  # low, medium, high
    notes: str = ""

WATCHLIST = [
    WatchItem(
        ticker="AMAT",
        name="Applied Materials",
        sector="Semiconductor Equipment",
        related=["ASML", "LRCX", "KLAC", "TSM", "INTC", "SMH"],
        keywords=[
            "Applied Materials", "AMAT",
            "EUV", "High-NA", "GAA", "Gate-All-Around",
            "advanced packaging", "HBM", "CMP", "CVD", "PVD",
            "etch", "ion implant", "WFE",
            "2nm", "3nm", "N2", "A16",
            "BIS", "export control", "Entity List",
            "CHIPS Act", "TSMC capex", "Samsung foundry",
        ],
        china_exposure="high",
        notes="WFE 1위. AI/HBM 수혜. BIS 수출규제 리스크."
    ),
    # 워치리스트 추가는 여기에
]

# ticker → WatchItem 빠른 조회
WATCHMAP = {item.ticker: item for item in WATCHLIST}

# ============================================================
# Pre-signal Index 가중치
# ============================================================
SCORE_WEIGHTS = {
    "options": 0.35,
    "attention": 0.30,
    "fact": 0.35,
}

CONFLUENCE_BONUS = 1.0   # 2개 이상 요소 동시 급증 시
NOISE_PENALTY_MAX = 2.0  # 평시 노이즈 보정 최대치

# ============================================================
# 트리거 임계치
# ============================================================
# Pre-signal 등급
PSI_LEVELS = {
    "normal": (0, 3),
    "watch": (3, 5),
    "alert": (5, 7),
    "critical": (7, 10),
}

# Flash Reason 자동 실행 조건
TRIGGER_PSI_THRESHOLD = 7.0

# 가격 급변 트리거
TRIGGER_PRICE_CHANGE_5MIN = 2.0    # 5분 수익률 ±2% 이상
TRIGGER_VOLUME_RATIO = 3.0          # 20일 평균 대비 3배 이상
TRIGGER_PREMARKET_CHANGE = 3.0      # 장전/장후 ±3% 이상

# ============================================================
# 옵션 이상 점수 기준
# ============================================================
OPTIONS_SCORING = {
    "otm_volume_3x": 3,   # OTM 거래량 3배 → +3
    "otm_volume_5x": 5,   # OTM 거래량 5배 → +5 (3x 대체)
    "short_expiry_60pct": 2,  # 7일 이내 만기 60%+ → +2
    "oi_change_50pct": 2,     # OI 변화 50%+ → +2
    "iv_skew_2sigma": 1,      # IV 스큐 2σ 이탈 → +1
    "large_trade_100k": 1,    # 단일 $100K+ 거래 → +1
}

# ============================================================
# 관심도 가속도 점수 기준
# ============================================================
ATTENTION_SCORING = {
    "mention_accel_100pct": 3,   # 언급 가속도 100%+ → +3
    "mention_accel_300pct": 5,   # 언급 가속도 300%+ → +5 (100% 대체)
    "breaking_keywords": 2,       # 현장성 키워드 → +2
    "google_trends_2x": 2,        # 트렌드 스파이크 2배 → +2
    "multi_platform": 1,          # 다중 플랫폼 동시 → +1
}

# 현장성 키워드 (한국어/영어)
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
    "sec_8k": 4,           # SEC 8-K Filing → +4
    "sec_other": 2,        # 기타 SEC Filing → +2
    "regulatory": 3,       # 규제기관 발표 → +3
    "earnings_window": 2,  # 실적 발표일 ±1일 → +2
    "multi_source": 1,     # 다중 출처 확인 → +1
}

# ============================================================
# Noise/Fracture/Catalyst 판정
# ============================================================
# 부정적 키워드 (Fracture 판정용)
NEGATIVE_KEYWORDS = [
    "lawsuit", "sued", "recall", "fraud", "investigation",
    "downgrade", "ban", "sanction", "penalty", "fine",
    "layoff", "cut", "miss", "disappointing", "weak",
    "소송", "리콜", "사기", "조사", "제재", "벌금",
]

# 긍정적 키워드 (Catalyst 판정용)
POSITIVE_KEYWORDS = [
    "beat", "raise", "upgrade", "approved", "deal",
    "contract", "partnership", "record", "strong",
    "guidance above", "upside", "outperform",
    "상향", "호실적", "계약", "승인", "신고가",
]

# ============================================================
# 알림 설정
# ============================================================
ALERT_COOLDOWN_MINUTES = 30       # 동일 종목 연속 알림 쿨다운
NOISE_ALERTS_MAX_PER_DAY = 3      # Noise 등급 일일 최대 알림
VIX_SUPPRESS_THRESHOLD = 30       # VIX 30 이상 시 개별 알림 억제

# ============================================================
# 수집 주기 (초)
# ============================================================
INTERVALS = {
    "price": 60,         # 가격: 1분
    "news": 300,         # 뉴스: 5분
    "social": 600,       # 소셜: 10분
    "options": 900,      # 옵션: 15분
    "score_calc": 900,   # PSI 재계산: 15분
    "google_trends": 3600,  # 트렌드: 1시간
}

# ============================================================
# 뉴스 RSS 피드
# ============================================================
NEWS_RSS_FEEDS = {
    "google_news": "https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en",
    "seeking_alpha": "https://seekingalpha.com/api/sa/combined/{ticker}.xml",
    "yahoo_finance": "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US",
}

# SEC EDGAR
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
