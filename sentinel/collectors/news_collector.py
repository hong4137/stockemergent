"""
Stock Sentinel — News Collector
뉴스/공시 수집: Google News RSS, Finnhub, SEC EDGAR
"""
import feedparser
import requests
import json
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import time

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import (
    WATCHMAP, NEWS_RSS_FEEDS, FINNHUB_API_KEY,
    BREAKING_KEYWORDS, POSITIVE_KEYWORDS, NEGATIVE_KEYWORDS
)


def collect_google_news(ticker: str, hours: int = 24) -> List[Dict]:
    """Google News RSS로 종목 관련 뉴스 수집"""
    watch = WATCHMAP.get(ticker)
    if not watch:
        return []
    
    results = []

    # 티커 + 영문 회사명으로 각각 검색 (한글 표시명은 영문 뉴스 검색에 쓸 수 없다)
    queries = _search_terms(ticker)

    for query in queries:
        safe_query = query.replace(" ", "+")
        url = f"https://news.google.com/rss/search?q={safe_query}+stock&hl=en-US&gl=US&ceid=US:en"
        try:
            feed = feedparser.parse(url)
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            
            for entry in feed.entries[:20]:  # 최대 20개
                # 발행 시간 파싱
                pub_time = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_time = datetime(*entry.published_parsed[:6])
                else:
                    pub_time = datetime.utcnow()
                
                if pub_time < cutoff:
                    continue
                
                title = entry.get('title', '')
                link, source_name = _resolve_google_news_url(entry)
                summary = entry.get('summary', '')
                
                # title에서 " - 매체명" 분리
                clean_title = title
                if ' - ' in title and not source_name:
                    clean_title, source_name = title.rsplit(' - ', 1)
                    source_name = source_name.strip()
                elif ' - ' in title:
                    clean_title = title.rsplit(' - ', 1)[0]
                
                # 키워드 매칭
                text = (title + " " + summary).lower()
                matched_keywords = [kw for kw in (watch.keywords + [ticker, watch.name])
                                   if kw.lower() in text]
                
                # 센티멘트 간이 판정
                sentiment = _simple_sentiment(text)
                
                article = {
                    "ticker": ticker,
                    "timestamp": pub_time.isoformat(),
                    "title": _clean_html(clean_title),
                    "summary": _clean_html(summary)[:500],
                    "url": link,
                    "source": f"google_news:{source_name}" if source_name else "google_news",
                    "source_type": "news",
                    "sentiment": sentiment,
                    "keywords_matched": matched_keywords,
                }
                results.append(article)
                
            time.sleep(1)  # Rate limit
            
        except Exception as e:
            print(f"  ⚠️ Google News 수집 오류 ({query}): {e}")
    
    # URL 기준 중복 제거
    seen = set()
    unique = []
    for r in results:
        if r['url'] not in seen:
            seen.add(r['url'])
            unique.append(r)
    
    print(f"  📰 Google News [{ticker}]: {len(unique)}건 수집")
    return unique


