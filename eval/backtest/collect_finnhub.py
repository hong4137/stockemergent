"""
알림 시점 기사 수집: Finnhub company-news (기사마다 초 단위 발행 시각).
종목 + 동종업체, 2026-08-10 ~ 2026-10-17. 7일 창으로 받고, 결과가 많으면 하루 단위로 쪼갠다.

키: 환경변수 FINNHUB_API_KEY, 없으면 상위 폴더 .env / 레포 .env 에서 읽는다. 키는 출력하지 않는다.
출력: cache/finnhub/<SYMBOL>.jsonl  (한 줄에 {"t": unix, "headline", "source", "summary", "url"})
"""
import json
import os
import sys
import time
from datetime import date, timedelta

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from collect import META  # noqa: E402

OUT = os.path.join(HERE, "cache", "finnhub")
os.makedirs(OUT, exist_ok=True)
import bt_config  # noqa: E402
START, END = date.fromisoformat(bt_config.SINCE), date.fromisoformat(bt_config.UNTIL)
if bt_config.TAG:
    OUT = os.path.join(HERE, "cache", "finnhub_" + bt_config.TAG)
    os.makedirs(OUT, exist_ok=True)


def api_key():
    k = os.environ.get("FINNHUB_API_KEY")
    if k:
        return k.strip()
    for p in (os.path.join(HERE, "..", "..", ".env"), os.path.join(HERE, "..", "..", "..", ".env")):
        p = os.path.abspath(p)
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                if line.strip().startswith("FINNHUB_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def call(key, sym, d1, d2):
    for attempt in range(5):
        r = requests.get("https://finnhub.io/api/v1/company-news",
                         params={"symbol": sym, "from": d1.isoformat(), "to": d2.isoformat(), "token": key}, timeout=30)
        if r.status_code == 429:
            time.sleep(15)
            continue
        if r.status_code != 200:
            raise RuntimeError(f"{sym} {d1}~{d2}: HTTP {r.status_code} {r.text[:120]}")
        time.sleep(1.05)   # 무료 한도 분당 60회
        return r.json()
    raise RuntimeError(f"{sym}: 429 반복")


def fetch(key, sym):
    items, d = {}, START
    while d <= END:
        d2 = min(d + timedelta(days=6), END)
        got = call(key, sym, d, d2)
        if len(got) >= 200:          # 상한에 걸렸을 수 있다 → 하루씩
            got = []
            x = d
            while x <= d2:
                got += call(key, sym, x, x)
                x += timedelta(days=1)
        for a in got:
            items[a.get("id") or (a.get("datetime"), a.get("headline"))] = dict(
                t=a.get("datetime"), headline=a.get("headline", ""), source=a.get("source", ""),
                summary=(a.get("summary") or "")[:300], url=a.get("url", ""))
        d = d2 + timedelta(days=1)
    rows = sorted(items.values(), key=lambda a: a["t"] or 0)
    with open(os.path.join(OUT, sym + ".jsonl"), "w", encoding="utf-8") as f:
        for a in rows:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    return rows


def fetch_windows(key, sym, days):
    """표본 사건 날짜 주변만 받는다(새 홀드아웃용). days: 사건 날짜 집합. 각 날짜의 이틀 전~당일."""
    items = {}
    for d in sorted(days):
        d1 = d - timedelta(days=2)
        got = call(key, sym, d1, d)
        if len(got) >= 200:
            got = []
            x = d1
            while x <= d:
                got += call(key, sym, x, x)
                x += timedelta(days=1)
        for a in got:
            items[a.get("id") or (a.get("datetime"), a.get("headline"))] = dict(
                t=a.get("datetime"), headline=a.get("headline", ""), source=a.get("source", ""),
                summary=(a.get("summary") or "")[:300], url=a.get("url", ""))
    rows = sorted(items.values(), key=lambda a: a["t"] or 0)
    with open(os.path.join(OUT, sym + ".jsonl"), "w", encoding="utf-8") as f:
        for a in rows:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    return rows


def main():
    key = api_key()
    if not key:
        sys.exit("FINNHUB_API_KEY가 없습니다 (.env에 FINNHUB_API_KEY=... 한 줄)")
    if bt_config.TAG:
        import csv
        need = {}
        for e in csv.DictReader(open(bt_config.EVENTS, encoding="utf-8")):
            d = date.fromisoformat(e["et_date"])
            for s in [e["ticker"]] + META[e["ticker"]]["peers"]:
                need.setdefault(s, set()).add(d)
        for s, days in need.items():
            rows = fetch_windows(key, s, days)
            print(s, len(rows), "기사,", len(days), "개 날짜", flush=True)
        return
    syms = []
    for tk, m in META.items():
        for s in [tk] + m["peers"]:
            if s not in syms:
                syms.append(s)
    for s in syms:
        if os.path.exists(os.path.join(OUT, s + ".jsonl")):
            continue
        rows = fetch(key, s)
        first = time.strftime("%m-%d", time.gmtime(rows[0]["t"])) if rows else "-"
        print(s, len(rows), "기사, 가장 이른 것", first, flush=True)


if __name__ == "__main__":
    main()
