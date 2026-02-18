"""
Stock Sentinel — Alert System
알림 생성, 포맷팅, 발송 (Console + Telegram)
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
    """고유 알림 ID 생성"""
    now = datetime.utcnow()
    seq = now.strftime("%H%M%S")
    return f"SEN-{now.strftime('%Y%m%d')}-{ticker}-{seq}"


def should_send_alert(ticker: str, classification: str) -> bool:
    """알림 발송 여부 결정 (쿨다운 + 피로 방지)"""
    # 쿨다운 체크
    last_time = get_last_alert_time(ticker)
    if last_time:
        try:
            last_dt = datetime.fromisoformat(last_time)
            if datetime.utcnow() - last_dt < timedelta(minutes=ALERT_COOLDOWN_MINUTES):
                print(f"  ⏳ 쿨다운 중 ({ticker}): {ALERT_COOLDOWN_MINUTES}분 미경과")
                return False
        except:
            pass
    
    # Noise 일일 제한
    if classification == "Noise":
        count = count_noise_alerts_today(ticker)
        if count >= NOISE_ALERTS_MAX_PER_DAY:
            print(f"  🔕 Noise 일일 한도 초과 ({ticker}): {count}/{NOISE_ALERTS_MAX_PER_DAY}")
            return False
    
    return True


def format_console_alert(ticker: str, psi_result: Dict, flash_result: Dict) -> str:
    """콘솔 출력용 포맷"""
    psi = psi_result.get('psi_total', 0)
    level = psi_result.get('level', 'unknown')
    classification = flash_result.get('classification', {})
    candidates = flash_result.get('reason_candidates', [])
    playbook = flash_result.get('playbook', {})
    
    # 등급별 이모지
    level_emoji = {
        "normal": "🟢", "watch": "🟡", "alert": "🟠", "critical": "🔴"
    }
    class_emoji = {
        "Noise": "⚠️", "Fracture": "🔴", "Catalyst": "🟢", "Unknown": "❓"
    }
    
    emoji = level_emoji.get(level, "❓")
    cls_type = classification.get('type', 'Unknown')
    cls_emoji = class_emoji.get(cls_type, "❓")
    
    lines = []
    lines.append("")
    lines.append("╔══════════════════════════════════════════════════════╗")
    lines.append(f"║  {emoji} SENTINEL ALERT — {ticker:6s}                        ║")
    lines.append("╠══════════════════════════════════════════════════════╣")
    lines.append(f"║  Pre-signal Index:  {psi:4.1f} / 10  [{level.upper():8s}]          ║")
    lines.append(f"║  Classification:    {cls_emoji} {cls_type:10s}  ({classification.get('confidence', 0):.0%})     ║")
    lines.append("╠══════════════════════════════════════════════════════╣")
    lines.append(f"║  Options:  {psi_result.get('options_score', 0):4.1f}  │  Attention: {psi_result.get('attention_score', 0):4.1f}  │  Fact: {psi_result.get('fact_score', 0):4.1f}  ║")
    lines.append(f"║  Confluence: +{psi_result.get('confluence_bonus', 0):.1f}  │  Noise: -{psi_result.get('noise_penalty', 0):.1f}               ║")
    lines.append("╠══════════════════════════════════════════════════════╣")
    lines.append("║  🔍 원인 후보 Top-3                                  ║")
    
    for c in candidates[:3]:
        rank = c.get('rank', 0)
        title = c.get('title', '')[:45]
        conf = c.get('confidence', 0)
        etype = c.get('event_type', '')[:8]
        lines.append(f"║  #{rank} [{etype:8s}] {title:45s} {conf:.0%} ║")
    
    lines.append("╠══════════════════════════════════════════════════════╣")
    lines.append(f"║  📖 Playbook: {playbook.get('id', 'N/A'):39s}  ║")
    
    for action in playbook.get('actions', [])[:3]:
        act = action[:52]
        lines.append(f"║    ▸ {act:50s}  ║")
    
    lines.append("╚══════════════════════════════════════════════════════╝")
    
    return "\n".join(lines)


def format_telegram_alert(ticker: str, psi_result: Dict, flash_result: Dict) -> str:
    """Telegram 발송용 마크다운 포맷"""
    psi = psi_result.get('psi_total', 0)
    level = psi_result.get('level', 'unknown')
    classification = flash_result.get('classification', {})
    candidates = flash_result.get('reason_candidates', [])
    playbook = flash_result.get('playbook', {})
    
    cls_type = classification.get('type', 'Unknown')
    emoji_map = {"Noise": "⚠️", "Fracture": "🔴", "Catalyst": "🟢"}
    level_map = {"normal": "🟢", "watch": "🟡", "alert": "🟠", "critical": "🔴"}
    
    msg = f"""
{level_map.get(level, '❓')} *SENTINEL ALERT — {ticker}*
━━━━━━━━━━━━━━━━━━━
📊 *PSI: {psi:.1f}/10* [{level.upper()}]
🏷️ *{emoji_map.get(cls_type, '❓')} {cls_type}* ({classification.get('confidence', 0):.0%})

