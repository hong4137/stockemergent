"""
Stock Sentinel -- AI Summarizer v5.0
v3.1: price direction priority + macro/sector event detection
v4.0: 구조화 출력 + 실패 가시화
v5.0: Claude Haiku + 원인 판정 절차 v4 (증거 시트: 공시·증권사 의견·일정·기사·속보·급변 시각)
      백테스트: eval/결과_v4.md (새 데이터에서 알림 시점 엄격 43%·관대 77%, 이전 v1은 31%·53%)

모델은 ANTHROPIC_MODEL 환경변수로 바꾼다 (기본 claude-haiku-5-5). 롤백은 이 파일의 git 이력으로 한다.
"""
import json
import os
from typing import Dict, List, Optional
from urllib.parse import urlparse

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")
# Haiku 5.5 기본값은 medium. 알림 1건당 입력 1만 토큰 안팎이라 medium도 건당 0.2센트 수준이다.
CAUSE_EFFORT = os.environ.get("CAUSE_EFFORT", "medium")

with open(os.path.join(os.path.dirname(__file__), "cause_prompt.md"), encoding="utf-8") as _f:
    PROCEDURE = _f.read()

CONFIDENCE = {"높음": 0.85, "중간": 0.65, "낮음": 0.4}

# 구조화 출력 스키마 — 모델이 이 형태를 벗어난 응답을 낼 수 없게 강제한다.
CAUSE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["원인 있음", "원인 미확인"]},
        "scope": {"type": "string", "enum": ["시장", "섹터", "개별"]},
        "headline": {"type": "string"},
        "cause": {"type": "string"},
        "secondary": {"type": "string"},
        "excluded": {"type": "string"},
        "layer": {"type": "string", "enum": ["공시", "평가", "예고", "기사", "속보", "시세"]},
        "confidence": {"type": "string", "enum": ["높음", "중간", "낮음"]},
        "classification": {"type": "string", "enum": ["Catalyst", "Fracture", "Noise"]},
        "event_type": {
            "type": "string",
            "enum": [
                "earnings", "partnership", "regulatory", "macro", "geopolitical",
                "analyst", "product", "sector_rotation", "insider",
                "institutional", "controversy", "other",
            ],
        },
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verdict", "scope", "headline", "cause", "secondary", "excluded", "layer",
                 "confidence", "classification", "event_type", "evidence"],
    "additionalProperties": False,
}


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


def _direction_move(price_data):
    """분류 방향을 정할 움직임. 시간외 알림이면 종가 이후 움직임."""
    if not price_data:
        return None
    if price_data.get("session") in ("pre", "post") and price_data.get("ext_change_pct") is not None:
        return price_data["ext_change_pct"]
    return price_data.get("change_pct", 0)


def build_prompt(ticker, news_data, price_data=None, market_context=None, prev_alert=None,
                 followup=False):
    """증거 시트를 만든다. (API 호출 없이 확인할 수 있게 분리)
    반환: (시트 텍스트, 헤드라인→URL, 숫자로 정한 범위)"""
    from config.settings import WATCHMAP
    from engines.evidence_sheet import build

    sheet = build(ticker, WATCHMAP.get(ticker), price_data or {}, news_data or [],
                  market_context=market_context, prev_alert=prev_alert, followup=followup)
    return sheet["text"], sheet["urls"], sheet["scope"]


def _key_source(evidence: List[str], urls: Dict[str, str], news_data: List[Dict]) -> str:
    """근거로 쓰인 줄에 해당하는 기사 링크. 없으면 상위 뉴스 중 쓸 수 있는 링크."""
    for line in evidence or []:
        for head, url in urls.items():
            if head and head[:40] in line and url_quality(url) > 0:
                return url
    candidates = [n.get("url", "") for n in (news_data or [])[:10]]
    candidates = [u for u in candidates if url_quality(u) > 0]
    return max(candidates, key=url_quality) if candidates else ""


