"""
Stock Sentinel — AI 요약 엔진 (OpenAI GPT-4o-mini)
수집된 뉴스를 분석하여 한국어 요약 생성
"""
import os
import json
import requests
from typing import Dict, List, Optional

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL = "gpt-4.1-mini"  # $0.40/M input, $1.60/M output — 뉴스 요약에 최적


def summarize_event(ticker: str, news_data: List[Dict], price_data: Dict = None) -> Dict:
    """
    뉴스 + 가격 데이터를 분석하여 한국어 이벤트 요약 생성
    
    Returns:
        {
            "headline": "Meta와 수백만 GPU 공급 계약 확대",
            "detail": "멀티이어 전략적 파트너십 체결. AI 인프라 투자 확대 기조.",
            "classification": "Catalyst" | "Fracture" | "Noise",
            "confidence": 0.9,
            "event_type": "partnership" | "earnings" | "regulatory" | ...,
            "source_count": 5,
            "key_source": "https://...",
        }
    """
    if not OPENAI_API_KEY:
        return _fallback_summary(ticker, news_data, price_data)
    
    # 뉴스 텍스트 준비 (최대 10건)
    news_text = ""
    sources = []
    for i, article in enumerate(news_data[:10]):
        title = article.get('title', '').strip()
        summary = article.get('summary', '').strip()[:200]
        source = article.get('source', '')
        url = article.get('url', '')
        sentiment = article.get('sentiment', '')
        
        news_text += f"[{i+1}] {title}\n"
        if summary:
            news_text += f"    {summary}\n"
        news_text += f"    출처: {source} | 센티멘트: {sentiment}\n\n"
        
        if url and 'news.google.com/rss' not in url:
            sources.append(url)
    
    # 가격 정보
    price_info = ""
    if price_data:
        change = price_data.get('change_pct', 0)
        vol = price_data.get('volume_ratio', 1.0)
        latest = price_data.get('latest', {})
        close = latest.get('close', 0) if latest else 0
        direction = "상승" if change > 0 else "하락" if change < 0 else "보합"
        price_info = f"현재가: ${close:.2f} | 변동: {change:+.1f}% ({direction}) | 거래량: 평균 대비 {vol:.1f}배"
    
    prompt = f"""당신은 주식 시장 분석가입니다. 아래 {ticker} 관련 뉴스와 가격 데이터를 분석하여 JSON으로 답하세요.

## 가격 데이터
{price_info or "없음"}

## 최근 뉴스
{news_text}

## 요청
아래 JSON 형식으로만 답하세요. 다른 텍스트 없이 JSON만 출력:
{{
  "headline": "핵심 이유 한 줄 (한국어, 20자 이내, 예: 'Meta GPU 대규모 공급 계약 체결')",
  "detail": "부연 설명 1~2문장 (한국어, 배경/맥락 포함)",
  "classification": "Catalyst 또는 Fracture 또는 Noise",
  "confidence": 0.0~1.0,
  "event_type": "earnings/guidance/partnership/ma/regulatory/analyst/sector/macro/other 중 하나"
}}

판단 기준:
- Catalyst: 주가 상승 요인 (호실적, 계약, 업그레이드 등)
- Fracture: 주가 하락 요인 (가이던스 하향, 규제, 다운그레이드 등)
- Noise: 유의미한 팩트 없음, 단순 시장 변동
- 실적 beat + 가이던스 하향 = Fracture (가이던스가 더 중요)
- headline은 "왜 움직이는지"를 한 줄로 설명해야 함"""

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
                "temperature": 0.2,
                "max_tokens": 300,
            },
            timeout=15,
        )
        
        if resp.status_code != 200:
            print(f"  ⚠️ OpenAI API 오류 {resp.status_code}: {resp.text[:200]}")
            return _fallback_summary(ticker, news_data, price_data)
        
        content = resp.json()["choices"][0]["message"]["content"].strip()
        
        # JSON 파싱 (```json 래퍼 제거)
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        
        result = json.loads(content)
        result["source_count"] = len(news_data)
        result["key_source"] = sources[0] if sources else ""
        result["ai_generated"] = True
        
        print(f"  🤖 AI 요약: {result.get('headline', '?')}")
        return result
    
    except json.JSONDecodeError as e:
        print(f"  ⚠️ AI 응답 JSON 파싱 실패: {e}")
        return _fallback_summary(ticker, news_data, price_data)
    except Exception as e:
        print(f"  ⚠️ OpenAI 요약 실패: {e}")
        return _fallback_summary(ticker, news_data, price_data)


def _fallback_summary(ticker: str, news_data: List[Dict], price_data: Dict = None) -> Dict:
    """AI 실패 시 규칙 기반 폴백 요약"""
    headline = ""
    event_type = "other"
    classification = "Noise"
    
    if news_data:
        # 가장 관련도 높은 뉴스 제목 사용
        top = news_data[0]
        headline = top.get('title', '')[:40]
        
        title_lower = headline.lower()
        if any(w in title_lower for w in ['earnings', 'eps', 'revenue', 'quarter']):
            event_type = "earnings"
        elif any(w in title_lower for w in ['deal', 'partner', 'contract']):
            event_type = "partnership"
    
    # 가격 방향으로 분류
    if price_data:
        change = price_data.get('change_pct', 0)
        if change >= 2:
            classification = "Catalyst"
        elif change <= -2:
            classification = "Fracture"
    
    return {
        "headline": headline or f"{ticker} 시장 변동",
        "detail": "",
        "classification": classification,
        "confidence": 0.5,
        "event_type": event_type,
        "source_count": len(news_data),
        "key_source": "",
        "ai_generated": False,
    }
