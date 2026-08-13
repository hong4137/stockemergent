"""
Stock Sentinel -- AI Summarizer v4.0
v3.1: price direction priority + macro/sector event detection
v4.0: gpt-5.6-luna 전환 + 구조화 출력 + 실패 가시화

모델 롤백은 OPENAI_MODEL 환경변수로 한다 (코드 수정 불필요).
  예) OPENAI_MODEL=gpt-4.1-mini
"""
import os
import json
from typing import Dict, List, Optional
from urllib.parse import urlparse

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-luna")

# GPT-5 계열은 temperature/max_tokens를 받지 않고, reasoning_effort를 명시하지 않으면
# 기본값 medium으로 추론 토큰이 생성돼 출력 요금이 몇 배로 뛴다. 이 작업은 추론이 필요 없다.
REASONING_EFFORT = os.environ.get("OPENAI_REASONING_EFFORT", "none")

# 구조화 출력 스키마 — 모델이 이 형태를 벗어난 응답을 낼 수 없게 강제한다.
# 이게 있으면 응답에서 ```json 을 문자열로 벗겨내던 취약한 파싱이 필요 없다.
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "핵심 원인 한 줄 (한국어, 20자 이내)"},
        "detail": {"type": "string", "description": "1-2문장 설명 (한국어, 주가 방향과 일치해야 함)"},
        "classification": {"type": "string", "enum": ["Catalyst", "Fracture", "Noise"]},
        "confidence": {"type": "number"},
        "event_type": {
            "type": "string",
            "enum": [
                "earnings", "partnership", "regulatory", "macro", "geopolitical",
                "analyst", "product", "sector_rotation", "insider",
                "institutional", "controversy", "other",
            ],
        },
    },
    "required": ["headline", "detail", "classification", "confidence", "event_type"],
    "additionalProperties": False,
}