def summarize_event(ticker, news_data, price_data=None, market_context=None, prev_alert=None,
                    followup=False):
    if not ANTHROPIC_API_KEY:
        print("  ❌ ANTHROPIC_API_KEY 미설정")
        return _fallback_summary(ticker, news_data, price_data, fallback_reason="API 키 없음")

    try:
        import anthropic
    except ImportError:
        print("  ❌ anthropic 패키지 없음 (requirements.txt 확인)")
        return _fallback_summary(ticker, news_data, price_data, fallback_reason="패키지 없음")

    try:
        sheet, urls, scope = build_prompt(ticker, news_data, price_data, market_context,
                                          prev_alert, followup)
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=8000,
            # 절차 문서는 매번 같으므로 캐시한다 (같은 스캔에서 여러 종목이 알림을 낼 때 이득)
            system=[{"type": "text", "text": PROCEDURE, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": sheet}],
            output_config={
                "effort": CAUSE_EFFORT,
                "format": {"type": "json_schema", "schema": CAUSE_SCHEMA},
            },
        )
    except anthropic.APIStatusError as e:
        # 에러 본문을 반드시 남긴다. 상태 코드만 찍고 조용히 폴백하면 문제가 몇 주씩 묻힌다.
        print(f"  ❌ Claude {ANTHROPIC_MODEL} API error {e.status_code}: {str(e.message)[:400]}")
        return _fallback_summary(ticker, news_data, price_data, fallback_reason=f"API {e.status_code}")
    except anthropic.APIConnectionError as e:
        print(f"  ❌ Claude 연결 실패: {e}")
        return _fallback_summary(ticker, news_data, price_data, fallback_reason="연결 실패")
    except Exception as e:
        print(f"  ❌ AI 준비 실패: {type(e).__name__}: {e}")
        return _fallback_summary(ticker, news_data, price_data, fallback_reason=type(e).__name__)

    if response.stop_reason in ("refusal", "max_tokens"):
        print(f"  ❌ Claude 응답 중단: {response.stop_reason}")
        return _fallback_summary(ticker, news_data, price_data, fallback_reason=response.stop_reason)

    try:
        text = next(b.text for b in response.content if b.type == "text")
        r = json.loads(text)
    except Exception as e:
        print(f"  ❌ 응답 해석 실패: {type(e).__name__}: {e}")
        return _fallback_summary(ticker, news_data, price_data, fallback_reason="응답 해석 실패")

    u = response.usage
    print(f"  🧮 tokens in:{u.input_tokens} out:{u.output_tokens} "
          f"cache_read:{u.cache_read_input_tokens or 0}")

    # 보조 요인은 괄호 "(보조: …)"로 붙이지 않고 다음 줄의 문장으로 쓴다.
    # 괄호 속 보고서체가 알림을 'AI끼리 하는 말'처럼 보이게 만들었다.
    if r["verdict"] == "원인 미확인":
        detail = "뚜렷한 원인은 찾지 못했다. " + (r["excluded"] or r["cause"])
    else:
        detail = r["cause"]
        if r["secondary"]:
            detail += "\n" + r["secondary"]
    result = {
        "headline": r["headline"],
        "detail": detail.strip(),
        "classification": r["classification"],
        "confidence": CONFIDENCE.get(r["confidence"], 0.5),
        "cause_confidence": r["confidence"],
        "event_type": r["event_type"],
        "cause_verdict": r["verdict"],
        "cause_layer": r["layer"],
        "cause_scope": r["scope"],
        "evidence": r["evidence"],
        "rule_scope": scope,
    }
    apply_safety_nets(result, price_data, market_context)
    result["ai_generated"] = True
    result["model"] = ANTHROPIC_MODEL
    result["source_count"] = len(news_data or [])
    result["key_source"] = _key_source(r["evidence"], urls, news_data)
    print(f"  AI: {result['headline']} [{result['classification']} {r['confidence']} · {r['layer']}]")
    return result


def apply_safety_nets(result, price_data=None, market_context=None):
    """AI 응답을 데이터로 교정한다. result를 제자리에서 고친다."""
    move = _direction_move(price_data)

    # 1) 가격 방향과 반대되는 분류
    if move is not None:
        cls = result.get("classification", "Noise")
        if move <= -3 and cls == "Catalyst":
            result["classification"] = "Fracture"
            print(f"  Override: Catalyst->Fracture (price {move:+.1f}%)")
        elif move >= 3 and cls == "Fracture":
            result["classification"] = "Catalyst"
            print(f"  Override: Fracture->Catalyst (price {move:+.1f}%)")

    # 2) 데이터와 모순되는 '섹터/매크로' 설명
    #    섹터가 반대로 움직였거나, 종목이 섹터와 크게 벌어졌는데 섹터 탓을 하면
    #    플레이북이 "개별 이슈 아님 — 대응 불필요"라는 틀린 조언을 낸다.
    if market_context and move is not None and result.get("event_type") in (
        "sector_rotation", "macro", "geopolitical"
    ):
        from collectors.market_context import assess_scope
        scope = assess_scope(move, market_context)
        if scope["scope"] == "idiosyncratic":
            print(f"  Override: event_type {result['event_type']}->other "
                  f"(섹터 대비 {scope['excess']:+.1f}%p — 섹터로 설명 안 됨)")
            result["event_type"] = "other"
            result["context_override"] = True


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
    for n in (news_data or [])[:5]:
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
        "source_count": len(news_data or []),
        "key_source": key_source,
    }