*점수 구성:*
  Options: {psi_result.get('options_score', 0):.1f} | Attention: {psi_result.get('attention_score', 0):.1f} | Fact: {psi_result.get('fact_score', 0):.1f}

🔍 *원인 후보 Top-3:*"""
    
    for c in candidates[:3]:
        msg += f"\n  {c.get('rank', 0)}. [{c.get('event_type', '')}] {c.get('title', '')[:50]}"
        if c.get('source_url'):
            msg += f"\n     🔗 {c['source_url'][:60]}"
    
    msg += f"\n\n📖 *Playbook: {playbook.get('id', 'N/A')}*"
    for action in playbook.get('actions', [])[:3]:
        msg += f"\n  ▸ {action}"
    
    msg += f"\n\n⏰ 재평가: {playbook.get('reevaluation', 'N/A')}"
    msg += f"\n🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    
    return msg.strip()


def send_alert(ticker: str, psi_result: Dict, flash_result: Dict,
               trigger_type: str = "psi_critical") -> bool:
    """알림 생성 + 발송"""
    classification = flash_result.get('classification', {})
    cls_type = classification.get('type', 'Unknown')
    
    # 발송 여부 결정
    if not should_send_alert(ticker, cls_type):
        return False
    
    # 콘솔 출력
    console_msg = format_console_alert(ticker, psi_result, flash_result)
    print(console_msg)
    
    # Telegram 발송
    sent_via = "console"
    tg_msg = format_telegram_alert(ticker, psi_result, flash_result)
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
    
    print(f"  💾 Alert saved: {alert_id}")
    return True


# ============================================================
# 테스트
# ============================================================
if __name__ == "__main__":
    # 테스트용 더미 데이터
    psi_result = {
        "ticker": "AMAT",
        "psi_total": 9.4,
        "level": "critical",
        "options_score": 8,
        "attention_score": 7,
        "fact_score": 10,
        "confluence_bonus": 1.0,
        "noise_penalty": 0,
    }
    
    flash_result = {
        "classification": {"type": "Catalyst", "confidence": 0.95,
                          "reasoning": "Fact Score 10 + 긍정 키워드"},
        "reason_candidates": [
            {"rank": 1, "title": "AMAT Q1 Beat & Raise", "event_type": "earnings",
             "confidence": 0.95, "source_url": "https://ir.appliedmaterials.com"},
            {"rank": 2, "title": "BIS $252M Settlement", "event_type": "regulatory",
             "confidence": 0.90, "source_url": "https://bis.gov"},
            {"rank": 3, "title": "KeyBanc raises target to $450", "event_type": "analyst",
             "confidence": 0.85, "source_url": ""},
        ],
        "playbook": {
            "id": "PB-CATALYST-01",
            "actions": [
                "추적 강화: 15분 간격 모니터링",
                "관련 종목 ASML, LRCX, KLAC 확인",
                "재평가: 금일 종가 기준",
            ],
            "reevaluation": "종가 (16:00 ET)"
        },
    }
    
    msg = format_console_alert("AMAT", psi_result, flash_result)
    print(msg)
