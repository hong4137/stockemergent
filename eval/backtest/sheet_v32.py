"""
v3.2 시트 (A 모드 전용) = v3.1 시트 + '4-기사' 섹션 (Finnhub, 기사마다 초 단위 발행 시각).
알림 시각 이전 36시간 안에 나온 자사·동종업체 기사만, 잡음(임원 매각·13F·추천 목록·등락 재탕)은 뺀다.
v3.1과 다른 것은 이 섹션 하나뿐이다 — 알림 시점 기사의 효과만 잰다.   python sheet_v32.py 1 109
"""
import json
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from collect import ET, META  # noqa: E402
from sheet import tag  # noqa: E402

sys.path.insert(0, HERE)
import bt_config  # noqa: E402
CACHE = os.path.join(HERE, "cache", "finnhub" + ("_" + bt_config.TAG if bt_config.TAG else ""))
_ART = {}


def articles(sym):
    if sym not in _ART:
        p = os.path.join(CACHE, sym + ".jsonl")
        rows = []
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                a = json.loads(line)
                if a.get("t"):
                    a["dt"] = datetime.fromtimestamp(a["t"], tz=ET)
                    rows.append(a)
        _ART[sym] = rows
    return _ART[sym]


def lines(tk, T):
    out, seen = [], set()
    for who, syms in (("자사", [tk]), ("동종", META[tk]["peers"])):
        picked = []
        for s in syms:
            for a in articles(s):
                if not (T - timedelta(hours=36) <= a["dt"] < T):
                    continue
                h = " ".join(a["headline"].split())
                k = h.lower()[:80]
                if not h or k in seen or tag(h):
                    continue
                seen.add(k)
                picked.append((a["dt"], s, h, a["source"]))
        picked.sort(reverse=True)
        cap = 25 if who == "자사" else 15
        out += [f"- [{who}] {dt:%m-%d %H:%M} ET {s} ({src}) {h[:170]}" for dt, s, h, src in picked[:cap]]
    return out


def main(lo, hi):
    import bt_config
    out_dir = bt_config.path("sheets_v32", "A", "_")[:-2]
    os.makedirs(out_dir, exist_ok=True)
    for i in range(lo, hi + 1):
        eid = f"{bt_config.PREFIX}{i:03d}"
        text = open(bt_config.path("sheets_v31", "A", eid + ".txt"), encoding="utf-8").read()
        with open(bt_config.path("bundles_v3", eid + ".json"), encoding="utf-8") as f:
            b = json.load(f)
        T = datetime.fromisoformat(b["alert_et"])
        sec = ["## 4-기사. 기사 — 발행 시각 확인됨 (Finnhub, 알림 시각 이전 36시간, 자사→동종 최신순)"]
        sec += lines(b["ticker"], T) or ["- 없음"]
        ls = text.split("\n")
        at = next(i for i, l in enumerate(ls) if l.startswith("## 4-속보"))
        ls = ls[:at] + sec + [""] + ls[at:]
        with open(os.path.join(out_dir, eid + ".txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(ls))
        print(eid, len(sec) - 1)


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]))
