"""
Stock Sentinel — 증거 시트 (v4)

판단 AI에게 줄 증거를 층별로 정리한다. 숫자로 정할 수 있는 것(범위, 급변 시각)은 여기서 코드로 정하고,
AI는 시트 안에서 원인만 고른다. 숫자만으로 원인을 단정하지 않는다(연구 대장 #077: 수치 역추적 35%).

백테스트 원형: eval/backtest/sheet_v4.py
"""
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from collectors import evidence as ev
from collectors.market_context import sector_etf_for, _peers
from collectors.noise_filter import classify_noise

MARKET = ["SPY", "QQQ"]


def _fmt(p):
    return "n/a" if p is None else f"{p:+.2f}%"


def judge_scope(pct: float, sigma: Optional[float], mkt: Optional[float], etf_moves: List,
                peer_moves: List) -> str:
    """시장 / 섹터 / 섹터+개별 / 개별. 같은 방향으로 절반 이상 움직였는지로 본다."""
    def same(p, ratio):
        return p is not None and pct and p * pct > 0 and abs(p) >= ratio * abs(pct)

    sec = [p for _, p in etf_moves if p is not None]
    sec_best = max(sec, key=lambda p: p * (1 if pct > 0 else -1)) if sec else None
    peer_same = [p for _, p in peer_moves if same(p, 0.5)]
    peer_share = len(peer_same) / len(peer_moves) if peer_moves else 0
    if same(mkt, 0.5) and (sec_best is None or abs(sec_best) < 1.6 * abs(mkt)):
        return "시장"
    if same(sec_best, 0.45) or peer_share >= 0.5:
        return "섹터"
    if same(mkt, 0.35) or same(sec_best, 0.3):
        return "섹터+개별"
    return "개별"


