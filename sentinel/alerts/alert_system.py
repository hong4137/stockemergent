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
from alerts.wording import price_header, price_explainer, basis_line, verdict_line, time_line


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

# 알림 아래에 붙는 '확인해 볼 것'. 전문 용어 없이, 휴대폰에서 바로 읽히게 쓴다.
# (예전 문구: "섹터 로테이션 / 개별 펀더멘털 변화 없으면 대응 불필요", "10b5-1", "13D/13G")
PLAYBOOKS = {
    "Catalyst": {
        "id": "오르는 중",
        "actions": [
            "이 종목 움직임을 조금 더 지켜보기",
            "같은 업종 종목들도 함께 오르는지 보기",
        ],
    },
    "Fracture": {
        "id": "내리는 중",
        "actions": [
            "보유 중이라면 비중과 손절 기준 다시 보기",
            "같은 업종 종목들도 함께 내리는지 보기",
        ],
    },
    "Noise": {
        "id": "평소 수준의 움직임",
        "actions": [
            "근거가 될 소식이 실제로 있는지 다시 보기",
            "조금 뒤 추세가 이어지는지 확인하기",
        ],
    },
}

# 원인의 종류별 체크리스트. AI가 판정한 event_type이 있으면 이쪽을 우선 쓴다.
EVENT_PLAYBOOKS = {
    "earnings": {
        "id": "실적 발표",
        "actions": [
            "시장 예상보다 매출·이익이 좋았는지 보기",
            "다음 분기 전망을 올렸는지 내렸는지 보기 — 실적이 좋아도 전망을 낮추면 주가는 빠진다",
        ],
    },
    "regulatory": {
        "id": "규제·정책",
        "actions": [
            "언제부터, 어디까지 적용되는지 보기",
            "같은 업종 다른 회사들도 영향을 받는지 보기",
        ],
    },
    "geopolitical": {
        "id": "국제 정세",
        "actions": [
            "이 회사만의 문제가 아니다 — 업종 전체 흐름 보기",
            "시장보다 유독 더 빠졌는지 보기",
        ],
    },
    "macro": {
        "id": "시장 전체 흐름",
        "actions": [
            "이 회사만의 문제가 아니다 — 금리·환율·지수 흐름 보기",
            "업종 전체가 움직인 건지, 이 종목만 움직인 건지 구분하기",
        ],
    },
    "analyst": {
        "id": "증권사 의견 변경",
        "actions": [
            "목표가를 얼마나 바꿨는지, 매수·매도 의견이 바뀌었는지 보기",
            "실적 전망이 바뀐 건지, 눈높이만 조정한 건지 보기",
        ],
    },
    "partnership": {
        "id": "계약·제휴",
        "actions": [
            "계약 규모와 기간 보기",
            "매출에 언제 반영되는지 보기 — 당장인지 몇 년 뒤인지",
        ],
    },
    "product": {
        "id": "제품·기술",
        "actions": [
            "출시나 생산이 언제인지 보기",
            "경쟁사보다 앞서는 내용인지 보기",
        ],
    },
    "insider": {
        "id": "임원 주식 매매",
        "actions": [
            "미리 정해 둔 정기 매도인지 보기 — 대부분 큰 의미 없다",
            "가진 주식 중 얼마나 팔았는지 보기",
        ],
    },
    "institutional": {
        "id": "큰손 투자자 움직임",
        "actions": [
            "얼마나 샀는지, 경영에 목소리를 내겠다는 건지 보기",
            "처음 사들인 건지, 원래 갖고 있다가 더 산 건지 보기",
        ],
    },
    "controversy": {
        "id": "여론·평판 문제",
        "actions": [
            "실적에 실제로 영향을 줄 일인지 보기 — 대부분 단기 심리",
            "소송이나 규제로 번질 수 있는지 보기",
        ],
    },
    "sector_rotation": {
        "id": "업종 전체의 움직임",
        "actions": [
            "같은 업종 종목들이 함께 움직였는지 보기",
            "이 회사만의 소식이 없다면 급하게 대응할 필요는 적다",
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

    # 가격: 헤더엔 숫자 하나, 그 아래 '평소보다 얼마나 큰 움직임인지'를 말로.
    # (예전 표기 "+6.7% (2.0σ) (저점대비 +7.8%)"는 σ를 아는 사람만 읽을 수 있었다)
    header = f"{cls_emoji} *{ticker}*"
    price_line = price_header(price_data)
    if price_line:
        header += f"  {price_line}"

    msg = f"{header}\n"
    explainer = price_explainer(price_data)
    if explainer:
        msg += f"{explainer}\n"
    msg += "━━━━━━━━━━━━━━━━━━━\n"

    if headline:
        msg += f"📌 *{sanitize_title(headline)}*\n"
    if detail_text:
        msg += f"→ {_indent(sanitize_title(detail_text))}\n"
    # 근거의 층 — 공시·증권사 의견이면 사실·권위, 기사·속보면 보도, 시세면 업종 동반 추정

    msg += "\n"
    # 확신도는 AI 판정의 높음/중간/낮음을 그대로 쓴다. 85% 같은 수치는 가짜 정밀도이고,
    # PSI는 내부 점수라 알림을 받는 사람에게 의미가 없다(로그·DB에는 남는다).
    conf_label = (ai_summary or {}).get("cause_confidence", "") if ai_ok else ""
    msg += verdict_line(cls_emoji, cls_kr, conf_label) + "\n"
    if ai_ok and ai_summary.get("cause_layer"):
        msg += basis_line(ai_summary["cause_layer"], ai_summary.get("cause_scope", "")) + "\n"

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

    msg += f"\n📖 *{playbook['id']}* — 확인해 볼 것\n"
    for a in playbook["actions"]:
        msg += f"  ▸ {a}\n"

    # AI 요약이 실패해 규칙 기반으로 나간 건은 반드시 표시한다.
    # 표시가 없으면 모델/파라미터 문제로 품질이 떨어져도 몇 주씩 묻힌다.
    if ai_summary and not ai_ok:
        reason = ai_summary.get("fallback_reason", "")
        # 문구는 바꿔도 되지만 '⚠️ AI 요약 실패' 머리말은 유지한다 (CLAUDE.md, 운영 점검에서 이 문자열을 찾는다)
        msg += (f"\n⚠️ AI 요약 실패 — 원인 분석이 안 돼 위 설명은 자동 문구입니다"
                f"{f' ({reason})' if reason else ''}\n")

    msg += "\n" + time_line(_get_et_now())
    return msg.strip()


def _indent(text: str) -> str:
    """'→ ' 다음 줄들을 같은 칸에 맞춘다 (보조 요인이 둘째 줄로 온다)"""
    return "\n   ".join(line.strip() for line in (text or "").splitlines() if line.strip())


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
        cause_verdict=ai.get("cause_verdict", ""),
        cause_layer=ai.get("cause_layer", ""),
        cause_scope=ai.get("cause_scope", ""),
    )

    print(f"  Alert: {alert_id}")
    return True


# ── 장 마감 후 재판정 ──
# 알림 시점에는 원인 기사가 아직 없는 경우가 많다. 하루치 증거가 모인 저녁에 다시 판정해
# 원인이 새로 확인되거나 더 단단한 근거로 바뀌었을 때만 '원인 업데이트'를 보낸다.
# 백테스트: 같은 로직을 장 마감 후 정보로 돌리면 엄격 정답률이 알림 시점보다 6~12%p 높았다.

STRONG_LAYERS = {"공시", "평가", "예고"}


def should_send_followup(old: Dict, new: Dict) -> bool:
    if not new or not new.get("ai_generated"):
        return False
    if new.get("cause_verdict") != "원인 있음":
        return False
    same = (new.get("headline") or "").strip() == (old.get("headline") or "").strip()
    if not old.get("ai_generated"):
        return True                                   # 알림 땐 AI 요약이 실패했다
    if old.get("cause_verdict") == "원인 미확인":
        return True                                   # 원인을 새로 찾았다
    if same:
        return False
    if (old.get("confidence") or 0) < 0.5 and new.get("confidence", 0) >= 0.65:
        return True                                   # 막연했던 설명이 확실해졌다
    if new.get("cause_layer") in STRONG_LAYERS and old.get("cause_layer") not in STRONG_LAYERS:
        return True                                   # 공시·증권사·일정으로 근거가 단단해졌다
    return False


def format_followup(old: Dict, new: Dict, price_data: Dict = None) -> str:
    pct = (price_data or {}).get("change_pct")
    head = f"🔁 *{old['ticker']}* 원인 업데이트" + (f"  (종가 {pct:+.1f}%)" if pct is not None else "")
    msg = f"{head}\n━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📌 *{sanitize_title(new['headline'])}*\n→ {_indent(sanitize_title(new['detail']))}\n"
    line = basis_line(new.get("cause_layer", ""), new.get("cause_scope", ""))
    if line:
        msg += line + (f" · 확신도 {new['cause_confidence']}" if new.get("cause_confidence") else "") + "\n"
    if old.get("headline"):
        msg += f"\n낮에 보낸 알림의 설명: {sanitize_title(old['headline'])}\n"
    if new.get("key_source"):
        msg += f"🔗 {new['key_source'][:80]}\n"
    msg += "\n" + time_line(_get_et_now())
    return msg.strip()


def run_followup(old: Dict, news_data: List[Dict], price_data: Dict = None,
                 market_context: Dict = None) -> bool:
    """알림 1건을 재판정하고, 바뀌었으면 보낸다. 결과는 어느 쪽이든 DB에 남긴다."""
    from engines.ai_summarizer import summarize_event
    from storage.database import save_followup
    new = summarize_event(old["ticker"], news_data, price_data, market_context=market_context,
                          prev_alert={"headline": old.get("headline"), "change_pct": old.get("change_pct")},
                          followup=True)
    send = should_send_followup(old, new)
    if send:
        from alerts.telegram import send_telegram
        msg = format_followup(old, new, price_data)
        print(msg)
        send = bool(send_telegram(msg))
    else:
        print(f"  ⏭️ {old['ticker']} 재판정 — 설명 변화 없음 ({(new or {}).get('headline', '')})")
    save_followup(old["alert_id"], (new or {}).get("headline", ""), (new or {}).get("detail", ""), send)
    return send
