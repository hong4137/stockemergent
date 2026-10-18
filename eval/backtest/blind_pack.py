"""
홀드아웃 독립 채점 묶음 만들기 (채점규칙_v2.md '비교 방식')

건마다 네 답(운영 v1 실제, v1 재현, v2.1 A, v2.1 B)을 섞어 X1~X4로 이름을 가린다.
채점자는 어느 답이 어느 로직인지 모른다. 대응표는 runs/hold/blind_map.json 에만 둔다.
"""
import csv
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
HOLD = os.path.join(HERE, "runs", "hold")


def jl(*names):
    out = {}
    for n in names:
        p = os.path.join(HOLD, n + ".jsonl")
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    o = json.loads(line)
                    out[o["eid"]] = o
                except (json.JSONDecodeError, KeyError):
                    pass
    return out


def v2_text(o, gate):
    if o is None:
        if gate.startswith("평소"):
            return "평소 변동폭 안의 움직임이다. 특정 원인을 찾을 대상이 아니다."
        if gate.startswith("알릴"):
            return "알릴 움직임 없음 — 휴장일이거나 정규장 전이라 오늘의 움직임이 아니다(직전 거래일 등락이 남아 있는 값)."
        return "(답 없음)"
    parts = [o.get("cause", "")]
    if o.get("secondary"):
        parts.append("보조: " + o["secondary"])
    if o.get("verdict") == "원인 미확인" and o.get("excluded"):
        parts.append("배제: " + o["excluded"])
    return f"[{o.get('verdict')}] " + " / ".join(p for p in parts if p)


def main():
    rnd = random.Random(20261018)
    E = {r["eid"]: r for r in csv.DictReader(open(os.path.join(EVAL, "events.csv"), encoding="utf-8-sig"))}
    K = {r["eid"]: r for r in csv.DictReader(open(os.path.join(EVAL, "answer_key_v2.csv"), encoding="utf-8-sig"))}
    gates = {l.split()[0]: " ".join(l.split()[1:]) for l in open(os.path.join(HERE, "gates_A_hold.txt"), encoding="utf-8")}
    A, B, V = jl("A1", "A2"), jl("B1", "B2"), jl("V1", "V2")
    mapping, lines = {}, []
    for i in range(68, 110):
        eid = f"E{i:03d}"
        e, k = E[eid], K[eid]
        answers = {
            "prod": f"{e['headline']} — {e['detail']}",
            "v1r": (f"{V[eid].get('headline','')} — {V[eid].get('detail','')}" if eid in V else "(답 없음)"),
            "v2A": v2_text(A.get(eid), gates[eid]),
            "v2B": v2_text(B.get(eid), gates[eid]),
        }
        keys = list(answers)
        rnd.shuffle(keys)
        mapping[eid] = {f"X{j+1}": kk for j, kk in enumerate(keys)}
        lines.append(f"### {eid} {e['ticker']} {e['et_date']} 알림 {e['et_time']} ET, 알림 당시 기록 등락 {e['change_pct']}%")
        lines.append(f"정답지: [{k['confidence']}/{k['scope']}] {k['cause']}" + (f" (보조: {k['secondary']})" if k['secondary'] else ""))
        lines.append(f"실제 등락: {k['actual_move']}")
        for j, kk in enumerate(keys):
            lines.append(f"X{j+1}: {answers[kk]}")
        lines.append("")
    with open(os.path.join(HOLD, "blind_pack.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(os.path.join(HOLD, "blind_map.json"), "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=1)
    print("events", len(mapping), "A", len(A), "B", len(B), "V", len(V))


if __name__ == "__main__":
    main()
