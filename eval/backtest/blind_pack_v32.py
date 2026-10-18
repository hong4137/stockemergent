"""v3.2 A 독립 채점 묶음: 109건 × 세 답(운영 v1, v3.1 A, v3.2 A)을 섞어 이름을 가린다. 대응표는 runs/v32/blind_map.json."""
import csv
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from blind_pack_v3 import jl, v3_text  # noqa: E402


def main():
    rnd = random.Random(20261020)
    E = {r["eid"]: r for r in csv.DictReader(open(os.path.join(EVAL, "events.csv"), encoding="utf-8-sig"))}
    K = {r["eid"]: r for r in csv.DictReader(open(os.path.join(EVAL, "answer_key_v2.csv"), encoding="utf-8-sig"))}
    gates = {l.split()[0]: " ".join(l.split()[1:]) for l in open(os.path.join(HERE, "gates_v3A.txt"), encoding="utf-8")}
    v31A = jl("v31", "A1", "A2", "A3", "A4")
    v32A = jl("v32", "A1", "A2", "A3", "A4")
    mapping, parts = {}, [[], []]
    for i in range(1, 110):
        eid = f"E{i:03d}"
        e, k = E[eid], K[eid]
        answers = {"prod": f"{e['headline']} — {e['detail']}",
                   "v31A": v3_text(v31A.get(eid), gates[eid]),
                   "v32A": v3_text(v32A.get(eid), gates[eid])}
        keys = list(answers)
        rnd.shuffle(keys)
        mapping[eid] = {f"X{j+1}": kk for j, kk in enumerate(keys)}
        block = [f"### {eid} {e['ticker']} {e['et_date']} 알림 {e['et_time']} ET, 알림 당시 기록 등락 {e['change_pct']}%",
                 f"정답지: [{k['confidence']}/{k['scope']}] {k['cause']}" + (f" (보조: {k['secondary']})" if k['secondary'] else ""),
                 f"실제 등락: {k['actual_move']}"]
        block += [f"X{j+1}: {answers[kk]}" for j, kk in enumerate(keys)]
        parts[(i - 1) % 2] += block + [""]
    os.makedirs(os.path.join(HERE, "runs", "v32"), exist_ok=True)
    for j, p in enumerate(parts):
        with open(os.path.join(HERE, "runs", "v32", f"blind_pack_{j+1}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(p))
    with open(os.path.join(HERE, "runs", "v32", "blind_map.json"), "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=1)
    print("events", len(mapping), "v31A", len(v31A), "v32A", len(v32A))


if __name__ == "__main__":
    main()
