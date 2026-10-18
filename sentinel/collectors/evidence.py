"""
Stock Sentinel — 원인 판정용 증거 수집 (v4)

발송이 확정된 알림에만 호출한다. 매 스캔마다 돌리면 yfinance·SEC 호출이 종목 수만큼 늘어난다.
같은 스캔 안에서 여러 종목이 알림을 내면 시세·속보·업종 뉴스는 한 번만 받는다(모듈 캐시).

층(근거의 신뢰도가 다르다)
  공시   SEC 공시 — 자사·동종업체, 8-K 항목 번호
  평가   증권사 의견 변경·목표가 변경 — yfinance upgrades_downgrades
  예고   실적 일정(자사·동종), FOMC, 옵션 만기
  기사   Finnhub 기사 (발행 시각 확인됨)
  속보   Bluesky 속보 계정 (분 단위 시각)
  시세   5분봉 급변 시각, 동종업체·섹터 선후 관계

백테스트(eval/결과_v4.md)에서 이 증거를 쓴 알림 시점 판정이 엄격 43~46%로, 기사만 보던 v1(31%)보다 높았다.
"""
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests
import yfinance as yf

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except ImportError:
    ET = timezone(timedelta(hours=-4))

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
SEC_HEADERS = {"User-Agent": "StockSentinel research research@example.com"}

# 주가를 움직이는 공시만. Form 4(임원 지분)·144는 정기적이라 원인 후보에서 뺀다.
SEC_FORMS = {"8-K", "6-K", "10-Q", "10-K", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A",
             "S-3", "S-3ASR", "424B2", "424B5", "DEF 14A", "425"}
ITEMS = {
    "1.01": "중요 계약 체결", "1.02": "중요 계약 종료", "1.05": "사이버보안 사고", "2.01": "인수·매각 완료",
    "2.02": "실적 발표", "2.03": "채무 발생", "2.05": "구조조정 비용", "2.06": "자산 손상",
    "3.01": "상장 관련 통지", "3.02": "미등록 증권 발행", "5.02": "임원·이사 변동", "5.03": "정관 변경",
    "5.07": "주주총회 결과", "7.01": "공정공시(Reg FD)", "8.01": "기타 중요 사건",
}
ACTION_KR = {"up": "상향", "down": "하향", "init": "커버리지 개시", "main": "유지(목표가 변경)", "reit": "재확인"}

# 속보 계정 (Bluesky 공개 API, 인증 불필요). skybrg는 블룸버그식 헤드라인이다.
BREAKING_ACCOUNTS = ["skybrg.bsky.social", "livesquawknews.bsky.social", "unusualwhales.bsky.social"]
MACRO_RX = re.compile(
    r"\bCPI\b|\bPPI\b|payroll|jobs report|unemployment|\bFed\b|FOMC|Powell|Warsh|rate (hike|cut)|"
    r"yield|Treasur|oil|Brent|WTI|Iran|Hormuz|tariff|Trump|Nasdaq|S&P 500|stocks? (fall|drop|slide|rally|jump)|"
    r"\bAI\b|Anthropic|OpenAI", re.I)

# 회사 이름 — 속보·기사 제목에서 동종업체를 알아보기 위해. 없으면 티커로만 찾는다.
NAMES = {
    "MU": "Micron", "AVGO": "Broadcom", "QCOM": "Qualcomm", "PANW": "Palo Alto", "NET": "Cloudflare",
    "AMZN": "Amazon", "NFLX": "Netflix", "AMAT": "Applied Materials", "NVDA": "Nvidia", "AMD": "AMD",
    "MRVL": "Marvell", "ARM": "Arm Holdings", "SWKS": "Skyworks", "AAPL": "Apple", "WDC": "Western Digital",
    "SNDK": "Sandisk", "STX": "Seagate", "CRWD": "CrowdStrike", "ZS": "Zscaler", "FTNT": "Fortinet",
    "AKAM": "Akamai", "DDOG": "Datadog", "MSFT": "Microsoft", "GOOGL": "Google|Alphabet", "META": "Meta",
    "DIS": "Disney", "WBD": "Warner Bros", "ROKU": "Roku", "SPOT": "Spotify", "LRCX": "Lam Research",
    "KLAC": "KLA", "ASML": "ASML", "TSM": "TSMC|Taiwan Semiconductor",
}
# 섹터 ETF별 업종 뉴스 검색어 · 업종 단어(속보 분류용) · 함께 볼 ETF
SECTOR = {
    "SOXX": dict(queries=["semiconductor stocks", "chip stocks"], words=r"chip|semiconductor|memory|DRAM|HBM|wafer", etfs=["SOXX"]),
    "CIBR": dict(queries=["cybersecurity stocks", "software stocks"], words=r"cyber|security|hack|software", etfs=["CIBR", "IGV"]),
    "IGV": dict(queries=["software stocks"], words=r"software|cloud|SaaS", etfs=["IGV"]),
    "XLC": dict(queries=["streaming stocks", "media stocks"], words=r"stream|media|YouTube", etfs=["XLC"]),
    "QQQ": dict(queries=["megacap tech stocks"], words=r"megacap|Magnificent|big tech|cloud|AWS", etfs=["QQQ"]),
    "XLY": dict(queries=["megacap tech stocks"], words=r"megacap|Magnificent|retail|e-commerce", etfs=["XLY"]),
}
MARKET_QUERIES = ["stock market today", "Nasdaq stocks"]

