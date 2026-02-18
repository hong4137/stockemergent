"""
Stock Sentinel — GitHub Actions 엔트리포인트
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import WATCHLIST, WATCHMAP
from storage.database import init_db
from collectors.news_collector import collect_all_news
from collectors.price_collector import collect_price_yfinance, check_price_trigger
from engines.psi_engine import PreSignalEngine, FlashReasonEngine
from alerts.alert_system import send_alert
from alerts.telegram import send_telegram

SCAN_TICKER = os.environ.get("SCAN_TICKER", "")
FORCE_ALERT = os.environ.get("FORCE_ALERT", "false") == "true"
ET = timezone(timedelta(hours=-5))


def log(msg):
    print(f"[{datetime.now(ET).strftime('%H:%M ET')}] {msg}")


def scan_single(ticker):
    watch = WATCHMAP.get(ticker)
    if not watch:
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
                       news_data=all_news, price_data=price_data)

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
    results = [scan_single(t) for t in tickers]
    results = [r for r in results if r]

    log(f"\n📊 SUMMARY")
    for r in results:
        e = {"normal": "🟢", "watch": "🟡", "alert": "🟠", "critical": "🔴"}.get(r['level'], "❓")
        log(f"  {e} {r['ticker']:6s} PSI {r['psi']:4.1f} → {r['cls']} ({r['news']}건)")

    # 장마감 일일요약
    if now.hour == 16 and now.minute < 35:
        msg = f"📊 *Daily Summary* {now.strftime('%m/%d')}\n━━━━━━━━━━━━━━━\n"
        for r in results:
            e = {"normal": "🟢", "watch": "🟡", "alert": "🟠", "critical": "🔴"}.get(r['level'], "❓")
            msg += f"{e} *{r['ticker']}* PSI {r['psi']:.1f} → {r['cls']}\n"
        send_telegram(msg)


if __name__ == "__main__":
    main()
