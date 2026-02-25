"""
Stock Sentinel — Price Collector
yfinance 기반 + 장중 반전 감지
"""
import yfinance as yf
from datetime import datetime, timezone, timedelta


def collect_price_yfinance(ticker: str) -> dict:
    """가격 데이터 수집 + 변동률 + 거래량 비율 + 장중 반전"""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")

        if hist.empty or len(hist) < 2:
            return None

        today = hist.iloc[-1]
        yesterday = hist.iloc[-2]

        close = today["Close"]
        prev_close = yesterday["Close"]
        change_pct = ((close - prev_close) / prev_close) * 100

        # 거래량 비율 (평균 대비)
        avg_vol = hist["Volume"].iloc[:-1].mean()
        vol_ratio = today["Volume"] / avg_vol if avg_vol > 0 else 1.0

        # ── 장중 반전 감지 ──
        high = today["High"]
        low = today["Low"]

        # 전일 종가 기준 고가/저가 변동률
        high_from_prev = ((high - prev_close) / prev_close) * 100
        low_from_prev = ((low - prev_close) / prev_close) * 100
        close_from_prev = change_pct

        # 고점 대비 하락폭 (양수였다가 떨어진 경우)
        drop_from_high = high_from_prev - close_from_prev
        # 저점 대비 반등폭 (음수였다가 올라간 경우)
        bounce_from_low = close_from_prev - low_from_prev

        intraday_reversal = 0
        reversal_detail = ""

        # 고점 대비 급락: 고점이 양수이고 현재가가 많이 내려온 경우
        if high_from_prev >= 1 and drop_from_high >= 3:
            intraday_reversal = -drop_from_high
            reversal_detail = f"고점 {high_from_prev:+.1f}% → 현재 {close_from_prev:+.1f}% (고점 대비 -{drop_from_high:.1f}%)"

        # 저점 대비 급반등: 저점이 음수이고 현재가가 많이 올라온 경우
        if low_from_prev <= -1 and bounce_from_low >= 3:
            if abs(bounce_from_low) > abs(intraday_reversal):
                intraday_reversal = bounce_from_low
                reversal_detail = f"저점 {low_from_prev:+.1f}% → 현재 {close_from_prev:+.1f}% (저점 대비 +{bounce_from_low:.1f}%)"

        result = {
            "price": round(close, 2),
            "prev_close": round(prev_close, 2),
            "change_pct": round(change_pct, 2),
            "volume": int(today["Volume"]),
            "volume_ratio": round(vol_ratio, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "intraday_reversal": round(intraday_reversal, 2),
            "reversal_detail": reversal_detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        print(f"  💰 ${close:.2f} ({change_pct:+.1f}%) vol:{vol_ratio:.1f}x", end="")
        if abs(intraday_reversal) >= 3:
            print(f" 🔄반전:{intraday_reversal:+.1f}%", end="")
        print()

        return result

    except Exception as e:
        print(f"  ⚠️ yfinance 오류 ({ticker}): {e}")
        return None


def check_price_trigger(ticker: str) -> dict:
    """가격 급변 트리거 (±3% 이상)"""
    price_data = collect_price_yfinance(ticker)
    if not price_data:
        return {"triggered": False}

    triggers = []
    change = price_data["change_pct"]
    vol_ratio = price_data["volume_ratio"]
    reversal = price_data.get("intraday_reversal", 0)

    if abs(change) >= 3:
        direction = "급등" if change > 0 else "급락"
        triggers.append({
            "type": "price_move",
            "detail": f"{direction} {change:+.1f}% (거래량 {vol_ratio:.1f}x)",
        })

    if abs(reversal) >= 3:
        direction = "급락 반전" if reversal < 0 else "급등 반전"
        triggers.append({
            "type": "intraday_reversal",
            "detail": f"장중 {direction} {reversal:+.1f}%: {price_data.get('reversal_detail', '')}",
        })

    if vol_ratio >= 3 and abs(change) >= 1:
        triggers.append({
            "type": "volume_spike",
            "detail": f"거래량 {vol_ratio:.1f}x (변동 {change:+.1f}%)",
        })

    return {
        "triggered": len(triggers) > 0,
        "triggers": triggers,
        "price_data": price_data,
    }
