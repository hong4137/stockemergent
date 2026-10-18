"""
v3.1 시트 = v3 시트 + '4-속보' 섹션 (Bluesky 속보 계정, 분 단위 시각).  python sheet_v31.py A 1 109
모드 A: 알림 시각 이전 60시간, 모드 B: 당일 20:00 ET까지.
종목·동종업체·업종·거시 키워드에 걸리는 글만 넣는다(최신순, 종목·동종 먼저).
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from collect import ET, META  # noqa: E402
from sheet_v3 import build_v3  # noqa: E402

NAMES = {"MU": "Micron", "AVGO": "Broadcom", "QCOM": "Qualcomm", "PANW": "Palo Alto", "NET": "Cloudflare",
         "AMZN": "Amazon", "NFLX": "Netflix", "WDC": "Western Digital", "SNDK": "Sandisk", "STX": "Seagate",
         "NVDA": "Nvidia", "MRVL": "Marvell", "AMD": "AMD", "ARM": "Arm Holdings", "SWKS": "Skyworks",
         "AAPL": "Apple", "CRWD": "CrowdStrike", "ZS": "Zscaler", "FTNT": "Fortinet", "AKAM": "Akamai",
         "DDOG": "Datadog", "MSFT": "Microsoft", "GOOGL": "Google|Alphabet", "META": "Meta", "DIS": "Disney",
         "WBD": "Warner Bros", "ROKU": "Roku", "SPOT": "Spotify",
         "AMAT": "Applied Materials", "LRCX": "Lam Research", "KLAC": "KLA", "ASML": "ASML", "TSM": "TSMC|Taiwan Semiconductor"}
SECTOR = {"MU": r"memory|DRAM|NAND|HBM|chip|semiconductor|CXMT|SK Hynix|Samsung",
          "AVGO": r"chip|semiconductor|AI infrastructure|custom silicon|OpenAI|TPU",
          "QCOM": r"chip|semiconductor|smartphone|Apple|Arm",
          "PANW": r"cyber|security|hack|software", "NET": r"cyber|security|hack|software|cloud",
          "AMZN": r"AWS|cloud|retail|e-commerce|megacap", "NFLX": r"stream|media|YouTube",
          "AMAT": r"chip|semiconductor|equipment|wafer|export control|China"}
MACRO = (r"\bCPI\b|\bPPI\b|payroll|jobs report|unemployment|\bFed\b|FOMC|Powell|Warsh|rate (hike|cut)|"
         r"yield|Treasur|oil|Brent|WTI|Iran|Hormuz|tariff|Trump|Nasdaq|S&P 500|stocks? (fall|drop|slide|rally|jump)|"
         r"\bAI\b|Anthropic|OpenAI")

POSTS = None


def posts():
    global POSTS
    if POSTS is None:
        POSTS = []
        import bt_config
        for line in open(os.path.join(HERE, "cache", f"breaking{bt_config.TAG}.jsonl"), encoding="utf-8"):
            p = json.loads(line)
            t = datetime.fromisoformat(p["t"].replace("Z", "+00:00"))
            POSTS.append((t.astimezone(ET), p["src"], " ".join(p["text"].split())))
        POSTS.sort(reverse=True)
    return POSTS


def breaking_lines(b, mode):
    tk = b["ticker"]
    T = datetime.fromisoformat(b["alert_et"])
    end = T if mode == "A" else T.replace(hour=20, minute=0)
    start = T - timedelta(hours=60)
    own = re.compile(rf"\b({NAMES[tk]}|{tk})\b", re.I)
    peer = re.compile(r"\b(" + "|".join(NAMES.get(p, p) for p in META[tk]["peers"]) + r")\b", re.I)
    sect = re.compile(SECTOR[tk], re.I)
    macro = re.compile(MACRO, re.I)
    hits = []
    for t, src, text in posts():
        if not (start <= t <= end):
            continue
        if own.search(text):
            pri = 0
        elif peer.search(text):
            pri = 1
        elif sect.search(text):
            pri = 2
        elif macro.search(text):
            pri = 3
        else:
            continue
        hits.append((pri, t, src, text))
    hits.sort(key=lambda h: (h[0], -h[1].timestamp()))
    tag = {0: "자사", 1: "동종", 2: "업종", 3: "거시"}
    near = [h for h in hits if h[0] < 3][:20]
    macro_hits = [h for h in hits if h[0] == 3][:30]
    return [f"- [{tag[p]}] {t:%m-%d %H:%M} ET ({src}) {text[:160]}" for p, t, src, text in near + macro_hits]


# 규칙으로 정해지는 일정 (실사 audit_schedule_alt.md): 옵션 만기, S&P 리밸런싱
FIXED = {"2026-08-21": "월간 옵션 만기", "2026-09-18": "분기 옵션 동시 만기(쿼드러플 위칭)",
         "2026-10-16": "월간 옵션 만기", "2026-09-04": "S&P 지수 정기변경 발표(장 마감 후)",
         "2026-09-21": "S&P 지수 정기변경 시행(PANW·SNDK S&P100 편입)"}


def main(mode, lo, hi):
    import bt_config
    out_dir = bt_config.path("sheets_v31", mode, "_")[:-2]
    os.makedirs(out_dir, exist_ok=True)
    for i in range(lo, hi + 1):
        eid = f"{bt_config.PREFIX}{i:03d}"
        with open(bt_config.path("bundles_v3", eid + ".json"), encoding="utf-8") as f:
            b = json.load(f)
        b["etfs"], b["peers"] = META[b["ticker"]]["etfs"], META[b["ticker"]]["peers"]
        gate, scope, text = build_v3(b, mode)
        cut = "알림 시각까지" if mode == "A" else "당일 20:00 ET까지"
        sec = [f"## 4-속보. 속보 헤드라인 — 분 단위 시각 ({cut}, 최근 60시간. 자사·동종·업종·거시 순)"]
        sec += breaking_lines(b, mode) or ["- 없음"]
        lines = text.split("\n")
        d0 = datetime.fromisoformat(b["alert_et"]).date()
        extra = [f"- {v} ({(datetime.fromisoformat(k).date() - d0).days:+d}일)" for k, v in FIXED.items()
                 if -1 <= (datetime.fromisoformat(k).date() - d0).days <= 1]
        if extra:
            c = next(i for i, l in enumerate(lines) if l.startswith("## 2."))
            if lines[c + 1] == "- 없음":
                lines[c + 1:c + 2] = extra
            else:
                lines[c + 1:c + 1] = extra
        at = next(i for i, l in enumerate(lines) if l.startswith("## 4-"))
        lines = lines[:at] + sec + [""] + lines[at:]
        with open(os.path.join(out_dir, eid + ".txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(eid, gate, scope)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
