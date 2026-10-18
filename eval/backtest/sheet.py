"""
증거 묶음(bundles/Exxx.json) → 판단용 증거 시트(sheets/{mode}/Exxx.txt)

규칙으로 정하는 것 (AI에게 맡기지 않는다)
  1. 알릴 움직임이 있나 — 휴장일, 정규장 전(묵은 값), 평소 변동폭 이내
  2. 범위 — 시장/섹터/개별 (숫자는 '범위'와 '배제'에만 쓴다. 원인은 정하지 않는다: 연구 대장 #077)
  3. 뉴스 잡음 표시 — 임원 지분 매각(Form 4), 13F 보유 보고, 등락 재탕 기사, '살 만한 주식' 목록
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, HERE)
import bt_config  # noqa: E402
BUNDLES = bt_config.path("bundles", "_")[:-2]

NOISE = [
    (r"\b(sells?|sold|selling|buys?|bought)\b.*\bshares?\b.*\b(director|officer|ceo|cfo|cto|evp|svp|insider|trustee|chief)\b|"
     r"\b(director|officer|ceo|cfo|cto|evp|svp|insider|trustee|chief)\b.*\b(sells?|sold|buys?|bought|to sell)\b", "임원 지분 거래"),
    (r"\b(stake|position|holdings?|shares)\b.*\b(acquires?|raises?|lifts?|boosts?|trims?|cuts?|lowers?|reduces?|sells?|buys?|grows?|increases?|decreases?)\b|"
     r"\b(acquires?|raises?|lifts?|boosts?|trims?|cuts?|lowers?|reduces?|grows?|increases?|decreases?)\b.*\b(stake|position|holdings)\b|"
     r"\b13f\b|\bLLC\b.*\bshares\b", "기관 보유 변동(13F)"),
    (r"\b(best|top \d+|\d+ (stocks?|reasons)|should you buy|buy now|is it a buy|millionaire|forever|dividend stocks)\b", "추천·목록 기사"),
    (r"\b(stock|shares)\b.*\b(price|trading)\b.*\b(down|up)\b.*\b(here'?s why|what'?s next)\b|"
     r"\b(trading (down|up|higher|lower) \d|shares (gap|trade) (up|down)|stock price (down|up) \d|"
     r"hits new (12-month|52-week) (high|low)|sets new|reaches new)\b", "등락 재탕"),
    (r"\b(price target|forecast|prediction)\b.*\b(20[23]\d)\b|\bstock forecast\b", "전망 기사"),
]
NOISE_RX = [(re.compile(p, re.I), tag) for p, tag in NOISE]


NOTABLE = re.compile(r"\b(ackman|pershing square|berkshire|buffett|icahn|elliott|starboard|activist|13d)\b", re.I)


def tag(title):
    if NOTABLE.search(title):
        return ""
    for rx, t in NOISE_RX:
        if rx.search(title):
            return t
    return ""


def fmt(p):
    return "n/a" if p is None else f"{p:+.2f}%"


def judge_scope(b, bypass_normal=False):
    """숫자로 범위를 정한다. 반환: (gate, scope, lines)"""
    tk = b["ticker"]
    mv = b["moves_at_alert"]
    me = (mv.get(tk) or {})
    lines = []
    if not b["trading_day"]:
        return "알릴 움직임 없음", None, [f"{b['alert_et'][:10]}({b['weekday']})은 미국 증시 휴장일이다. "
                                        f"직전 거래일 {b.get('last_session', {}).get('date')} 등락 {fmt(b.get('last_session', {}).get('pct'))}는 이미 지난 움직임이다."]
    if me.get("pct") is None:
        ls = b.get("last_session", {})
        return "알릴 움직임 없음", None, [f"알림 시각 {b['alert_et'][11:16]} ET는 정규장 시작 전이다. 오늘 정규장 움직임은 아직 없다. "
                                        f"직전 거래일 {ls.get('date')} 등락 {fmt(ls.get('pct'))}는 이미 지난 움직임이다(장전 시세는 이 시트에 없다)."]
    pct = me["pct"]
    sig = b.get("sigma20") or 2.0
    z = pct / sig
    lines.append(f"{tk} 알림 시점 {fmt(pct)} (장중 고점 {fmt(me.get('high_pct'))}, 저점 {fmt(me.get('low_pct'))}) "
                 f"= 평소 하루 변동폭(σ {sig:.2f}%)의 {z:+.1f}배")
    rev = None
    if pct >= 0 and me.get("low_pct") is not None and me["low_pct"] < 0:
        rev = pct - me["low_pct"]
    elif pct < 0 and me.get("high_pct") is not None and me["high_pct"] > 0:
        rev = me["high_pct"] - pct
    if rev and rev >= 2.5:
        lines.append(f"장중 반전 폭 {rev:.1f}%p (방향이 바뀐 날이다)")

    mkt = (mv.get("QQQ") or {}).get("pct")
    spy = (mv.get("SPY") or {}).get("pct")
    lines.append(f"시장: 나스닥100(QQQ) {fmt(mkt)}, S&P500(SPY) {fmt(spy)}")
    etf_moves = [(s, (mv.get(s) or {}).get("pct")) for s in b["etfs"]]
    lines.append("섹터 ETF: " + ", ".join(f"{s} {fmt(p)}" for s, p in etf_moves))
    peer_moves = [(s, (mv.get(s) or {}).get("pct")) for s in b["peers"]]
    peer_moves = [(s, p) for s, p in peer_moves if p is not None]
    lines.append("동종업체: " + ", ".join(f"{s} {fmt(p)}" for s, p in peer_moves))

    if abs(z) < 1.0 and abs(pct) < 1.5 and not bypass_normal:
        return "평소 범위", None, lines + ["→ 평소 변동폭 안의 움직임이다. 원인을 찾을 대상이 아니다."]

    def same(p, ratio):
        return p is not None and p * pct > 0 and abs(p) >= ratio * abs(pct)

    sec = [p for _, p in etf_moves if p is not None]
    sec_best = max(sec, key=lambda p: p * (1 if pct > 0 else -1)) if sec else None
    peer_same = [p for _, p in peer_moves if same(p, 0.5)]
    peer_share = len(peer_same) / len(peer_moves) if peer_moves else 0
    if same(mkt, 0.5) and (sec_best is None or abs(sec_best) < 1.6 * abs(mkt)):
        scope = "시장"
    elif same(sec_best, 0.45) or peer_share >= 0.5:
        scope = "섹터"
    elif same(mkt, 0.35) or same(sec_best, 0.3):
        scope = "섹터+개별"
    else:
        scope = "개별"
    resid = pct - (sec_best if sec_best is not None else (mkt or 0))
    lines.append(f"섹터 대비 초과 변동 {resid:+.2f}%p, 같은 방향으로 절반 이상 움직인 동종업체 {len(peer_same)}/{len(peer_moves)}")
    return "알림 대상", scope, lines


def build_sheet(b, mode, bypass_normal=False):
    gate, scope, mlines = judge_scope(b, bypass_normal)
    out = [f"# {b['eid']} {b['ticker']} ({b['name']}) — 알림 시각 {b['alert_et'][:16].replace('T', ' ')} ET",
           "", "## 1. 움직임 (규칙 판정)"] + [f"- {l}" for l in mlines]
    out.append(f"- 판정: {gate}" + (f" / 범위: {scope}" if scope else ""))
    if b.get("prev_days"):
        out.append("- 최근 5거래일 등락: " + ", ".join(f"{d[5:]} {p:+.1f}%" for d, p in b["prev_days"]))

    out += ["", "## 2. 일정 (실적 발표·FOMC, 알림일 기준 일수)"]
    out += [f"- {c['symbol']} {c.get('earnings_et') or c.get('date')} ({c['days_from_alert']:+d}일)" for c in b["calendar"]] or ["- 없음"]

    out += ["", "## 3. SEC 공시 (알림 시각 이전 4일)"]
    secs = [s for s in b["sec"] if s["before_alert"] or mode == "B"]
    f4 = [s for s in secs if s["form"] == "4"]
    other = [s for s in secs if s["form"] != "4"]
    out += [f"- {s['form']} {s['accepted_et']} {s['desc']}" for s in other] or ["- 주요 공시 없음"]
    if f4:
        out.append(f"- (임원 지분 거래 Form 4 {len(f4)}건 — 정기적 매각은 원인이 아니다)")

    news = b["news_A"] if mode == "A" else b["news_B"]
    cutoff = "알림 전날까지" if mode == "A" else "알림 당일 장 마감 무렵(20:00 ET)까지"
    for kind in ("종목", "동종", "섹터", "시장"):
        items = [n for n in news if n["kind"] == kind]
        clean = [n for n in items if not tag(n["title"])]
        noisy = [n for n in items if tag(n["title"])]
        out += ["", f"## 4-{kind}. {kind} 뉴스 ({cutoff} 발행, 최신순)"]
        out += [f"- [{n['date']}] {n['title']}" for n in clean[:25]] or ["- 없음"]
        if noisy:
            out.append(f"- (잡음으로 분류해 뺀 기사 {len(noisy)}건: " +
                       "; ".join(f"{tag(n['title'])}" for n in noisy[:3]) + " 등)")
    return gate, scope, "\n".join(out)


def main(mode, eids):
    os.makedirs(os.path.join(HERE, "sheets", mode), exist_ok=True)
    summary = {}
    for eid in eids:
        with open(os.path.join(BUNDLES, eid + ".json"), encoding="utf-8") as f:
            b = json.load(f)
        from collect import META
        b["etfs"], b["peers"] = META[b["ticker"]]["etfs"], META[b["ticker"]]["peers"]
        gate, scope, text = build_sheet(b, mode)
        with open(os.path.join(HERE, "sheets", mode, eid + ".txt"), "w", encoding="utf-8") as f:
            f.write(text)
        summary[eid] = (gate, scope)
    return summary


if __name__ == "__main__":
    mode = sys.argv[1]
    lo, hi = int(sys.argv[2]), int(sys.argv[3])
    s = main(mode, [f"{bt_config.PREFIX}{i:03d}" for i in range(lo, hi + 1)])
    for k, v in s.items():
        print(k, *v)
