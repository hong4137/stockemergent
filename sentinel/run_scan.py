"""
Stock Sentinel — GitHub Actions 엔트리포인트
환경변수로 스캔 모드를 받아 실행
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta

# 경로 설정
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import WATCHLIST, WATCHMAP
from storage.database import init_db
from collectors.news_collector import collect_all_news
from collectors.price_collector import collect_price_yfinance, check_price_trigger
from engines.psi_engine import PreSignalEngine, FlashReasonEngine
from alerts.alert_system import send_alert
from alerts.telegram import send_telegram

# 환경변수
SCAN_MODE = os.environ.get("SCAN_MODE", "market_open")
SCAN_TICKER = os.environ.get("SCAN_TICKER", "").upper().strip().strip()
FORCE_ALERT = os.environ.get("FORCE_ALERT", "false") == "true"

ET = timezone(timedelta(hours=-5))


def log(msg: str):
    ts = datetime.now(ET).strftime("%H:%M:%S ET")
    print(f"[{ts}] {msg}")


def scan_single(ticker: str) -> dict:
    """단일 종목 스캔"""
    watch = WATCHMAP.get(ticker)
    if not watch:
        log(f"❌ 워치리스트에 없음: {ticker}")
        return {}

    log(f"📡 스캔 시작: {ticker} ({watch.name})")

    # 1. 가격 수집
    price_data = None
    try:
        price_data = collect_price_yfinance(ticker)
    except Exception as e:
        log(f"  ⚠️ 가격 수집 실패: {e}")

    # 2. 뉴스 수집
    all_news_raw = {}
    try:
        all_news_raw = collect_all_news(ticker)
    except Exception as e:
        log(f"  ⚠️ 뉴스 수집 실패: {e}")

    all_news = []
    for source_news in all_news_raw.values():
        all_news.extend(source_news)

    # 3. PSI 계산 (옵션/소셜은 추후 API 연동)
    engine = PreSignalEngine(ticker)
    psi_result = engine.calculate(
        options_data={},
        social_data={},
        news_data=all_news,
        price_data=price_data,
    )

    level_emoji = {"normal": "🟢", "watch": "🟡", "alert": "🟠", "critical": "🔴"}
    emoji = level_emoji.get(psi_result["level"], "❓")
    log(f"  {emoji} PSI: {psi_result['psi_total']:.1f}/10 [{psi_result['level'].upper()}]")
    log(f"     O:{psi_result['options_score']:.0f} A:{psi_result['attention_score']:.0f} F:{psi_result['fact_score']:.0f} P:{psi_result.get('price_boost', 0):.1f}")

    # 4. Flash Reason + 알림 (PSI ≥ 5 또는 강제)
    flash_result = None
    if psi_result["psi_total"] >= 5 or FORCE_ALERT:
        flash_engine = FlashReasonEngine(ticker)
        flash_result = flash_engine.analyze(all_news, price_data)

        cls = flash_result["classification"]
        log(f"  🔍 분류: {cls['type']} ({cls['confidence']:.0%})")

        # PSI ≥ 7 또는 강제 → 알림 발송
        if psi_result["psi_total"] >= 7 or FORCE_ALERT:
            send_alert(
                ticker, psi_result, flash_result, "psi_critical",
                news_data=all_news, price_data=price_data,
                force=FORCE_ALERT,
            )
            log(f"  📤 알림 발송 시도")

    # 5. 가격 트리거 독립 체크 (장중에만 동작)
    from alerts.alert_system import _is_market_hours
    reversal_triggered = False
    if _is_market_hours() and price_data and abs(price_data.get("intraday_reversal", 0)) >= 3:
        reversal_triggered = True
        log(f"  🔄 장중 반전 감지: {price_data['intraday_reversal']:+.1f}%")

    if _is_market_hours():
        pt = check_price_trigger(ticker)
        if (pt and pt.get("triggered") or reversal_triggered) and not flash_result:
            flash_result = FlashReasonEngine(ticker).analyze(all_news, price_data)
            trigger = "price_reversal" if reversal_triggered else "price_surge"
            send_alert(
                ticker, psi_result, flash_result, trigger,
                news_data=all_news, price_data=price_data,
            )

    return {
        "ticker": ticker,
        "psi": psi_result["psi_total"],
        "level": psi_result["level"],
        "classification": flash_result["classification"]["type"] if flash_result else "N/A",
        "news_count": len(all_news),
    }


def main():
    init_db()

    now_et = datetime.now(ET)
    log(f"{'='*50}")
    log(f"📡 STOCK SENTINEL — {SCAN_MODE.upper()}")
    log(f"   {now_et.strftime('%Y-%m-%d %H:%M ET')} | 모드: {SCAN_MODE}")
    log(f"{'='*50}")

    # 스캔 대상 결정
    if SCAN_TICKER:
        tickers = [SCAN_TICKER]
    else:
        tickers = [item.ticker for item in WATCHLIST]

    log(f"🎯 스캔 대상: {tickers}")

    results = []
    for ticker in tickers:
        result = scan_single(ticker)
        if result:
            results.append(result)

    # 요약
    log(f"\n{'='*50}")
    log(f"📊 SCAN SUMMARY")
    log(f"{'='*50}")
    for r in results:
        emoji = {"normal": "🟢", "watch": "🟡", "alert": "🟠", "critical": "🔴"}.get(r["level"], "❓")
        log(f"  {emoji} {r['ticker']:6s} PSI {r['psi']:4.1f} [{r['level'].upper():8s}] "
            f"→ {r['classification']} | 뉴스 {r['news_count']}건")

    # 일일 요약 (장 마감 시) → Telegram
    if SCAN_MODE == "after_hours" and now_et.hour == 16 and now_et.minute < 35:
        _send_daily_summary(results)


def _send_daily_summary(results: list):
    """장 마감 일일 요약 Telegram 발송"""
    now_et = datetime.now(ET)

    msg = f"📊 *Daily Sentinel Summary*\n"
    msg += f"📅 {now_et.strftime('%Y-%m-%d')} 장마감\n"
    msg += f"━━━━━━━━━━━━━━━━━━━\n"

    for r in results:
        emoji = {"normal": "🟢", "watch": "🟡", "alert": "🟠", "critical": "🔴"}.get(r["level"], "❓")
        msg += f"{emoji} *{r['ticker']}* PSI {r['psi']:.1f} [{r['level'].upper()}]\n"

    msg += f"\n🕐 Next scan: ET 16:30"

    try:
        send_telegram(msg)
        log("📤 Daily summary 발송 완료")
    except Exception as e:
        log(f"⚠️ Daily summary 발송 실패: {e}")


if __name__ == "__main__":
    main()
