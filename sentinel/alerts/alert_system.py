"""
Stock Sentinel — Alert System v3.2
v3.2: 주말/장외 반복 알림 완전 차단 + 서머타임 자동 대응
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    ALERT_COOLDOWN_MINUTES, NOISE_ALERTS_MAX_PER_DAY,
)
from storage.database import (
    save_alert, get_last_alert_time, get_last_alert_psi,
    count_noise_alerts_today,
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

PRICE_ALERT_LEVELS = [3, 5, 8, 12]


def _get_current_level(abs_move: float) -> int:
    level = 0
    for threshold in PRICE_ALERT_LEVELS:
        if abs_move >= threshold:
            level += 1
        else:
            break
    return level


def _get_et_now():
    """미국 동부시간 (서머타임 자동 대응)"""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except ImportError:
        # zoneinfo 없으면 -4 (EDT) 사용
        return datetime.now(timezone(timedelta(hours=-4)))


def _is_market_open() -> bool:
    """미국 정규장 오픈 중인지 (ET 09:30-16:00, 평일만)"""
    now_et = _get_et_now()
    if now_et.weekday() >= 5:
        return False
    hour, minute = now_et.hour, now_et.minute
    if hour < 9 or (hour == 9 and minute < 30):
        return False
    if hour >= 16:
        return False
    return True


def _is_extended_hours() -> bool:
    """프리마켓/애프터마켓 (ET 04:00-09:30, 16:00-20:00, 평일만)"""
    now_et = _get_et_now()
    if now_et.weekday() >= 5:
        return False
    hour, minute = now_et.hour, now_et.minute
    # 프리마켓 04:00-09:30
    if 4 <= hour < 9 or (hour == 9 and minute < 30):
        return True
    # 애프터마켓 16:00-20:00
    if 16 <= hour < 20:
        return True
    return False


def _is_article_url(url: str) -> bool:
    if not url:
        return False
    bad = ["news.google.com/rss", "finnhub.io/api"]
    if any(p in url for p in bad):
        return False
    path = urlparse(url).path.strip("/")
    if not path or len(path) < 3:
        return False
    return True


def generate_alert_id(ticker: str) -> str:
    now = datetime.utcnow()
    return f"SEN-{now.strftime('%Y%m%d')}-{ticker}-{now.strftime('%H%M%S')}"


def should_send_alert(
    ticker: str,
    classification: str,
    change_pct: float = 0,
    intraday_reversal: float = 0,
) -> bool:
    """
    v3.2 — 알림 발송 판단

    시간대별 규칙:
    1. 주말/야간(장외+프리/애프터 아님): 알림 완전 차단
    2. 프리/애프터마켓: 10%+ 급변동만 허용
    3. 정규장: 단계별 임계치 적용

    단계별 규칙 (정규장):
    - 새 단계 돌파 시 즉시 알림
    - 같은 단계 내: 2시간 쿨다운
    - 8%+ 고변동: 30분 간격
    - 장중 반전: 새 단계일 때만 (같은 단계 반복 차단)
    """

    # ── 1. 시간대 체크 ──
    if not _is_market_open() and not _is_extended_hours():
        # 주말/야간: 완전 차단 (어떤 변동이든)
        print(f"  🌙 장외(주말/야간) — 알림 차단")
        return False

    if not _is_market_open() and _is_extended_hours():
        # 프리/애프터마켓: 10%+ 급변동만
        effective = max(abs(change_pct), abs(intraday_reversal))
        if effective < 10:
            print(f"  🌅 프리/애프터마켓 — {effective:.1f}% < 10% 차단")
            return False
        print(f"  🚨 프리/애프터마켓 — {effective:.1f}% 급변동 알림!")

    # ── 2. 쿨다운 체크 ──
    last_time = get_last_alert_time(ticker)
    hours_since = 999

    if last_time:
        try:
            last_dt = datetime.fromisoformat(last_time)
            diff = datetime.utcnow() - last_dt
            hours_since = diff.total_seconds() / 3600

            # 최소 쿨다운: 15분
            if hours_since < 0.25:
                print(f"  ⏳ 쿨다운 15분 미경과 ({ticker})")
                return False
        except:
            pass

    # ── 3. 단계별 판단 (정규장) ──
    effective_move = max(abs(change_pct), abs(intraday_reversal))
    current_level = _get_current_level(effective_move)

    last_psi_data = get_last_alert_psi(ticker)
    prev_level = 0
    if last_psi_data:
        prev_change = abs(last_psi_data.get("change_pct", 0))
        prev_level = _get_current_level(prev_change)

    # 새 거래일 시작 (6시간+ 경과 + 정규장) → 리셋
    if hours_since >= 6 and _is_market_open():
        print(f"  ✅ 새 거래일 리셋")
        return True

    # 장중 반전 3%+ → 새 단계일 때만
    if abs(intraday_reversal) >= 3:
        reversal_level = _get_current_level(abs(intraday_reversal))
        if reversal_level > prev_level:
            print(f"  🔄 반전 새 단계: {prev_level}->{reversal_level}")
            return True
        if hours_since >= 2:
            print(f"  ✅ 반전 2시간+ 경과, 재알림")
            return True
        print(f"  ⏳ 반전 같은 단계 ({reversal_level}), 중복 차단")
        return False

    # 새 단계 돌파
    if current_level > prev_level:
        threshold = PRICE_ALERT_LEVELS[current_level - 1] if current_level > 0 else 0
        print(f"  📊 레벨 상승: {prev_level}->{current_level} ({threshold}%+)")
        return True

    # 8%+ (레벨3) → 30분 간격
    if current_level >= 3 and hours_since >= 0.5:
        print(f"  🚨 고변동 ({effective_move:.1f}%), 30분 경과")
        return True

    # Noise 일일 한도
    if classification in ("Noise", "노이즈"):
        noise_count = count_noise_alerts_today(ticker)
        if noise_count >= NOISE_ALERTS_MAX_PER_DAY:
            print(f"  🔇 노이즈 일일 한도")
            return False

    # 같은 단계 → 2시간 쿨다운
    if current_level <= prev_level:
        if hours_since < 2:
            print(f"  ⏳ 같은 단계 ({current_level}), 2시간 쿨다운")
            return False

    return True


# ── 알림 포맷 ──

def format_telegram_alert(
    ticker: str,
    psi_result: Dict,
    flash_result: Dict,
    ai_summary: Dict = None,
    price_data: Dict = None,
) -> str:
    psi = psi_result.get("psi_total", 0)
    details = psi_result.get("details", {})
    candidates = flash_result.get("reason_candidates", [])
    rule_cls = flash_result.get("classification", {})

    if ai_summary and ai_summary.get("ai_generated"):
        cls_type = ai_summary.get("classification", "Noise")
        confidence = ai_summary.get("confidence", 0.5)
        headline = ai_summary.get("headline", "")
        detail_text = ai_summary.get("detail", "")
    else:
        cls_type = rule_cls.get("type", "Noise")
        confidence = rule_cls.get("confidence", 0.5)
        headline = candidates[0].get("title", "")[:40] if candidates else ""
        detail_text = rule_cls.get("reasoning", "")

    cls_kr = CLS_KR.get(cls_type, cls_type)
    cls_emoji = CLS_EMOJI.get(cls_type, "?")
    playbook = PLAYBOOKS.get(cls_type, PLAYBOOKS["Noise"])

    # 가격 변동
    price_line = ""
    if price_data:
        pct = price_data.get("change_pct", 0)
        rev = price_data.get("intraday_reversal", 0)
        if abs(pct) >= 0.5:
            price_line = f"{pct:+.1f}%"
        if abs(rev) >= 3:
            rev_dir = "고점대비" if rev < 0 else "저점대비"
            price_line += f" ({rev_dir} {rev:+.1f}%)"
    else:
        pf = details.get("price_boost", {}).get("factors", [])
        if pf:
            price_line = pf[0].split("->")[0].replace("가격 변동", "").strip()

    header = f"{cls_emoji} *{ticker}*"
    if price_line:
        header += f"  {price_line}"

    msg = f"{header}\n"
    msg += "━━━━━━━━━━━━━━━━━━━\n"

    if headline:
        msg += f"📌 *{headline}*\n"
    if detail_text:
        msg += f"→ {detail_text}\n"

    msg += "\n"
    msg += f"{cls_emoji} {cls_kr} ({confidence:.0%}) | PSI {psi:.1f}\n"

    src_count = (
        ai_summary.get("source_count", len(candidates))
        if ai_summary
        else len(candidates)
    )
    if src_count:
        msg += f"📰 {src_count}개 매체\n"

    # 핵심 소스 URL
    key_url = ""
    if ai_summary and ai_summary.get("key_source"):
        key_url = ai_summary["key_source"]
    if not key_url:
        for c in candidates:
            u = c.get("source_url", "")
            if _is_article_url(u):
                key_url = u
                break
    if key_url:
        msg += f"🔗 {key_url[:80]}\n"

    msg += f"\n📖 *{playbook['id']}*\n"
    for a in playbook["actions"]:
        msg += f"  ▸ {a}\n"

    now_et = _get_et_now()
    msg += f"\n🕐 {now_et.strftime('%H:%M ET')}"
    return msg.strip()


# ── 발송 ──

def send_alert(
    ticker: str,
    psi_result: Dict,
    flash_result: Dict,
    trigger_type: str = "psi_critical",
    news_data: List[Dict] = None,
    price_data: Dict = None,
    force: bool = False,
) -> bool:
    classification = flash_result.get("classification", {})
    cls_type = classification.get("type", "Unknown")

    # AI 요약
    ai_summary = None
    try:
        from engines.ai_summarizer import summarize_event
        if news_data:
            ai_summary = summarize_event(ticker, news_data, price_data)
            if ai_summary and ai_summary.get("ai_generated"):
                cls_type = ai_summary.get("classification", cls_type)
    except Exception as e:
        print(f"  AI 요약 실패: {e}")

    change_pct = 0
    intraday_reversal = 0
    if price_data:
        change_pct = price_data.get("change_pct", 0)
        intraday_reversal = price_data.get("intraday_reversal", 0)

    if not force and not should_send_alert(ticker, cls_type, change_pct, intraday_reversal):
        return False

    sent_via = "console"
    tg_msg = format_telegram_alert(ticker, psi_result, flash_result, ai_summary, price_data)
    print(tg_msg)

    try:
        from alerts.telegram import send_telegram
        if send_telegram(tg_msg):
            sent_via = "both"
    except Exception as e:
        print(f"  Telegram: {e}")

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
        change_pct=change_pct,
    )

    print(f"  Alert: {alert_id}")
    return True
