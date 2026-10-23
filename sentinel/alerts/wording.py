"""
Stock Sentinel — 사람이 읽는 문구

텔레그램에 나가는 숫자·용어를 일반 투자자가 바로 이해하는 말로 바꾼다.
내부 계산(σ, PSI, 0.85 같은 확신도 수치)은 DB와 로그에만 남기고 알림에는 쓰지 않는다.

  예) "+6.7% (2.0σ) (저점대비 +7.8%)"
   →  "+6.7%" / "평소 하루 움직임(±3.3%)의 2배 · 장중 저점에서 7.8% 반등"
"""
from datetime import datetime
from typing import Dict, Optional

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except ImportError:  # pragma: no cover
    from datetime import timedelta, timezone
    KST = timezone(timedelta(hours=9))

LAYER_KR = {
    "공시": "회사 공시",
    "평가": "증권사 의견",
    "예고": "예정된 일정(실적 발표 등)",
    "기사": "언론 보도",
    "속보": "속보",
    "시세": "주가 흐름으로 추정",
}

SCOPE_KR = {
    "시장": "시장 전체가 함께 움직임",
    "섹터": "업종 전체가 함께 움직임",
    "섹터+개별": "업종 흐름 + 이 종목만의 요인",
    "개별": "이 종목만 움직임",
}


def _times(x: float) -> str:
    """2.0 → '2배', 2.4 → '2.4배'"""
    x = abs(x)
    return f"{round(x)}배" if abs(x - round(x)) < 0.05 else f"{x:.1f}배"


def price_header(price_data: Optional[Dict]) -> str:
    """헤더 옆 숫자 하나: '+6.7%' 또는 '+12.0% (장 마감 후)'"""
    if not price_data:
        return ""
    session = price_data.get("session")
    ext = price_data.get("ext_change_pct")
    if session in ("pre", "post") and ext is not None:
        return f"{ext:+.1f}% ({'장 시작 전' if session == 'pre' else '장 마감 후'})"
    pct = price_data.get("change_pct", 0) or 0
    return f"{pct:+.1f}%"


def price_explainer(price_data: Optional[Dict]) -> str:
    """헤더 아래 한 줄: 이 움직임이 평소에 비해 얼마나 큰지, 장중에 어떻게 움직였는지"""
    if not price_data:
        return ""
    parts = []
    session = price_data.get("session")
    if session in ("pre", "post") and price_data.get("ext_change_pct") is not None:
        pct = price_data.get("change_pct", 0) or 0
        parts.append(f"정규장은 {pct:+.1f}%로 마감")
        return " · ".join(parts)

    z = price_data.get("z_change")
    vol = price_data.get("vol20")
    if z is not None and vol:
        if abs(z) >= 1.5:
            parts.append(f"평소 하루 움직임(±{vol:.1f}%)의 {_times(z)}")
        else:
            parts.append(f"평소 하루 움직임(±{vol:.1f}%) 수준")

    rev = price_data.get("intraday_reversal", 0) or 0
    if abs(rev) >= 3:
        parts.append(f"장중 고점에서 {abs(rev):.1f}% 밀림" if rev < 0
                     else f"장중 저점에서 {rev:.1f}% 반등")
    return " · ".join(parts)


def basis_line(layer: str, scope: str) -> str:
    """🧭 근거: 언론 보도 · 업종 전체가 함께 움직임"""
    if not layer:
        return ""
    line = f"🧭 근거: {LAYER_KR.get(layer, layer)}"
    if scope:
        line += f" · {SCOPE_KR.get(scope, scope)}"
    return line


def verdict_line(cls_emoji: str, cls_kr: str, confidence_label: str = "") -> str:
    """🟢 호재 · 확신도 중간  (수치 확신도 85% 같은 가짜 정밀도는 쓰지 않는다)"""
    line = f"{cls_emoji} {cls_kr}"
    if confidence_label:
        line += f" · 확신도 {confidence_label}"
    return line


def time_line(now_et: datetime) -> str:
    """🕐 미 동부 10:53 · 한국 23:53"""
    kst = now_et.astimezone(KST)
    day = "" if kst.date() == now_et.date() else f"{kst.month}/{kst.day} "
    return f"🕐 미 동부 {now_et:%H:%M} · 한국 {day}{kst:%H:%M}"
