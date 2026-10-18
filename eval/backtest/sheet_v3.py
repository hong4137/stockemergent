"""
v3 증거 시트: v2 시트(sheet.build_sheet)에 정보원 층을 더한다.  python sheet_v3.py A 1 109

추가 섹션
  1-시각  급변 시각 — 갭이었나 장중이었나, 동종업체·섹터 중 누가 먼저 움직였나
  3-공시  자사·동종업체 SEC 공시 (8-K 항목 뜻 포함)  ← v2의 SEC 섹션을 대체
  3-평가  증권사 의견 변경 (자사 → 동종업체 순, 상향·하향·개시를 먼저)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from collect import META  # noqa: E402
from sheet import build_sheet  # noqa: E402


def timing_lines(b):
    tk = b["ticker"]
    tm = b.get("v3_timing") or {}
    me = tm.get(tk)
    if not me:
        return ["- 정규장 시세 없음 (장 시작 전·휴장)"]
    out = []
    gap = abs(me["open_pct"]) >= 0.6 * abs(me["last"]) and abs(me["open_pct"]) >= 1.5
    kind = "시가부터 벌어진 갭 → 장 시작 전(전날 장 마감 후~당일 장 전)에 나온 소식" if gap else "장중에 움직임 → 장중에 나온 소식이거나 업종·시장 흐름"
    out.append(f"- {tk}: 시가 {me['open_pct']:+.2f}% → 알림 시점 {me['last']:+.2f}%. {kind}")
    if me.get("half"):
        out.append(f"- {tk}가 움직임의 절반에 처음 닿은 시각 {me['half']} ET, 가장 큰 15분 변화 {me['big']:+.2f}% ({me['big_t']} ET, {me['bar']}분봉)")
    firsts = []
    for s, v in tm.items():
        if s == tk or not v or not v.get("half") or v["last"] * me["last"] <= 0 or abs(v["last"]) < 1:
            continue
        firsts.append((v["half"], s, v["last"]))
    if firsts:
        firsts.sort()
        out.append("- 같은 방향 동종·섹터가 절반에 닿은 시각: " + ", ".join(f"{s} {h} ({p:+.1f}%)" for h, s, p in firsts[:5]))
    return out


def build_v3(b, mode, bypass_normal=False):
    gate, scope, text = build_sheet(b, mode, bypass_normal)
    lines = text.split("\n")
    # v2의 '## 3. SEC 공시' 섹션을 걷어내고 v3 섹션으로 바꾼다
    start = next(i for i, l in enumerate(lines) if l.startswith("## 3."))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("## "))
    before_ok = (lambda x: x["before"]) if mode == "A" else (lambda x: True)
    cut = "알림 시각까지" if mode == "A" else "당일 20:00 ET까지"

    sec = ["## 3-공시. SEC 공시 — 자사·동종업체 (" + cut + ", 최근 3일)"]
    fl = [x for x in b.get("v3_filings", []) if before_ok(x) and " 4 " not in x["line"]]
    sec += [f"- {'[자사] ' if x['own'] else ''}{x['line']}" for x in fl[:12]] or ["- 없음"]

    sec += ["", "## 3-평가. 증권사 의견 변경 — 자사·동종업체 (" + cut + ", 최근 3일. 시각은 기록 시각)"]
    rl = [x for x in b.get("v3_ratings", []) if before_ok(x)]
    hard_own = [x for x in rl if x["own"] and x["hard"]]
    hard_peer = [x for x in rl if not x["own"] and x["hard"]]
    soft_own = [x for x in rl if x["own"] and not x["hard"]]
    soft_peer = [x for x in rl if not x["own"] and not x["hard"]]
    sec += [f"- [자사 의견 변경] {x['line']}" for x in hard_own]
    sec += [f"- [동종 의견 변경] {x['line']}" for x in hard_peer[:6]]
    sec += [f"- [자사 목표가] {x['line']}" for x in soft_own[:6]]
    if soft_peer:
        sec.append(f"- (동종업체 목표가 조정·재확인 {len(soft_peer)}건 — 개별 원인 아님)")
    if not rl:
        sec.append("- 없음")

    tim = ["", "## 1-시각. 급변 시각과 선후 관계"] + timing_lines(b)
    # 움직임 섹션(## 1.) 바로 뒤에 시각 섹션을 넣는다
    two = next(i for i, l in enumerate(lines) if l.startswith("## 2."))
    new = lines[:two] + tim[1:] + [""] + lines[two:start] + sec + [""] + lines[end:]
    return gate, scope, "\n".join(new)


def main(mode, lo, hi):
    import bt_config
    out_dir = bt_config.path("sheets_v3", mode, "_")[:-2]
    os.makedirs(out_dir, exist_ok=True)
    for i in range(lo, hi + 1):
        eid = f"{bt_config.PREFIX}{i:03d}"
        with open(bt_config.path("bundles_v3", eid + ".json"), encoding="utf-8") as f:
            b = json.load(f)
        b["etfs"], b["peers"] = META[b["ticker"]]["etfs"], META[b["ticker"]]["peers"]
        gate, scope, text = build_v3(b, mode)
        with open(os.path.join(out_dir, eid + ".txt"), "w", encoding="utf-8") as f:
            f.write(text)
        print(eid, gate, scope)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
