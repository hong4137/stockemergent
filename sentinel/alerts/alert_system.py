"""
Stock Sentinel — Alert System v4
Top-3 원인 + 기사 링크 필수 포함 / AI 환각 제거
"""
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urlparse

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    ALERT_COOLDOWN_MINUTES, NOISE_ALERTS_MAX_PER_DAY,
)
from storage.database import (
    save_alert, get_last_alert_time, count_noise_alerts_today
)


# ── 한글 매핑 ──

CLS_KR = {
    "Catalyst": "호재",
    "Fracture": "악재",
    "Noise": "노이즈",
}

CLS_EMOJI = {
    "Catalyst": "🟢",
    "Fracture": "🔴",
    "Noise": "⚠️",
}

EVENT_TYPE_KR = {
    "earnings": "실적",
    "regulatory": "규제",
    "supply_chain": "공급망",
    "analyst": "애널리스트",
    "ma": "인수합병",
    "sector": "업종",
    "macro": "매크로",
    "partnership": "파트너십",
    "guidance": "가이던스",
    "other": "기타",
}

PLAYBOOKS = {
    "Catalyst": {
        "id": "호재 감지",
        "actions": [
            "추적 강화: 15분 간격 모니터링",
            "관련 종목 동향 확인",
        ],
    },
    "Fracture": {
        "id": "악재 감지",
        "actions": [
            "리스크 상향: 포지션 재평가",
            "손절 체크리스트 확인",
        ],
    },
    "Noise": {
        "id": "노이즈",
        "actions": [
            "팩트 근거 재확인",
            "15분 후 재평가",
        ],
    },
}


# ── 유틸 ──

def _extract_source_name(url: str, source_field: str = "") -> str:
    """URL 또는 source 필드에서 매체명 추출"""
    if source_field:
        if ":" in source_field:
            name = source_field.split(":", 1)[1].strip()
            if name and name.lower() not in ("", "unknown"):
                return name
        if source_field not in ("google_news", "sec_edgar"):
            return source_field

    if not url:
        return ""

    try:
        domain = urlparse(url).netloc.lower().replace("www.", "")
        known = {
            "reuters.com": "Reuters", "bloomberg.com": "Bloomberg",
            "cnbc.com": "CNBC", "seekingalpha.com": "Seeking Alpha",
            "fool.com": "Motley Fool", "barrons.com": "Barron's",
            "wsj.com": "WSJ", "ft.com": "FT",
            "marketwatch.com": "MarketWatch", "yahoo.com": "Yahoo Finance",
            "finance.yahoo.com": "Yahoo Finance", "benzinga.com": "Benzinga",
            "thestreet.com": "TheStreet", "tipranks.com": "TipRanks",
            "investing.com": "Investing.com", "sec.gov": "SEC",
            "prnewswire.com": "PR Newswire", "businesswire.com": "Business Wire",
            "globenewswire.com": "GlobeNewsWire",
        }
        for pattern, name in known.items():
            if pattern in domain:
                return name
        parts = domain.split(".")
        if len(parts) >= 2:
            return parts[-2].capitalize()
    except:
        pass
    return ""


def _is_usable_url(url: str) -> bool:
    """사용자에게 보여줄 수 있는 URL인지"""
    if not url:
        return False
    bad = ["news.google.com/rss", "finnhub.io/api", "efts.sec.gov"]
    if any(p in url for p in bad):
        return False
    try:
        path = urlparse(url).path.strip("/")
        return bool(path) and len(path) >= 3
    except:
        return False


def _shorten_url(url: str, max_len: int = 60) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url)
        domain = p.netloc.replace("www.", "")
        path = p.path
        full = domain + path
        return full if len(full) <= max_len else full[:max_len - 3] + "..."
    except:
        return url[:max_len]


def generate_alert_id(ticker: str) -> str:
    now = datetime.utcnow()
    return f"SEN-{now.strftime('%Y%m%d')}-{ticker}-{now.strftime('%H%M%S')}"


def should_send_alert(ticker: str, classification: str) -> bool:
    last_time = get_last_alert_time(ticker)
    if last_time:
        try:
            last_dt = datetime.fromisoformat(last_time)
            if datetime.utcnow() - last_dt < timedelta(minutes=ALERT_COOLDOWN_MINUTES):
                print(f"  ⏳ 쿨다운 중 ({ticker})")
                return False
        except:
            pass
    if classification in ("Noise", "노이즈"):
        if count_noise_alerts_today(ticker) >= NOISE_ALERTS_MAX_PER_DAY:
            print(f"  🔇 노이즈 일일 한도 초과")
            return False
    return True


# ── 소스별 건수 집계 ──

def _count_by_source(news_data: List[Dict]) -> Dict[str, int]:
    counts = {}
    for article in news_data:
        source = article.get("source", "unknown")
        if "google" in source.lower():
            key = "Google"
        elif "finnhub" in source.lower():
            key = "Finnhub"
        elif "sec" in source.lower() or "edgar" in source.lower():
            key = "SEC"
        else:
            key = "기타"
        counts[key] = counts.get(key, 0) + 1
    return counts


# ══════════════════════════════════════════════
# 알림 포맷 v4 — Top-3 원인 필수
# ══════════════════════════════════════════════

