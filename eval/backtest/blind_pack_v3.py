"""
v3 독립 채점 묶음 (채점규칙_v3.md): 109건 × 일곱 답(운영 v1, v2.1 A·B, v3 A·B, v3.1 A·B)을 섞어 이름을 가린다.
묶음은 세 파일로 나눠(채점 에이전트 셋), 대응표는 runs/v3/blind_map.json 에만 둔다.
"""
import csv
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
RUNS = os.path.join(HERE, "runs")
sys.path.insert(0, HERE)

from blind_pack import v2_text  # noqa: E402


def jl(folder, *names):
    out = {}
    for n in names:
        p = os.path.join(RUNS, folder, n + ".jsonl")
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


def v3_text(o, gate):
    t = v2_text(o, gate)
    if o and o.get("layer"):
        t += f" (근거: {o['layer']})"
    return t


def main():
    rnd = random.Random(20261019)
    E = {r["eid"]: r for r in csv.DictReader(open(os.path.join(EVAL, "events.csv"), encoding="utf-8-sig"))}
    K = {r["eid"]: r for r in csv.DictReader(open(os.path.join(EVAL, "answer_key_v2.csv"), encoding="utf-8-sig"))}
    gates = {l.split()[0]: " ".join(l.split()[1:]) for l in open(os.path.join(HERE, "gates_v3A.txt"), encoding="utf-8")}
    v21A = {**jl("dev2", "A1", "A2"), **jl("hold", "A1", "A2")}
    v21B = {**jl("dev2", "B1", "B2"), **jl("hold", "B1", "B2")}
    v3A = jl("v3", "A1", "A2", "A3", "A4")
    v3B = jl("v3", "B1", "B2", "B3", "B4")
    v31A = jl("v31", "A1", "A2", "A3", "A4")
    v31B = jl("v31", "B1", "B2", "B3", "B4")
    mapping, parts = {}, [[], [], []]
    for i in range(1, 110):
        eid = f"E{i:03d}"
        e, k = E[eid], K[eid]
        answers = {
            "prod": f"{e['headline']} — {e['detail']}",
            "v21A": v2_text(v21A.get(eid), gates[eid]),
            "v21B": v2_text(v21B.get(eid), gates[eid]),
            "v3A": v3_text(v3A.get(eid), gates[eid]),
            "v3B": v3_text(v3B.get(eid), gates[eid]),
            "v31A": v3_text(v31A.get(eid), gates[eid]),
            "v31B": v3_text(v31B.get(eid), gates[eid]),
        }
        keys = list(answers)
        rnd.shuffle(keys)
        mapping[eid] = {f"X{j+1}": kk for j, kk in enumerate(keys)}
        block = [f"### {eid} {e['ticker']} {e['et_date']} 알림 {e['et_time']} ET, 알림 당시 기록 등락 {e['change_pct']}%",
                 f"정답지: [{k['confidence']}/{k['scope']}] {k['cause']}" + (f" (보조: {k['secondary']})" if k['secondary'] else ""),
                 f"실제 등락: {k['actual_move']}"]
        block += [f"X{j+1}: {answers[kk]}" for j, kk in enumerate(keys)]
        parts[(i - 1) % 3] += block + [""]
    for j, p in enumerate(parts):
        with open(os.path.join(RUNS, "v3", f"blind_pack_{j+1}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(p))
    with open(os.path.join(RUNS, "v3", "blind_map.json"), "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=1)
    print("events", len(mapping), "v21A", len(v21A), "v21B", len(v21B), "v3A", len(v3A), "v3B", len(v3B), "v31A", len(v31A), "v31B", len(v31B))


if __name__ == "__main__":
    main()
