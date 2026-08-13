"""
Stock Sentinel — Pre-Signal Intelligence Engine
PSI 점수 계산 + Flash Reason 분석
가격 충격 직접 반영 + 장중 반전 감지
"""
from typing import Dict, List, Tuple
from datetime import datetime, timezone

# ── 가중치 ──
SCORE_WEIGHTS = {
    "options": 0.35,
    "attention": 0.30,
    "fact": 0.35,
}
CONFLUENCE_BONUS = 1.0

# 옵션 데이터는 무료 소스가 없어 미연동이다. 점수가 항상 0인데도 가중치 0.35를
# 그대로 두면 PSI 만점의 35%가 영구히 잠겨 전 종목이 normal에 눌린다.
# 연동되면 True로 바꾸면 된다.
OPTIONS_ENABLED = False


def _live_weights() -> dict:
    """실제로 값이 들어오는 요소들로 가중치를 재정규화한다."""
    live = {k: v for k, v in SCORE_WEIGHTS.items()
            if k != "options" or OPTIONS_ENABLED}
    total = sum(live.values())
    return {k: v / total for k, v in live.items()}


class PreSignalEngine:
    def __init__(self, ticker: str):
        self.ticker = ticker

    def calculate(
        self,
        options_data: Dict = None,
        social_data: Dict = None,
        news_data: List = None,
        price_data: Dict = None,
        news_baseline: float = None,
    ) -> Dict:
        # 1. 각 요소 점수 계산
        opt_score, opt_details = self._calc_options_score(options_data or {})
        att_score, att_details = self._calc_attention_score(
            social_data or {}, news_data or [], news_baseline
        )
        fact_score, fact_details = self._calc_fact_score(news_data or [])

        # 1b. 가격 충격 보너스 (급등/급락 시 PSI 직접 부스트)
        price_boost, price_boost_details = self._calc_price_boost(price_data or {})

        # 2. Confluence 보너스 (2개 이상 요소가 동시에 높을 때)
        high_count = sum(1 for s in [opt_score, att_score, fact_score] if s >= 5)
        confluence = CONFLUENCE_BONUS if high_count >= 2 else 0

        # 3. Noise 패널티 (평시 노이즈 수준 보정)
        noise = self._calc_noise_penalty(att_score, fact_score)

        # 4. 종합 점수 (가격 충격은 직접 가산)
        w = _live_weights()
        psi = (
            w.get("options", 0) * opt_score
            + w["attention"] * att_score
            + w["fact"] * fact_score
            + confluence
            + price_boost
            - noise
        )
        psi = max(0, min(10, round(psi, 1)))

        # 레벨 — settings.PSI_LEVELS 및 run_scan의 임계치(5=분석, 7=발송)와 일치시킨다
        if psi >= 7:
            level = "critical"
        elif psi >= 5:
            level = "alert"
        elif psi >= 3:
            level = "watch"
        else:
            level = "normal"

        return {
            "ticker": self.ticker,
            "psi_total": psi,
            "level": level,
            "options_score": round(opt_score, 1),
            "attention_score": round(att_score, 1),
            "fact_score": round(fact_score, 1),
            "price_boost": round(price_boost, 1),
            "confluence": confluence,
            "noise_penalty": round(noise, 1),
            "details": {
                "options": opt_details,
                "attention": att_details,
                "fact": fact_details,
                "price_boost": price_boost_details,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # =========================================================
    # 개별 점수 계산
    # =========================================================
    def _calc_options_score(self, data: Dict) -> Tuple[float, Dict]:
        """옵션 이상 감지 (추후 API 연동)"""
        score = 0.0
        details = {"factors": []}
        # TODO: 옵션 데이터 API 연동
        return score, details

    def _calc_attention_score(
        self, social: Dict, news: List, baseline: float = None
    ) -> Tuple[float, Dict]:
        """미디어 관심도 — '평소 대비' 로 측정한다.

        절대 건수로 재면 대형주는 평상시에도 20건을 넘겨 상시 만점이 됐다.
        그 결과 PSI가 5.5점 언저리에 고정돼 변별력이 사라졌고, 실제로 알림
        827건 중 19%가 주가 2% 미만에서 발송됐다. 이상 징후는 절대량이 아니라
        평소 대비 증가폭이다.
        """
        score = 0.0
        details = {"factors": []}
        news_count = len(news) if news else 0

        if not news_count:
            return 0.0, details

        if baseline and baseline >= 1:
            ratio = news_count / baseline
            if ratio >= 3:
                score = 8
                label = "폭증"
            elif ratio >= 2:
                score = 6
                label = "급증"
            elif ratio >= 1.5:
                score = 4
                label = "증가"
            elif ratio >= 1.2:
                score = 2
                label = "소폭 증가"
            else:
                score = 0
                label = "평시 수준"
            details["factors"].append(
                f"뉴스 {news_count}건 / 평소 {baseline:.0f}건 = {ratio:.1f}x ({label})"
            )
        else:
            # 이력 부족 — 절대 건수 폴백. 기존보다 보수적으로 잡는다.
            if news_count >= 25:
                score = 5
            elif news_count >= 15:
                score = 3
            elif news_count >= 8:
                score = 2
            elif news_count >= 3:
                score = 1
            details["factors"].append(f"뉴스 {news_count}건 (기준선 미확보)")

        return min(10, score), details

    def _calc_fact_score(self, news: List) -> Tuple[float, Dict]:
        """팩트 심각도 — 키워드 종류가 아니라 '몇 건의 기사가' 사건을 다루는지로 잰다.

        기존에는 전체 제목을 이어붙여 키워드 '종류'를 셌기 때문에, 무관한 기사가
        섞이기만 해도 점수가 올랐고 대부분의 스캔에서 4~7점이 나왔다.
        """
        score = 0.0
        details = {"factors": []}

        if not news:
            return 0, details

        # 실제 시장을 움직인 헤드라인이 이 목록을 비껴가는 경우가 많아 보강했다.
        # (예: "Bill Ackman Takes Another Swing At NFLX" — 기존 목록에 하나도 안 걸림)
        high_impact = [
            "earnings", "revenue", "guidance", "fda", "acquisition",
            "merger", "layoff", "recall", "investigation", "lawsuit",
            "bankruptcy", "downgrade", "upgrade", "halted", "subpoena",
            "stake", "buyback", "settlement", "probe", "tariff", "ban",
            "beats", "misses", "acquires", "activist", "sues",
        ]
        medium_impact = [
            "analyst", "price target", "rating", "estimate",
            "forecast", "outlook", "contract", "partnership",
        ]

        high_articles = 0
        med_articles = 0
        filings = 0

        for n in news:
            title = (n.get("title") or n.get("headline") or "").lower()
            if not title:
                continue
            if n.get("source_type") == "filing":
                filings += 1
                continue
            if any(k in title for k in high_impact):
                high_articles += 1
            elif any(k in title for k in medium_impact):
                med_articles += 1

        if high_articles >= 4:
            score += 6
            details["factors"].append(f"고영향 기사 {high_articles}건")
        elif high_articles >= 2:
            score += 4
            details["factors"].append(f"고영향 기사 {high_articles}건")
        elif high_articles >= 1:
            score += 2
            details["factors"].append(f"고영향 기사 {high_articles}건")

        if med_articles >= 3:
            score += 1
            details["factors"].append(f"중영향 기사 {med_articles}건")

        # 공시는 추측이 아니라 확정 사실이므로 가중치를 높게 준다
        if filings:
            score += 3
            details["factors"].append(f"SEC 공시 {filings}건")

        return min(10, score), details

    # =========================================================
    # 보조 계산
    # =========================================================
    def _calc_price_boost(self, price_data: Dict) -> Tuple[float, Dict]:
        """
        가격 충격 부스트: 큰 가격 변동 자체가 이상 신호
        전일 대비: ±2% → +1.0, ±5% → +2.0, ±8% → +3.0, ±10%+ → +4.0
        장중 반전: ±3%+ 반전도 동일 기준 적용
        거래량 3x 이상 시 추가 +0.5
        """
        boost = 0.0
        details = {"factors": []}

        if not price_data:
            return 0.0, details

        # 전일 대비 변동률
        change_pct = abs(price_data.get("change_pct", 0))

        # 장중 반전폭 (고점→하락 or 저점→반등)
        reversal = abs(price_data.get("intraday_reversal", 0))

        # 더 큰 쪽을 사용 (전일 대비 vs 장중 반전)
        effective_move = max(change_pct, reversal)
        move_label = ""

        if reversal > change_pct and reversal >= 3:
            raw_rev = price_data.get("intraday_reversal", 0)
            if raw_rev < 0:
                move_label = f"장중 고점 대비 {raw_rev:+.1f}% 급락"
            else:
                move_label = f"장중 저점 대비 {raw_rev:+.1f}% 반등"
        else:
            move_label = f"가격 변동 {price_data.get('change_pct', 0):+.1f}%"

        if effective_move >= 10:
            boost += 4.0
            details["factors"].append(f"{move_label} → +4.0")
        elif effective_move >= 8:
            boost += 3.0
            details["factors"].append(f"{move_label} → +3.0")
        elif effective_move >= 5:
            boost += 2.0
            details["factors"].append(f"{move_label} → +2.0")
        elif effective_move >= 2:
            boost += 1.0
            details["factors"].append(f"{move_label} → +1.0")

        # 거래량 급증
        vol_ratio = price_data.get("volume_ratio", 1.0)
        if vol_ratio >= 3:
            boost += 0.5
            details["factors"].append(f"거래량 {vol_ratio:.1f}x 평균 → +0.5")

        return min(4.5, boost), details

    def _calc_noise_penalty(self, att_score: float, fact_score: float) -> float:
        """일상 노이즈 보정"""
        if att_score <= 2 and fact_score <= 2:
            return 0.5
        return 0.0


class FlashReasonEngine:
    """이벤트 분류 + 이유 후보 추출"""

    def __init__(self, ticker: str):
        self.ticker = ticker

    def analyze(self, news: List, price_data: Dict = None) -> Dict:
        candidates = self._extract_candidates(news)
        classification = self._classify_event(candidates, price_data)

        return {
            "ticker": self.ticker,
            "reason_candidates": candidates,
            "classification": classification,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _extract_candidates(self, news: List) -> List[Dict]:
        """뉴스에서 이유 후보 추출"""
        candidates = []
        seen = set()

        for n in news[:15]:
            title = n.get("title", n.get("headline", ""))
            if not title or title in seen:
                continue
            seen.add(title)

            candidates.append({
                "title": title,
                "source": n.get("source", ""),
                "source_url": n.get("url", n.get("source_url", "")),
                "summary": n.get("summary", "")[:200],
                "relevance": 0.5,
            })

        return candidates[:10]

    def _classify_event(
        self, candidates: List[Dict], price_data: Dict = None
    ) -> Dict:
        """N/F/C 분류 — 가격 방향 반영 + beat-but-guide-down 패턴"""
        if not candidates:
            return {"type": "Noise", "confidence": 0.5, "reasoning": "데이터 부족"}

        all_text = " ".join(c["title"].lower() for c in candidates)

        catalyst_kw = [
            "beat", "exceed", "surge", "soar", "upgrade", "raise",
            "approve", "partnership", "deal", "contract", "bullish",
            "record", "breakthrough",
        ]
        fracture_kw = [
            "miss", "decline", "cut", "downgrade", "warning",
            "recall", "lawsuit", "investigation", "weak", "below",
            "layoff", "restructur",
        ]
        guidance_down_kw = [
            "guidance below", "cut guidance", "weak guidance",
            "lower guidance", "disappointing guidance", "outlook below",
            "guides below", "guided below", "lowered outlook",
        ]

        c_hits = sum(1 for k in catalyst_kw if k in all_text)
        f_hits = sum(1 for k in fracture_kw if k in all_text)

        # Beat-but-guide-down 패턴 감지
        has_beat = "beat" in all_text or "exceed" in all_text
        has_guide_down = any(k in all_text for k in guidance_down_kw)

        # 가격 방향 반영
        price_direction = 0  # -1: 하락, 0: 중립, 1: 상승
        if price_data:
            pct = price_data.get("change_pct", 0)
            rev = price_data.get("intraday_reversal", 0)
            effective = pct if abs(pct) > abs(rev) else rev

            if effective >= 2:
                price_direction = 1
            elif effective <= -2:
                price_direction = -1

        # 분류 로직
        cls_type = "Noise"
        confidence = 0.5
        reasoning = ""

        # Beat-but-guide-down: 실적 beat + 주가 하락 = Fracture
        if has_beat and (has_guide_down or price_direction == -1):
            cls_type = "Fracture"
            confidence = 0.9
            reasoning = "실적 Beat에도 가이던스 하향/주가 하락 → Fracture"
        elif c_hits > f_hits and c_hits >= 2:
            cls_type = "Catalyst"
            confidence = min(0.5 + c_hits * 0.1, 0.9)
            reasoning = f"호재 키워드 {c_hits}개 우세"
            # 주가 하락이면 신뢰도 하향
            if price_direction == -1:
                confidence = max(confidence - 0.2, 0.4)
                reasoning += " (주가 역행 → 신뢰도 하향)"
        elif f_hits > c_hits and f_hits >= 2:
            cls_type = "Fracture"
            confidence = min(0.5 + f_hits * 0.1, 0.9)
            reasoning = f"악재 키워드 {f_hits}개 우세"
            if price_direction == 1:
                confidence = max(confidence - 0.2, 0.4)
                reasoning += " (주가 역행 → 신뢰도 하향)"
        else:
            # 키워드 불명확할 때 가격 방향으로 판단
            if price_direction == 1 and abs(price_data.get("change_pct", 0) if price_data else 0) >= 3:
                cls_type = "Catalyst"
                confidence = 0.6
                reasoning = "키워드 불명확, 주가 상승으로 호재 판단"
            elif price_direction == -1 and abs(price_data.get("change_pct", 0) if price_data else 0) >= 3:
                cls_type = "Fracture"
                confidence = 0.6
                reasoning = "키워드 불명확, 주가 하락으로 악재 판단"
            else:
                reasoning = f"호재 {c_hits}개 vs 악재 {f_hits}개 (불명확)"

        return {
            "type": cls_type,
            "confidence": confidence,
            "reasoning": reasoning,
        }
