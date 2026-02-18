"""
Stock Sentinel — Alert System v2
AI 요약 + 한국어 알림 + Telegram 발송
"""
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    ALERT_COOLDOWN_MINUTES, NOISE_ALERTS_MAX_PER_DAY,
)
from storage.database import (
    save_alert, get_last_alert_time, count_noise_alerts_today
)


def generate_alert_id(ticker: str) -> str:
    now = datetime.utcnow()
    return f"SEN-{now.strftime('%Y%m%d')}-{ticker}-{now.strftime('%H%M%S')}"


def should_send_alert(ticker: str, classification: str) -> bool:
    # 쿨다운
    last_time = get_last_alert_time(ticker)
    if last_time:
        try:
            last_dt = datetime.fromisoformat(last_time)
            if datetime.utcnow() - last_dt < timedelta(minutes=ALERT_COOLDOWN_MINUTES):
                print(f"  ⏳ 쿨다운 중 ({ticker})")
                return False
        except:
            pass
    # Noise 일일 제한
    if classification == "Noise":
        noise_count = count_noise_alerts_today(ticker)
        if noise_count >= NOISE_ALERTS_MAX_PER_DAY:
            print(f"  🔇 Noise 일일 한도 초과 ({noise_count}/{NOISE_ALERTS_MAX_PER_DAY})")
            return False
    return True


def format_telegram_alert(ticker: str, psi_result: Dict, flash_result: Dict,
                          ai_summary: Dict = None) -> str:
    """Telegram 알림 — AI 요약 중심 한국어 포맷"""
    psi = psi_result.get('psi_total', 0)
    level = psi_result.get('level', 'unknown')
    classification = flash_result.get('classification', {})
    candidates = flash_result.get('reason_candidates', [])
    playbook = flash_result.get('playbook', {})
    details = psi_result.get('details', {})

    # AI 요약 우선, 없으면 규칙 기반
    if ai_summary and ai_summary.get('ai_generated'):
        cls_type = ai_summary.get('classification', classification.get('type', 'Noise'))
        confidence = ai_summary.get('confidence', 0.5)
        headline = ai_summary.get('headline', '')
        detail = ai_summary.get('detail', '')
    else:
        cls_type = classification.get('type', 'Noise')
        confidence = classification.get('confidence', 0.5)
        headline = candidates[0].get('title', '')[:40] if candidates else ''
        detail = classification.get('reasoning', '')

    # 이모지
    cls_e = {"Catalyst": "🟢", "Fracture": "🔴", "Noise": "⚠️"}
    
    # 가격 변동
    price_line = ""
    pf = details.get('price_boost', {}).get('factors', [])
    if pf:
        pct = pf[0].split('→')[0].replace('가격 변동', '').strip()
        price_line = pct

    # ── 메시지 ──
    header = f"{cls_e.get(cls_type, '❓')} *{ticker}*"
    if price_line:
        header += f"  {price_line}"

    msg = f"{header}\n"
    msg += f"━━━━━━━━━━━━━━━━━━━\n"

    # 핵심 요약
    if headline:
        msg += f"📌 *{headline}*\n"
    if detail:
        msg += f"→ {detail}\n"

    msg += f"\n"
    msg += f"{cls_e.get(cls_type, '❓')} {cls_type} ({confidence:.0%})"
    msg += f" | PSI {psi:.1f}\n"

    # 소스
    src_count = ai_summary.get('source_count', len(candidates)) if ai_summary else len(candidates)
    if src_count:
        msg += f"📰 {src_count}개 매체\n"

    # 링크 (1개, 유효한 것만)
    key_url = ""
    if ai_summary and ai_summary.get('key_source'):
        key_url = ai_summary['key_source']
    else:
        for c in candidates:
            u = c.get('source_url', '')
            if u and 'news.google.com/rss' not in u and 'finnhub.io/api' not in u:
                key_url = u
                break
    if key_url:
        msg += f"🔗 {key_url[:80]}\n"

    # 플레이북 (간결)
    pb_id = playbook.get('id', '')
    if pb_id:
        msg += f"\n📖 *{pb_id}*\n"
        for a in playbook.get('actions', [])[:2]:
            msg += f"  ▸ {a}\n"

    msg += f"\n🕐 {datetime.utcnow().strftime('%H:%M UTC')}"
    return msg.strip()


def send_alert(ticker: str, psi_result: Dict, flash_result: Dict,
               trigger_type: str = "psi_critical",
               news_data: List[Dict] = None,
               price_data: Dict = None) -> bool:
    """알림 생성 + AI 요약 + 발송"""
    classification = flash_result.get('classification', {})
    cls_type = classification.get('type', 'Unknown')

    if not should_send_alert(ticker, cls_type):
        return False

    # AI 요약 시도
    ai_summary = None
    try:
        from engines.ai_summarizer import summarize_event
        if news_data:
            ai_summary = summarize_event(ticker, news_data, price_data)
            # AI 분류가 더 정확하면 flash_result 덮어쓰기
            if ai_summary and ai_summary.get('ai_generated'):
                cls_type = ai_summary.get('classification', cls_type)
    except Exception as e:
        print(f"  ⚠️ AI 요약 실패: {e}")

    # Telegram 발송
    sent_via = "console"
    tg_msg = format_telegram_alert(ticker, psi_result, flash_result, ai_summary)
    print(tg_msg)  # 콘솔에도 출력

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
        playbook_id=flash_result.get('playbook', {}).get('id', ''),
        playbook_actions=flash_result.get('playbook', {}).get('actions', []),
        sent_via=sent_via,
    )

    print(f"  💾 Alert: {alert_id}")
    return True
