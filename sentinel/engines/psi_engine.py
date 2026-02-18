"""
Stock Sentinel — Pre-signal Index Engine
3요소 점수 계산 → 종합 PSI 산출 → 등급 판정
"""
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import (
    SCORE_WEIGHTS, CONFLUENCE_BONUS, NOISE_PENALTY_MAX,
    PSI_LEVELS, TRIGGER_PSI_THRESHOLD,
    OPTIONS_SCORING, ATTENTION_SCORING, FACT_SCORING,
    BREAKING_KEYWORDS, POSITIVE_KEYWORDS, NEGATIVE_KEYWORDS,
    WATCHMAP,
)
from storage.database import (
    save_psi_score, get_recent_news, get_recent_social,
    get_latest_psi, get_psi_history,
)


class PreSignalEngine:
    """Pre-signal Index 계산 엔진"""
    
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.watch = WATCHMAP.get(ticker)
        self.details = {}  # 점수 산출 상세 근거
    
    def calculate(self, 
                  options_data: Dict = None,
                  social_data: Dict = None,
                  news_data: List[Dict] = None,
                  price_data: Dict = None) -> Dict:
        """
        전체 Pre-signal Index 계산
        
        Returns:
            {
                "ticker": str,
                "options_score": float,
                "attention_score": float,
                "fact_score": float,
                "confluence_bonus": float,
                "noise_penalty": float,
                "psi_total": float,
                "level": str,
                "details": dict,
            }
        """
        # 1. 각 요소 점수 계산
        opt_score, opt_details = self._calc_options_score(options_data or {})
        att_score, att_details = self._calc_attention_score(social_data or {}, news_data or [])
        fact_score, fact_details = self._calc_fact_score(news_data or [])
        
        # 1b. 가격 충격 보너스 (급등/급락 시 PSI 직접 부스트)
        price_boost, price_boost_details = self._calc_price_boost(price_data or {})
        
        # 2. Confluence 보너스 (2개 이상 요소가 동시에 높을 때)
        high_count = sum(1 for s in [opt_score, att_score, fact_score] if s >= 5)
        confluence = CONFLUENCE_BONUS if high_count >= 2 else 0
        
        # 3. Noise 패널티 (평시 노이즈 수준 보정)
        noise = self._calc_noise_penalty(att_score, fact_score)
        
        # 4. 종합 점수 (가격 충격은 직접 가산)
        psi = (
            SCORE_WEIGHTS["options"] * opt_score +
            SCORE_WEIGHTS["attention"] * att_score +
            SCORE_WEIGHTS["fact"] * fact_score +
            confluence + price_boost - noise
        )
        psi = max(0, min(10, round(psi, 1)))
        
        # 5. 등급 판정
        level = self._get_level(psi)
        
        # 6. 상세 근거
        self.details = {
            "options": opt_details,
            "attention": att_details,
            "fact": fact_details,
            "price_boost": price_boost_details,
            "confluence": {"bonus": confluence, "high_count": high_count},
            "noise": {"penalty": noise},
            "formula": (
                f"{SCORE_WEIGHTS['options']}×{opt_score} + "
                f"{SCORE_WEIGHTS['attention']}×{att_score} + "
                f"{SCORE_WEIGHTS['fact']}×{fact_score} + "
                f"price_boost:{price_boost} + "
                f"confluence:{confluence} - noise:{noise} = {psi}"
            ),
        }
        
        result = {
            "ticker": self.ticker,
            "timestamp": datetime.utcnow().isoformat(),
            "options_score": opt_score,
            "attention_score": att_score,
            "fact_score": fact_score,
            "confluence_bonus": confluence,
            "noise_penalty": noise,
            "psi_total": psi,
            "level": level,
            "details": self.details,
        }
        
        # DB 저장
        save_psi_score(
            ticker=self.ticker,
            timestamp=result["timestamp"],
            options_score=opt_score,
            attention_score=att_score,
            fact_score=fact_score,
            confluence_bonus=confluence,
            noise_penalty=noise,
            psi_total=psi,
            level=level,
            details=self.details,
        )
        
        return result
    
    # =========================================================
    # 1. Options Anomaly Score (0~10)
    # =========================================================
    def _calc_options_score(self, data: Dict) -> Tuple[float, Dict]:
        """옵션 이상 점수 계산"""
        score = 0
        details = {"factors": [], "raw": data}
        
        if not data:
            return 0, {"factors": ["옵션 데이터 없음"], "raw": {}}
        
        # OTM 거래량 급증
        otm_ratio = data.get("otm_call_volume_ratio", 0)
        if otm_ratio >= 5:
            score += OPTIONS_SCORING["otm_volume_5x"]
            details["factors"].append(f"OTM 콜 거래량 {otm_ratio:.1f}배 → +{OPTIONS_SCORING['otm_volume_5x']}")
        elif otm_ratio >= 3:
            score += OPTIONS_SCORING["otm_volume_3x"]
            details["factors"].append(f"OTM 콜 거래량 {otm_ratio:.1f}배 → +{OPTIONS_SCORING['otm_volume_3x']}")
        
        # 단기만기 집중
        short_pct = data.get("short_expiry_pct", 0)
        if short_pct >= 0.6:
            score += OPTIONS_SCORING["short_expiry_60pct"]
            details["factors"].append(f"단기만기 비중 {short_pct:.0%} → +{OPTIONS_SCORING['short_expiry_60pct']}")
        
        # OI 급변
        oi_change = data.get("oi_change_pct", 0)
        if abs(oi_change) >= 50:
            score += OPTIONS_SCORING["oi_change_50pct"]
            details["factors"].append(f"OI 변화 {oi_change:+.0f}% → +{OPTIONS_SCORING['oi_change_50pct']}")
        
        # IV Skew
        iv_skew_sigma = data.get("iv_skew_sigma", 0)
        if abs(iv_skew_sigma) >= 2:
            score += OPTIONS_SCORING["iv_skew_2sigma"]
            details["factors"].append(f"IV Skew {iv_skew_sigma:.1f}σ → +{OPTIONS_SCORING['iv_skew_2sigma']}")
        
        # 대량 거래
        large_trades = data.get("large_trade_count", 0)
        if large_trades > 0:
            score += OPTIONS_SCORING["large_trade_100k"]
            details["factors"].append(f"대량거래 {large_trades}건 → +{OPTIONS_SCORING['large_trade_100k']}")
        
        # Put/Call 비율 이상
        pc_ratio = data.get("pc_ratio", 1.0)
        if pc_ratio < 0.5 or pc_ratio > 2.0:
            score += 1
            details["factors"].append(f"P/C 비율 이상: {pc_ratio:.2f} → +1")
        
        score = min(10, score)
        return score, details
    
    # =========================================================
    # 2. Attention Acceleration Score (0~10)
    # =========================================================
    def _calc_attention_score(self, social_data: Dict, news_data: List[Dict]) -> Tuple[float, Dict]:
        """관심도 가속도 점수 계산"""
        score = 0
        details = {"factors": [], "raw_social": social_data}
        
        # 소셜 언급 가속도
        current_mentions = social_data.get("current_mentions", 0)
        previous_mentions = social_data.get("previous_mentions", 0)
        
        if previous_mentions > 0 and current_mentions > 0:
            accel = ((current_mentions - previous_mentions) / previous_mentions) * 100
            if accel >= 300:
                score += ATTENTION_SCORING["mention_accel_300pct"]
                details["factors"].append(f"언급 가속도 {accel:.0f}% → +{ATTENTION_SCORING['mention_accel_300pct']}")
            elif accel >= 100:
                score += ATTENTION_SCORING["mention_accel_100pct"]
                details["factors"].append(f"언급 가속도 {accel:.0f}% → +{ATTENTION_SCORING['mention_accel_100pct']}")
        
        # 현장성 키워드 감지
        breaking_found = False
        for article in news_data:
            text = (article.get('title', '') + ' ' + article.get('summary', '')).lower()
            if any(kw.lower() in text for kw in BREAKING_KEYWORDS):
                breaking_found = True
                break
        
        if breaking_found or social_data.get("breaking_keyword_found", False):
            score += ATTENTION_SCORING["breaking_keywords"]
            details["factors"].append(f"현장성 키워드 감지 → +{ATTENTION_SCORING['breaking_keywords']}")
        
        # Google Trends 스파이크
        trends_ratio = social_data.get("google_trends_ratio", 0)
        if trends_ratio >= 2:
            score += ATTENTION_SCORING["google_trends_2x"]
            details["factors"].append(f"Google Trends {trends_ratio:.1f}배 → +{ATTENTION_SCORING['google_trends_2x']}")
        
        # 다중 플랫폼 동시 급증
        platforms_active = social_data.get("platforms_active", [])
        if len(platforms_active) >= 2:
            score += ATTENTION_SCORING["multi_platform"]
            details["factors"].append(f"다중 플랫폼 동시: {', '.join(platforms_active)} → +{ATTENTION_SCORING['multi_platform']}")
        
        # 뉴스 볼륨 자체도 가속도 반영
        if len(news_data) >= 10:
            score += 1
            details["factors"].append(f"뉴스 볼륨 {len(news_data)}건 → +1")
        
        score = min(10, score)
        return score, details
    
    # =========================================================
    # 3. Disclosure/Fact Score (0~10)
    # =========================================================
    def _calc_fact_score(self, news_data: List[Dict]) -> Tuple[float, Dict]:
        """공시/팩트 점수 계산"""
        score = 0
        details = {"factors": [], "filings": [], "news_count": len(news_data)}
        
        has_8k = False
        has_other_filing = False
        has_regulatory = False
        has_earnings = False
        sources_count = set()
        
        for article in news_data:
            source_type = article.get('source_type', '')
            source = article.get('source', '')
            title = article.get('title', '').lower()
            
            sources_count.add(source)
            
            # SEC Filing 감지
            if source_type == 'filing' or 'sec' in source.lower():
                if '8-k' in title or '8k' in title:
                    has_8k = True
                    details["filings"].append(article.get('title', ''))
                else:
                    has_other_filing = True
            
            # 규제기관 발표
            regulatory_terms = ['bis', 'fda', 'ftc', 'doj', 'sec ', 'settlement',
                              'export control', 'entity list', 'approved', 'cleared']
            if any(term in title for term in regulatory_terms):
                has_regulatory = True
            
            # 실적 관련
            earnings_terms = ['earnings', 'eps', 'revenue', 'guidance', 'quarter',
                            'fiscal', 'q1', 'q2', 'q3', 'q4', 'beat', 'miss']
            if any(term in title for term in earnings_terms):
                has_earnings = True
        
        # 점수 부여
        if has_8k:
            score += FACT_SCORING["sec_8k"]
            details["factors"].append(f"SEC 8-K Filing 감지 → +{FACT_SCORING['sec_8k']}")
        elif has_other_filing:
            score += FACT_SCORING["sec_other"]
            details["factors"].append(f"SEC Filing 감지 → +{FACT_SCORING['sec_other']}")
        
        if has_regulatory:
            score += FACT_SCORING["regulatory"]
            details["factors"].append(f"규제기관 발표 감지 → +{FACT_SCORING['regulatory']}")
        
        if has_earnings:
            score += FACT_SCORING["earnings_window"]
            details["factors"].append(f"실적 관련 뉴스 감지 → +{FACT_SCORING['earnings_window']}")
        
        # 다중 출처 확인
        if len(sources_count) >= 3:
            score += FACT_SCORING["multi_source"]
            details["factors"].append(f"다중 출처 {len(sources_count)}개 확인 → +{FACT_SCORING['multi_source']}")
        
        score = min(10, score)
        return score, details
    
    # =========================================================
    # 보조 계산
    # =========================================================
    def _calc_price_boost(self, price_data: Dict) -> Tuple[float, Dict]:
        """
        가격 충격 부스트: 큰 가격 변동 자체가 이상 신호
        ±2% → +1.0, ±5% → +2.0, ±8% → +3.0, ±10%+ → +4.0
        거래량 3x 이상 시 추가 +0.5
        """
        boost = 0.0
        details = {"factors": []}
        
        if not price_data:
            return 0.0, details
        
        # 가격 변동률
        change_pct = abs(price_data.get("change_pct", 0))
        if change_pct >= 10:
            boost += 4.0
            details["factors"].append(f"가격 변동 {price_data.get('change_pct', 0):+.1f}% → +4.0")
        elif change_pct >= 8:
            boost += 3.0
            details["factors"].append(f"가격 변동 {price_data.get('change_pct', 0):+.1f}% → +3.0")
        elif change_pct >= 5:
            boost += 2.0
            details["factors"].append(f"가격 변동 {price_data.get('change_pct', 0):+.1f}% → +2.0")
        elif change_pct >= 2:
            boost += 1.0
            details["factors"].append(f"가격 변동 {price_data.get('change_pct', 0):+.1f}% → +1.0")
        
        # 거래량 급증
        vol_ratio = price_data.get("volume_ratio", 1.0)
        if vol_ratio >= 3:
            boost += 0.5
            details["factors"].append(f"거래량 {vol_ratio:.1f}x 평균 → +0.5")
        
        return min(4.5, boost), details
    
    def _calc_noise_penalty(self, attention_score: float, fact_score: float) -> float:
        """Noise 패널티: 관심도만 높고 팩트가 없으면 차감"""
        if attention_score >= 5 and fact_score <= 2:
            return min(NOISE_PENALTY_MAX, (attention_score - fact_score) * 0.3)
        return 0
    
    def _get_level(self, psi: float) -> str:
        """PSI 등급 판정"""
        for level, (low, high) in PSI_LEVELS.items():
            if low <= psi < high:
                return level
        return "critical" if psi >= 7 else "normal"