# FOMC 결정일 (Fed 발표 일정). 2027년 말 이후 날짜는 추가할 것.
FOMC_DATES = {
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28",
    "2026-12-09", "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15",
    "2027-10-27", "2027-12-08",
}

_CACHE: Dict[str, object] = {}


def _cached(key, fn):
    if key not in _CACHE:
        try:
            _CACHE[key] = fn()
        except Exception as e:
            print(f"  ⚠️ 증거 수집 실패 [{key}]: {type(e).__name__}: {e}")
            _CACHE[key] = None
    return _CACHE[key]


# ── 평가: 증권사 의견 변경 ──

def ratings(sym: str) -> List[Dict]:
    """최근 의견·목표가 변경. yfinance 기록 시각은 시간대 표기가 없지만 UTC다(장전 보도 시각과 대조해 확인)."""
    def go():
        d = yf.Ticker(sym).upgrades_downgrades
        if d is None or len(d) == 0:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=5)
        out = []
        for ts, r in d.iterrows():
            t = ts.to_pydatetime()
            t = (t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t).astimezone(ET)
            if t < cutoff:
                continue
            pt, prior = float(r.get("currentPriceTarget") or 0), float(r.get("priorPriceTarget") or 0)
            out.append(dict(t=t, sym=sym, firm=str(r.get("Firm", "")), action=str(r.get("Action", "")),
                            to=str(r.get("ToGrade", "")), frm=str(r.get("FromGrade", "")),
                            pt=pt, prior=prior, pt_change=bool(pt and prior and pt != prior)))
        return sorted(out, key=lambda x: x["t"], reverse=True)
    return _cached(f"ratings|{sym}", go) or []


# ── 공시: SEC ──

def _sec_time(raw: str) -> datetime:
    """submissions JSON의 acceptanceDateTime은 'Z'가 붙어 있지만 UTC가 아니다.
    공시 헤더(ACCEPTANCE-DATETIME, 동부시각)와 대조하면 '실제 UTC + 동부시각 오프셋'으로 찍혀 있다
    (EDT +4h, EST +5h. 예: 헤더 2026-09-08 09:00:20 ↔ JSON 17:00:20Z, 헤더 2026-01-21 16:05:37 ↔ JSON 01-22 02:05:37Z).
    그래서 오프셋을 한 번 빼서 실제 UTC를 만든 뒤 동부시각으로 바꾼다."""
    naive = datetime.fromisoformat(raw.replace("Z", "")[:19])
    off = ET.utcoffset(naive) if hasattr(ET, "utcoffset") else timedelta(hours=-4)
    true_utc = (naive + off).replace(tzinfo=timezone.utc)
    return true_utc.astimezone(ET)


def sec_filings(sym: str) -> List[Dict]:
    def go():
        from collectors.news_collector import _load_cik_map
        cik = _load_cik_map().get(sym)
        if not cik:
            return []
        r = requests.get(f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json",
                         headers=SEC_HEADERS, timeout=15)
        r.raise_for_status()
        rec = r.json()["filings"]["recent"]
        cutoff = (datetime.now(ET) - timedelta(days=5)).date().isoformat()
        n = len(rec["form"])
        items = rec.get("items") or [""] * n
        out = []
        for i in range(n):
            if rec["filingDate"][i] < cutoff:
                break
            if rec["form"][i] not in SEC_FORMS:
                continue
            codes = [c.strip() for c in (items[i] or "").split(",") if c.strip() and c.strip() != "9.01"]
            out.append(dict(t=_sec_time(rec["acceptanceDateTime"][i]), sym=sym, form=rec["form"][i],
                            items=", ".join(f"{c} {ITEMS.get(c, '')}".strip() for c in codes)))
        return out
    return _cached(f"sec|{sym}", go) or []


# ── 기사: Finnhub (발행 시각) ──

def finnhub_articles(sym: str) -> List[Dict]:
    if not FINNHUB_API_KEY:
        return []

    def go():
        today = datetime.now(timezone.utc).date()
        r = requests.get("https://finnhub.io/api/v1/company-news", timeout=15, params={
            "symbol": sym, "from": (today - timedelta(days=2)).isoformat(), "to": today.isoformat(),
            "token": FINNHUB_API_KEY})
        r.raise_for_status()
        return [dict(t=datetime.fromtimestamp(a["datetime"], tz=timezone.utc).astimezone(ET), sym=sym,
                     headline=" ".join((a.get("headline") or "").split()), source=a.get("source", ""),
                     url=a.get("url", ""))
                for a in r.json() if a.get("datetime") and a.get("headline")]
    return _cached(f"finnhub|{sym}", go) or []


