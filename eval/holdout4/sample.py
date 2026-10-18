"""새 홀드아웃 표본 추출 (채점규칙_v4.md 1절). 시드 고정, 종목별 비례 층화 45건.
출력: events.csv(내부용), events_blind.csv(조사자용 — 종목·날짜·시각·기록 등락만)"""
import csv
import os
import random
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "..", "sentinel", "storage", "sentinel.db")
ET = ZoneInfo("America/New_York")
N, SEED = 45, 20261019


def main():
    c = sqlite3.connect(DB)
    rows = c.execute("select ticker,timestamp,change_pct,trigger_type from alerts where ai_generated=0 "
                     "and timestamp>='2026-03-01' and timestamp<'2026-08-01' order by timestamp").fetchall()
    days = {}
    for tk, ts, ch, tr in rows:
        t = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).astimezone(ET)
        days.setdefault((tk, t.date().isoformat()), (t, ch, tr))
    by = {}
    for k in sorted(days):
        by.setdefault(k[0], []).append(k)
    total = len(days)
    quota = {tk: max(1, round(N * len(v) / total)) for tk, v in by.items()}
    while sum(quota.values()) > N:   # 반올림 보정: 가장 큰 종목에서 뺀다
        quota[max(quota, key=quota.get)] -= 1
    while sum(quota.values()) < N:
        quota[max(by, key=lambda t: len(by[t]) / quota[t])] += 1
    rnd = random.Random(SEED)
    picked = []
    for tk in sorted(by):
        picked += rnd.sample(by[tk], quota[tk])
    picked.sort(key=lambda k: (k[1], k[0]))
    out = []
    for i, k in enumerate(picked, 1):
        t, ch, tr = days[k]
        out.append(dict(eid=f"H{i:03d}", ticker=k[0], et_date=k[1], et_time=t.strftime("%H:%M"),
                        change_pct="" if ch is None else round(ch, 2), trigger=tr))
    with open(os.path.join(HERE, "events.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(out[0])); w.writeheader(); w.writerows(out)
    with open(os.path.join(HERE, "events_blind.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["eid", "ticker", "et_date", "et_time", "change_pct"], extrasaction="ignore")
        w.writeheader(); w.writerows(out)
    print(total, "→", len(out), quota)


if __name__ == "__main__":
    main()
