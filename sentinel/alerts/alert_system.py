"""
Stock Sentinel — Alert System v3.2
v3.2: 주말/장외 반복 알림 완전 차단 + 서머타임 자동 대응
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

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
from alerts.telegram import sanitize_title


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

# 이벤트 성격별 체크리스트. 분류(호재/악재)만으로는 "추적 강화" 같은 빈 문구밖에
# 못 주므로, AI가 판정한 event_type이 있으면 그쪽을 우선 쓴다.
EVENT_PLAYBOOKS = {
    "earnings": {
        "id": "실적 발표",
        "actions": [
            "컨센서스 대비 매출/EPS 확인",
            "가이던스 방향 확인 — beat했어도 가이던스 하향이면 악재",
        ],
    },
    "regulatory": {
        "id": "규제·정책",
        "actions": [
            "적용 시점과 대상 범위 확인",
            "동종업체 동반 영향 여부 확인",
        ],
    },
    "geopolitical": {
        "id": "지정학 이슈",
        "actions": [
            "개별 종목 이슈 아님 — 섹터 전반 확인",
            "지수 대비 상대강도로 과매도 여부 판단",
        ],
    },
    "macro": {
        "id": "매크로 요인",
        "actions": [
            "개별 종목 이슈 아님 — 금리/환율/지수 확인",
            "섹터 로테이션인지 개별 악재인지 구분",
        ],
    },
    "analyst": {
        "id": "애널리스트 액션",
        "actions": [
            "목표주가 변경폭과 투자의견 확인",
            "펀더멘털 변화 없는 단순 리레이팅인지 확인",
        ],
    },
    "partnership": {
        "id": "계약·파트너십",
        "actions": [
            "계약 규모와 기간 확인",
            "매출 반영 시점 확인 — 즉시인지 수년 뒤인지",
        ],
    },
    "product": {
        "id": "제품·기술",
        "actions": [
            "출시/양산 일정 확인",
            "경쟁사 대비 포지션 변화 확인",
        ],
    },
    "insider": {
        "id": "내부자 거래",
        "actions": [
            "10b5-1 사전계획 매도인지 확인 — 대부분 신호 아님",
            "보유분 대비 매도 비중 확인",
        ],
    },
    "institutional": {
        "id": "기관·행동주의 수급",
        "actions": [
            "지분 규모와 13D/13G 구분 확인 — 13D는 경영 개입 의도",
            "해당 기관의 과거 보유 이력 확인 — 신규 진입인지 추가 매수인지",
        ],
    },
    "controversy": {
        "id": "여론·평판 이슈",
        "actions": [
            "실적에 영향을 주는 사안인지 구분 — 대부분 단기 심리",
            "규제·소송으로 번질 소지가 있는지 확인",
        ],
    },
    "sector_rotation": {
        "id": "섹터 로테이션",
        "actions": [
            "동일 섹터 종목 동반 움직임 확인",
            "개별 펀더멘털 변화 없으면 대응 불필요",
        ],
    },
}


def resolve_playbook(cls_type: str, event_type: str = "") -> Dict:
    """event_type이 있으면 상황별 체크리스트를, 없으면 분류 기본값을 쓴다."""
    if event_type and event_type in EVENT_PLAYBOOKS:
        return EVENT_PLAYBOOKS[event_type]
    return PLAYBOOKS.get(cls_type, PLAYBOOKS["Noise"])

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
    """링크로 쓸 수 있는 주소인지. 판정 기준은 ai_summarizer.url_quality에 있다."""
    from engines.ai_summarizer import url_quality
    return url_quality(url) > 0


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

    ai_ok = bool(ai_summary and ai_summary.get("ai_generated"))
    event_type = (ai_summary or {}).get("event_type", "")

    if ai_ok:
        cls_type = ai_summary.get("classification", "Noise")
        confidence = ai_summary.get("confidence", 0.5)
        headline = ai_summary.get("headline", "")
        detail_text = ai_summary.get("detail", "")
    elif ai_summary:
        # 폴백 결과도 headline/detail을 채워서 온다
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
    playbook = resolve_playbook(cls_type, event_type)

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
        from engines.ai_summarizer import url_quality
        usable = [c.get("source_url", "") for c in candidates]
        usable = [u for u in usable if url_quality(u) > 0]
        if usable:
            key_url = max(usable, key=url_quality)
    if key_url:
        msg += f"🔗 {key_url[:80]}\n"

    # 근거 기사 — AI 판단의 출처를 직접 보여준다.
    # 요약이 이상할 때 원인이 모델인지 입력인지 바로 구분할 수 있다.
    shown = 0
    for c in candidates:
        title = sanitize_title(c.get("title", ""))
        if not title:
            continue
        msg += f"\n  · {title[:60]}"
        url = c.get("source_url", "")
        if _is_article_url(url) and url != key_url:
            msg += f"\n    {url[:70]}"
        shown += 1
        if shown >= 2:
            break
    if shown:
        msg += "\n"

    msg += f"\n📖 *{playbook['id']}*\n"
    for a in playbook["actions"]:
        msg += f"  ▸ {a}\n"

    # AI 요약이 실패해 규칙 기반으로 나간 건은 반드시 표시한다.
    # 표시가 없으면 모델/파라미터 문제로 품질이 떨어져도 몇 주씩 묻힌다.
    if ai_summary and not ai_ok:
        reason = ai_summary.get("fallback_reason", "")
        msg += f"\n⚠️ AI 요약 실패 — 규칙 기반 문구{f' ({reason})' if reason else ''}\n"

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

    change_pct = 0
    intraday_reversal = 0
    if price_data:
        change_pct = price_data.get("change_pct", 0)
        intraday_reversal = price_data.get("intraday_reversal", 0)

    # 발송 여부를 먼저 판정한다. AI 요약을 앞에서 돌리면 주말/쿨다운으로 차단될
    # 건에도 OpenAI 비용이 그대로 나간다. 게이트에 쓰이는 분류는 규칙 기반으로 충분하다
    # (AI 분류는 Noise 일일한도 판정에만 쓰였고, Noise는 전체의 0.1%다).
    if not force and not should_send_alert(ticker, cls_type, change_pct, intraday_reversal):
        return False

    # 여기서부터는 발송이 확정된 건이다.
    ai_summary = None
    try:
        from engines.ai_summarizer import summarize_event
        if news_data:
            ai_summary = summarize_event(ticker, news_data, price_data)
            if ai_summary and ai_summary.get("ai_generated"):
                cls_type = ai_summary.get("classification", cls_type)
    except Exception as e:
        print(f"  ❌ AI 요약 호출 실패: {type(e).__name__}: {e}")

    sent_via = "console"
    tg_msg = format_telegram_alert(ticker, psi_result, flash_result, ai_summary, price_data)
    print(tg_msg)

    try:
        from alerts.telegram import send_telegram
        if send_telegram(tg_msg):
            sent_via = "both"
    except Exception as e:
        print(f"  Telegram: {e}")

    ai = ai_summary or {}
    event_type = ai.get("event_type", "")
    playbook = resolve_playbook(cls_type, event_type)

    alert_id = generate_alert_id(ticker)
    save_alert(
        alert_id=alert_id,
        ticker=ticker,
        timestamp=datetime.utcnow().isoformat(),
        trigger_type=trigger_type,
        psi_total=psi_result.get("psi_total", 0),
        classification=cls_type,
        confidence=ai.get("confidence", classification.get("confidence", 0)),
        reason_candidates=flash_result.get("reason_candidates", []),
        playbook_id=playbook["id"],
        playbook_actions=playbook["actions"],
        sent_via=sent_via,
        change_pct=change_pct,
        # ── 실제로 발송된 내용 (사후 검증용) ──
        headline=ai.get("headline", ""),
        detail=ai.get("detail", ""),
        event_type=event_type,
        ai_generated=ai.get("ai_generated", False),
        key_source=ai.get("key_source", ""),
        model=ai.get("model", ""),
    )

    print(f"  Alert: {alert_id}")
    return True