def collect_finnhub_news(ticker: str, hours: int = 72) -> List[Dict]:
    """Finnhub API로 뉴스 수집 (무료 티어)"""
    if not FINNHUB_API_KEY:
        print(f"  ⚠️ Finnhub API 키 미설정 — 건너뜀")
        return []
    
    watch = WATCHMAP.get(ticker)
    results = []
    
    now = datetime.utcnow()
    from_date = (now - timedelta(hours=hours)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")
    
    try:
        url = f"https://finnhub.io/api/v1/company-news"
        params = {
            "symbol": ticker,
            "from": from_date,
            "to": to_date,
            "token": FINNHUB_API_KEY,
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        articles = resp.json()
        
        for a in articles[:30]:
            pub_time = datetime.fromtimestamp(a.get('datetime', 0))
            title = a.get('headline', '')
            summary = a.get('summary', '')
            link = a.get('url', '')
            source_name = a.get('source', 'finnhub')
            
            text = (title + " " + summary).lower()
            matched_keywords = []
            if watch:
                matched_keywords = [kw for kw in watch.keywords if kw.lower() in text]
            
            sentiment = _simple_sentiment(text)
            
            article = {
                "ticker": ticker,
                "timestamp": pub_time.isoformat(),
                "title": title,
                "summary": summary[:500],
                "url": link,
                "source": f"finnhub:{source_name}",
                "source_type": "news",
                "sentiment": sentiment,
                "keywords_matched": matched_keywords,
            }
            results.append(article)
        
        print(f"  📰 Finnhub [{ticker}]: {len(results)}건 수집")
        
    except Exception as e:
        print(f"  ⚠️ Finnhub 수집 오류: {e}")
    
    return results


SEC_HEADERS = {"User-Agent": "StockSentinel research@example.com"}

# 주가를 움직이는 서식만. Form 4(내부자), 144(매도예정), 13G 등 상시 제출물은 제외한다.
SEC_MATERIAL_FORMS = {"8-K", "10-K", "10-Q", "6-K", "20-F", "SC 13D", "425", "DEFA14A"}


def _load_cik_map() -> Dict:
    """티커 → CIK(10자리) 매핑. SEC 전체 목록을 받아 7일간 캐시한다."""
    from storage.database import get_meta, set_meta

    today = datetime.utcnow().strftime("%Y-%m-%d")
    cached, cached_at = get_meta("cik_map"), get_meta("cik_map_date")
    if cached and cached_at:
        age = (datetime.utcnow() - datetime.strptime(cached_at, "%Y-%m-%d")).days
        if age < 7:
            try:
                return json.loads(cached)
            except Exception:
                pass

    try:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_HEADERS, timeout=15,
        )
        resp.raise_for_status()
        mapping = {
            row["ticker"].upper(): str(row["cik_str"]).zfill(10)
            for row in resp.json().values()
        }
        set_meta("cik_map", json.dumps(mapping))
        set_meta("cik_map_date", today)
        return mapping
    except Exception as e:
        print(f"  ⚠️ CIK 목록 조회 실패: {e}")
        try:
            return json.loads(cached) if cached else {}
        except Exception:
            return {}


def collect_sec_edgar(ticker: str, company_name: str = None, days: int = 7) -> List[Dict]:
    """SEC EDGAR 최근 공시.

    과거에는 full-text search 엔드포인트에 `q="{ticker}"` 로 질의했는데,
    (1) 티커 문자열이 들어간 '남의 회사 공시'까지 딸려오고
    (2) 응답 필드명이 form_type/entity_name 이 아니라 form/display_names 라
    제목이 전부 빈 문자열로 들어왔다. 그 결과 공시가 뉴스 건수만 부풀리고
    fact 점수에는 전혀 기여하지 못했다.

    회사 단위 공식 API(data.sec.gov/submissions)로 교체해 정확한 서식·날짜·
    문서 URL을 얻는다.
    """
    results = []
    cik = _load_cik_map().get(ticker.upper())
    if not cik:
        print(f"  ⚠️ SEC CIK 없음: {ticker}")
        return results

    try:
        resp = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=SEC_HEADERS, timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        name = data.get("name", company_name or ticker)
        recent = data.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accs = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])
        descs = recent.get("primaryDocDescription", [])
        items = recent.get("items", [])

        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

        for i, form in enumerate(forms):
            if dates[i] < cutoff:
                break  # 최신순 정렬이므로 더 볼 필요 없음
            if form not in SEC_MATERIAL_FORMS:
                continue

            acc_nodash = accs[i].replace("-", "")
            doc = docs[i] if i < len(docs) else ""
            url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                   f"{acc_nodash}/{doc}") if doc else \
                  (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}")

            desc = descs[i] if i < len(descs) else ""
            item = items[i] if i < len(items) else ""

            results.append({
                "ticker": ticker,
                "timestamp": dates[i],
                # 관련성 필터가 회사를 식별할 수 있도록 제목에 회사명을 넣는다
                "title": f"[SEC {form}] {name}" + (f" — {desc}" if desc else ""),
                "summary": f"Item {item}" if item else "",
                "url": url,
                "source": "sec_edgar",
                "source_type": "filing",
                "sentiment": "neutral",
                "keywords_matched": [form],
            })

        print(f"  📋 SEC EDGAR [{ticker}]: {len(results)}건 (최근 {days}일 주요 서식)")

    except Exception as e:
        print(f"  ⚠️ SEC EDGAR 수집 오류: {e}")

    return results


