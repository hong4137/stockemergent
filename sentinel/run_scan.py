"""
Stock Sentinel — GitHub Actions 엔트리포인트

흐름
  1. 시장 맥락(S&P·섹터 ETF·동종업체) 1회 일괄 조회
  2. 종목별 가격·뉴스를 병렬 수집 (I/O 대기 시간이 대부분이라 직렬보다 훨씬 빠르다.
     Actions는 잡 단위로 분 올림 과금되므로 실행 시간이 곧 월 사용량이다)
  3. 종목별로 순서대로 PSI → 트리거 → 발송 판정 → AI 요약 → 텔레그램
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import WATCHLIST, WATCHMAP
from storage.database import (
    init_db, save_scan, prune_scan_log, get_news_baseline, claim_once_per_day,
)
from collectors.news_collector import collect_all_news, _load_cik_map
from collectors.price_collector import collect_price_yfinance, check_price_trigger
from collectors.market_context import build_market_context
from engines.psi_engine import PreSignalEngine, FlashReasonEngine
from alerts.alert_system import send_alert
from alerts.telegram import send_telegram

# WATCHMAP 키는 대문자다. workflow_dispatch로 'mu' 처럼 들어오면 조용히 아무것도
# 스캔하지 않으므로 반드시 대문자로 맞춘다.
SCAN_TICKER = os.environ.get("SCAN_TICKER", "").strip().upper()
FORCE_ALERT = os.environ.get("FORCE_ALERT", "false").lower() == "true"
MAX_WORKERS = 7  # 종목당 Finnhub 1회라 무료 한도(분당 60회)에 여유가 있다
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except ImportError:
    ET = timezone(timedelta(hours=-4))  # DST fallback


def log(msg):
    print(f"[{datetime.now(ET).strftime('%H:%M ET')}] {msg}")


def prefetch(ticker):
    """가격·뉴스 수집 (스레드에서 실행). 실패해도 None/[]로 돌려 스캔을 멈추지 않는다."""
    price_data, news = None, []
    try:
        price_data = collect_price_yfinance(ticker)
    except Exception as e:
        print(f"  ⚠️ {ticker} 가격: {e}")
    try:
        for v in collect_all_news(ticker).values():
            news.extend(v)
    except Exception as e:
        print(f"  ⚠️ {ticker} 뉴스: {e}")
    return price_data, news


def _trigger_name(pt, price_data):
    if price_data and price_data.get("session") in ("pre", "post"):
        return "extended_move"
    types = {t["type"] for t in (pt or {}).get("triggers", [])}
    if types == {"intraday_reversal"}:
        return "price_reversal"
    return "price_surge"


def scan_single(ticker, price_data, all_news, market_context=None):
    watch = WATCHMAP.get(ticker)
    if not watch:
        return {}

    log(f"📡 {ticker} ({watch.name})")
    ctx = (market_context or {}).get(ticker)

    # PSI — 뉴스는 '평소 대비' 로 평가하므로 기준선을 넘긴다
    baseline = get_news_baseline(ticker)
    psi_result = PreSignalEngine(ticker).calculate(
        options_data={}, social_data={}, news_data=all_news, price_data=price_data,
        news_baseline=baseline,
    )

    emoji = {"normal": "🟢", "watch": "🟡", "alert": "🟠", "critical": "🔴"}
    log(f"  {emoji.get(psi_result['level'], '❓')} PSI {psi_result['psi_total']:.1f} "
        f"[O:{psi_result['options_score']:.0f} A:{psi_result['attention_score']:.0f} F:{psi_result['fact_score']:.0f}]")

    # 스캔 이력 기록 — 다음 스캔의 뉴스 기준선이 된다
    save_scan(ticker, psi_result['psi_total'], psi_result['level'], len(all_news))

    session_trigger = "extended_move" if (price_data or {}).get("session") in ("pre", "post") else None

    # Flash Reason + 알림
    flash_result = None
    if psi_result['psi_total'] >= 5 or FORCE_ALERT:
        flash_result = FlashReasonEngine(ticker).analyze(all_news, price_data)
        cls = flash_result['classification']
        log(f"  🔍 {cls['type']} ({cls['confidence']:.0%})")

        if psi_result['psi_total'] >= 7 or FORCE_ALERT:
            send_alert(ticker, psi_result, flash_result, session_trigger or "psi_critical",
                       news_data=all_news, price_data=price_data, force=FORCE_ALERT,
                       market_context=ctx)

    # 가격 트리거 — 세션·변동성(σ) 기준 판정은 check_price_trigger에 일원화한다.
    # (예전엔 여기서 '반전 3%'만 보고 바로 발송해, 하루 변동폭이 큰 NET에서
    #  반전 알림이 쏟아졌다 — 2% 미만 변동 알림 49건 중 38건이 이 경로)
    pt = check_price_trigger(ticker, price_data)
    if pt.get("triggered"):
        for t in pt["triggers"]:
            log(f"  ⚡ {t['detail']}")
        if not flash_result:
            flash_result = FlashReasonEngine(ticker).analyze(all_news, price_data)
            send_alert(ticker, psi_result, flash_result, _trigger_name(pt, price_data),
                       news_data=all_news, price_data=price_data, market_context=ctx)

    return {
        "ticker": ticker,
        "psi": psi_result['psi_total'],
        "level": psi_result['level'],
        "cls": flash_result['classification']['type'] if flash_result else "-",
        "news": len(all_news),
    }


def main():
    started = time.time()
    init_db()
    prune_scan_log()
    now = datetime.now(ET)
    log(f"{'='*40}")
    log(f"📡 SENTINEL SCAN | {now.strftime('%Y-%m-%d %H:%M ET')}")
    log(f"{'='*40}")

    tickers = [SCAN_TICKER] if SCAN_TICKER else [w.ticker for w in WATCHLIST]
    log(f"🎯 스캔 대상: {tickers} (FORCE={FORCE_ALERT})")
    if not tickers:
        log("⚠️ 스캔할 종목이 없습니다! WATCHLIST 확인 필요")
        return

    watches = [WATCHMAP[t] for t in tickers if t in WATCHMAP]
    market_context = build_market_context(watches)

    # CIK 매핑은 DB 캐시를 쓰므로 스레드에 들어가기 전에 한 번 데워둔다
    _load_cik_map()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        fetched = dict(zip(tickers, pool.map(prefetch, tickers)))
    log(f"⏱ 수집 완료 {time.time() - started:.0f}초")

    results = []
    for t in tickers:
        price_data, news = fetched.get(t, (None, []))
        try:
            r = scan_single(t, price_data, news, market_context)
        except Exception as e:
            # 한 종목의 예외가 나머지 종목 스캔을 막지 않게 한다
            log(f"  ❌ {t} 처리 실패: {type(e).__name__}: {e}")
            r = {}
        if r:
            results.append(r)

    log(f"\n📊 SUMMARY ({time.time() - started:.0f}초)")
    for r in results:
        e = {"normal": "🟢", "watch": "🟡", "alert": "🟠", "critical": "🔴"}.get(r['level'], "❓")
        log(f"  {e} {r['ticker']:6s} PSI {r['psi']:4.1f} → {r['cls']} ({r['news']}건)")

    # 장마감 일일요약 — 하루 1회.
    # 시간 조건만 쓰면 cron 슬롯이 여러 개 걸려 하루 3번씩 나갔다.
    if now.weekday() < 5 and now.hour == 16 and now.minute < 35:
        if claim_once_per_day("daily_summary", now.strftime("%Y-%m-%d")):
            msg = f"📊 *Daily Summary* {now.strftime('%m/%d')}\n━━━━━━━━━━━━━━━\n"
            for r in results:
                e = {"normal": "🟢", "watch": "🟡", "alert": "🟠", "critical": "🔴"}.get(r['level'], "❓")
                msg += f"{e} *{r['ticker']}* PSI {r['psi']:.1f} → {r['cls']}\n"
            send_telegram(msg)
        else:
            log("  ⏭️ 일일요약 이미 발송됨")


if __name__ == "__main__":
    main()
