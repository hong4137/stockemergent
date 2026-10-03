"""
Stock Sentinel — Alert System v5
v3.2: 주말/장외 반복 알림 완전 차단 + 서머타임 자동 대응
v5  : 세션 인식(휴장·지난 세션·시간외 실제 가격), σ 기준 단계,
      같은 날 재알림은 '새로운 움직임'이 있을 때만, 시장 맥락 표시
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
    save_alert, get_last_alert_time, get_last_alert_psi, get_last_alert,
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

PRICE_ALERT_LEVELS = [3, 5, 8, 12]   # σ를 모를 때 쓰는 % 단계
Z_ALERT_LEVELS = [2, 3, 4.5, 6]      # 20일 σ 배수 단계


def _get_current_level(abs_move: float) -> int:
    level = 0
    for threshold in PRICE_ALERT_LEVELS:
        if abs_move >= threshold:
            level += 1
        else:
            break
    return level


def _move_level(move: float, vol20: Optional[float]) -> int:
    """변동 단계. σ를 알면 σ 배수로, 모르면 % 고정 단계로 잰다."""
    if move is None:
        return 0
    if vol20:
        z = abs(move) / vol20
        return sum(1 for c in Z_ALERT_LEVELS if z >= c)
    return _get_current_level(abs(move))


def effective_move(price_data: Optional[Dict]) -> float:
    """알림 근거가 되는 움직임.

    시간외: 종가 이후 움직임 / 정규장: 전일 대비 또는 (더 크면) 장중 반전
    """
    if not price_data:
        return 0.0
    if price_data.get("session") in ("pre", "post"):
        return price_data.get("ext_change_pct") or 0.0
    change = price_data.get("change_pct", 0) or 0.0
    rev = price_data.get("intraday_reversal", 0) or 0.0
    if abs(rev) > abs(change) and abs(rev) >= 3:
        return rev
    return change


def _get_et_now():
    """미국 동부시간 (서머타임 자동 대응)"""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except ImportError:
        # zoneinfo 없으면 -4 (EDT) 사용
        return datetime.now(timezone(timedelta(hours=-4)))


def _et_date(iso_utc: str):
    dt = datetime.fromisoformat(iso_utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_get_et_now().tzinfo).date()


def _is_article_url(url: str) -> bool:
    """링크로 쓸 수 있는 주소인지. 판정 기준은 ai_summarizer.url_quality에 있다."""
    from engines.ai_summarizer import url_quality
    return url_quality(url) > 0


def generate_alert_id(ticker: str) -> str:
    now = datetime.utcnow()
    return f"SEN-{now.strftime('%Y%m%d')}-{ticker}-{now.strftime('%H%M%S')}"


def same_day_previous_alert(ticker: str) -> Optional[Dict]:
    """오늘(ET) 이미 보낸 이 종목의 마지막 알림"""
    last = get_last_alert(ticker)
    if not last:
        return None
    try:
        if _et_date(last["timestamp"]) != _get_et_now().date():
            return None
    except Exception:
        return None
    return last


def should_send_alert(
    ticker: str,
    classification: str,
    change_pct: float = 0,
    intraday_reversal: float = 0,
    price_data: Dict = None,
) -> bool:
    """
    v5 — 알림 발송 판단 (트리거 자체는 상위에서 σ 기준으로 이미 걸러졌다)

    1. 세션 게이트
       - 장외(야간·주말): 차단
       - 정규장인데 오늘 일봉이 없음(휴장일·데이터 지연): 차단
       - 시간외: '종가 이후' 움직임이 10% 이상일 때만.
         예전엔 정규장 일봉(=이미 끝난 세션의 변동)을 읽어서, 9/14 PANW +13.1%를
         그날 저녁 2번, 다음 날 새벽 1번 다시 알렸다.
    2. 최소 간격 15분
    3. 오늘 첫 알림이면 발송
    4. 같은 날 재알림은 '새로운 움직임'이 있을 때만
       - 변동 단계 상승 (σ 2/3/4.5/6배, σ 모르면 3/5/8/12%)
       - 직전 알림 대비 추가 변동 ≥ max(2%p, 1σ) — 되돌림·방향 전환 포함
       시간만 지났다고 같은 이야기를 반복하지 않는다
       (예: PANW 8/21 "AI 보안 기대감에 상승" 하루 5회).
    """
    from collectors.price_collector import market_session, EXT_MOVE

    pd_ = price_data or {}
    if not pd_:
        pd_ = {"change_pct": change_pct, "intraday_reversal": intraday_reversal}
    now_et = _get_et_now()
    session = pd_.get("session") or market_session(now_et)
    vol20 = pd_.get("vol20")

    # ── 1. 세션 게이트 ──
    if session == "closed":
        print("  🌙 장외(야간/주말) — 알림 차단")
        return False
    if session == "regular" and pd_.get("stale"):
        print(f"  🗓 오늘 일봉 없음(휴장/데이터 지연) — 지난 세션"
              f"({pd_.get('session_date')}) 변동으로는 알리지 않음")
        return False
    extended = session in ("pre", "post")
    if extended:
        ext = pd_.get("ext_change_pct")
        if ext is None or abs(ext) < EXT_MOVE:
            shown = f"{ext:+.1f}%" if ext is not None else "확인 불가"
            print(f"  🌅 시간외 — 종가 이후 {shown}, {EXT_MOVE:.0f}% 미만 차단")
            return False

    cur_move = effective_move(pd_)

    # ── 2. 최소 간격 ──
    last = get_last_alert(ticker)
    if last:
        try:
            hours_since = (datetime.utcnow() - datetime.fromisoformat(last["timestamp"])
                           ).total_seconds() / 3600
            if hours_since < 0.25:
                print(f"  ⏳ 쿨다운 15분 미경과 ({ticker})")
                return False
        except Exception:
            pass

    # ── 3. 오늘 첫 알림 ──
    prev = same_day_previous_alert(ticker)
    if not prev:
        print("  ✅ 오늘 첫 알림")
        return True

    prev_extended = prev.get("trigger_type") == "extended_move"
    if extended != prev_extended:
        # 정규장 알림 뒤 첫 시간외 알림(또는 반대) — 잣대가 다르므로 새 정보다
        print("  ✅ 세션 전환 후 첫 알림")
        return True

    # ── 4. 같은 날 재알림 ──
    prev_move = prev.get("alert_move")
    if prev_move is None:  # v5 이전 알림
        prev_move = prev.get("change_pct") or 0.0
    cur_level = _move_level(cur_move, vol20)
    prev_level = _move_level(prev_move, vol20)
    if cur_level > prev_level:
        print(f"  📊 단계 상승 {prev_level}→{cur_level} ({cur_move:+.1f}%)")
        return True

    # 가격 위치 비교: 정규장은 전일 대비 변동끼리, 시간외는 시간외 변동끼리
    cur_pos = cur_move if extended else (pd_.get("change_pct") or 0.0)
    prev_pos = prev_move if extended else (prev.get("change_pct") or 0.0)
    step = max(2.0, vol20 or 0.0)
    if abs(cur_pos - prev_pos) >= step:
        print(f"  📈 직전 알림 대비 추가 변동 {prev_pos:+.1f}% → {cur_pos:+.1f}% (기준 {step:.1f}%p)")
        return True

    if classification in ("Noise", "노이즈"):
        if count_noise_alerts_today(ticker) >= NOISE_ALERTS_MAX_PER_DAY:
            print("  🔇 노이즈 일일 한도")
            return False

    print(f"  ⏸ 오늘 이미 알림 — 새로운 움직임 없음 ({prev_pos:+.1f}% → {cur_pos:+.1f}%)")
    return False


# ── 알림 포맷 ──

def format_telegram_alert(
    ticker: str,
    psi_result: Dict,
    flash_result: Dict,
    ai_summary: Dict = None,
    price_data: Dict = None,
    market_context: Dict = None,
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
        z = price_data.get("z_change")
        if price_data.get("session") in ("pre", "post") and price_data.get("ext_change_pct") is not None:
            label = "프리마켓" if price_data["session"] == "pre" else "시간외"
            price_line = f"{label} {price_data['ext_change_pct']:+.1f}% (정규장 {pct:+.1f}%)"
        else:
            if abs(pct) >= 0.5:
                price_line = f"{pct:+.1f}%"
                if z is not None:
                    price_line += f" ({abs(z):.1f}σ)"
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

    # 섹터 전체가 움직인 건지, 이 종목만 움직인 건지 한눈에 보이게
    if market_context:
        from collectors.market_context import format_context_for_alert
        ctx_line = format_context_for_alert(
            (price_data or {}).get("change_pct"), market_context
        )
        if ctx_line:
            msg += ctx_line + "\n"

    src_count = (
        ai_summary.get("source_count", len(candidates))
        if ai_summary
        else len(candidates)
    )
    if src_count:
        msg += f"📰 관련 기사 {src_count}건\n"

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
    market_context: Dict = None,
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
    if not force and not should_send_alert(
        ticker, cls_type, change_pct, intraday_reversal, price_data=price_data
    ):
        return False

    # 여기서부터는 발송이 확정된 건이다.
    # 오늘 이미 보낸 알림이 있으면 AI에게 알려서 같은 설명을 반복하지 않게 한다.
    prev = same_day_previous_alert(ticker)
    prev_alert = None
    if prev and prev.get("headline"):
        try:
            hours = (datetime.utcnow() - datetime.fromisoformat(prev["timestamp"])
                     ).total_seconds() / 3600
        except Exception:
            hours = None
        prev_alert = {"headline": prev["headline"], "hours_ago": hours,
                      "change_pct": prev.get("change_pct")}

    ai_summary = None
    try:
        from engines.ai_summarizer import summarize_event
        if news_data:
            ai_summary = summarize_event(
                ticker, news_data, price_data,
                market_context=market_context, prev_alert=prev_alert,
            )
            if ai_summary and ai_summary.get("ai_generated"):
                cls_type = ai_summary.get("classification", cls_type)
    except Exception as e:
        print(f"  ❌ AI 요약 호출 실패: {type(e).__name__}: {e}")

    sent_via = "console"
    tg_msg = format_telegram_alert(
        ticker, psi_result, flash_result, ai_summary, price_data, market_context
    )
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
        z_score=(price_data or {}).get("z_change"),
        session=(price_data or {}).get("session", ""),
        market_context=market_context,
        alert_move=round(effective_move(price_data), 2) if price_data else None,
    )

    print(f"  Alert: {alert_id}")
    return True
