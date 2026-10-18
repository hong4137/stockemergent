"""
백테스트용 시점 고정 증거 수집기 (채점규칙_v2.md)

알림 시각 T 기준으로 '그때 알 수 있었던 것'만 모아 이벤트별 증거 묶음(bundles/Exxx.json)을 만든다.

모드
  A  알림 시점   : 뉴스는 T의 UTC 날짜 '이전' 발행분만 (당일 기사는 시각을 알 수 없어 뺀다 → 하한선)
  B  장 마감 후  : 뉴스는 T의 UTC 날짜까지 (Google News 날짜는 UTC 기준 → 미 동부 20시 이전 기사)

시세는 1시간봉으로 T 시점 값을 근사한다. SEC는 접수 시각 < T (A), < 당일 20:00 ET (B).
실행: python collect.py   (캐시는 cache/ 에 남는다. 다시 돌리면 네트워크를 거의 안 쓴다)
"""
import csv
import sys
import hashlib
import json
import os
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import feedparser
import requests
import yfinance as yf

ET = ZoneInfo("America/New_York")
HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "cache")
sys.path.insert(0, HERE)
import bt_config  # noqa: E402
BUNDLES = bt_config.path("bundles", "_")[:-2]
os.makedirs(CACHE, exist_ok=True)
os.makedirs(BUNDLES, exist_ok=True)

# 종목 메타. 동종업체는 미국 티커만(CLAUDE.md: SAMSUNG 같은 건 시세 조회 실패)
META = {
    "MU":   dict(name="Micron",             etfs=["SOXX"],         peers=["WDC", "SNDK", "STX", "NVDA"],
                 sector_q=["memory chip stocks", "semiconductor stocks"]),
    "AVGO": dict(name="Broadcom",           etfs=["SOXX"],         peers=["NVDA", "MRVL", "AMD", "QCOM"],
                 sector_q=["semiconductor stocks", "AI chip stocks"]),
    "QCOM": dict(name="Qualcomm",           etfs=["SOXX"],         peers=["ARM", "AVGO", "SWKS", "AAPL"],
                 sector_q=["semiconductor stocks", "chip stocks"]),
    "PANW": dict(name="Palo Alto Networks", etfs=["CIBR", "IGV"],  peers=["CRWD", "ZS", "FTNT", "NET"],
                 sector_q=["cybersecurity stocks", "software stocks"]),
    "NET":  dict(name="Cloudflare",         etfs=["CIBR", "IGV"],  peers=["CRWD", "ZS", "PANW", "AKAM", "DDOG"],
                 sector_q=["cybersecurity stocks", "software stocks"]),
    "AMAT": dict(name="Applied Materials",  etfs=["SOXX"],         peers=["LRCX", "KLAC", "ASML", "TSM"],
                 sector_q=["semiconductor equipment stocks", "chip stocks"]),
    "AMZN": dict(name="Amazon",             etfs=["XLY"],          peers=["MSFT", "GOOGL", "META", "AAPL"],
                 sector_q=["megacap tech stocks"]),
    "NFLX": dict(name="Netflix",            etfs=["XLC"],          peers=["DIS", "WBD", "ROKU", "SPOT"],
                 sector_q=["streaming stocks", "media stocks"]),
}
MARKET = ["SPY", "QQQ"]
MARKET_Q = ["stock market today", "Nasdaq stocks"]
CIK = {"MU": "0000723125", "AVGO": "0001730168", "QCOM": "0000804328", "PANW": "0001327567",
       "NET": "0001477333", "AMZN": "0001018724", "NFLX": "0001065280", "AMAT": "0000006951"}
