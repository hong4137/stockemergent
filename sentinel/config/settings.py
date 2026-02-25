"""
Stock Sentinel — Configuration
watchlist.json 자동 로드 + 하드코딩 폴백
"""
import os
import json
from dataclasses import dataclass
from typing import List

# ── API Keys (GitHub Secrets → 환경변수) ──
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# ── Alert Settings ──
ALERT_COOLDOWN_MINUTES = 30
NOISE_ALERTS_MAX_PER_DAY = 3

# ── PSI Thresholds ──
PSI_WATCH = 4.0
PSI_ALERT = 6.0
PSI_CRITICAL = 8.0

# ── Watchlist ──

@dataclass
class WatchItem:
    ticker: str
    name: str
    sector: str
    thesis: str
    alert_threshold: float = 5.0


def _load_watchlist() -> List[WatchItem]:
    """watchlist.json에서 active 종목 로드, 없으면 하드코딩 폴백"""
    json_path = os.path.join(os.path.dirname(__file__), "..", "watchlist.json")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = []
        for w in data.get("watchlist", []):
            if not w.get("active", False):
                continue
            items.append(WatchItem(
                ticker=w["ticker"],
                name=w.get("name", w["ticker"]),
                sector=w.get("sector", ""),
                thesis=w.get("thesis", ""),
                alert_threshold=w.get("alert_threshold", 5.0),
            ))
        if items:
            print(f"📋 워치리스트: {len(items)}개 활성 — {', '.join(i.ticker for i in items)}")
            return items
    except FileNotFoundError:
        print("⚠️ watchlist.json 없음, 하드코딩 폴백")
    except Exception as e:
        print(f"⚠️ watchlist.json 로드 실패: {e}, 하드코딩 폴백")

    return [
        WatchItem("AMAT", "Applied Materials", "Semiconductor", "AI/HBM capex"),
    ]


WATCHLIST = _load_watchlist()
WATCHMAP = {item.ticker: item for item in WATCHLIST}
