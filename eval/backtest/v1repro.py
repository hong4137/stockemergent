"""
현재 운영 로직(v1, 10/4 수정판)의 프롬프트를 백테스트 증거로 그대로 재현한다.

운영 코드의 build_prompt()·잡음 필터·관련도 점수를 직접 불러 쓴다. 입력만 증거 묶음에서 만든다.
  - 뉴스: 종목 뉴스만 (운영은 섹터·시장 뉴스를 수집하지 않는다), 모드 A 시점
  - 시장 맥락: SPY·QQQ·섹터 ETF·watchlist의 related 동종업체 (운영과 같은 구성)
출력: sheets/v1/Exxx.txt (판단 AI에게 그대로 준다)
"""
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SENT = os.path.join(HERE, "..", "..", "sentinel")
sys.path.insert(0, os.path.abspath(SENT))

from engines.ai_summarizer import build_prompt  # noqa: E402
from collectors.news_collector import _relevance_score, _rank  # noqa: E402
from collectors.noise_filter import classify_noise  # noqa: E402
from collectors.market_context import SECTOR_LABELS  # noqa: E402

WATCH = {"MU": ("SOXX", []), "AVGO": ("SOXX", ["NVDA", "MRVL", "QCOM"]), "PANW": ("CIBR", []),
         "NET": ("CIBR", ["FSLY", "AKAM", "DDOG", "ZS", "PANW"]), "AMZN": ("QQQ", ["MSFT", "GOOGL", "AAPL", "META", "NVDA"]),
         "QCOM": ("SOXX", ["AAPL", "AVGO", "ARM", "NVDA"]), "NFLX": ("XLC", ["DIS", "WBD", "SPOT", "ROKU", "AMZN"])}


def main(lo, hi):
    import collect
    os.makedirs(os.path.join(HERE, "sheets", "v1"), exist_ok=True)
    syms = set()
    for etf, peers in WATCH.values():
        syms.update([etf] + peers)
    collect.load_prices(sorted(syms | set(WATCH) | {"SPY", "QQQ"}))
    for i in range(lo, hi + 1):
        eid = f"E{i:03d}"
        with open(os.path.join(HERE, "bundles", eid + ".json"), encoding="utf-8") as f:
            b = json.load(f)
        tk = b["ticker"]
        T = datetime.fromisoformat(b["alert_et"])
        news = []
        for n in b["news_A"]:
            if n["kind"] != "종목":
                continue
            pub = datetime.fromisoformat(n["date"] + "T07:00:00+00:00")
            a = dict(title=n["title"], source=n["source"], url="", summary="",
                     age_hours=max(0.0, (T.astimezone(timezone.utc) - pub).total_seconds() / 3600))
            a["relevance"] = _relevance_score(a, tk)
            if a["relevance"] < 0.3:
                continue
            a["noise"] = classify_noise(a["title"])
            a["rank"] = _rank(a)
            news.append(a)
        mv = collect.move_at(tk, T) or {}
        pct = mv.get("pct")
        sig = collect.sigma20(tk, T.date())
        if pct is None:
            # 운영은 장전에도 직전 정규장 변동률을 그대로 썼다(묵은 값 사고) — 그대로 재현
            pct = (b.get("last_session") or {}).get("pct", 0.0)
            hi_, lo_ = pct, pct
        else:
            hi_, lo_ = mv["high_pct"], mv["low_pct"]
        rev = (pct - lo_) if pct >= 0 else (pct - hi_)
        price = dict(change_pct=pct, z_change=(pct / sig) if sig else None, vol20=sig, volume_ratio=1.0,
                     intraday_reversal=-rev if abs(rev) >= 2 else 0, session="regular")
        etf, peers = WATCH[tk]
        g = lambda s: (collect.move_at(s, T) or {}).get("pct")
        ctx = dict(spy=g("SPY"), qqq=g("QQQ"), sector_etf=etf, sector_label=SECTOR_LABELS.get(etf, etf),
                   sector=g(etf), peers=[(p, g(p)) for p in peers if g(p) is not None])
        prompt, _, used = build_prompt(tk, news, price, ctx, None)
        with open(os.path.join(HERE, "sheets", "v1", eid + ".txt"), "w", encoding="utf-8") as f:
            f.write(prompt)
        print(eid, tk, "news", used)


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]))
