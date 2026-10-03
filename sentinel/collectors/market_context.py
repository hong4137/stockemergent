"""
Stock Sentinel — Market Context

AI에게 '시장 전체·섹터·동종업체가 오늘 어떻게 움직였는지'를 숫자로 준다.

이게 없을 때 AI는 원인이 안 보이면 "섹터 동반 하락", "매크로 영향"을 지어냈다.
7주간 AI가 섹터/매크로로 설명한 58건 중 22건(38%)이 실제 데이터와 맞지 않았다.
  예) QCOM 9/18 -5.6% "반도체 섹터 동반 하락" — 그날 반도체 섹터(SOXX)는 +2.7%

스캔 1회당 yfinance 일괄 요청 1번으로 전 종목 맥락을 만든다.
"""
import re
from typing import Dict, List, Optional

import yfinance as yf

MARKET_INDEXES = {"SPY": "S&P500", "QQQ": "나스닥100"}

SECTOR_LABELS = {
    "SOXX": "반도체", "CIBR": "사이버보안", "IGV": "소프트웨어", "XLC": "커뮤니케이션",
    "XLY": "경기소비재", "XLK": "기술", "XLF": "금융", "XLE": "에너지",
    "XLV": "헬스케어", "XLI": "산업재", "XLP": "필수소비재", "XLU": "유틸리티",
    "XLB": "소재", "XLRE": "리츠", "QQQ": "나스닥100", "SPY": "S&P500",
}

# watchlist.json에 sector_etf가 없을 때 sector 문자열로 추정
_SECTOR_RULES = [
    (r"semi|반도체", "SOXX"),
    (r"cyber|security|보안", "CIBR"),
    (r"software|saas|cloud", "IGV"),
    (r"stream|media|communication|entertainment", "XLC"),
    (r"e-?commerce|retail|consumer disc|auto", "XLY"),
    (r"bank|financ|insur", "XLF"),
    (r"energy|oil|gas", "XLE"),
    (r"health|pharma|bio|medical", "XLV"),
    (r"industrial|aerospace|defen", "XLI"),
]

_US_TICKER = re.compile(r"^[A-Z]{1,5}$")


def sector_etf_for(watch) -> str:
    explicit = (getattr(watch, "sector_etf", "") or "").strip().upper()
    if explicit:
        return explicit
    sector = (getattr(watch, "sector", "") or "").lower()
    for pattern, etf in _SECTOR_RULES:
        if re.search(pattern, sector):
            return etf
    return "QQQ"


def _peers(watch, limit: int = 5) -> List[str]:
    """related 중 미국 티커 형태만 (SAMSUNG, 'SK HYNIX' 같은 건 제외)"""
    out = []
    for r in getattr(watch, "related", []) or []:
        r = (r or "").strip().upper()
        if _US_TICKER.match(r) and r != watch.ticker and r not in out:
            out.append(r)
        if len(out) >= limit:
            break
    return out


def _last_change(closes) -> Optional[float]:
    s = closes.dropna()
    if len(s) < 2:
        return None
    return float((s.iloc[-1] - s.iloc[-2]) / s.iloc[-2] * 100)


