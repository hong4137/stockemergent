"""런 결과를 정답지와 나란히 출력 (채점용). python pairs.py runs/dev1 1 67"""
import csv
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load_run(run_dir):
    out = {}
    for f in glob.glob(os.path.join(HERE, run_dir, "*.jsonl")):
        name = os.path.basename(f)[0]  # A / B / V
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                out.setdefault(name, {})[o.get("eid")] = o
    return out


def gates(mode):
    g = {}
    path = os.path.join(HERE, f"gates_{mode}.txt")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            p = line.split()
            g[p[0]] = " ".join(p[1:])
    return g


def main(run_dir, lo, hi):
    K = {r["eid"]: r for r in csv.DictReader(open(os.path.join(HERE, "..", "answer_key_v2.csv"), encoding="utf-8-sig"))}
    R = load_run(run_dir)
    G = gates("A")
    for i in range(lo, hi + 1):
        e = f"E{i:03d}"
        k = K[e]
        print(f"## {e} {k['ticker']} {k['et_date']} act {k['actual_move'][:25]} | KEY[{k['confidence']}/{k['scope']}] {k['cause'][:160]}")
        print(f"   gate: {G.get(e)}")
        for m in ("A", "B"):
            o = R.get(m, {}).get(e)
            if o:
                print(f"   {m}: [{o.get('verdict')}/{o.get('scope')}/{o.get('confidence')}] {o.get('cause','')[:170]} || 2nd {str(o.get('secondary',''))[:80]}")
        o = R.get("V", {}).get(e)
        if o:
            print(f"   V1r: [{o.get('event_type')}] {o.get('headline','')} :: {o.get('detail','')[:170]}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
