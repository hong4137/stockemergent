"""
v3 증거 추가 (채점규칙_v3.md): 기존 묶음(bundles/) 위에 정보원을 더해 bundles_v3/ 에 쓴다.

  ratings  증권사 의견 변경 — yfinance upgrades_downgrades (종목 + 동종업체)
  filings  SEC 공시 — 종목 + 동종업체, 8-K 항목 번호 포함
  timing   급변 시각 — 5분봉(없으면 1시간봉)으로 이 종목·동종업체·섹터 ETF가 언제 움직였나

시각은 모두 미 동부(ET). yfinance 의견 변경 시각은 시간대가 표시되지 않아 ET로 간주한다
(UTC라면 실제보다 늦게 보는 쪽이라 누출이 생기지 않는다).
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import requests  # noqa: E402
import yfinance as yf  # noqa: E402

import collect  # noqa: E402
from collect import ET, META, SEC_UA, _cache, _PX  # noqa: E402

import bt_config  # noqa: E402
OUT = bt_config.path("bundles_v3", "_")[:-2]
os.makedirs(OUT, exist_ok=True)

# 8-K 항목 번호 → 뜻 (판단 AI가 읽을 수 있게)
ITEMS = {
    "1.01": "중요 계약 체결", "1.02": "중요 계약 종료", "1.05": "사이버보안 사고", "2.01": "인수·매각 완료",
    "2.02": "실적 발표", "2.03": "채무 발생", "2.05": "구조조정 비용", "2.06": "자산 손상",
    "3.01": "상장 관련 통지", "3.02": "미등록 증권 발행", "5.02": "임원·이사 변동", "5.03": "정관 변경",
    "5.07": "주주총회 결과", "7.01": "공정공시(Reg FD)", "8.01": "기타 중요 사건", "9.01": "재무제표·첨부",
}


def ratings(sym):
    def go():
        try:
            d = yf.Ticker(sym).upgrades_downgrades
        except Exception:
            return []
        if d is None or len(d) == 0:
            return []
        d = d.reset_index()
        out = []
        for _, r in d.iterrows():
            ts = r.get("GradeDate")
            if ts is None or str(ts) < bt_config.SINCE:
                continue
            out.append(dict(t=str(ts)[:19], firm=str(r.get("Firm", "")), to=str(r.get("ToGrade", "")),
                            frm=str(r.get("FromGrade", "")), action=str(r.get("Action", "")),
                            pt_action=str(r.get("priceTargetAction", "")),
                            pt=float(r.get("currentPriceTarget") or 0), prior=float(r.get("priorPriceTarget") or 0)))
        return out
    return _cache(f"ratings|{sym}|20261018{bt_config.TAG}", go)


def cik_map():
    def go():
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_UA, timeout=30)
        return {v["ticker"]: str(v["cik_str"]).zfill(10) for v in r.json().values()}
    return _cache("sec|cikmap|20261018", go)


def filings(sym):
    cik = cik_map().get(sym)
    if not cik:
        return []

    def go():
        time.sleep(0.2)
        r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=SEC_UA, timeout=30)
        if r.status_code != 200:
            return []
        rec = r.json()["filings"]["recent"]
        n = len(rec["form"])
        return [dict(form=rec["form"][i], accepted=rec["acceptanceDateTime"][i],
                     items=(rec.get("items") or [""] * n)[i], desc=(rec.get("primaryDocDescription") or [""] * n)[i])
                for i in range(n) if rec["filingDate"][i] >= bt_config.SINCE]
    return _cache(f"sec2|{sym}|20261018{bt_config.TAG}", go)


ACTION = {"up": "상향", "down": "하향", "init": "커버리지 개시", "main": "유지(목표가 변경)", "reit": "재확인"}


def rating_lines(sym, T, end):
    out = []
    for r in ratings(sym):
        t = datetime.fromisoformat(r["t"]).replace(tzinfo=ET)
        if T - timedelta(days=3) <= t <= end:
            act = ACTION.get(r["action"], r["action"])
            pt = f", 목표가 {r['prior']:.0f}→{r['pt']:.0f}" if r["pt"] and r["prior"] and r["pt"] != r["prior"] else ""
            grade = f"{r['frm']}→{r['to']}" if r["action"] in ("up", "down") else r["to"]
            out.append(dict(t=t, line=f"{t:%m-%d %H:%M} {sym} {r['firm']} {act} ({grade}{pt})",
                            hard=r["action"] in ("up", "down", "init"), before=t <= T))
    return out


def rating_lines_v4(sym, T, end):
    """v4: 기록 시각을 UTC로 보고 동부시각으로 바꾼다. 목표가 변경(pt)을 따로 표시한다."""
    from datetime import timezone
    out = []
    for r in ratings(sym):
        t = datetime.fromisoformat(r["t"]).replace(tzinfo=timezone.utc).astimezone(ET)
        if T - timedelta(days=3) <= t <= end:
            act = ACTION.get(r["action"], r["action"])
            changed = bool(r["pt"] and r["prior"] and r["pt"] != r["prior"])
            pt = f", 목표가 {r['prior']:.0f}→{r['pt']:.0f}" if changed else ""
            grade = f"{r['frm']}→{r['to']}" if r["action"] in ("up", "down") else r["to"]
            out.append(dict(t=t, line=f"{t:%m-%d %H:%M} {sym} {r['firm']} {act} ({grade}{pt})",
                            hard=r["action"] in ("up", "down", "init"), pt_change=changed, before=t <= T))
    return out


def filing_lines(sym, T, end):
    out = []
    for f in filings(sym):
        if f["form"] not in collect.SEC_FORMS:
            continue
        # submissions JSON의 acceptanceDateTime은 'Z'가 붙어 있지만 UTC가 아니다.
        # 공시 헤더(ACCEPTANCE-DATETIME, 동부시각)와 대조하면 이 기간(EDT)엔 정확히 +8시간이다.
        # 예: QCOM 8-K JSON 2026-09-08T17:00:20Z = 헤더 20260908090020
        t = (datetime.fromisoformat(f["accepted"][:19]) - timedelta(hours=8)).replace(tzinfo=ET)
        if T - timedelta(days=3) <= t <= end:
            items = [i.strip() for i in (f["items"] or "").split(",") if i.strip()]
            meaning = ", ".join(f"{i} {ITEMS.get(i, '')}".strip() for i in items if i != "9.01")
            out.append(dict(t=t, line=f"{t:%m-%d %H:%M} {sym} {f['form']}" + (f" [{meaning}]" if meaning else "")
                            + (f" {f['desc']}" if f["desc"] and not meaning else ""), before=t <= T))
    return out


def timing(sym, T):
    """그날 정규장에서 T까지: 움직임의 절반에 처음 닿은 시각, 가장 큰 15분 변화 시각."""
    px = _PX.get(sym)
    if not px:
        return None
    day = T.date()
    bars, width = px["m5"], timedelta(minutes=5)
    if not any(b[0].date() == day for b in bars):
        bars, width = px["h"], timedelta(hours=1)
    today = [b for b in bars if b[0].date() == day and b[0] + width <= T]
    prev = [c for d, c in px["d"] if d < day]
    if not today or not prev:
        return None
    pc = prev[-1]
    path = [(b[0] + width, 100 * (b[1] / pc - 1)) for b in today]
    open_pct = 100 * (today[0][4] / pc - 1)
    last = path[-1][1]
    half = None
    if abs(last) >= 0.5:
        for t, p in path:
            if p * last > 0 and abs(p) >= abs(last) / 2:
                half = t
                break
    big, big_t = 0.0, None
    step = max(1, int(timedelta(minutes=15) / width))
    for i in range(step, len(path)):
        d = path[i][1] - path[i - step][1]
        if abs(d) > abs(big):
            big, big_t = d, path[i][0]
    return dict(open_pct=round(open_pct, 2), last=round(last, 2), half=half.strftime("%H:%M") if half else None,
                big=round(big, 2), big_t=big_t.strftime("%H:%M") if big_t else None, bar=int(width.total_seconds() // 60))


def main(lo, hi):
    syms = set(collect.MARKET)
    for m in META.values():
        syms.update(m["etfs"] + m["peers"])
    syms.update(META)
    collect.load_prices(sorted(syms))
    for i in range(lo, hi + 1):
        eid = f"{bt_config.PREFIX}{i:03d}"
        with open(os.path.join(collect.BUNDLES, eid + ".json"), encoding="utf-8") as f:
            b = json.load(f)
        tk = b["ticker"]
        m = META[tk]
        T = datetime.fromisoformat(b["alert_et"])
        close_b = T.replace(hour=20, minute=0)   # 모드 B: 당일 20:00 ET까지
        peers = m["peers"]
        r_all, f_all = [], []
        for s in [tk] + peers:
            r_all += rating_lines(s, T, close_b)
            f_all += filing_lines(s, T, close_b)
        b["v3_ratings"] = [dict(line=x["line"], hard=x["hard"], before=x["before"], own=x["line"].split()[2] == tk)
                           for x in sorted(r_all, key=lambda x: x["t"], reverse=True)]
        r4 = []
        for s in [tk] + peers:
            r4 += rating_lines_v4(s, T, close_b)
        b["v4_ratings"] = [dict(line=x["line"], hard=x["hard"], pt_change=x["pt_change"], before=x["before"],
                                own=x["line"].split()[2] == tk, t=x["t"].isoformat())
                           for x in sorted(r4, key=lambda x: x["t"], reverse=True)]
        b["v3_filings"] = [dict(line=x["line"], before=x["before"], own=x["line"].split()[2] == tk)
                           for x in sorted(f_all, key=lambda x: x["t"], reverse=True)]
        b["v3_timing"] = {s: timing(s, T) for s in [tk] + m["etfs"] + peers + ["QQQ"]}
        with open(os.path.join(OUT, eid + ".json"), "w", encoding="utf-8") as f:
            json.dump(b, f, ensure_ascii=False, indent=1, default=str)
        print(eid, tk, "ratings", sum(x["before"] for x in b["v3_ratings"]), "/", len(b["v3_ratings"]),
              "filings", sum(x["before"] for x in b["v3_filings"]), "/", len(b["v3_filings"]), flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]))