# ============================================================
# Flash Reason Engine (간소화 버전)
# ============================================================

class FlashReasonEngine:
    """60초 원인 규명 엔진"""
    
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.watch = WATCHMAP.get(ticker)
    
    def analyze(self, news_data: List[Dict], price_data: Dict = None,
                options_data: Dict = None) -> Dict:
        """
        원인 후보 Top-3 생성 + Noise/Fracture/Catalyst 분류
        """
        # 1. 뉴스를 시간순 정렬 + 관련도 스코어링
        scored_news = self._score_and_rank_news(news_data)
        
        # 2. Top-3 후보 추출
        top3 = scored_news[:3]
        
        reason_candidates = []
        for i, item in enumerate(top3):
            reason_candidates.append({
                "rank": i + 1,
                "title": item["title"],
                "summary": item.get("summary", "")[:200],
                "source_url": item.get("url", ""),
                "source": item.get("source", ""),
                "source_type": item.get("source_type", "news"),
                "confidence": item.get("relevance_score", 0.5),
                "event_type": self._classify_event_type(item),
                "sentiment": item.get("sentiment", "neutral"),
                "timestamp": item.get("timestamp", ""),
            })
        
        # 3. Noise / Fracture / Catalyst 분류
        classification = self._classify_event(reason_candidates, news_data, price_data)
        
        # 4. 플레이북 결정
        playbook = self._get_playbook(classification)
        
        return {
            "ticker": self.ticker,
            "timestamp": datetime.utcnow().isoformat(),
            "reason_candidates": reason_candidates,
            "classification": classification,
            "playbook": playbook,
        }
    
    def _score_and_rank_news(self, news_data: List[Dict]) -> List[Dict]:
        """뉴스 관련도 스코어링 + 랭킹"""
        for article in news_data:
            score = 0
            title = article.get('title', '').lower()
            
            # 키워드 매칭 점수
            matched = article.get('keywords_matched', [])
            score += len(matched) * 0.1
            
            # 소스 타입 가중치
            if article.get('source_type') == 'filing':
                score += 0.3
            elif article.get('source') in ['finnhub', 'sec_edgar']:
                score += 0.2
            
            # 현장성 키워드
            if any(kw.lower() in title for kw in BREAKING_KEYWORDS):
                score += 0.2
            
            # 시간 가중치 (최신일수록 높음)
            try:
                pub_time = datetime.fromisoformat(article.get('timestamp', ''))
                hours_ago = (datetime.utcnow() - pub_time).total_seconds() / 3600
                if hours_ago < 1:
                    score += 0.3
                elif hours_ago < 6:
                    score += 0.2
                elif hours_ago < 24:
                    score += 0.1
            except:
                pass
            
            article['relevance_score'] = min(1.0, round(score, 2))
        
        # 관련도 내림차순 정렬
        return sorted(news_data, key=lambda x: x.get('relevance_score', 0), reverse=True)
    
    def _classify_event_type(self, article: Dict) -> str:
        """사건 유형 분류"""
        title = article.get('title', '').lower()
        
        type_keywords = {
            "earnings": ['earnings', 'eps', 'revenue', 'quarter', 'fiscal', 'guidance'],
            "regulatory": ['bis', 'fda', 'ftc', 'sec', 'settlement', 'export', 'sanction', 'penalty'],
            "supply_chain": ['tsmc', 'samsung', 'foundry', 'fab', 'capex', 'equipment order'],
            "analyst": ['upgrade', 'downgrade', 'target', 'rating', 'overweight', 'analyst'],
            "ma": ['acquisition', 'merger', 'buyout', 'deal', 'partnership'],
            "sector": ['semiconductor', 'chip', 'sector', 'etf', 'industry'],
            "macro": ['fed', 'fomc', 'inflation', 'tariff', 'trade war'],
        }
        
        for event_type, keywords in type_keywords.items():
            if any(kw in title for kw in keywords):
                return event_type
        
        return "other"
    
    def _classify_event(self, candidates: List[Dict], all_news: List[Dict],
                        price_data: Dict = None) -> Dict:
        """Noise / Fracture / Catalyst 판정 — 가격 방향 + 패턴 인식"""
        if not candidates:
            return {"type": "Unknown", "confidence": 0, "reasoning": "데이터 부족"}
        
        # 팩트 근거 강도 확인
        fact_sources = sum(1 for c in candidates 
                         if c.get('source_type') in ['filing', 'regulatory'])
        
        # 센티멘트 방향
        sentiments = [c.get('sentiment', 'neutral') for c in candidates]
        positive_count = sentiments.count('positive')
        negative_count = sentiments.count('negative')
        
        # 키워드 체크
        negative_found = False
        positive_found = False
        all_text = ""
        for c in candidates:
            text = (c.get('title', '') + ' ' + c.get('summary', '')).lower()
            all_text += text + " "
            if any(kw.lower() in text for kw in NEGATIVE_KEYWORDS):
                negative_found = True
            if any(kw.lower() in text for kw in POSITIVE_KEYWORDS):
                positive_found = True
        
        # ── 가격 방향 신호 ──
        price_direction = 0  # -1=하락, 0=중립, 1=상승
        price_change = 0
        if price_data:
            price_change = price_data.get("change_pct", 0)
            if price_change <= -2:
                price_direction = -1
            elif price_change >= 2:
                price_direction = 1
        
        # ── 패턴 인식: Beat but Guide Down ──
        beat_guide_down = False
        guide_down_terms = ['guidance below', 'guide down', 'lowered guidance',
                           'cut guidance', 'reduced outlook', 'below expectations',
                           'disappointing guidance', 'weak guidance', 'outlook miss',
                           'declines after', 'falls despite', 'drops despite',
                           'despite beat', 'despite strong']
        beat_terms = ['beat', 'topped', 'exceeded', 'surpassed', 'above estimate']
        
        has_beat = any(t in all_text for t in beat_terms)
        has_guide_down = any(t in all_text for t in guide_down_terms)
        
        # 실적 beat + 하락 = beat but guide down 패턴
        if has_beat and price_direction == -1:
            beat_guide_down = True
        if has_guide_down:
            beat_guide_down = True
        
        # ── 판정 로직 (가격 방향 우선) ──
        
        # 1. Beat but Guide Down → Fracture (실적 좋아도 가이던스가 나쁘면 하락)
        if beat_guide_down:
            return {
                "type": "Fracture",
                "confidence": 0.9,
                "reasoning": "실적 Beat에도 가이던스 하향/주가 하락 → Fracture"
            }
        
        # 2. 강한 하락 + 뉴스 있음 → Fracture
        if price_direction == -1 and (fact_sources >= 1 or len(all_news) >= 3):
            conf = 0.85 if fact_sources >= 1 else 0.7
            return {
                "type": "Fracture",
                "confidence": conf,
                "reasoning": f"주가 {price_change:+.1f}% 하락 + 뉴스 {len(all_news)}건 → Fracture"
            }
        
        # 3. 강한 상승 + 팩트 있음 → Catalyst
        if price_direction == 1 and (fact_sources >= 1 or positive_found):
            conf = 0.85 if fact_sources >= 1 else 0.7
            return {
                "type": "Catalyst",
                "confidence": conf,
                "reasoning": f"주가 {price_change:+.1f}% 상승 + 팩트/긍정 키워드 → Catalyst"
            }
        
        # 4. 팩트 소스 + 부정 키워드 → Fracture
        if fact_sources >= 1 and negative_found and not positive_found:
            return {
                "type": "Fracture",
                "confidence": 0.8,
                "reasoning": f"팩트 소스 {fact_sources}건 + 부정 키워드 → Fracture"
            }
        
        # 5. 팩트 소스 + 긍정 키워드 → Catalyst
        if fact_sources >= 1 and positive_found:
            return {
                "type": "Catalyst",
                "confidence": 0.85,
                "reasoning": f"팩트 소스 {fact_sources}건 + 긍정 키워드 → Catalyst"
            }
        
        # 6. 뉴스 볼륨 + 센티멘트 방향
        if positive_count > negative_count and len(all_news) >= 5:
            return {
                "type": "Catalyst",
                "confidence": 0.7,
                "reasoning": f"긍정 뉴스 {positive_count} > 부정 {negative_count} + 뉴스 볼륨 → Catalyst"
            }
        elif negative_count > positive_count:
            return {
                "type": "Fracture",
                "confidence": 0.65,
                "reasoning": f"부정 뉴스 {negative_count} > 긍정 {positive_count} → Fracture"
            }
        
        return {
            "type": "Noise",
            "confidence": 0.5,
            "reasoning": "팩트 근거 약함 + 방향성 불분명 → Noise"
        }
    
    def _get_playbook(self, classification: Dict) -> Dict:
        """분류에 따른 플레이북"""
        ctype = classification.get("type", "Unknown")
        
        playbooks = {
            "Noise": {
                "id": "PB-NOISE-01",
                "actions": [
                    "체크리스트: 팩트 근거 재확인",
                    "재평가 타이머: 15분 후",
                    "추가 소스 확인 필요",
                ],
                "reevaluation": "15min"
            },
            "Fracture": {
                "id": "PB-FRACTURE-01",
                "actions": [
                    "리스크 상향: 즉시 포지션 재평가",
                    "손절 체크리스트 확인",
                    "관련 종목 영향 확인",
                    "재평가 타이머: 종가 기준",
                ],
                "reevaluation": "close"
            },
            "Catalyst": {
                "id": "PB-CATALYST-01",
                "actions": [
                    "추적 강화: 15분 간격 모니터링",
                    "관련 종목 동향 확인",
                    "재평가 시점: 종가 기준",
                    "서사 전환 여부 추적",
                ],
                "reevaluation": "close"
            },
        }
        
        return playbooks.get(ctype, {
            "id": "PB-UNKNOWN-01",
            "actions": ["수동 확인 필요"],
            "reevaluation": "30min"
        })


