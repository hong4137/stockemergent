"""
Stock Sentinel — Price Collector v2

v2에서 바뀐 것
- 세션 인식: 지금이 정규장/프리/애프터/장외인지, 마지막 일봉이 '오늘' 것인지 판별한다.
  yfinance 일봉의 마지막 줄은 정규장 기준이라, 장 마감 후·다음 날 새벽·휴장일에도
  직전 세션의 변동률을 그대로 돌려준다. 이걸 '지금 움직임'으로 착각해
  PANW +13.1%(9/14)를 그날 저녁 2번, 다음 날 새벽 1번 다시 알렸다.
- 시간외 가격: 정규장 밖에서는 1분봉(prepost)으로 '종가 이후 움직임'을 따로 잰다.
- 변동성 정규화: 20일 일간 수익률 표준편차(σ)와 평균 일중 변동폭(ATR%).
  ±3% 고정 기준은 하루 변동이 큰 NET에겐 일상, AMZN에겐 이례적이었다
  (7주간 알림 NET 64건 vs AMZN 3건).
- 거래량 페이스: 장중에는 '지금 시각까지의 예상 거래량' 대비로 비교한다.
  하루 평균과 반나절 누적을 비교하면 오후에도 0.5배처럼 보여 AI가
  "거래량이 낮아 상승 강도가 제한적"이라는 틀린 해석을 했다.
"""
from datetime import datetime, timezone, time as dtime
from typing import Optional

import yfinance as yf

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except ImportError:  # pragma: no cover
    from datetime import timedelta
    ET = timezone(timedelta(hours=-4))

REG_OPEN, REG_CLOSE = dtime(9, 30), dtime(16, 0)
PRE_OPEN, POST_CLOSE = dtime(4, 0), dtime(20, 0)

# ── 트리거 기준 ──
Z_MOVE = 2.0        # 20일 σ의 2배 이상 움직이면 이상 징후
MOVE_FLOOR = 2.0    # 단, 저변동 종목이 1%대에서 울리지 않도록 최소 2%
MOVE_ABS = 8.0      # σ와 무관하게 8% 이상은 무조건
REV_FLOOR = 3.0     # 장중 반전 최소 3%p
REV_ATR = 1.0       # 그리고 평소 하루 변동폭(ATR) 이상이어야 함
VOL_SPIKE = 3.0     # 거래량 페이스 3배
VOL_SPIKE_Z = 1.0   # + 1σ 이상 움직임
EXT_MOVE = 10.0     # 시간외는 10% 이상 급변만

# 누적 거래량 곡선(개장 후 분 → 하루 거래량 대비 누적 비율). U자형 근사.
_VOLUME_CURVE = [
    (0, 0.0), (30, 0.15), (60, 0.24), (120, 0.37), (180, 0.48),
    (240, 0.58), (300, 0.69), (360, 0.83), (390, 1.0),
]


def market_session(now_et: datetime = None) -> str:
    """'regular' / 'pre' / 'post' / 'closed' (시계 기준. 휴장일 판별은 일봉으로 한다)"""
    now_et = now_et or datetime.now(ET)
    if now_et.weekday() >= 5:
        return "closed"
    t = now_et.time()
    if REG_OPEN <= t < REG_CLOSE:
        return "regular"
    if PRE_OPEN <= t < REG_OPEN:
        return "pre"
    if REG_CLOSE <= t < POST_CLOSE:
        return "post"
    return "closed"


def _expected_volume_fraction(now_et: datetime) -> float:
    minutes = (now_et.hour * 60 + now_et.minute) - (9 * 60 + 30)
    minutes = max(0, min(390, minutes))
    for (m0, f0), (m1, f1) in zip(_VOLUME_CURVE, _VOLUME_CURVE[1:]):
        if m0 <= minutes <= m1:
            frac = f0 + (f1 - f0) * (minutes - m0) / (m1 - m0)
            # 개장 직후엔 분모가 0에 가까워 배율이 폭주하므로 하한을 둔다
            return max(frac, 0.10)
    return 1.0


