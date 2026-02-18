"""
Stock Sentinel — GitHub Actions 엔트리포인트 v2
각 종목 독립 실행 + 진단 로그
"""
import os
import sys
import traceback
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import WATCHLIST, WATCHMAP
from storage.database import init_db
from collectors.news_collector import collect_all_news
from collectors.price_collector import collect_price_yfinance, check_price_trigger
from engines.psi_engine import PreSignalEngine, FlashReasonEngine
from alerts.alert_system import send_alert
from alerts.telegram import send_telegram

SCAN_TICKER = os.environ.get("SCAN_TICKER", "").strip()
FORCE_ALERT = os.environ.get("FORCE_ALERT", "false").lower() == "true"
ET = timezone(timedelta(hours=-5))


def log(msg):
    print(f"[{datetime.now(ET).strftime('%H:%M ET')}] {msg}")


def scan_single(ticker):
    watch = WATCHMAP.get(ticker)
    if not watch:
        log(f"❌ {ticker} not in WATCHMAP")
        return {}

    log(f"📡 {ticker} ({watch.name})")

    # 가격
    price_data = None
    try:
        price_data = collect_price_yfinance(ticker)
    except Exception as e:
        log(f"  ⚠️ 가격: {e}")

    # 뉴스
    all_news = []
    try:
        for v in collect_all_news(ticker).values():
            all_news.extend(v)
    except Exception as e:
        log(f"  ⚠️ 뉴스: {e}")

    # PSI
    psi_result = PreSignalEngine(ticker).calculate(
        options_data={}, social_data={}, news_data=all_news, price_data=price_data
    )

    emoji = {"normal": "🟢", "watch": "🟡", "alert": "🟠", "critical": "🔴"}
    log(f"  {emoji.get(psi_result['level'], '❓')} PSI {psi_result['psi_total']:.1f} "
        f"[O:{psi_result['options_score']:.0f} A:{psi_result['attention_score']:.0f} F:{psi_result['fact_score']:.0f}]")

    # Flash Reason + 알림
    flash_result = None
    if psi_result['psi_total'] >= 5 or FORCE_ALERT:
        flash_result = FlashReasonEngine(ticker).analyze(all_news, price_data)
        cls = flash_result['classification']
        log(f"  🔍 {cls['type']} ({cls['confidence']:.0%})")

        if psi_result['psi_total'] >= 7 or FORCE_ALERT:
            send_alert(ticker, psi_result, flash_result, "psi_critical",
                       news_data=all_news, price_data=price_data, force=FORCE_ALERT)

    # 가격 트리거
    pt = check_price_trigger(ticker)
    if pt and pt.get('triggered') and not flash_result:
        flash_result = FlashReasonEngine(ticker).analyze(all_news, price_data)
        send_alert(ticker, psi_result, flash_result, "price_surge",
                   news_data=all_news, price_data=price_data)

    return {
        "ticker": ticker,
        "psi": psi_result['psi_total'],
        "level": psi_result['level'],
        "cls": flash_result['classification']['type'] if flash_result else "-",
        "news": len(all_news),
    }


def main():
    init_db()
    now = datetime.now(ET)
    log(f"{'='*40}")
    log(f"📡 SENTINEL SCAN | {now.strftime('%Y-%m-%d %H:%M ET')}")
    log(f"{'='*40}")

    tickers = [SCAN_TICKER] if SCAN_TICKER else [w.ticker for w in WATCHLIST]
    log(f"🎯 스캔 대상: {tickers} (FORCE={FORCE_ALERT})")

    if not tickers:
        log("⚠️ 스캔할 종목이 없습니다! WATCHLIST 확인 필요")
        return

    results = []
    errors = []

    for t in tickers:
        try:
            r = scan_single(t)
            if r:
                results.append(r)
        except Exception as e:
            err_msg = f"❌ {t} 스캔 실패: {e}"
            log(err_msg)
            log(traceback.format_exc())
            errors.append(err_msg)

    # SUMMARY
    log(f"\n📊 SUMMARY")
    for r in results:
        e = {"normal": "🟢", "watch": "🟡", "alert": "🟠", "critical": "🔴"}.get(r['level'], "❓")
        log(f"  {e} {r['ticker']:6s} PSI {r['psi']:4.1f} → {r['cls']} ({r['news']}건)")

    if errors:
        log(f"\n⚠️ ERRORS: {len(errors)}")
        for err in errors:
            log(f"  {err}")
        # 에러도 텔레그램으로 알림
        err_msg = f"⚠️ *Sentinel 오류*\n"
        for err in errors:
            err_msg += f"  {err}\n"
        send_telegram(err_msg)

    # 장마감 일일요약
    if now.hour == 16 and now.minute < 35:
        msg = f"📊 *Daily Summary* {now.strftime('%m/%d')}\n━━━━━━━━━━━━━━━\n"
        for r in results:
            e = {"normal": "🟢", "watch": "🟡", "alert": "🟠", "critical": "🔴"}.get(r['level'], "❓")
            msg += f"{e} *{r['ticker']}* PSI {r['psi']:.1f} → {r['cls']}\n"
        send_telegram(msg)


if __name__ == "__main__":
    main()
