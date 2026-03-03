"""
Stock Sentinel -- AI Summarizer v3.1
v3.1: price direction priority + macro/sector event detection
"""
import os
import json
from typing import Dict, List, Optional
from urllib.parse import urlparse

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")


def _is_valid_article_url(url):
    if not url:
        return False
    bad = ["news.google.com/rss", "finnhub.io/api", "googleapis.com"]
    if any(p in url for p in bad):
        return False
    path = urlparse(url).path.strip("/")
    if not path or len(path) < 3:
        return False
    return True


def summarize_event(ticker, news_data, price_data=None, sector_context=""):
    if not OPENAI_API_KEY:
        print("  OPENAI_API_KEY missing")
        return _fallback_summary(ticker, news_data, price_data)

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
            "   - Stock declining -> Fracture (NEVER Catalyst)\n"
            "   - Stock rising -> Catalyst (NEVER Fracture)\n"
            "   - Flat -> Noise\n"
            "2. If no clear company-specific cause (earnings, lawsuit, guidance), "
            "consider macro/geopolitical factors: war, tariffs, interest rates, risk-off. "
            'Set event_type to "geopolitical" or "macro".\n'
            "3. Even if bullish news exists, if stock is DOWN, explain "
            '"declining despite positive news" pattern.\n\n'
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
            'analyst/product/sector_rotation/other"\n'
            "}"
        )

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
                "temperature": 0.2,
            },
            timeout=15,
        )

        if response.status_code != 200:
            print(f"  OpenAI API error {response.status_code}")
            return _fallback_summary(ticker, news_data, price_data)

        content = response.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content.rsplit("```", 1)[0]
        content = content.strip()

        result = json.loads(content)

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
        result["source_count"] = len(news_data)
        result["key_source"] = valid_urls[0] if valid_urls else ""

        cls = result.get("classification", "Noise")
        conf = result.get("confidence", 0.5)
        hl = result.get("headline", "")
        print(f"  AI: {hl} [{cls} {conf:.0%}]")

        return result

    except Exception as e:
        print(f"  AI error: {e}")
        return _fallback_summary(ticker, news_data, price_data)


def _fallback_summary(ticker, news_data, price_data=None):
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

    return {
        "headline": headline,
        "detail": detail,
        "classification": classification,
        "confidence": confidence,
        "event_type": event_type,
        "ai_generated": False,
        "source_count": len(news_data),
        "key_source": key_source,
    }
