"""
Stock Sentinel — Price Collector
시장 가격/거래량 데이터 수집
네트워크 제한 환경에서는 웹 검색 폴백 사용
"""
import json
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from storage.database import save_price, get_recent_prices


def collect_price_yfinance(ticker: str) -> Optional[Dict]:
    """yfinance로 가격 수집 (직접 네트워크 접근 가능 시)"""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="5d")
        
        if hist.empty:
            return None
        
        results = []
        for idx, row in hist.iterrows():
            ts = idx.strftime("%Y-%m-%dT%H:%M:%S")
            save_price(
                ticker=ticker,
                timestamp=ts,
                open_=round(row['Open'], 2),
                high=round(row['High'], 2),
                low=round(row['Low'], 2),
                close=round(row['Close'], 2),
                volume=int(row['Volume']),
                source="yfinance"
            )
            results.append({
                "timestamp": ts,
                "open": round(row['Open'], 2),
                "high": round(row['High'], 2),
                "low": round(row['Low'], 2),
                "close": round(row['Close'], 2),
                "volume": int(row['Volume']),
            })
        
        latest = results[-1] if results else None
        print(f"  💰 Price [{ticker}]: ${latest['close']:.2f} | Vol: {latest['volume']:,}")
        
        # 가격 변동률 계산
        change_pct = 0.0
        volume_ratio = 1.0
        if len(results) >= 2:
            prev_close = results[-2]['close']
            if prev_close > 0:
                change_pct = ((latest['close'] - prev_close) / prev_close) * 100
            # 평균 거래량 대비 비율
            avg_vol = sum(r['volume'] for r in results[:-1]) / len(results[:-1])
            if avg_vol > 0:
                volume_ratio = latest['volume'] / avg_vol
            print(f"  📈 Change: {change_pct:+.1f}% | Volume: {volume_ratio:.1f}x avg")
        
        return {
            "ticker": ticker,
            "latest": latest,
            "history": results,
            "change_pct": round(change_pct, 2),
            "volume_ratio": round(volume_ratio, 2),
            "source": "yfinance",
        }
    
    except Exception as e:
        print(f"  ⚠️ yfinance 수집 실패: {e}")
        return None


def collect_price_manual(ticker: str, close: float, volume: int = 0,
                        open_: float = 0, high: float = 0, low: float = 0,
                        timestamp: str = None) -> Dict:
    """수동 가격 입력 (웹 검색 결과 등에서 파싱 후 사용)"""
    ts = timestamp or datetime.utcnow().isoformat()
    
    save_price(
        ticker=ticker,
        timestamp=ts,
        open_=open_ or close,
        high=high or close,
        low=low or close,
        close=close,
        volume=volume,
        source="manual"
    )
    
    print(f"  💰 Price [{ticker}] (manual): ${close:.2f}")
    return {
        "ticker": ticker,
        "latest": {
            "timestamp": ts,
            "close": close,
            "volume": volume,
        },
        "source": "manual",
    }


def get_price_change(ticker: str, periods: int = 2) -> Optional[Dict]:
    """최근 가격 변동 계산"""
    prices = get_recent_prices(ticker, limit=periods + 1)
    
    if len(prices) < 2:
        return None
    
    latest = prices[0]
    previous = prices[1]
    
    change = latest['close'] - previous['close']
    change_pct = (change / previous['close']) * 100 if previous['close'] else 0
    
    # 거래량 비율 (최근 vs 이전)
    vol_ratio = latest['volume'] / previous['volume'] if previous['volume'] else 0
    
    return {
        "ticker": ticker,
        "latest_close": latest['close'],
        "previous_close": previous['close'],
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        "latest_volume": latest['volume'],
        "volume_ratio": round(vol_ratio, 2),
        "timestamp": latest['timestamp'],
    }


def get_avg_volume(ticker: str, days: int = 20) -> int:
    """N일 평균 거래량"""
    prices = get_recent_prices(ticker, limit=days)
    if not prices:
        return 0
    volumes = [p['volume'] for p in prices if p['volume']]
    return int(sum(volumes) / len(volumes)) if volumes else 0


def check_price_trigger(ticker: str) -> Optional[Dict]:
    """가격 급변 트리거 확인"""
    from config.settings import (
        TRIGGER_PRICE_CHANGE_5MIN, 
        TRIGGER_VOLUME_RATIO,
        TRIGGER_PREMARKET_CHANGE
    )
    
    change_info = get_price_change(ticker)
    if not change_info:
        return None
    
    avg_vol = get_avg_volume(ticker)
    vol_ratio = change_info['latest_volume'] / avg_vol if avg_vol else 0
    
    triggers = []
    
    # 가격 변동 체크
    if abs(change_info['change_pct']) >= TRIGGER_PRICE_CHANGE_5MIN:
        triggers.append({
            "type": "price_change",
            "detail": f"{change_info['change_pct']:+.2f}% (임계치: ±{TRIGGER_PRICE_CHANGE_5MIN}%)",
            "severity": "high" if abs(change_info['change_pct']) >= 5 else "medium",
        })
    
    # 거래량 폭증 체크
    if vol_ratio >= TRIGGER_VOLUME_RATIO:
        triggers.append({
            "type": "volume_surge",
            "detail": f"거래량 {vol_ratio:.1f}배 (임계치: {TRIGGER_VOLUME_RATIO}배)",
            "severity": "high" if vol_ratio >= 5 else "medium",
        })
    
    if triggers:
        return {
            "ticker": ticker,
            "triggered": True,
            "triggers": triggers,
            "price_info": change_info,
            "avg_volume_20d": avg_vol,
            "volume_ratio": round(vol_ratio, 2),
        }
    
    return None


# ============================================================
# 관련 종목 수집
# ============================================================

def collect_related_prices(ticker: str) -> List[Dict]:
    """관련 종목 가격 수집"""
    watch = None
    try:
        from config.settings import WATCHMAP
        watch = WATCHMAP.get(ticker)
    except:
        pass
    
    if not watch or not watch.related:
        return []
    
    results = []
    for rel_ticker in watch.related:
        data = collect_price_yfinance(rel_ticker)
        if data:
            results.append(data)
    
    return results


# ============================================================
# 테스트
# ============================================================
if __name__ == "__main__":
    from storage.database import init_db
    init_db()
    
    # 수동 입력 테스트 (웹 검색 결과 기반)
    collect_price_manual("AMAT", close=369.31, open_=361.50, high=372.50, 
                        low=361.50, volume=6879498,
                        timestamp="2026-02-13T16:00:00")
    collect_price_manual("AMAT", close=328.39, open_=327.00, high=332.00,
                        low=325.00, volume=8414305,
                        timestamp="2026-02-12T16:00:00")
    
    change = get_price_change("AMAT")
    if change:
        print(f"\n  변동: {change['change_pct']:+.2f}%")
        print(f"  거래량 비율: {change['volume_ratio']:.2f}x")
