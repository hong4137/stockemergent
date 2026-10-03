"""
Stock Sentinel — 잡음 기사 판별

AI에게 '왜 움직였나'를 물을 때 원인이 아닌 기사가 섞이면 순환논리가 생긴다.
두 종류를 걸러낸다(삭제가 아니라 분석 입력에서 뒤로 미룬다).

1. recap    : 원인 없이 "얼마 올랐다/내렸다"만 다시 쓴 기사
              예) "Cloudflare Inc Stock (NET) Moved Up by 5.46% on Aug 13: Facts"
                  "Qualcomm Stock Price Up 1.5% - Still a Buy?"
2. holdings : MarketBeat류 13F 보유 변동 보고서
              예) "Micron Technology, Inc. $MU Shares Sold by Patton Fund Management Inc."

실측(저장 제목 4,983건): recap 약 3~7%, holdings 약 1%.
진짜 원인이 담긴 제목("Micron shares fall 5% after weak guidance",
"Pershing Square takes stake in Netflix")은 통과해야 한다 — tests는 하단 참조.
"""
import re

_MOVE = (
    r"(up|down|rises?|rose|falls?|fell|jumps?|jumped|gains?|gained|drops?|dropped|"
    r"slips?|slipped|climbs?|climbed|sinks?|sank|soars?|soared|surges?|surged|"
    r"plunges?|plunged|tumbles?|tumbled|rallies|rallied|declines?|declined|"
    r"moved up|moved down|trades? (?:up|down|higher|lower)|trading (?:up|down|higher|lower)|"
    r"gaps? (?:up|down)|higher|lower)"
)
_PCT = r"[+-]?\d+(?:\.\d+)?\s?%"

_RECAP_PHRASES = (
    "still a buy", "time to buy", "should you buy", "is it time to", "buy or sell",
    "buy, sell, or hold", "hold or sell", "time to hold", "book profits",
    "here's what happened", "what's going on", "what happened to",
    "stock price up", "stock price down", "moved up by", "moved down by", "shares gap",
    "trading up", "trading down", "stock is up", "stock is down",
    "should you be worried", "worth buying", "now a buy", "a buy now",
    "price prediction", "stock forecast", "stock prediction",
)

# 이 단어들이 있으면 원인을 담은 제목으로 본다.
# 'after-hours'의 after는 원인이 아니므로 제외한다.
_CAUSAL = re.compile(
    r"\b(after|on|as|following|amid|despite|due to|because|thanks to|"
    r"earn\w*|guid\w*|deals?|contract\w*|downgrad\w*|upgrad\w*|lawsuit\w*|"
    r"sue[sd]?|suing|probe\w*|investigat\w*|acqui\w*|merg\w*|results?|outlook\w*|"
    r"tariff\w*|ban|bans|banned|approv\w*|partner\w*|orders?|launch\w*|unveil\w*|"
    r"announc\w*|revenue\w*|sales|demand|buyback\w*|layoffs?|offering\w*|"
    r"split\w*|dividend\w*|ceo|cfo|recall\w*|sanction\w*|export\w*)\b(?!-hours)",
    re.I,
)

# "on Jul 31", "on Monday" 같은 날짜의 on 은 원인이 아니다.
_DATEISH = re.compile(
    r"\b(?:on|for|this|last)\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b"
    r"|\b(?:on|this|last)\s+(?:monday|tuesday|wednesday|thursday|friday|today|week)\b",
    re.I,
)

# 원인처럼 보이지만 실은 정형화된 꼬리말
_GENERIC_TAILS = re.compile(
    r"[:\-–—]\s*(what investors need to know|a full analysis|key drivers unveiled|"
    r"facts behind the movement|what signal does it send|facts|here's why|here is why)\s*\??$",
    re.I,
)

_HOLDINGS = re.compile(
    r"((?:shares|stock|stake|position) (?:sold|bought|purchased|acquired) by|"
    r"\b(?:cuts|trims|raises|lowers|boosts|increases|decreases|reduces|lifts|grows|"
    r"sells|buys|acquires|takes|initiates|establishes|opens|adds to|expands|has|holds)\b"
    r"[^.]{0,40}\b(?:position|stake|holdings?|shares)\b[^.]{0,25}\bin\b|"
    r"\b(?:new|stock|share) position in\b|"
    r"\bholdings? (?:lifted|trimmed|cut|raised|lowered|boosted|reduced|increased|decreased)\b)",
    re.I,
)
# MarketBeat 보고서는 항상 캐시태그($MU)를 달거나 'Shares Sold by' 형식이다.
# 이 조건이 없으면 "Pershing Square Capital takes stake in Netflix" 같은
# 진짜 행동주의 뉴스까지 잡음으로 걸린다.
_CASHTAG = re.compile(r"\$[A-Z]{1,5}\b")
_SOLD_BY = re.compile(r"(?:shares|stock) (?:sold|bought|purchased|acquired) by", re.I)