def build(ticker: str, watch, price_data: Dict, news_data: List[Dict], now: datetime = None,
          market_context: Dict = None, prev_alert: Dict = None, followup: bool = False) -> Dict:
    now = now or datetime.now(ev.ET)
    day = now.date()
    peers = _peers(watch, limit=4) if watch else []
    etf = sector_etf_for(watch) if watch else "QQQ"
    sector = ev.SECTOR.get(etf, ev.SECTOR["QQQ"])
    etfs = sector["etfs"]
    tm = ev.intraday([ticker] + MARKET + etfs + peers)

    def move(sym):
        v = tm.get(sym)
        return v["last"] if v and v.get("date") == day.isoformat() else None

    lines: List[str] = []
    pd = price_data or {}
    session = pd.get("session", "regular")
    if session in ("pre", "post") and pd.get("ext_change_pct") is not None:
        pct = pd["ext_change_pct"]
        label = "프리마켓" if session == "pre" else "시간외"
        lines.append(f"{ticker} {label} {pct:+.2f}% (직전 정규장 종가 대비, 정규장은 {pd.get('change_pct', 0):+.2f}%)")
    else:
        pct = pd.get("change_pct", 0) or 0
        sig = pd.get("vol20")
        hi = 100 * (pd["high"] / pd["prev_close"] - 1) if pd.get("high") and pd.get("prev_close") else None
        lo = 100 * (pd["low"] / pd["prev_close"] - 1) if pd.get("low") and pd.get("prev_close") else None
        z = f" = 평소 하루 변동폭(σ {sig:.2f}%)의 {pct / sig:+.1f}배" if sig else ""
        lines.append(f"{ticker} {'정규장 마감' if followup else '현재'} {pct:+.2f}% (장중 고점 {_fmt(hi)}, 저점 {_fmt(lo)}){z}")
        if abs(pd.get("intraday_reversal") or 0) >= 2.5:
            lines.append(f"장중 반전 {pd['intraday_reversal']:+.1f}%p — {pd.get('reversal_detail', '')}")

    ctx = market_context or {}
    mkt = move("QQQ") if move("QQQ") is not None else ctx.get("qqq")
    spy = move("SPY") if move("SPY") is not None else ctx.get("spy")
    etf_moves = [(s, move(s) if move(s) is not None else (ctx.get("sector") if s == ctx.get("sector_etf") else None)) for s in etfs]
    peer_moves = [(s, move(s)) for s in peers if move(s) is not None]
    if not peer_moves and ctx.get("peers"):
        peer_moves = [(p, c) for p, c in ctx["peers"]]
    lines.append(f"시장: 나스닥100(QQQ) {_fmt(mkt)}, S&P500(SPY) {_fmt(spy)}")
    lines.append("섹터 ETF: " + ", ".join(f"{s} {_fmt(p)}" for s, p in etf_moves))
    if peer_moves:
        lines.append("동종업체: " + ", ".join(f"{s} {_fmt(p)}" for s, p in peer_moves))
    scope = judge_scope(pct, pd.get("vol20"), mkt, etf_moves, peer_moves)
    sec_best = [p for _, p in etf_moves if p is not None]
    if sec_best:
        lines.append(f"섹터 대비 초과 변동 {pct - max(sec_best, key=lambda p: p * (1 if pct > 0 else -1)):+.2f}%p")
    lines.append(f"판정: 범위 {scope}")

    out = [f"# {ticker} — {'장 마감 후 재판정' if followup else '알림'} 시각 {now:%Y-%m-%d %H:%M} ET", "",
           "## 1. 움직임 (규칙 판정)"] + [f"- {l}" for l in lines]
    if prev_alert and prev_alert.get("headline"):
        out.append(f"- 오늘 앞선 알림: \"{prev_alert['headline']}\" (그때 {prev_alert.get('change_pct') or 0:+.1f}%). "
                   "그 뒤로 새로 생긴 것에 집중한다")

    # 1-시각
    out += ["", "## 1-시각. 급변 시각과 선후 관계"]
    me = tm.get(ticker)
    if me and me.get("date") == day.isoformat():
        gap = abs(me["open_pct"]) >= 0.6 * abs(me["last"]) and abs(me["open_pct"]) >= 1.5
        out.append(f"- {ticker}: 시가 {me['open_pct']:+.2f}% → {me['last']:+.2f}%. "
                   + ("시가부터 벌어진 갭 → 전날 장 마감 후~당일 장 전 소식" if gap else "장중에 움직임 → 장중 소식이거나 업종·시장 흐름"))
        if me.get("half"):
            out.append(f"- 움직임의 절반에 처음 닿은 시각 {me['half']} ET, 가장 큰 15분 변화 {me['big']:+.2f}% ({me['big_t']} ET)")
        firsts = sorted((v["half"], s, v["last"]) for s, v in tm.items()
                        if s != ticker and v.get("date") == day.isoformat() and v.get("half")
                        and v["last"] * me["last"] > 0 and abs(v["last"]) >= 1)
        if firsts:
            out.append("- 같은 방향 동종·섹터가 절반에 닿은 시각: " + ", ".join(f"{s} {h} ({p:+.1f}%)" for h, s, p in firsts[:5]))
    else:
        out.append("- 오늘 정규장 시세 없음 (장 시작 전·휴장)")

    # 2. 일정
    out += ["", "## 2. 일정 (실적 발표·FOMC·옵션 만기, 오늘 기준 일수)"]
    out += ev.calendar_lines(ticker, peers, day) or ["- 없음"]

    # 3-공시
    since = now - timedelta(days=3)
    out += ["", "## 3-공시. SEC 공시 — 자사·동종업체 (최근 3일, 접수 시각 ET)"]
    fl = sorted((f for s in [ticker] + peers for f in ev.sec_filings(s) if since <= f["t"] <= now),
                key=lambda f: f["t"], reverse=True)
    out += [f"- {'[자사] ' if f['sym'] == ticker else ''}{f['t']:%m-%d %H:%M} {f['sym']} {f['form']}"
            + (f" [{f['items']}]" if f["items"] else "") for f in fl[:12]] or ["- 없음"]

    # 3-평가 — 의견 변경 > 목표가 변경 > 동종업체
    out += ["", "## 3-평가. 증권사 의견 변경 — 자사·동종업체 (최근 3일, 기록 시각 ET)"]

    def rline(r):
        act = ev.ACTION_KR.get(r["action"], r["action"])
        pt = f", 목표가 {r['prior']:.0f}→{r['pt']:.0f}" if r["pt_change"] else ""
        grade = f"{r['frm']}→{r['to']}" if r["action"] in ("up", "down") else r["to"]
        return f"{r['t']:%m-%d %H:%M} {r['sym']} {r['firm']} {act} ({grade}{pt})"

    own = [r for r in ev.ratings(ticker) if since <= r["t"] <= now]
    peer_r = [r for s in peers for r in ev.ratings(s) if since <= r["t"] <= now]
    hard = lambda r: r["action"] in ("up", "down", "init")
    rl = [f"- [자사 의견 변경] {rline(r)}" for r in own if hard(r)]
    rl += [f"- [자사 목표가 변경·원인 후보] {rline(r)}" for r in own if not hard(r) and r["pt_change"]][:6]
    rl += [f"- [동종 의견 변경] {rline(r)}" for r in peer_r if hard(r)][:6]
    soft_peer = sum(1 for r in peer_r if not hard(r))
    if soft_peer:
        rl.append(f"- (동종업체 목표가 조정·재확인 {soft_peer}건 — 개별 원인 아님)")
    out += rl or ["- 없음"]

    # 4-기사 — 발행 시각이 확인된 기사
    urls = {}
    out += ["", "## 4-기사. 기사 — 발행 시각 확인됨 (최근 36시간, 자사→동종 최신순, 잡음 제외)"]
    seen = set()
    for who, syms, cap in (("자사", [ticker], 25), ("동종", peers, 15)):
        picked = []
        for s in syms:
            for a in ev.finnhub_articles(s):
                k = a["headline"].lower()[:80]
                if not (now - timedelta(hours=36) <= a["t"] <= now) or k in seen or classify_noise(a["headline"]):
                    continue
                seen.add(k)
                picked.append(a)
        picked.sort(key=lambda a: a["t"], reverse=True)
        for a in picked[:cap]:
            out.append(f"- [{who}] {a['t']:%m-%d %H:%M} ET {a['sym']} ({a['source']}) {a['headline'][:170]}")
            urls[a["headline"][:60]] = a["url"]
    if out[-1].startswith("## 4-기사"):
        out.append("- 없음")

    # 4-속보
    own_rx = re.compile(rf"\b({ev.NAMES.get(ticker, ticker)}|{ticker})\b", re.I)
    peer_rx = re.compile(r"\b(" + "|".join(ev.NAMES.get(p, p) for p in peers) + r")\b", re.I) if peers else None
    sect_rx = re.compile(sector["words"], re.I)
    hits = []
    for p in ev.breaking_posts():
        if p["t"] > now:
            continue
        pri = 0 if own_rx.search(p["text"]) else 1 if (peer_rx and peer_rx.search(p["text"])) else \
            2 if sect_rx.search(p["text"]) else 3 if ev.MACRO_RX.search(p["text"]) else None
        if pri is not None:
            hits.append((pri, p))
    tag = {0: "자사", 1: "동종", 2: "업종", 3: "거시"}
    near = [h for h in hits if h[0] < 3][:20]
    macro = [h for h in hits if h[0] == 3][:30]
    out += ["", "## 4-속보. 속보 헤드라인 — 분 단위 시각 (최근 60시간, 자사·동종·업종·거시 순)"]
    out += [f"- [{tag[k]}] {p['t']:%m-%d %H:%M} ET ({p['src']}) {p['text'][:160]}" for k, p in sorted(near, key=lambda h: h[0]) + macro] or ["- 없음"]

    # 4-업종·시장 뉴스
    for title, queries in (("업종", sector["queries"]), ("시장", ev.MARKET_QUERIES)):
        out += ["", f"## 4-{title}. {title} 뉴스 (최근 2일, 발행 시각 ET)"]
        items, seen2 = [], set()
        for q in queries:
            for n in ev.google_news(q):
                k = n["title"].lower()[:80]
                if n["t"] <= now and k not in seen2 and not classify_noise(n["title"]):
                    seen2.add(k)
                    items.append(n)
        items.sort(key=lambda n: n["t"], reverse=True)
        out += [f"- {n['t']:%m-%d %H:%M} {n['title'][:160]}" for n in items[:15]] or ["- 없음"]

    # 4-종목 뉴스 (운영 수집분: 관련도·최신성 정렬)
    from collectors.news_collector import analysis_view, format_age
    out += ["", "## 4-종목. 종목 뉴스 (관련도·최신순)"]
    for n in analysis_view(news_data or [], limit=15):
        title = n.get("title", "")
        out.append(f"- [{format_age(n.get('age_hours'))}] {title[:160]}")
        urls.setdefault(title[:60], n.get("url", ""))
    if out[-1].startswith("## 4-종목"):
        out.append("- 없음")

    return {"text": "\n".join(out), "scope": scope, "urls": urls}