def format_telegram_alert(ticker: str, psi_result: Dict, flash_result: Dict,
                          ai_summary: Dict = None,
                          news_data: List[Dict] = None) -> str:
    psi = psi_result.get("psi_total", 0)
    level = psi_result.get("level", "unknown")
    details = psi_result.get("details", {})
    candidates = flash_result.get("reason_candidates", [])
    rule_cls = flash_result.get("classification", {})

    # ── 분류 결정 ──
    if ai_summary and ai_summary.get("ai_generated"):
        cls_type = ai_summary.get("classification", "Noise")
        confidence = ai_summary.get("confidence", 0.5)
        headline = ai_summary.get("headline", "")
        detail_text = ai_summary.get("detail", "")
    else:
        cls_type = rule_cls.get("type", "Noise")
        confidence = rule_cls.get("confidence", 0.5)
        headline = candidates[0].get("title", "")[:50] if candidates else ""
        detail_text = rule_cls.get("reasoning", "")

    cls_kr = CLS_KR.get(cls_type, cls_type)
    cls_emoji = CLS_EMOJI.get(cls_type, "❓")
    playbook = PLAYBOOKS.get(cls_type, PLAYBOOKS["Noise"])

    # 가격 변동
    price_line = ""
    pf = details.get("price_boost", {}).get("factors", [])
    if pf:
        price_line = pf[0].split("→")[0].replace("가격 변동", "").strip()

    # ═══ 메시지 조립 ═══
    header = f"{cls_emoji} *{ticker}*"
    if price_line:
        header += f"  {price_line}"

    msg = f"{header}\n"
    msg += "━━━━━━━━━━━━━━━━━━━\n"

    if headline:
        msg += f"📌 {headline}\n"
    if detail_text:
        msg += f"→ {detail_text}\n"
    msg += "\n"

    # ═══ 핵심: Top-3 원인 기사 ═══
    if candidates:
        msg += "🔍 *원인 Top-3:*\n"
        for c in candidates[:3]:
            rank = c.get("rank", "?")
            etype = c.get("event_type", "other")
            etype_kr = EVENT_TYPE_KR.get(etype, etype)
            title = c.get("title", "")[:55]
            source_url = c.get("source_url", "")
            source_field = c.get("source", "")
            source_name = _extract_source_name(source_url, source_field)
            sentiment = c.get("sentiment", "")
            sent_emoji = {"positive": "📈", "negative": "📉"}.get(sentiment, "➖")

            msg += f"  {rank}. {sent_emoji}[{etype_kr}] {title}\n"
            if source_name:
                msg += f"     — {source_name}"
            if _is_usable_url(source_url):
                msg += f"\n     {_shorten_url(source_url)}"
            msg += "\n"
        msg += "\n"
    else:
        msg += "🔍 수집된 기사에서 명확한 원인 미확인\n\n"

    # 분류 + PSI
    msg += f"{cls_emoji} {cls_kr} ({confidence:.0%}) | PSI {psi:.1f}\n"

    # 소스별 수집 건수
    src_counts = _count_by_source(news_data or [])
    if src_counts:
        parts = [f"{name} {cnt}건" for name, cnt in src_counts.items()]
        msg += f"📰 {' · '.join(parts)}\n"

    # 플레이북
    msg += f"\n📖 *{playbook['id']}*\n"
    for a in playbook["actions"]:
        msg += f"  ▸ {a}\n"

    msg += f"\n🕐 {datetime.utcnow().strftime('%H:%M UTC')}"
    return msg.strip()


# ══════════════════════════════════════════════
# 발송
# ══════════════════════════════════════════════

def send_alert(ticker: str, psi_result: Dict, flash_result: Dict,
               trigger_type: str = "psi_critical",
               news_data: List[Dict] = None,
               price_data: Dict = None,
               force: bool = False) -> bool:
    classification = flash_result.get("classification", {})
    cls_type = classification.get("type", "Unknown")

    # AI 요약 시도
    ai_summary = None
    try:
        from engines.ai_summarizer import summarize_event
        if news_data:
            ai_summary = summarize_event(ticker, news_data, price_data)
            if ai_summary and ai_summary.get("ai_generated"):
                cls_type = ai_summary.get("classification", cls_type)
    except Exception as e:
        print(f"  ⚠️ AI 요약 실패: {e}")

    if not force and not should_send_alert(ticker, cls_type):
        return False

    tg_msg = format_telegram_alert(
        ticker, psi_result, flash_result, ai_summary,
        news_data=news_data or []
    )
    print(tg_msg)

    sent_via = "console"
    try:
        from alerts.telegram import send_telegram
        if send_telegram(tg_msg):
            sent_via = "both"
    except Exception as e:
        print(f"  ⚠️ Telegram: {e}")

    alert_id = generate_alert_id(ticker)
    save_alert(
        alert_id=alert_id,
        ticker=ticker,
        timestamp=datetime.utcnow().isoformat(),
        trigger_type=trigger_type,
        psi_total=psi_result.get("psi_total", 0),
        classification=cls_type,
        confidence=classification.get("confidence", 0),
        reason_candidates=flash_result.get("reason_candidates", []),
        playbook_id=PLAYBOOKS.get(cls_type, PLAYBOOKS["Noise"])["id"],
        playbook_actions=PLAYBOOKS.get(cls_type, PLAYBOOKS["Noise"])["actions"],
        sent_via=sent_via,
    )
    print(f"  💾 Alert: {alert_id}")
    return True
