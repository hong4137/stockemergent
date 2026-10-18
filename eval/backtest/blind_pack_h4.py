"""새 홀드아웃(h4) 독립 채점 묶음: 45건 × 세 답(v3.2 A, v4 A, v4 B)을 섞어 이름을 가린다.
대응표는 holdout4/runs/blind_map.json 에만 둔다."""
import csv
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from blind_pack import v2_text  # noqa: E402

H4 = os.path.join(os.path.dirname(HERE), "holdout4")


def jl(*names):
    out = {}
    for n in names:
        p = os.path.join(H4, "runs", n + ".jsonl")
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                if line.strip():
                    try:
                        o = json.loads(line)
                        out[o["eid"]] = o
                    except (json.JSONDecodeError, KeyError):
                        pass
    return out


def text(o, gate):
    t = v2_text(o, gate)
    return t + (f" (근거: {o['layer']})" if o and o.get("layer") else "")


def gates(name):
    return {l.split()[0]: " ".join(l.split()[1:4]) for l in open(os.path.join(H4, name), encoding="utf-8")}


def main():
    rnd = random.Random(20261021)
    E = {r["eid"]: r for r in csv.DictReader(open(os.path.join(H4, "events.csv"), encoding="utf-8"))}
    K = {r["eid"]: r for r in csv.DictReader(open(os.path.join(H4, "answer_key.csv"), encoding="utf-8-sig"))}
    g3, g4A, g4B = gates("gates_v3A.txt"), gates("gates_v4A.txt"), gates("gates_v4B.txt")
    a32 = jl("v32A_1", "v32A_2")
    a4A = jl("v4A_1", "v4A_2")
    a4B = jl("v4B_1", "v4B_2")
    mapping, lines = {}, []
    for i in range(1, 46):
        eid = f"H{i:03d}"
        e, k = E[eid], K[eid]
        answers = {"v32A": text(a32.get(eid), g3[eid]), "v4A": text(a4A.get(eid), g4A[eid]), "v4B": text(a4B.get(eid), g4B[eid])}
        keys = list(answers)
        rnd.shuffle(keys)
        mapping[eid] = {f"X{j+1}": kk for j, kk in enumerate(keys)}
        lines += [f"### {eid} {e['ticker']} {e['et_date']} 알림 {e['et_time']} ET, 알림 당시 기록 등락 {e['change_pct']}%",
                  f"정답지: [{k['confidence']}/{k['scope']}] {k['cause']}" + (f" (보조: {k['secondary']})" if k['secondary'] else ""),
                  f"실제 등락: {k['actual_move']}"]
        lines += [f"X{j+1}: {answers[kk]}" for j, kk in enumerate(keys)] + [""]
    with open(os.path.join(H4, "runs", "blind_pack.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(os.path.join(H4, "runs", "blind_map.json"), "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=1)
    print("events", len(mapping), "v32A", len(a32), "v4A", len(a4A), "v4B", len(a4B))


if __name__ == "__main__":
    main()
