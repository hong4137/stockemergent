"""
Stock Sentinel — Telegram Module v2
Markdown 이스케이프 + 연속 발송 딜레이
"""
import os
import re
import time
import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# 마지막 발송 시각 (연속 발송 시 딜레이)
_last_send_time = 0


def escape_markdown(text: str) -> str:
    """
    Telegram Markdown에서 문제 되는 문자 이스케이프.
    *bold*, _italic_ 의도적 포맷은 유지하되,
    뉴스 제목 등 동적 텍스트의 특수문자는 제거/치환.
    """
    # 이미 의도적으로 사용된 *bold* 패턴은 보존
    # 홀수개의 * 나 _ 가 있으면 문제 → 짝수로 맞추기 어려우므로
    # 동적 텍스트는 별도로 sanitize 권장
    return text


def sanitize_title(text: str) -> str:
    """뉴스 제목 등 동적 텍스트에서 Markdown 깨짐 방지"""
    if not text:
        return ""
    # Telegram Markdown v1에서 문제 되는 문자: * _ ` [
    text = text.replace("*", "✱")
    text = text.replace("_", " ")
    text = text.replace("`", "'")
    text = text.replace("[", "(")
    text = text.replace("]", ")")
    return text


def send_telegram(text: str, parse_mode: str = "Markdown") -> bool:
    """Telegram 메시지 발송 (Markdown 실패 시 plain text 폴백)"""
    global _last_send_time

    if not TOKEN or not CHAT_ID:
        print("  ⚠️ Telegram 미설정")
        return False

    # 연속 발송 시 1초 딜레이 (Telegram rate limit 방지)
    now = time.time()
    elapsed = now - _last_send_time
    if elapsed < 1.5:
        time.sleep(1.5 - elapsed)

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        _last_send_time = time.time()

        if r.status_code == 200:
            print("  ✅ Telegram 발송")
            return True

        # Markdown 파싱 에러 시 plain text 재시도
        if r.status_code == 400:
            print(f"  ⚠️ Markdown 파싱 실패, plain text 재시도: {r.text[:100]}")
            payload["parse_mode"] = ""
            time.sleep(0.5)
            r2 = requests.post(url, json=payload, timeout=10)
            _last_send_time = time.time()
            if r2.status_code == 200:
                print("  ✅ Telegram 발송 (plain text)")
                return True
            print(f"  ❌ Plain text도 실패: {r2.status_code} {r2.text[:100]}")

        print(f"  ⚠️ Telegram {r.status_code}: {r.text[:150]}")
        return False

    except Exception as e:
        print(f"  ⚠️ Telegram: {e}")
        return False
