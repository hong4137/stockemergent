"""
Stock Sentinel — AI 요약 엔진 v2
환각 방지: 수집된 뉴스에 언급된 팩트만 사용, 추측/일반론 금지
"""
import os
import json
import requests
from typing import Dict, List, Optional
from urllib.parse import urlparse

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL = "gpt-4.1-mini"


def _is_valid_article_url(url: str) -> bool:
    if not url:
        return False
    bad = ["news.google.com/rss", "finnhub.io/api"]
    if any(p in url for p in bad):
        return False
    try:
        path = urlparse(url).path.strip("/")
        return bool(path) and len(path) >= 3
    except:
        return False


def summarize_event(ticker: str, news_data: List[Dict], price_data: Dict = None) -> Dict:
    """
    뉴스 + 가격 → 한국어 요약.
    핵심 원칙: 수집된 뉴스에 있는 정보만 사용. 추측/일반론 절대 금지.
    """
    if not OPENAI_API_KEY:
        return _fallback_summary(ticker, news_data, price_data)

    # 뉴스 텍스트 (최대 10건)
    news_text = ""
    sources = []
    for i, article in enumerate(news_data[:10]):
        title = article.get("title", "").strip()
        summary = article.get("summary", "").strip()[:200]
        source = article.get("source", "")
        url = article.get("url", "")
        sentiment = article.get("sentiment", "")

        news_text += f"[{i+1}] {title}\n"
        if summary:
            news_text += f"    {summary}\n"
        news_text += f"    출처: {source} | 센티멘트: {sentiment}\n\n"

        if url and _is_valid_article_url(url):
            sources.append(url)

    # 가격 정보
    price_info = ""
    if price_data:
        change = price_data.get("change_pct", 0)
        vol = price_data.get("volume_ratio", 1.0)
        latest = price_data.get("latest", {})
        close = latest.get("close", 0) if latest else 0
        direction = "상승" if change > 0 else "하락" if change < 0 else "보합"
        price_info = f"현재가: ${close:.2f} | 변동: {change:+.1f}% ({direction}) | 거래량: 평균 대비 {vol:.1f}배"

    # ═══ 환각 방지 프롬프트 ═══
    prompt = f"""아래 {ticker} 관련 뉴스를 분석하여 JSON으로 답하세요.

## 절대 규칙
1. headline과 detail은 반드시 아래 뉴스 목록에 나온 정보만 사용할 것
2. 뉴스에 없는 추측, 전망, 일반론 절대 금지 (예: "AI 수요 확대", "시장 성장 전망" 등 삽입 금지)
3. 어떤 뉴스가 가장 직접적인 원인인지 번호로 명시할 것
4. 뉴스에서 구체적 원인을 찾을 수 없으면 headline을 "원인 미확인 — 추가 확인 필요"로 작성

## 가격 데이터
{price_info or "없음"}

## 최근 뉴스
{news_text}

## JSON 형식 (다른 텍스트 없이 JSON만):
{{
  "headline": "뉴스에서 확인된 핵심 원인 한 줄 (한국어, 25자 이내)",
  "detail": "해당 뉴스의 구체적 내용 1문장 (한국어, 뉴스 원문 기반만)",
  "classification": "Catalyst / Fracture / Noise",
  "confidence": 0.0~1.0,
  "event_type": "earnings/guidance/partnership/ma/regulatory/analyst/sector/macro/other",
  "primary_source_index": 가장 핵심 뉴스 번호 (정수)
}}"""

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,  # 더 낮춰서 창작 억제
                "max_tokens": 250,
            },
            timeout=15,
        )

        if resp.status_code != 200:
            print(f"  ⚠️ OpenAI API 오류 {resp.status_code}: {resp.text[:200]}")
            return _fallback_summary(ticker, news_data, price_data)

        content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]

        result = json.loads(content)
        result["source_count"] = len(news_data)
        result["key_source"] = sources[0] if sources else ""
        result["ai_generated"] = True

        # primary_source_index로 key_source 보정
        psi = result.get("primary_source_index")
        if isinstance(psi, int) and 1 <= psi <= len(news_data):
            candidate_url = news_data[psi - 1].get("url", "")
            if _is_valid_article_url(candidate_url):
                result["key_source"] = candidate_url

        print(f"  🤖 AI 요약: {result.get('headline', '?')}")
        return result

    except json.JSONDecodeError as e:
        print(f"  ⚠️ AI JSON 파싱 실패: {e}")
        return _fallback_summary(ticker, news_data, price_data)
    except Exception as e:
        print(f"  ⚠️ OpenAI 요약 실패: {e}")
        return _fallback_summary(ticker, news_data, price_data)


def _fallback_summary(ticker: str, news_data: List[Dict], price_data: Dict = None) -> Dict:
    """AI 없이 규칙 기반 폴백 — 뉴스 제목 그대로 사용"""
    headline = ""
    event_type = "other"
    classification = "Noise"

    if news_data:
        top = news_data[0]
        headline = top.get("title", "")[:45]

        title_lower = headline.lower()
        if any(w in title_lower for w in ["earnings", "eps", "revenue", "quarter"]):
            event_type = "earnings"
        elif any(w in title_lower for w in ["deal", "partner", "contract"]):
            event_type = "partnership"
        elif any(w in title_lower for w in ["upgrade", "downgrade", "target", "rating"]):
            event_type = "analyst"
        elif any(w in title_lower for w in ["bis", "fda", "sec", "sanction", "export"]):
            event_type = "regulatory"

    if price_data:
        change = price_data.get("change_pct", 0)
        if change >= 2:
            classification = "Catalyst"
        elif change <= -2:
            classification = "Fracture"

    return {
        "headline": headline or f"{ticker} 시장 변동 — 원인 확인 필요",
        "detail": "",
        "classification": classification,
        "confidence": 0.5,
        "event_type": event_type,
        "source_count": len(news_data),
        "key_source": "",
        "ai_generated": False,
    }
