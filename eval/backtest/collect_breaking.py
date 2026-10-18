"""
속보 층 수집: Bluesky 공개 API(인증 불필요)로 속보 계정의 글을 2026-08-10 이후 전부 받는다.
시각(createdAt, UTC)이 초 단위로 있어 알림 시각 기준으로 정확히 자를 수 있다.

  skybrg.bsky.social           블룸버그식 헤드라인 (*대문자 헤드라인)
  livesquawknews.bsky.social   LiveSquawk 속보
  unusualwhales.bsky.social    Unusual Whales 속보

출력: cache/breaking.jsonl  (한 줄에 {"t": ISO UTC, "src": 계정, "text": 본문})
"""
import json
import sys
import os
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_config  # noqa: E402
OUT = os.path.join(HERE, "cache", f"breaking{bt_config.TAG}.jsonl")
ACCOUNTS = ["skybrg.bsky.social", "livesquawknews.bsky.social", "unusualwhales.bsky.social"]
SINCE = bt_config.SINCE if bt_config.TAG else "2026-08-10"


def fetch(actor):
    posts, cursor = [], None
    for _ in range(2000):
        params = {"actor": actor, "limit": 100, "filter": "posts_no_replies"}
        if cursor:
            params["cursor"] = cursor
        for attempt in range(4):
            try:
                r = requests.get("https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed", params=params, timeout=30)
                if r.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(3 * (attempt + 1))
        else:
            print(actor, "실패 — 여기까지만 저장", flush=True)
            break
        j = r.json()
        feed = j.get("feed", [])
        if not feed:
            break
        oldest = None
        for it in feed:
            rec = it["post"]["record"]
            t = rec.get("createdAt", "")
            oldest = t
            if t[:10] >= SINCE:
                posts.append(dict(t=t, src=actor.split(".")[0], text=rec.get("text", "")))
        cursor = j.get("cursor")
        if not cursor or (oldest and oldest[:10] < SINCE):
            break
        time.sleep(0.3)
    print(actor, len(posts), "posts, oldest", posts[-1]["t"] if posts else None, flush=True)
    return posts


def main():
    allp = []
    for a in ACCOUNTS:
        allp += fetch(a)
    with open(OUT, "w", encoding="utf-8") as f:
        for p in allp:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print("total", len(allp))


if __name__ == "__main__":
    main()