def _is_ascii(s: str) -> bool:
    return bool(s) and all(ord(c) < 128 for c in s)


def _aliases(ticker: str) -> tuple:
    """종목 식별용 별칭. (대소문자 구분 티커, 소문자 이름들)

    티커는 대소문자를 구분해 단어 경계로 찾는다. NET/MU 같은 짧은 티커를
    소문자까지 허용하면 'net income', 'mu' 같은 일반 단어에 전부 걸린다.
    """
    watch = WATCHMAP.get(ticker)
    names = []
    if not watch:
        return ticker, names

    name = (watch.name or "").strip()
    if _is_ascii(name) and name.upper() != ticker:
        names.append(name.lower())
        first = name.split()[0]
        # 'Palo'(4) 같은 짧은 조각은 오탐이 많아 제외
        if len(first) >= 5:
            names.append(first.lower())
    elif name:
        # 표시명이 한글인 종목(예: PANW '팔로알토 네트웍스')은 영문 기사와 대조할 수
        # 없다. 이때만 키워드의 영문 명칭을 별칭으로 쓴다. 항상 키워드를 쓰면
        # 'memory' 같은 일반어가 게이트를 뚫는다.
        for k in watch.keywords or []:
            k = (k or "").strip()
            if _is_ascii(k) and len(k) >= 5 and k.upper() != ticker:
                names.append(k.lower())

    # 'Netflix'처럼 한 단어 이름은 전체명과 첫 단어가 같아 중복된다
    return ticker, list(dict.fromkeys(names))


def _search_terms(ticker: str) -> List[str]:
    """Google News 검색어. 영문 명칭이 없으면 티커만 쓴다."""
    _, names = _aliases(ticker)
    terms = [ticker]
    # 가장 긴 영문 명칭 하나 (예: 'palo alto networks')
    ascii_names = [n for n in names if " " in n] or names
    if ascii_names:
        terms.append(max(ascii_names, key=len))
    return terms


def _relevance_score(article: Dict, ticker: str) -> float:
    """기사가 이 종목 이야기인지 0~1로 채점. 0이면 버린다.

    실측상 수집 기사의 21%가 종목과 무관했다(예: MU 알림의 1순위 근거가
    '한국 증시 3.5% 상승'). 이 오염이 PSI 점수와 AI 요약 입력을 동시에 망친다.
    """
    tk, names = _aliases(ticker)
    title = article.get("title", "") or ""
    summary = article.get("summary", "") or ""
    blob = f"{title} {summary}"
    blob_lower = blob.lower()

    # ── 게이트: 티커(단어경계, 대소문자 구분) 또는 회사명이 있어야 통과 ──
    has_ticker = re.search(rf"\b{re.escape(tk)}\b", blob) is not None
    has_name = any(n in blob_lower for n in names)

    if not has_ticker and not has_name:
        return 0.0

    score = 0.5
    # 제목에 등장하면 본문에만 있는 것보다 훨씬 관련성이 높다
    title_lower = title.lower()
    if re.search(rf"\b{re.escape(tk)}\b", title) or any(n in title_lower for n in names):
        score += 0.3
    if has_ticker and has_name:
        score += 0.1

    # 공시는 항상 우선
    if article.get("source_type") == "filing":
        score += 0.2

    watch = WATCHMAP.get(ticker)
    if watch and watch.keywords:
        hits = sum(1 for k in watch.keywords if k and k.lower() in blob_lower)
        score += min(hits * 0.05, 0.15)

    if has_breaking_keywords(blob):
        score += 0.1

    return min(score, 1.0)


def _dedupe(articles: List[Dict]) -> List[Dict]:
    """URL + 제목 기준 중복 제거.

    같은 기사가 Google News와 Finnhub 양쪽에서 들어오면 뉴스 건수가 부풀고,
    그 건수가 PSI 점수에 그대로 반영된다.
    """
    seen_url, seen_title = set(), set()
    out = []
    for a in articles:
        url = (a.get("url") or "").split("?")[0].rstrip("/")
        # 제목 정규화: 소문자 + 영숫자만
        title_key = re.sub(r"[^a-z0-9]", "", (a.get("title") or "").lower())[:60]
        if url and url in seen_url:
            continue
        if title_key and title_key in seen_title:
            continue
        if url:
            seen_url.add(url)
        if title_key:
            seen_title.add(title_key)
        out.append(a)
    return out