def _build_request_body(model: str, prompt: str) -> dict:
    """모델 계열에 맞는 요청 본문. GPT-5 계열과 구형 모델의 파라미터가 다르다."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "stock_event_summary",
                "schema": SUMMARY_SCHEMA,
                "strict": True,
            },
        },
    }

    if model.startswith("gpt-5"):
        body["max_completion_tokens"] = 400
        body["reasoning_effort"] = REASONING_EFFORT
    else:
        # gpt-4.x 계열 (롤백 경로)
        body["max_tokens"] = 400
        body["temperature"] = 0.2

    return body


def url_quality(url: str) -> int:
    """링크 품질 순위. 높을수록 좋다. 0이면 쓸 수 없다.

    2 = 언론사 기사 주소 (가장 좋음)
    1 = 리다이렉터 주소. 보기엔 지저분해도 클릭하면 기사로 연결된다.
        Google News RSS는 2024년 이후 실제 URL을 노출하지 않으므로
        (link/summary 어디에도 없고 ID도 불투명) 이걸 막으면 링크가 아예 없어진다.
    0 = 언론사 대문 등 기사로 연결되지 않는 주소
    """
    if not url:
        return 0
    if "googleapis.com" in url:
        return 0
    if "news.google.com/rss" in url or "finnhub.io/api" in url:
        return 1
    path = urlparse(url).path.strip("/")
    if not path or len(path) < 3:
        return 0
    return 2


def _is_valid_article_url(url):
    return url_quality(url) > 0


def _post_with_param_recovery(httpx, model: str, prompt: str, max_retries: int = 3):
    """요청을 보내되, 모델이 특정 파라미터를 거부하면 그 파라미터만 빼고 재시도한다.

    OpenAI는 미지원 파라미터를 400과 함께 error.param 으로 알려준다.
    모델 세대가 바뀔 때마다 파라미터 규칙이 달라지는데(GPT-5는 temperature 거부,
    max_tokens 대신 max_completion_tokens), 이 복구가 없으면 그런 변화가
    전 알림의 조용한 품질 저하로 나타난다.
    """
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    body = _build_request_body(model, prompt)
    dropped = []

    for _ in range(max_retries):
        response = httpx.post(url, headers=headers, json=body, timeout=30)
        if response.status_code != 400:
            if dropped:
                print(f"  ⚠️ 미지원 파라미터 제외 후 성공: {dropped} "
                      f"— 코드에 반영 필요 (모델: {model})")
            return response

        try:
            err = response.json().get("error", {})
            param = err.get("param")
        except Exception:
            return response

        # messages 같은 필수 필드는 빼면 안 된다
        if not param or param not in body or param in ("model", "messages"):
            return response

        body.pop(param)
        dropped.append(param)
        print(f"  🔁 '{param}' 미지원 — 제외하고 재시도")

    return response


def summarize_event(ticker, news_data, price_data=None, sector_context=""):
    if not OPENAI_API_KEY:
        print("  ❌ OPENAI_API_KEY 미설정")
        return _fallback_summary(
            ticker, news_data, price_data, fallback_reason="API 키 없음"
        )

    try:
        import httpx

        news_text = ""
        valid_urls = []
        for i, n in enumerate(news_data[:10]):
            title = n.get("title", n.get("headline", ""))
            source = n.get("source", "")
            url = n.get("url", n.get("source_url", ""))
            summary = n.get("summary", "")[:100]
            news_text += f"{i+1}. [{source}] {title}"
            if summary:
                news_text += f" -- {summary}"
            news_text += "\n"
            if _is_valid_article_url(url):
                valid_urls.append(url)

        # 언론사 직링크를 리다이렉터보다 우선 (정렬 안정성 유지)
        valid_urls.sort(key=url_quality, reverse=True)

        price_text = "no data"
        price_direction = ""
        if price_data:
            pct = price_data.get("change_pct", 0)
            vol = price_data.get("volume_ratio", 1)
            rev = price_data.get("intraday_reversal", 0)
            price_text = f"vs prev close: {pct:+.1f}%, vol ratio: {vol:.1f}x"
            if abs(rev) >= 2:
                price_text += f", intraday reversal: {rev:+.1f}%"
            if pct <= -3:
                price_direction = (
                    "WARNING: stock DOWN " + f"{pct:+.1f}%"
                    + ". You MUST explain the decline."
                )
            elif pct >= 3:
                price_direction = (
                    "WARNING: stock UP " + f"{pct:+.1f}%"
                    + ". You MUST explain the rise."
                )
            elif pct <= -1:
                price_direction = f"Stock is down {pct:+.1f}%."
            elif pct >= 1:
                price_direction = f"Stock is up {pct:+.1f}%."

        sector_line = ""
        if sector_context:
            sector_line = "\nSector context: " + sector_context

        prompt = (
            f"You are a stock market analyst. Analyze why {ticker} stock is moving.\n\n"
            "=== ABSOLUTE RULES ===\n"
            "1. classification MUST match price direction:\n"
            "   - Down more than 1.5% -> Fracture (NEVER Catalyst)\n"
            "   - Up more than 1.5% -> Catalyst (NEVER Fracture)\n"
            "   - Between -1.5% and +1.5% -> Noise, UNLESS a hard event\n"
            "     (earnings, filing, lawsuit, M&A) clearly explains the move.\n"
            "     Do not invent a cause for a move this small.\n"
            "2. If no clear company-specific cause (earnings, lawsuit, guidance), "
            "consider macro/geopolitical factors: war, tariffs, interest rates, risk-off. "
            'Set event_type to "geopolitical" or "macro".\n'
            "3. Even if bullish news exists, if stock is DOWN, explain "
            '"declining despite positive news" pattern.\n'
            "4. event_type definitions — pick precisely:\n"
            "   - insider: the company's OWN officers/directors buying or selling\n"
            "     their own shares (SEC Form 4). NOT outside investors.\n"
            "   - institutional: outside funds, activists, or large holders taking\n"
            "     or exiting a position (e.g. Pershing Square, ARK, 13F/13D moves).\n"
            "   - regulatory: action by a government or regulator (fines, approvals,\n"
            "     export controls, antitrust). NOT user backlash or public criticism.\n"
            "   - controversy: public backlash, boycott, PR problem, or ethical\n"
            "     dispute with no regulator involved.\n"
            "   - sector_rotation: the whole sector moved together and there is no\n"
            "     company-specific cause.\n\n"
            "=== DATA ===\n"
            f"Price: {price_text}\n"
            f"{price_direction}\n"
            f"{sector_line}\n\n"
            "News:\n"
            f"{news_text}\n"
            "=== OUTPUT (JSON only, Korean for headline/detail) ===\n"
            "{\n"
            '  "headline": "core reason 1 line (Korean, max 20 chars)",\n'
            '  "detail": "1-2 sentences (Korean, must match price direction)",\n'
            '  "classification": "Catalyst/Fracture/Noise",\n'
            '  "confidence": 0.0~1.0,\n'
            '  "event_type": "earnings/partnership/regulatory/macro/geopolitical/'
            'analyst/product/sector_rotation/insider/institutional/controversy/other"\n'
            "}"
        )

        response = _post_with_param_recovery(httpx, OPENAI_MODEL, prompt)

        if response.status_code != 200:
            # 에러 본문을 반드시 남긴다. 상태 코드만 찍고 조용히 폴백하면
            # 파라미터 비호환 같은 문제가 몇 주씩 묻힌다.
            print(f"  ❌ OpenAI {OPENAI_MODEL} API error {response.status_code}: "
                  f"{response.text[:400]}")
            return _fallback_summary(
                ticker, news_data, price_data,
                fallback_reason=f"API {response.status_code}",
            )

        payload = response.json()
        content = payload["choices"][0]["message"]["content"].strip()

        # strict json_schema 사용 시 코드펜스가 붙지 않지만, 롤백 모델 대비 방어적으로 유지
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content.rsplit("```", 1)[0]
        content = content.strip()

        result = json.loads(content)

        # 토큰 사용량 로깅 — 추론 토큰이 새는지 Actions 로그에서 바로 보이게
        usage = payload.get("usage", {})
        if usage:
            reasoning = (usage.get("completion_tokens_details") or {}).get(
                "reasoning_tokens", 0
            )
            print(f"  🧮 tokens in:{usage.get('prompt_tokens', 0)} "
                  f"out:{usage.get('completion_tokens', 0)}"
                  + (f" (reasoning:{reasoning})" if reasoning else ""))

        # Price direction override (safety net)
        if price_data:
            pct = price_data.get("change_pct", 0)
            cls = result.get("classification", "Noise")
            if pct <= -3 and cls == "Catalyst":
                result["classification"] = "Fracture"
                print(f"  Override: Catalyst->Fracture (price {pct:+.1f}%)")
            elif pct >= 3 and cls == "Fracture":
                result["classification"] = "Catalyst"
                print(f"  Override: Fracture->Catalyst (price {pct:+.1f}%)")

        result["ai_generated"] = True
        result["model"] = OPENAI_MODEL
        result["source_count"] = len(news_data)
        result["key_source"] = valid_urls[0] if valid_urls else ""

        cls = result.get("classification", "Noise")
        conf = result.get("confidence", 0.5)
        hl = result.get("headline", "")
        print(f"  AI: {hl} [{cls} {conf:.0%}]")

        return result

    except Exception as e:
        print(f"  ❌ AI error ({OPENAI_MODEL}): {type(e).__name__}: {e}")
        return _fallback_summary(
            ticker, news_data, price_data, fallback_reason=type(e).__name__
        )


def _fallback_summary(ticker, news_data, price_data=None, fallback_reason=""):
    headline = "주요 신호 발생"
    detail = ""
    classification = "Noise"
    confidence = 0.5
    event_type = "other"

    if price_data:
        pct = price_data.get("change_pct", 0)
        rev = price_data.get("intraday_reversal", 0)
        if pct <= -3:
            headline = f"주가 {abs(pct):.1f}% 하락"
            classification = "Fracture"
            confidence = min(0.6 + abs(pct) / 20, 0.9)
        elif pct >= 3:
            headline = f"주가 {abs(pct):.1f}% 상승"
            classification = "Catalyst"
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
        detail = f"{ticker} 관련 {len(news_data)}건의 뉴스가 감지됨."

    key_source = ""
    for n in news_data[:5]:
        url = n.get("url", n.get("source_url", ""))
        if _is_valid_article_url(url):
            key_source = url
            break

    if fallback_reason:
        print(f"  ⚠️ 규칙 기반 폴백 사용 (사유: {fallback_reason})")

    return {
        "headline": headline,
        "detail": detail,
        "classification": classification,
        "confidence": confidence,
        "event_type": event_type,
        "ai_generated": False,
        "fallback_reason": fallback_reason,
        "model": "",
        "source_count": len(news_data),
        "key_source": key_source,
    }
