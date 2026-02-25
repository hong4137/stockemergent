"""
Stock Sentinel — AI Summarizer
OpenAI gpt-4.1-mini 기반 한국어 요약 엔진
"""
import os
import json
from typing import Dict, List, Optional
from urllib.parse import urlparse


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")


def _is_valid_article_url(url: str) -> bool:
    """실제 기사 URL인지 검증"""
    if not url:
        return False
    bad = ["news.google.com/rss", "finnhub.io/api", "googleapis.com"]
    if any(p in url for p in bad):
        return False
    path = urlparse(url).path.strip("/")
    if not path or len(path) < 3:
        return False
    return True


def summarize_event(
    ticker: str,
    news_data: List[Dict],
    price_data: Dict = None,
) -> Optional[Dict]:
    """뉴스 + 가격 → 한국어 2줄 요약 (OpenAI)"""
    if not OPENAI_API_KEY:
        print("  ⚠️ OPENAI_API_KEY 없음 → 규칙 기반 폴백")
        return _fallback_summary(ticker, news_data, price_data)

    try:
        import httpx

        # 뉴스 상위 10건 정리
        news_text = ""
        valid_urls = []
        for i, n in enumerate(news_data[:10]):
            title = n.get("title", n.get("headline", ""))
            source = n.get("source", "")
            url = n.get("url", n.get("source_url", ""))
            summary = n.get("summary", "")[:100]
            news_text += f"{i+1}. [{source}] {title}"
            if summary:
                news_text += f" — {summary}"
            news_text += "\n"
            if _is_valid_article_url(url):
                valid_urls.append(url)

        # 가격 정보
        price_text = ""
        if price_data:
            pct = price_data.get("change_pct", 0)
            vol = price_data.get("volume_ratio", 1)
            rev = price_data.get("intraday_reversal", 0)
            price_text = f"전일 대비: {pct:+.1f}%, 거래량 비율: {vol:.1f}x"
            if abs(rev) >= 2:
                price_text += f", 장중 반전: {rev:+.1f}%"

        prompt = f"""당신은 주식 시장 분석가입니다.
{ticker} 관련 뉴스와 가격 데이터를 분석하여 JSON으로만 답하세요.

뉴스:
{news_text}

가격: {price_text}

JSON 형식:
{{
  "headline": "핵심 이유 한 줄 (한국어, 20자 이내)",
  "detail": "부연 설명 1~2문장 (배경/맥락 포함, 한국어)",
  "classification": "Catalyst 또는 Fracture 또는 Noise",
  "confidence": 0.0~1.0,
  "event_type": "earnings/partnership/regulatory/macro/analyst/product/restructuring/other"
}}

JSON만 출력하고 다른 텍스트는 쓰지 마세요."""

        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4.1-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
                "temperature": 0.3,
            },
            timeout=15,
        )

        if response.status_code != 200:
            print(f"  ⚠️ OpenAI API 오류 {response.status_code}")
            return _fallback_summary(ticker, news_data, price_data)

        content = response.json()["choices"][0]["message"]["content"].strip()

        # JSON 파싱 (```json ``` 래핑 제거)
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content.rsplit("```", 1)[0]
        content = content.strip()

        result = json.loads(content)
        result["ai_generated"] = True
        result["source_count"] = len(news_data)
        result["key_source"] = valid_urls[0] if valid_urls else ""

        cls = result.get("classification", "Noise")
        conf = result.get("confidence", 0.5)
        print(f"  🤖 AI: {result.get('headline', '')} [{cls} {conf:.0%}]")

        return result

    except Exception as e:
        print(f"  ⚠️ AI 요약 오류: {e}")
        return _fallback_summary(ticker, news_data, price_data)


def _fallback_summary(
    ticker: str, news_data: List[Dict], price_data: Dict = None
) -> Dict:
    """AI 실패 시 규칙 기반 폴백"""
    headline = "주요 신호 발생"
    detail = ""
    classification = "Noise"
    confidence = 0.5

    if price_data:
        pct = price_data.get("change_pct", 0)
        rev = price_data.get("intraday_reversal", 0)

        if abs(pct) >= 3:
            direction = "상승" if pct > 0 else "하락"
            headline = f"주가 {abs(pct):.1f}% {direction}"
            classification = "Catalyst" if pct > 0 else "Fracture"
            confidence = min(0.6 + abs(pct) / 20, 0.9)

        if abs(rev) >= 3 and abs(rev) > abs(pct):
            if rev < 0:
                headline = f"장중 고점 대비 {abs(rev):.1f}% 급락"
                classification = "Fracture"
            else:
                headline = f"장중 저점 대비 {abs(rev):.1f}% 급반등"
                classification = "Catalyst"
            confidence = min(0.6 + abs(rev) / 20, 0.9)

    if news_data:
        first = news_data[0]
        title = first.get("title", first.get("headline", ""))
        if title and not detail:
            detail = f"{ticker} 관련 {len(news_data)}건의 뉴스가 감지됨."

    # 유효한 URL 찾기
    key_source = ""
    for n in news_data[:5]:
        url = n.get("url", n.get("source_url", ""))
        if _is_valid_article_url(url):
            key_source = url
            break

    return {
        "headline": headline,
        "detail": detail,
        "classification": classification,
        "confidence": confidence,
        "event_type": "other",
        "ai_generated": False,
        "source_count": len(news_data),
        "key_source": key_source,
    }
