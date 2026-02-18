"""
Stock Sentinel — Alert System v3
AI 분류 → 플레이북 연동 + 전체 한글화
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

# AI 분류 기반 플레이북 (한글)
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

def _is_article_url(url: str) -> bool:
    """실제 기사 URL인지 검증"""
    if not url:
        return False
    bad = ['news.google.com/rss', 'finnhub.io/api']
    if any(p in url for p in bad):
        return False
    path = urlparse(url).path.strip('/')
    if not path or len(path) < 3:
        return False
    return True


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
        noise_count = count_noise_alerts_today(ticker)
        if noise_count >= NOISE_ALERTS_MAX_PER_DAY:
            print(f"  🔇 노이즈 일일 한도 초과")
            return False
    return True


# ── 알림 포맷 ──

def format_telegram_alert(ticker: str, psi_result: Dict, flash_result: Dict,
                          ai_summary: Dict = None) -> str:
    """Telegram 알림 — AI 분류 기반, 전체 한글"""
    psi = psi_result.get('psi_total', 0)
    level = psi_result.get('level', 'unknown')
    details = psi_result.get('details', {})
    candidates = flash_result.get('reason_candidates', [])
    rule_cls = flash_result.get('classification', {})

    # ── 분류 결정: AI 우선, 폴백은 규칙 기반 ──
    if ai_summary and ai_summary.get('ai_generated'):
        cls_type = ai_summary.get('classification', 'Noise')
        confidence = ai_summary.get('confidence', 0.5)
        headline = ai_summary.get('headline', '')
        detail_text = ai_summary.get('detail', '')
    else:
        cls_type = rule_cls.get('type', 'Noise')
        confidence = rule_cls.get('confidence', 0.5)
        headline = candidates[0].get('title', '')[:40] if candidates else ''
        detail_text = rule_cls.get('reasoning', '')

    # 분류를 한글로
    cls_kr = CLS_KR.get(cls_type, cls_type)
    cls_emoji = CLS_EMOJI.get(cls_type, '❓')

    # ── 플레이북: AI 분류 기반 ──
    playbook = PLAYBOOKS.get(cls_type, PLAYBOOKS["Noise"])

    # 가격 변동
    price_line = ""
    pf = details.get('price_boost', {}).get('factors', [])
    if pf:
        pct = pf[0].split('→')[0].replace('가격 변동', '').strip()
        price_line = pct

    # ── 메시지 조립 ──
    header = f"{cls_emoji} *{ticker}*"
    if price_line:
        header += f"  {price_line}"

    msg = f"{header}\n"
    msg += f"━━━━━━━━━━━━━━━━━━━\n"

    if headline:
        msg += f"📌 *{headline}*\n"
    if detail_text:
        msg += f"→ {detail_text}\n"

    msg += f"\n"
    msg += f"{cls_emoji} {cls_kr} ({confidence:.0%}) | PSI {psi:.1f}\n"

    # 소스 수
    src_count = ai_summary.get('source_count', len(candidates)) if ai_summary else len(candidates)
    if src_count:
        msg += f"📰 {src_count}개 매체\n"

    # 링크 (유효한 것 1개만)
    key_url = ""
    if ai_summary and ai_summary.get('key_source'):
        key_url = ai_summary['key_source']
    if not key_url:
        for c in candidates:
            u = c.get('source_url', '')
            if _is_article_url(u):
                key_url = u
                break
    if key_url:
        msg += f"🔗 {key_url[:80]}\n"

    # 플레이북 (AI 분류 기반)
    msg += f"\n📖 *{playbook['id']}*\n"
    for a in playbook['actions']:
        msg += f"  ▸ {a}\n"

    msg += f"\n🕐 {datetime.utcnow().strftime('%H:%M UTC')}"
    return msg.strip()


# ── 발송 ──

def send_alert(ticker: str, psi_result: Dict, flash_result: Dict,
               trigger_type: str = "psi_critical",
               news_data: List[Dict] = None,
               price_data: Dict = None,
               force: bool = False) -> bool:
    """알림 생성 + AI 요약 + 발송"""
    classification = flash_result.get('classification', {})
    cls_type = classification.get('type', 'Unknown')

    # AI 요약 시도
    ai_summary = None
    try:
        from engines.ai_summarizer import summarize_event
        if news_data:
            ai_summary = summarize_event(ticker, news_data, price_data)
            if ai_summary and ai_summary.get('ai_generated'):
                cls_type = ai_summary.get('classification', cls_type)
    except Exception as e:
        print(f"  ⚠️ AI 요약 실패: {e}")

    # 발송 여부 (force면 무조건 발송)
    if not force and not should_send_alert(ticker, cls_type):
        return False

    # Telegram 발송
    sent_via = "console"
    tg_msg = format_telegram_alert(ticker, psi_result, flash_result, ai_summary)
    print(tg_msg)

    try:
        from alerts.telegram import send_telegram
        if send_telegram(tg_msg):
            sent_via = "both"
    except Exception as e:
        print(f"  ⚠️ Telegram: {e}")

    # DB 저장
    alert_id = generate_alert_id(ticker)
    save_alert(
        alert_id=alert_id,
        ticker=ticker,
        timestamp=datetime.utcnow().isoformat(),
        trigger_type=trigger_type,
        psi_total=psi_result.get('psi_total', 0),
        classification=cls_type,
        confidence=classification.get('confidence', 0),
        reason_candidates=flash_result.get('reason_candidates', []),
        playbook_id=PLAYBOOKS.get(cls_type, PLAYBOOKS["Noise"])['id'],
        playbook_actions=PLAYBOOKS.get(cls_type, PLAYBOOKS["Noise"])['actions'],
        sent_via=sent_via,
    )

    print(f"  💾 Alert: {alert_id}")
    return True
