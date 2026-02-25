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
    
    # 티커 + 회사명으로 각각 검색
    queries = [ticker, watch.name]
    
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


def collect_sec_edgar(ticker: str, company_name: str = None) -> List[Dict]:
    """SEC EDGAR에서 최근 Filing 확인"""
    watch = WATCHMAP.get(ticker)
    if not company_name and watch:
        company_name = watch.name
    
    results = []
    
    try:
        # EDGAR Full-Text Search API
        url = "https://efts.sec.gov/LATEST/search-index"
        params = {
            "q": f'"{ticker}"',
            "dateRange": "custom",
            "startdt": (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d"),
            "enddt": datetime.utcnow().strftime("%Y-%m-%d"),
            "forms": "8-K,10-Q,10-K,4",
        }
        
        headers = {"User-Agent": "StockSentinel research@example.com"}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            hits = data.get('hits', {}).get('hits', [])
            
            for hit in hits[:10]:
                source = hit.get('_source', {})
                filing = {
                    "ticker": ticker,
                    "timestamp": source.get('file_date', datetime.utcnow().isoformat()),
                    "title": f"[SEC {source.get('form_type', 'Filing')}] {source.get('entity_name', '')}",
                    "summary": source.get('display_names', [''])[0] if source.get('display_names') else '',
                    "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=&dateb=&owner=include&count=10",
                    "source": "sec_edgar",
                    "source_type": "filing",
                    "sentiment": "neutral",
                    "keywords_matched": [source.get('form_type', '')],
                }
                results.append(filing)
            
            print(f"  📋 SEC EDGAR [{ticker}]: {len(results)}건 수집")
        else:
            print(f"  ⚠️ SEC EDGAR 응답 코드: {resp.status_code}")
            
    except Exception as e:
        print(f"  ⚠️ SEC EDGAR 수집 오류: {e}")
    
    return results


def collect_all_news(ticker: str) -> Dict:
    """모든 뉴스 소스에서 종목 관련 뉴스 통합 수집"""
    print(f"\n📡 뉴스 수집 시작: {ticker}")
    
    all_news = {
        "google_news": collect_google_news(ticker),
        "finnhub": collect_finnhub_news(ticker),
        "sec_edgar": collect_sec_edgar(ticker),
    }
    
    total = sum(len(v) for v in all_news.values())
    print(f"  ✅ 총 {total}건 수집 완료")
    
    return all_news


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
    
    # 0. source 태그에서 매체명 추출 (가장 신뢰성 높음)
    if hasattr(entry, 'source'):
        if hasattr(entry.source, 'title'):
            source_name = entry.source.title or ""
        if hasattr(entry.source, 'href') and entry.source.href:
            return entry.source.href, source_name
    
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