# ============================================================
# 테스트
# ============================================================
if __name__ == "__main__":
    # AMAT 실제 데이터로 테스트
    engine = PreSignalEngine("AMAT")
    
    # 시뮬레이션 데이터
    options_data = {
        "otm_call_volume_ratio": 4.2,
        "short_expiry_pct": 0.65,
        "oi_change_pct": 55,
        "iv_skew_sigma": 2.3,
        "large_trade_count": 3,
        "pc_ratio": 0.45,
    }
    
    social_data = {
        "current_mentions": 340,
        "previous_mentions": 100,
        "breaking_keyword_found": True,
        "google_trends_ratio": 2.5,
        "platforms_active": ["reddit", "stocktwits"],
    }
    
    news_data = [
        {"title": "Applied Materials Q1 earnings beat estimates", 
         "source_type": "news", "source": "finnhub", "sentiment": "positive",
         "keywords_matched": ["AMAT", "earnings"], "timestamp": "2026-02-12T21:00:00",
         "url": "https://example.com/1", "summary": "EPS $2.38 vs $2.25 expected"},
        {"title": "[SEC 8-K] Applied Materials Q1 2026 Results",
         "source_type": "filing", "source": "sec_edgar", "sentiment": "neutral",
         "keywords_matched": ["AMAT"], "timestamp": "2026-02-12T21:30:00",
         "url": "https://example.com/2", "summary": ""},
        {"title": "BIS settlement: Applied Materials pays $252M penalty",
         "source_type": "news", "source": "google_news", "sentiment": "negative",
         "keywords_matched": ["AMAT", "BIS", "export control"],
         "timestamp": "2026-02-11T21:00:00", "url": "https://example.com/3",
         "summary": "Settlement resolves export violations"},
        {"title": "Applied Materials guidance above consensus, shares surge",
         "source_type": "news", "source": "finnhub", "sentiment": "positive",
         "keywords_matched": ["AMAT", "guidance"], "timestamp": "2026-02-13T10:00:00",
         "url": "https://example.com/4", "summary": "Q2 guidance $7.65B vs $7.02B expected"},
        {"title": "KeyBanc raises AMAT target to $450, sees 37% upside",
         "source_type": "news", "source": "google_news", "sentiment": "positive",
         "keywords_matched": ["AMAT"], "timestamp": "2026-02-13T12:00:00",
         "url": "https://example.com/5", "summary": ""},
    ]
    
    # PSI 계산
    from storage.database import init_db
    init_db()
    
    result = engine.calculate(
        options_data=options_data,
        social_data=social_data,
        news_data=news_data,
    )
    
    print("\n" + "=" * 60)
    print(f"📡 PRE-SIGNAL INDEX: {result['ticker']}")
    print("=" * 60)
    print(f"  Options Anomaly:     {result['options_score']}/10")
    print(f"  Attention Accel:     {result['attention_score']}/10")
    print(f"  Disclosure/Fact:     {result['fact_score']}/10")
    print(f"  Confluence Bonus:    +{result['confluence_bonus']}")
    print(f"  Noise Penalty:       -{result['noise_penalty']}")
    print(f"  ─────────────────────────")
    print(f"  PSI Total:           {result['psi_total']}/10")
    print(f"  Level:               {result['level'].upper()}")
    
    # Flash Reason
    flash = FlashReasonEngine("AMAT")
    reason_result = flash.analyze(news_data)
    
    print(f"\n🔍 FLASH REASON:")
    print(f"  Classification: {reason_result['classification']['type']}")
    print(f"  Confidence: {reason_result['classification']['confidence']:.0%}")
    print(f"  Playbook: {reason_result['playbook']['id']}")
    print(f"\n  Top-3 원인 후보:")
    for c in reason_result['reason_candidates']:
        print(f"    #{c['rank']} [{c['event_type']}] {c['title'][:60]}")
        print(f"       신뢰도: {c['confidence']:.0%} | {c['sentiment']}")
