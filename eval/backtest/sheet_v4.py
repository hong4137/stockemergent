"""
v4 시트 = v3.2 시트(v3 + 속보 + 기사) + 의견 변경 처리 수정 (채점규칙_v4.md 2절)
  1. 의견 변경 시각: UTC → 동부시각 (bundle의 v4_ratings)
  2. 목표가만 바꾼 경우도 증권사 이름과 함께 원인 후보로 올린다
  3. 알림 하루 전~알림 시각에 자사 의견·목표가 변경이 있으면 '평소 범위'로 거르지 않는다
  (4번 '범위 무관 우선'은 prompt_v4.md의 절차에 있다)
python sheet_v4.py A 1 45   (EVAL_SET=h4)
"""
import json
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bt_config  # noqa: E402
import sheet_v31  # noqa: E402
import sheet_v32  # noqa: E402
from collect import META  # noqa: E402
from sheet_v3 import build_v3  # noqa: E402


def v4_ratings_for_sheet(b, T):
    """v4_ratings를 v3 시트 형식으로 바꾼다. 목표가 변경은 own·hard=False로 두고 줄 앞에 표시를 붙인다."""
    out = []
    for x in b.get("v4_ratings", []):
        if not x["hard"] and not x["pt_change"]:
            continue                     # 재확인·변경 없는 유지는 뺀다
        line = x["line"]
        if not x["hard"]:
            line = "[목표가 변경·원인 후보] " + line
        out.append(dict(line=line, hard=x["hard"], before=x["before"], own=x["own"]))
    return out


def own_recent_change(b, T):
    for x in b.get("v4_ratings", []):
        if x["own"] and (x["hard"] or x["pt_change"]):
            t = datetime.fromisoformat(x["t"])
            if T - timedelta(hours=24) <= t <= T:
                return True
    return False


def build_v4(b, mode):
    T = datetime.fromisoformat(b["alert_et"])
    b = dict(b)
    b["v3_ratings"] = v4_ratings_for_sheet(b, T)
    bypass = own_recent_change(b, T)
    gate, scope, text = build_v3(b, mode, bypass_normal=bypass)
    text = text.replace("- [자사 목표가] [목표가 변경·원인 후보] ", "- [자사 목표가 변경·원인 후보] ")
    lines = text.split("\n")
    # v3.1: 고정 일정 + 속보
    d0 = T.date()
    extra = [f"- {v} ({(datetime.fromisoformat(k).date() - d0).days:+d}일)" for k, v in sheet_v31.FIXED.items()
             if -1 <= (datetime.fromisoformat(k).date() - d0).days <= 1]
    if extra:
        c = next(i for i, l in enumerate(lines) if l.startswith("## 2."))
        if lines[c + 1] == "- 없음":
            lines[c + 1:c + 2] = extra
        else:
            lines[c + 1:c + 1] = extra
    cut = "알림 시각까지" if mode == "A" else "당일 20:00 ET까지"
    sec = [f"## 4-속보. 속보 헤드라인 — 분 단위 시각 ({cut}, 최근 60시간. 자사·동종·업종·거시 순)"]
    sec += sheet_v31.breaking_lines(b, mode) or ["- 없음"]
    at = next(i for i, l in enumerate(lines) if l.startswith("## 4-"))
    lines = lines[:at] + sec + [""] + lines[at:]
    # v3.2: 발행 시각이 확인된 기사 (A 모드)
    if mode == "A":
        art = ["## 4-기사. 기사 — 발행 시각 확인됨 (Finnhub, 알림 시각 이전 36시간, 자사→동종 최신순)"]
        art += sheet_v32.lines(b["ticker"], T) or ["- 없음"]
        at = next(i for i, l in enumerate(lines) if l.startswith("## 4-속보"))
        lines = lines[:at] + art + [""] + lines[at:]
    return gate, scope, "\n".join(lines), bypass


def main(mode, lo, hi):
    out_dir = bt_config.path("sheets_v4", mode, "_")[:-2]
    for i in range(lo, hi + 1):
        eid = f"{bt_config.PREFIX}{i:03d}"
        with open(bt_config.path("bundles_v3", eid + ".json"), encoding="utf-8") as f:
            b = json.load(f)
        b["etfs"], b["peers"] = META[b["ticker"]]["etfs"], META[b["ticker"]]["peers"]
        gate, scope, text, bypass = build_v4(b, mode)
        with open(os.path.join(out_dir, eid + ".txt"), "w", encoding="utf-8") as f:
            f.write(text)
        print(eid, gate, scope, "게이트우회" if bypass else "")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