def collect_all_news(ticker: str) -> Dict:
    """모든 뉴스 소스에서 종목 관련 뉴스 통합 수집 + 관련성 필터 + 중복 제거"""
    print(f"\n📡 뉴스 수집 시작: {ticker}")

    raw = (
        collect_google_news(ticker)
        + collect_finnhub_news(ticker)
        + collect_sec_edgar(ticker)
    )
    raw_count = len(raw)

    deduped = _dedupe(raw)

    scored = []
    for a in deduped:
        s = _relevance_score(a, ticker)
        if s <= 0:
            continue
        a["relevance"] = round(s, 2)
        scored.append(a)

    # 관련도 높은 순 — AI 요약은 상위 10건만 보므로 정렬이 곧 입력 품질이다
    scored.sort(key=lambda x: x["relevance"], reverse=True)

    dropped_dup = raw_count - len(deduped)
    dropped_irr = len(deduped) - len(scored)
    print(f"  ✅ {raw_count}건 수집 → 중복 {dropped_dup}건, 무관 {dropped_irr}건 제외 "
          f"→ {len(scored)}건 사용")

    # 기존 호출부가 .values()로 순회하므로 dict 형태를 유지한다
    return {"filtered": scored}


# ============================================================
# 유틸리티
# ============================================================

def _resolve_google_news_url(entry) -> tuple:
    """
    Google News RSS에서 실제 기사 URL + 매체명 추출
    Returns: (url, source_name)
    """
    link = entry.get('link', '')
    source_name = ""

    # 0. source 태그에서 매체명만 추출.
    #    entry.source.href는 기사 주소가 아니라 언론사 대문(예: https://www.fool.com)이다.
    #    이걸 기사 URL로 반환하면 이후 _is_article_url() 필터에 걸려 링크가 통째로 사라진다.
    #    (실측: 수집 URL의 76%가 이 경로로 대문 주소가 됐다)
    if hasattr(entry, 'source') and hasattr(entry.source, 'title'):
        source_name = entry.source.title or ""

    # 1. title에서 매체명 추출 ("... - Reuters" 패턴)
    title = entry.get('title', '')
    if ' - ' in title:
        source_name = source_name or title.rsplit(' - ', 1)[-1].strip()
    
    # 2. summary/description에서 실제 URL 추출
    summary = entry.get('summary', '') or entry.get('description', '')
    if summary:
        match = re.search(r'href="(https?://(?!news\.google\.com)[^"]+)"', summary)
        if match:
            return match.group(1), source_name
    
    # 3. Google News 리다이렉트 → HEAD 요청
    if 'news.google.com' in link:
        try:
            resp = requests.head(link, allow_redirects=True, timeout=5,
                                headers={"User-Agent": "Mozilla/5.0"})
            if resp.url and 'news.google.com' not in resp.url:
                return resp.url, source_name
        except:
            pass
    
    return link, source_name

def _simple_sentiment(text: str) -> str:
    """간단한 키워드 기반 센티멘트 판정"""
    text_lower = text.lower()
    
    pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw.lower() in text_lower)
    neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw.lower() in text_lower)
    
    if pos_count > neg_count + 1:
        return "positive"
    elif neg_count > pos_count + 1:
        return "negative"
    return "neutral"


def has_breaking_keywords(text: str) -> bool:
    """현장성 키워드 포함 여부"""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in BREAKING_KEYWORDS)


def _clean_html(text: str) -> str:
    """HTML 태그 제거"""
    return re.sub(r'<[^>]+>', '', text).strip()


# ============================================================
# 테스트
# ============================================================
if __name__ == "__main__":
    from storage.database import init_db
    init_db()
    
    result = collect_all_news("AMAT")
    
    for source, articles in result.items():
        print(f"\n--- {source} ---")
        for a in articles[:3]:
            print(f"  [{a['sentiment']}] {a['title'][:80]}")