def _bar_date(idx) -> "datetime.date":
    ts = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
    if ts.tzinfo is not None:
        ts = ts.astimezone(ET)
    return ts.date()


def _extended_price(stock) -> Optional[float]:
    """시간외 포함 1분봉의 마지막 가격"""
    try:
        m = stock.history(period="2d", interval="1m", prepost=True)
        closes = m["Close"].dropna()
        if closes.empty:
            return None
        return float(closes.iloc[-1])
    except Exception as e:
        print(f"  ⚠️ 시간외 가격 조회 실패: {e}")
        return None


def collect_price_yfinance(ticker: str, now_et: datetime = None) -> Optional[dict]:
    """가격·변동률·σ·거래량 페이스·장중 반전·세션 상태를 한 번에 수집"""
    now_et = now_et or datetime.now(ET)
    session = market_session(now_et)

    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="3mo")
        if hist.empty or len(hist) < 2:
            return None

        # 프리마켓에 '오늘' 일봉이 미리 잡히는 경우가 있다 — 정규장 전이면 버린다
        if session == "pre" and _bar_date(hist.index[-1]) == now_et.date():
            hist = hist.iloc[:-1]
            if len(hist) < 2:
                return None

        session_date = _bar_date(hist.index[-1])
        # 마지막 일봉이 오늘 것이 아니면, 지금 보이는 변동률은 '지난 세션' 이야기다.
        # 주말·휴장일·프리마켓·장 시작 직후 데이터 지연이 여기에 해당한다.
        stale = session_date != now_et.date()

        today, prev = hist.iloc[-1], hist.iloc[-2]
        close, prev_close = float(today["Close"]), float(prev["Close"])
        change_pct = (close - prev_close) / prev_close * 100

        # ── 20일 변동성 (마지막 일봉 직전 20세션) ──
        rets = hist["Close"].pct_change() * 100
        window = rets.iloc[-21:-1].dropna()
        vol20 = float(window.std()) if len(window) >= 10 else None
        if vol20 is not None and vol20 <= 0:
            vol20 = None

        day_range = (hist["High"] - hist["Low"]) / hist["Close"].shift(1) * 100
        rng_window = day_range.iloc[-21:-1].dropna()
        atr20_pct = float(rng_window.mean()) if len(rng_window) >= 10 else None

        z_change = change_pct / vol20 if vol20 else None

        # ── 거래량 (20일 평균 대비, 장중엔 시각 보정) ──
        avg_vol = float(hist["Volume"].iloc[-21:-1].mean())
        today_vol = float(today["Volume"])
        if session == "regular" and not stale:
            expected = avg_vol * _expected_volume_fraction(now_et)
        else:
            expected = avg_vol
        vol_ratio = today_vol / expected if expected > 0 else 1.0

        # ── 장중 반전 ──
        high, low = float(today["High"]), float(today["Low"])
        high_from_prev = (high - prev_close) / prev_close * 100
        low_from_prev = (low - prev_close) / prev_close * 100
        drop_from_high = high_from_prev - change_pct
        bounce_from_low = change_pct - low_from_prev

        intraday_reversal = 0.0
        reversal_detail = ""
        if high_from_prev >= 1 and drop_from_high >= REV_FLOOR:
            intraday_reversal = -drop_from_high
            reversal_detail = (f"고점 {high_from_prev:+.1f}% → 현재 {change_pct:+.1f}% "
                               f"(고점 대비 -{drop_from_high:.1f}%)")
        if low_from_prev <= -1 and bounce_from_low >= REV_FLOOR:
            if bounce_from_low > abs(intraday_reversal):
                intraday_reversal = bounce_from_low
                reversal_detail = (f"저점 {low_from_prev:+.1f}% → 현재 {change_pct:+.1f}% "
                                   f"(저점 대비 +{bounce_from_low:.1f}%)")
        rev_ratio = abs(intraday_reversal) / atr20_pct if atr20_pct else None

        # ── 시간외: 직전 정규장 종가 대비 움직임 ──
        ext_price = ext_change_pct = None
        if session in ("pre", "post"):
            ext_price = _extended_price(stock)
            if ext_price:
                ext_change_pct = (ext_price - close) / close * 100

        result = {
            "price": round(close, 2),
            "prev_close": round(prev_close, 2),
            "change_pct": round(change_pct, 2),
            "volume": int(today_vol),
            "volume_ratio": round(vol_ratio, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "intraday_reversal": round(intraday_reversal, 2),
            "reversal_detail": reversal_detail,
            "vol20": round(vol20, 2) if vol20 else None,
            "atr20_pct": round(atr20_pct, 2) if atr20_pct else None,
            "z_change": round(z_change, 2) if z_change is not None else None,
            "rev_ratio": round(rev_ratio, 2) if rev_ratio is not None else None,
            "session": session,
            "session_date": session_date.isoformat(),
            "stale": stale,
            "ext_price": round(ext_price, 2) if ext_price else None,
            "ext_change_pct": round(ext_change_pct, 2) if ext_change_pct is not None else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        line = f"  💰 ${close:.2f} ({change_pct:+.1f}%"
        if z_change is not None:
            line += f", {z_change:+.1f}σ"
        line += f") vol:{vol_ratio:.1f}x [{session}{' · 지난세션' if stale else ''}]"
        if abs(intraday_reversal) >= REV_FLOOR:
            line += f" 🔄반전:{intraday_reversal:+.1f}%"
        if ext_change_pct is not None:
            line += f" ⏱시간외:{ext_change_pct:+.1f}%"
        print(line)

        return result

    except Exception as e:
        print(f"  ⚠️ yfinance 오류 ({ticker}): {e}")
        return None


def check_price_trigger(ticker: str, price_data: dict = None) -> dict:
    """가격 트리거 — 세션에 맞는 기준으로만 판정한다.

    price_data를 넘기면 재조회하지 않는다.
    """
    if price_data is None:
        price_data = collect_price_yfinance(ticker)
    if not price_data:
        return {"triggered": False}

    triggers = []
    session = price_data.get("session", "regular")
    stale = price_data.get("stale", False)

    if session in ("pre", "post"):
        ext = price_data.get("ext_change_pct")
        if ext is not None and abs(ext) >= EXT_MOVE:
            label = "프리마켓" if session == "pre" else "애프터마켓"
            triggers.append({"type": "extended_move", "detail": f"{label} {ext:+.1f}%"})

    elif session == "regular" and not stale:
        change = price_data["change_pct"]
        vol_ratio = price_data["volume_ratio"]
        reversal = price_data.get("intraday_reversal", 0)
        z = price_data.get("z_change")
        rev_ratio = price_data.get("rev_ratio")

        if z is not None:
            big_move = (abs(z) >= Z_MOVE and abs(change) >= MOVE_FLOOR) or abs(change) >= MOVE_ABS
            big_rev = abs(reversal) >= REV_FLOOR and (rev_ratio or 0) >= REV_ATR
            vol_spike = vol_ratio >= VOL_SPIKE and abs(z) >= VOL_SPIKE_Z
        else:
            # 이력이 짧아 σ를 못 구하면 고정 기준
            big_move = abs(change) >= 3
            big_rev = abs(reversal) >= 3
            vol_spike = vol_ratio >= 3 and abs(change) >= 1

        sigma = f", {z:+.1f}σ" if z is not None else ""
        if big_move:
            direction = "급등" if change > 0 else "급락"
            triggers.append({"type": "price_move",
                             "detail": f"{direction} {change:+.1f}%{sigma} (거래량 {vol_ratio:.1f}x)"})
        if big_rev:
            direction = "급락 반전" if reversal < 0 else "급등 반전"
            triggers.append({"type": "intraday_reversal",
                             "detail": f"장중 {direction} {reversal:+.1f}%: {price_data.get('reversal_detail', '')}"})
        if vol_spike:
            triggers.append({"type": "volume_spike",
                             "detail": f"거래량 {vol_ratio:.1f}x (변동 {change:+.1f}%{sigma})"})

    # session == 'closed' 이거나 지난 세션 데이터면 트리거 없음

    return {
        "triggered": len(triggers) > 0,
        "triggers": triggers,
        "price_data": price_data,
    }