def is_recap(title: str) -> bool:
    if not title:
        return False
    t = title.strip()
    if t.lower().startswith("why "):
        return False  # "Why Micron Stock Is Surging Today" 는 원인 기사
    t = t.replace("’", "'")  # 굽은 따옴표 정규화 (What’s → What's)
    t = _GENERIC_TAILS.sub("", t)
    t = _DATEISH.sub(" ", t)
    tl = t.lower()

    for phrase in _RECAP_PHRASES:
        if phrase in tl:
            # 문구 자체를 지우고 원인을 찾는다. "what's going on"의 on을
            # 원인 접속사로 오인하지 않기 위해서다.
            return not _CAUSAL.search(tl.replace(phrase, " "))
    if (re.search(rf"\b(?:stock|shares?)\b.*\b{_MOVE}\b.*{_PCT}", tl)
            or re.search(rf"{_PCT}.*\b{_MOVE}\b", tl)):
        return not _CAUSAL.search(tl)
    return False


def is_holdings(title: str) -> bool:
    if not title:
        return False
    return bool(_HOLDINGS.search(title)) and bool(
        _CASHTAG.search(title) or _SOLD_BY.search(title)
    )


def classify_noise(title: str) -> str:
    """'' / 'recap' / 'holdings'"""
    if is_holdings(title):
        return "holdings"
    if is_recap(title):
        return "recap"
    return ""


if __name__ == "__main__":
    cases = [
        # (제목, 기대값)
        ("Bill Ackman Takes Another Swing At NFLX After Colossal 2022 Loss", ""),
        ("NFLX Stock Soars as Bill Ackman's Pershing Square Re-Enters Netflix", ""),
        ("Pershing Square takes $1.2 billion stake in Netflix", ""),
        ("Pershing Square Capital takes stake in Netflix", ""),
        ("Elliott Management builds stake in Qualcomm, pushes for changes", ""),
        ("Why Micron Stock Is Surging Today", ""),
        ("Micron shares fall 5% after weak guidance", ""),
        ("Palo Alto Networks (NASDAQ:PANW) Stock Price Up 2.3% on Analyst Upgrade", ""),
        ("Palo Alto Networks to acquire CyberArk in $25 billion deal", ""),
        ("Netflix shares drop 4% as rising Treasury yields pressure growth stocks", ""),
        ("AMZN Stock Drops Nearly 2% After-Hours — Senate Panel Reportedly Probes Amazon", ""),
        ("Qualcomm (NASDAQ:QCOM) Stock Price Up 1.5% - Still a Buy?", "recap"),
        ("Cloudflare Inc Stock (NET) Moved Up by 5.46% on Aug 13: Facts", "recap"),
        ("Micron Technology Inc Stock (MU) Moved Down by 3.16% on Jul 31: What Investors Need To Know", "recap"),
        ("Broadcom Inc (AVGO) Shares Fall 4.0% -- What GF Score of 95 Tells Investors", "recap"),
        ("What's Going On With Micron Stock Wednesday?", "recap"),
        ("Micron Technology, Inc. $MU Shares Sold by Patton Fund Management Inc.", "holdings"),
        ("Danske Bank A S Buys New Stake in Netflix, Inc. $NFLX", "holdings"),
        ("Broadcom Inc. $AVGO Stock Acquired by CX Institutional", "holdings"),
        ("Liontrust Investment Partners LLP Decreases Holdings in Cloudflare, Inc. $NET", "holdings"),
    ]
    bad = 0
    for t, want in cases:
        got = classify_noise(t)
        mark = "✅" if got == want else "❌"
        bad += got != want
        print(f"{mark} {got or '-':9s} (기대 {want or '-':9s}) {t[:80]}")
    print(f"\n{len(cases) - bad}/{len(cases)} 통과")