def build_market_context(watchlist) -> Dict[str, Dict]:
    """종목별 맥락 dict. 실패해도 빈 dict를 돌려 스캔을 막지 않는다."""
    plan = {}
    symbols = set(MARKET_INDEXES)
    for w in watchlist:
        etf = sector_etf_for(w)
        peers = _peers(w)
        plan[w.ticker] = (etf, peers)
        symbols.add(etf)
        symbols.update(peers)

    try:
        data = yf.download(
            sorted(symbols), period="5d", interval="1d",
            auto_adjust=True, progress=False, threads=True,
        )
        closes = data["Close"]
    except Exception as e:
        print(f"  ⚠️ 시장 맥락 조회 실패: {e}")
        return {}

    def chg(sym):
        try:
            v = _last_change(closes[sym])
            return round(v, 2) if v is not None else None
        except Exception:
            return None

    market = {sym: chg(sym) for sym in MARKET_INDEXES}
    ctx = {}
    for ticker, (etf, peers) in plan.items():
        peer_moves = [(p, chg(p)) for p in peers]
        ctx[ticker] = {
            "spy": market.get("SPY"),
            "qqq": market.get("QQQ"),
            "sector_etf": etf,
            "sector_label": SECTOR_LABELS.get(etf, etf),
            "sector": chg(etf),
            "peers": [(p, round(c, 2)) for p, c in peer_moves if c is not None],
        }

    ok = sum(1 for c in ctx.values() if c["sector"] is not None)
    spy = market.get("SPY")
    print(f"🌐 시장 맥락: S&P {spy:+.1f}% · 섹터 데이터 {ok}/{len(ctx)}종목"
          if spy is not None else f"🌐 시장 맥락: 섹터 데이터 {ok}/{len(ctx)}종목")
    return ctx


def assess_scope(stock_move: float, ctx: Optional[Dict]) -> Dict:
    """종목 움직임이 섹터로 설명되는지 판정.

    sector_driven: 섹터가 같은 방향으로 종목 움직임의 40% 이상을 설명
    idiosyncratic: 섹터와 2.5%p 이상 벌어졌고 섹터가 설명하지 못함
    """
    if not ctx or ctx.get("sector") is None or stock_move is None:
        return {"scope": "unknown", "excess": None}
    sector = ctx["sector"]
    excess = stock_move - sector
    same_dir = sector * stock_move > 0
    explains = same_dir and abs(sector) >= abs(stock_move) * 0.4
    if explains:
        scope = "sector_driven"
    elif abs(excess) >= 2.5:
        scope = "idiosyncratic"
    else:
        scope = "mixed"
    return {"scope": scope, "excess": round(excess, 2)}


def format_context_for_prompt(stock_move: float, ctx: Optional[Dict]) -> str:
    if not ctx:
        return "Market context: unavailable"
    lines = []
    parts = []
    if ctx.get("spy") is not None:
        parts.append(f"S&P500 {ctx['spy']:+.1f}%")
    if ctx.get("qqq") is not None:
        parts.append(f"Nasdaq100 {ctx['qqq']:+.1f}%")
    if parts:
        lines.append("Market today: " + ", ".join(parts))
    if ctx.get("sector") is not None:
        lines.append(f"Sector ETF {ctx['sector_etf']} ({ctx['sector_label']}): {ctx['sector']:+.1f}%")
    if ctx.get("peers"):
        lines.append("Peers: " + ", ".join(f"{p} {c:+.1f}%" for p, c in ctx["peers"]))
    scope = assess_scope(stock_move, ctx)
    if scope["excess"] is not None:
        verdict = {
            "sector_driven": "the sector explains most of this move",
            "idiosyncratic": "the stock diverges from its sector — look for a company-specific cause",
            "mixed": "partly sector, partly company-specific",
        }[scope["scope"]]
        lines.append(f"Stock vs sector: {scope['excess']:+.1f} percentage points ({verdict})")
    return "\n".join(lines) if lines else "Market context: unavailable"


def format_context_for_alert(stock_move: float, ctx: Optional[Dict]) -> str:
    """텔레그램 한 줄: 📊 S&P -0.4% · 반도체 +2.7% · 섹터 대비 -8.3%p"""
    if not ctx:
        return ""
    parts = []
    if ctx.get("spy") is not None:
        parts.append(f"S&P {ctx['spy']:+.1f}%")
    if ctx.get("sector") is not None:
        parts.append(f"{ctx['sector_label']} {ctx['sector']:+.1f}%")
    scope = assess_scope(stock_move, ctx)
    if scope["excess"] is not None:
        parts.append(f"섹터 대비 {scope['excess']:+.1f}%p")
    return "📊 " + " · ".join(parts) if parts else ""