# ── 예고: 일정 ──

def earnings_dates(sym: str) -> List[datetime]:
    def go():
        df = yf.Ticker(sym).get_earnings_dates(limit=8)
        return [ts.to_pydatetime().astimezone(ET) for ts in df.index] if df is not None else []
    return _cached(f"earn|{sym}", go) or []


def _third_friday(y: int, m: int) -> date:
    d = date(y, m, 15)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def calendar_lines(ticker: str, peers: List[str], day: date) -> List[str]:
    out = []
    for s in [ticker] + peers:
        for t in earnings_dates(s):
            k = (t.date() - day).days
            if -4 <= k <= 7:
                out.append(f"- {s} 실적 {t:%Y-%m-%d %H:%M} ET ({k:+d}일)")
    for k in (-1, 0, 1):
        d = day + timedelta(days=k)
        if d.isoformat() in FOMC_DATES:
            out.append(f"- FOMC 결정 {d.isoformat()} 14:00 ET ({k:+d}일)")
    opex = _third_friday(day.year, day.month)
    if abs((opex - day).days) <= 1:
        kind = "분기 옵션 동시 만기(쿼드러플 위칭)" if day.month in (3, 6, 9, 12) else "월간 옵션 만기"
        out.append(f"- {kind} {opex.isoformat()} ({(opex - day).days:+d}일)")
    return out


# ── 시세: 5분봉 급변 시각 ──

def intraday(symbols: List[str]) -> Dict[str, Dict]:
    """오늘 정규장 5분봉으로 종목별 움직임 시각을 잰다. 한 번에 받아 캐시한다."""
    key = "intraday|" + ",".join(sorted(set(symbols)))

    def go():
        data = yf.download(sorted(set(symbols)), period="5d", interval="5m", auto_adjust=False,
                           progress=False, threads=True, group_by="ticker")
        out = {}
        for s in set(symbols):
            try:
                df = data[s].dropna() if len(set(symbols)) > 1 else data.dropna()
                idx = df.index.tz_convert(ET)
                days = sorted({t.date() for t in idx})
                if len(days) < 2:
                    continue
                today, prev = days[-1], days[-2]
                pc = float(df["Close"][[t.date() == prev for t in idx]].iloc[-1])
                td = df[[t.date() == today for t in idx]]
                tidx = td.index.tz_convert(ET)
                path = [(t + timedelta(minutes=5), 100 * (float(c) / pc - 1)) for t, c in zip(tidx, td["Close"])]
                last = path[-1][1]
                half = next((t for t, p in path if abs(last) >= 0.5 and p * last > 0 and abs(p) >= abs(last) / 2), None)
                big, big_t = 0.0, None
                for i in range(3, len(path)):
                    dlt = path[i][1] - path[i - 3][1]
                    if abs(dlt) > abs(big):
                        big, big_t = dlt, path[i][0]
                out[s] = dict(date=today.isoformat(), open_pct=round(100 * (float(td["Open"].iloc[0]) / pc - 1), 2),
                              last=round(last, 2), high=round(max(p for _, p in path), 2),
                              low=round(min(p for _, p in path), 2),
                              half=half.strftime("%H:%M") if half else None,
                              big=round(big, 2), big_t=big_t.strftime("%H:%M") if big_t else None)
            except Exception:
                continue
        return out
    return _cached(key, go) or {}


# ── 속보·업종/시장 뉴스 ──

def breaking_posts() -> List[Dict]:
    def go():
        out = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=60)
        for actor in BREAKING_ACCOUNTS:
            try:
                r = requests.get("https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed", timeout=15,
                                 params={"actor": actor, "limit": 100, "filter": "posts_no_replies"})
                r.raise_for_status()
                for it in r.json().get("feed", []):
                    rec = it["post"]["record"]
                    t = datetime.fromisoformat(rec.get("createdAt", "").replace("Z", "+00:00"))
                    if t >= cutoff:
                        out.append(dict(t=t.astimezone(ET), src=actor.split(".")[0], text=" ".join(rec.get("text", "").split())))
            except Exception as e:
                print(f"  ⚠️ 속보 수집 실패 [{actor}]: {e}")
        return sorted(out, key=lambda p: p["t"], reverse=True)
    return _cached("breaking", go) or []


def google_news(query: str) -> List[Dict]:
    """업종·시장 뉴스. 실시간 RSS의 pubDate는 실제 발행 시각이다(과거 검색과 달리 날짜로 뭉개지지 않는다)."""
    def go():
        import feedparser
        from urllib.parse import quote
        f = feedparser.parse(f"https://news.google.com/rss/search?q={quote(query + ' when:2d')}&hl=en-US&gl=US&ceid=US:en")
        out = []
        for e in f.entries[:40]:
            pp = e.get("published_parsed")
            if not pp:
                continue
            t = datetime(*pp[:6], tzinfo=timezone.utc).astimezone(ET)
            out.append(dict(t=t, title=e.get("title", ""), url=e.get("link", "")))
        return out
    return _cached(f"gnews|{query}", go) or []
