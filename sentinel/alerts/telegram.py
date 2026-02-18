"""
Stock Sentinel — Telegram Module
"""
import os
import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_telegram(text, parse_mode="Markdown"):
    if not TOKEN or not CHAT_ID:
        print("  ⚠️ Telegram 미설정")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode,
               "disable_web_page_preview": True}

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print("  ✅ Telegram 발송")
            return True
        # Markdown 파싱 에러 시 plain text 재시도
        if r.status_code == 400:
            payload["parse_mode"] = ""
            r2 = requests.post(url, json=payload, timeout=10)
            if r2.status_code == 200:
                return True
        print(f"  ⚠️ Telegram {r.status_code}")
        return False
    except Exception as e:
        print(f"  ⚠️ Telegram: {e}")
        return False