SEC_UA = {"User-Agent": "stock-sentinel-backtest research research@example.com"}
SEC_FORMS = {"8-K", "6-K", "10-Q", "10-K", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A", "S-3", "S-3ASR", "424B2", "424B5", "DEF 14A"}


def _cache(key, fn):
    path = os.path.join(CACHE, hashlib.md5(key.encode()).hexdigest() + ".json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    val = fn()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(val, f, ensure_ascii=False)
    return val


# ---------- 시세 ----------
_PX = {}


def load_prices(symbols):
    def fetch(sym, interval, period):
        def go():
            h = yf.Ticker(sym).history(period=period, interval=interval, auto_adjust=False)
            return [[ts.isoformat(), float(r["Close"]), float(r["High"]), float(r["Low"]), float(r["Volume"]),
                     float(r["Open"])] for ts, r in h.iterrows()]
        return _cache(f"px2|{sym}|{interval}|{period}|20261018", go)

    for s in symbols:
        if s in _PX:
            continue
        d = fetch(s, "1d", "1y")
        h = fetch(s, "1h", bt_config.H_PERIOD)
        m5 = fetch(s, "5m", "60d")
        _PX[s] = dict(
            d=[(datetime.fromisoformat(t).astimezone(ET).date(), c) for t, c, *_ in d],
            h=[(datetime.fromisoformat(t).astimezone(ET), c, hi, lo, op) for t, c, hi, lo, _, op in h],
            m5=[(datetime.fromisoformat(t).astimezone(ET), c, hi, lo, op) for t, c, hi, lo, _, op in m5],
        )
        time.sleep(0.3)


def move_at(sym, T):
    """T 시점 등락률(전일 종가 대비)·당일 고저 대비 위치. 장 전이면 None(정규장 값 없음).

    1시간봉의 시각은 봉 '시작'이다. 끝난 봉(시작+1h ≤ T)만 종가·고저를 쓰고,
    T가 걸친 진행 중인 봉은 시가만 쓴다 — 아니면 미래 가격이 섞인다.
    """
    px = _PX.get(sym)
    if not px:
        return None
    day = T.date()
    prev = [c for d, c in px["d"] if d < day]
    if not prev:
        return None
    pc = prev[-1]
    # 5분봉(최근 60일)이 그날 있으면 그걸 쓰고, 없으면 1시간봉
    bars, width = px["m5"], timedelta(minutes=5)
    if not any(b[0].date() == day for b in bars):
        bars, width = px["h"], timedelta(hours=1)
    today = [b for b in bars if b[0].date() == day and b[0] <= T]
    if not today:
        return dict(pct=None, note="정규장 시작 전 또는 휴장")
    done = [b for b in today if b[0] + width <= T]
    cur = [b for b in today if b[0] + width > T]
    pts_hi = [b[2] for b in done] + [b[4] for b in cur]
    pts_lo = [b[3] for b in done] + [b[4] for b in cur]
    last = cur[-1][4] if cur else done[-1][1]
    hi = max(pts_hi)
    lo = min(pts_lo)
    return dict(pct=round(100 * (last / pc - 1), 2),
                high_pct=round(100 * (hi / pc - 1), 2), low_pct=round(100 * (lo / pc - 1), 2))


def sigma20(sym, day):
    px = _PX.get(sym)
    closes = [c for d, c in px["d"] if d < day][-21:]
    if len(closes) < 21:
        return None
    rets = [100 * (closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
    m = sum(rets) / len(rets)
    return round((sum((r - m) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5, 2)


def recent_path(sym, day, n=5):
    px = _PX.get(sym)
    closes = [(d, c) for d, c in px["d"] if d < day][-(n + 1):]
    return [(d.isoformat(), round(100 * (closes[i][1] / closes[i - 1][1] - 1), 2)) for i, (d, _) in enumerate(closes) if i]


def is_trading_day(day):
    return any(d == day for d, _ in _PX["SPY"]["d"])


# ---------- 뉴스 ----------
def gnews(query, start, end):
    """Google News RSS, [start, end] 날짜 창 (after/before는 배타적이라 하루씩 넓힌다)"""
    q = f"{query} after:{(start - timedelta(days=1)).isoformat()} before:{(end + timedelta(days=1)).isoformat()}"

    def go():
        url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + "&hl=en-US&gl=US&ceid=US:en"
        for attempt in range(3):
            f = feedparser.parse(url)
            if f.entries or attempt == 2:
                break
            time.sleep(5)
        time.sleep(1.2)
        out = []
        for e in f.entries:
            pp = e.get("published_parsed")
            if not pp:
                continue
            title = e.get("title", "")
            src = (e.get("source") or {}).get("title", "")
            out.append(dict(date=time.strftime("%Y-%m-%d", pp), title=title, source=src))
        return out
    return _cache("gn|" + q, go)


def sec_filings(ticker):
    def go():
        r = requests.get(f"https://data.sec.gov/submissions/CIK{CIK[ticker]}.json", headers=SEC_UA, timeout=30)
        r.raise_for_status()
        rec = r.json()["filings"]["recent"]
        return [dict(form=f, accepted=a, desc=d) for f, a, d in
                zip(rec["form"], rec["acceptanceDateTime"], rec.get("primaryDocDescription", [""] * len(rec["form"])))]
    return _cache(f"sec|{ticker}|20261018", go)


def earnings_dates(sym):
    def go():
        try:
            df = yf.Ticker(sym).get_earnings_dates(limit=16)
            return [ts.astimezone(ET).isoformat() for ts in df.index]
        except Exception:
            return []
    return _cache(f"earn|{sym}|20261018", go)


def fomc_dates():
    p = r"D:\원드라이브\OneDrive\개발\통합 개발\market-watcher\docs\data\ext\fomc_dates.csv"
    with open(p, encoding="utf-8-sig") as f:
        return {r["Date"] for r in csv.DictReader(f)}


# ---------- 묶음 ----------
def build(ev, fomc):
    tk = ev["ticker"]
    m = META[tk]
    T = datetime.fromisoformat(f"{ev['et_date']}T{ev['et_time']}").replace(tzinfo=ET)
    day = T.date()
    t_utc_day = T.astimezone(timezone.utc).date()
    b = dict(eid=ev["eid"], ticker=tk, name=m["name"], alert_et=T.isoformat(),
             trading_day=is_trading_day(day), weekday=day.strftime("%a"))

    # 시세 — 이 종목·시장·섹터 ETF·동종업체
    syms = [tk] + MARKET + m["etfs"] + m["peers"]
    b["moves_at_alert"] = {s: move_at(s, T) for s in syms}
    b["sigma20"] = sigma20(tk, day)
    b["prev_days"] = recent_path(tk, day)
    last_daily = [(d, c) for d, c in _PX[tk]["d"] if d < day][-2:]
    if len(last_daily) == 2:
        b["last_session"] = dict(date=last_daily[1][0].isoformat(),
                                 pct=round(100 * (last_daily[1][1] / last_daily[0][1] - 1), 2))

    # 일정
    cal = []
    for s in [tk] + m["peers"]:
        for iso in earnings_dates(s):
            d = datetime.fromisoformat(iso)
            if -4 <= (d.date() - day).days <= 7:
                cal.append(dict(symbol=s, earnings_et=d.strftime("%Y-%m-%d %H:%M"), days_from_alert=(d.date() - day).days))
    for k in range(-1, 2):
        dd = (day + timedelta(days=k)).isoformat()
        if dd in fomc:
            cal.append(dict(symbol="FOMC", date=dd, days_from_alert=k))
    b["calendar"] = cal

    # SEC
    filings = []
    for f in sec_filings(tk):
        if f["form"] not in SEC_FORMS and f["form"] != "4":
            continue
        acc = datetime.fromisoformat(f["accepted"].replace("Z", "+00:00")).astimezone(ET)
        if timedelta(0) <= T - acc <= timedelta(days=4) or (day == acc.date() and acc > T):
            filings.append(dict(form=f["form"], accepted_et=acc.strftime("%Y-%m-%d %H:%M"), desc=f["desc"],
                                before_alert=acc <= T))
    b["sec"] = filings

    # 뉴스 — 종목·섹터·시장 (3일 창). 날짜만 있으므로 모드별로 잘라 쓴다.
    start = t_utc_day - timedelta(days=3)
    news = []
    for q, kind in ([(f'"{m["name"]}" stock', "종목"), (f"{tk} stock", "종목")] +
                    [(q, "섹터") for q in m["sector_q"]] + [(q, "시장") for q in MARKET_Q] +
                    [(f"{p} stock", "동종") for p in m["peers"][:2]]):
        for it in gnews(q, start, t_utc_day):
            it = dict(it, kind=kind)
            news.append(it)
    seen, uniq = set(), []
    for n in sorted(news, key=lambda x: x["date"], reverse=True):
        k = n["title"].lower()[:90]
        if k in seen:
            continue
        seen.add(k)
        uniq.append(n)
    b["news_A"] = [n for n in uniq if n["date"] < t_utc_day.isoformat()]
    b["news_B"] = [n for n in uniq if n["date"] <= t_utc_day.isoformat()]
    return b


def main(lo=1, hi=999):
    with open(bt_config.EVENTS, encoding="utf-8") as f:
        events = [e for e in csv.DictReader(f) if lo <= int(e["eid"][1:]) <= hi]
    syms = set(MARKET)
    for m in META.values():
        syms.update(m["etfs"] + m["peers"])
    syms.update(META)
    load_prices(sorted(syms))
    fomc = fomc_dates()
    for ev in events:
        out = os.path.join(BUNDLES, ev["eid"] + ".json")
        b = build(ev, fomc)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(b, f, ensure_ascii=False, indent=1, default=str)
        print(ev["eid"], ev["ticker"], ev["et_date"], "A", len(b["news_A"]), "B", len(b["news_B"]),
              "sec", len(b["sec"]), "cal", len(b["calendar"]), flush=True)


if __name__ == "__main__":
    import sys
    main(*map(int, sys.argv[1:3]))
