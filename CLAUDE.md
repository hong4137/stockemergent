# Stock Sentinel — 프로젝트 맥락

워치리스트 종목의 이상 징후를 감지해 원인을 AI로 분석하고 Telegram으로 한국어 알림을 보낸다.
서버 없이 Cloudflare Worker(스케줄러) + GitHub Actions(스캔)로 돌아간다.

**이 파일이 유일한 최신 문서다.** 과거 핸드오프 문서나 대화 요약본은 대부분 낡았으니 코드를 근거로 삼을 것.

## 실행 구조

```
scheduler/worker.js  (Cloudflare Worker, Durable Object 알람으로 15분마다 깨어남)
  └─ 시장 시간이면 GitHub workflow_dispatch 호출
       정규장 15분 · 프리 08:00~/애프터 ~18:00 30분 · 주말·NYSE 휴장일 제외 (평일 33회)
GitHub Actions cron (백업: 정규장 시간대 15분, 8/23/38/53분)

sentinel-scan.yml → cd sentinel && python run_scan.py
  1. collectors/market_context   S&P·나스닥100·섹터 ETF·동종업체 등락 (yfinance 일괄 1회)
  2. 종목별 병렬 수집 (ThreadPool)
       collectors/price_collector  세션·σ·거래량 페이스·장중반전·시간외 가격
       collectors/news_collector   Google News + Finnhub + SEC(data.sec.gov)
                                   → 중복제거 → 관련성 필터 → 잡음 태깅 → 관련도+최신성 정렬
  3. 종목별 순차 처리
       engines/psi_engine          PSI 0~10 + FlashReason 원인 후보
       storage/database.save_scan  스캔 이력 (뉴스 기준선)
       price_collector.check_price_trigger   세션·σ 기준 트리거
       alerts/alert_system         발송 판정 → AI 요약 → Telegram → DB 저장
  → sentinel/storage/sentinel.db 를 봇이 자동 커밋
```

## 반드시 알아야 할 것

### DB가 상태 저장소다
`sentinel/storage/sentinel.db`는 git에 커밋되며, **알림 재발송 판정의 유일한 근거**다.
- `init_db()`는 절대 `DROP TABLE` 하지 말 것. 컬럼 추가는 `ALTER TABLE`로만 한다
  (스키마 변경 시 `database.py`의 `ALERTS_COLUMNS` 리스트에 추가하면 자동 반영).
- `scan_log`는 30일치만 보관한다. 매 스캔 커밋되므로 안 지우면 레포가 부푼다.
- 워크플로의 `concurrency`가 스캔을 한 번에 하나씩만 돌린다. 이걸 빼면 두 스캔이 동시에
  DB를 커밋하다 한쪽 push가 거부돼 기록(재발송 판정 근거)이 유실된다.

### 세션 인식 — 가장 많이 사고 난 곳
yfinance 일봉의 마지막 줄은 **정규장 기준**이라 장 마감 후·다음 날 새벽·주말·휴장일에도
직전 세션의 변동률을 그대로 돌려준다. 이걸 '지금 움직임'으로 읽으면 같은 급등을 계속 다시 알린다
(실제 사고: PANW 9/14 +13.1%를 그날 저녁 2번, 다음 날 새벽 1번 재알림).
- `price_collector`가 `session`(regular/pre/post/closed)과 `stale`(마지막 일봉이 오늘 것이 아님)을 준다.
- 정규장인데 `stale`이면 휴장일 또는 장 시작 직후 데이터 지연 → 알리지 않는다.
- 시간외(pre/post)는 정규장 변동률이 아니라 **`ext_change_pct`(종가 이후 1분봉 기준)**가 10% 이상일 때만.
- 장외(야간·주말)는 전면 차단.

### 트리거는 종목 변동성(σ) 기준이다
고정 ±3%는 하루 변동이 큰 NET에겐 일상, AMZN에겐 이례적이었다(7주간 NET 64건 vs AMZN 3건,
3개월 백테스트에서 MU·NET은 63거래일 중 41일 트리거). 기준(`price_collector` 상단 상수):
- 가격: |변동| ≥ 2σ 이면서 ≥ 2%, 또는 ≥ 8% 무조건 (σ = 직전 20세션 일간 수익률 표준편차)
- 장중 반전: ≥ 3%p 이면서 평소 하루 변동폭(ATR) 이상
- 거래량: 시간대 보정 페이스 3배 + 1σ 이상 움직임
- 트리거 판정은 `check_price_trigger` 한 곳에서만 한다. run_scan에서 따로 판정하지 말 것
  (예전에 run_scan이 '반전 3%'만 보고 바로 보내서 반전 알림이 쏟아졌다).

### 같은 날 재알림은 '새로운 움직임'이 있을 때만
`should_send_alert` — 시간만 지났다고 같은 이야기를 반복하지 않는다.
- 오늘(ET) 첫 알림 → 발송
- 이후: σ 단계(2/3/4.5/6배) 상승, 또는 직전 알림 대비 추가 변동 ≥ max(2%p, 1σ)
- `alerts.alert_move`에 '알림을 정당화한 움직임'(반전 알림이면 반전폭)을 저장한다.
  change_pct만 쓰면 반전 알림 뒤 같은 반전을 매번 '단계 상승'으로 오인한다.

### 뉴스 분석 정확도
- **시장 맥락**: 프롬프트에 S&P·섹터 ETF·동종업체 등락과 '섹터 대비 초과 변동'을 준다.
  없을 때 AI는 원인을 못 찾으면 "섹터 동반 하락"을 지어냈다(섹터/매크로 설명 58건 중 38%가 데이터와 불일치).
  AI가 그래도 섹터 탓을 하는데 데이터상 개별 요인이면 `apply_safety_nets`가 event_type을 other로 고친다.
- **기사 나이**: 각 기사에 "3h ago"를 붙이고 관련도+최신성으로 정렬한다(`_rank`).
- **잡음 기사**(`collectors/noise_filter.py`): 원인 없이 등락만 쓴 기사(recap), MarketBeat류
  13F 보고서(holdings)는 분석 입력에서 뺀다. 언론 관심도 집계에는 남긴다.
  패턴 수정 시 `python collectors/noise_filter.py`로 테스트(진짜 뉴스가 걸리면 안 된다).
- 섹터 ETF는 `watchlist.json`의 `sector_etf`로 지정한다. 없으면 sector 문자열로 추정
  (`market_context.sector_etf_for`). AMZN은 XLY 비중이 커서 자기 자신이 섹터를 끌고 다니므로 QQQ와 비교한다.

### AI 요약 실패는 조용하다
`ai_summarizer`는 실패 시 예외를 던지지 않고 규칙 기반 폴백으로 넘어간다.
- 폴백이 쓰이면 **알림 본문에 `⚠️ AI 요약 실패`가 찍힌다.** 이 표시를 없애지 말 것.
- `alerts.ai_generated` 컬럼으로 사후 집계도 가능하다.

### 모델
`gpt-5.6-luna` ($0.20/$1.20 per 1M). 워크플로의 `OPENAI_MODEL` 환경변수만 바꾸면 롤백된다.
- GPT-5 계열은 `temperature`를 받지 않고 `max_tokens` 대신 `max_completion_tokens`를 쓴다.
- `reasoning_effort`를 명시하지 않으면 추론 토큰이 출력 요금으로 과금된다 → `none` 고정.
- 응답은 `response_format: json_schema` (strict). 파라미터 거부(400 + `error.param`) 시 자동 재시도.
- 프롬프트는 `build_prompt()`로 분리돼 있어 API 호출 없이 확인할 수 있다.

### 발송 판정이 AI 호출보다 먼저다
`send_alert()`는 `should_send_alert()`를 통과한 뒤에만 OpenAI를 부른다.

### 스케줄러 (scheduler/)
GitHub의 schedule은 보장되지 않아 실측 평일 정규장 스캔이 하루 2~3회뿐이었다.
- Cloudflare 계정의 무료 크론 트리거(5개)가 다른 프로젝트로 차 있어 **Durable Object 알람**을 쓴다.
  알람이 울리면 다음 15분 정각 알람을 스스로 예약한다.
- `GET https://stock-sentinel-scheduler.hong4137.workers.dev/` 는 알람을 **무장만** 한다(스캔 실행 안 함).
  스캔 워크플로가 매번 호출하므로 체인이 끊겨도 다음 백업 스캔 때 복구된다.
  응답에 `token: MISSING` 이 보이면 GitHub 토큰 비밀값이 없는 것.
- 배포: `cd scheduler && npx wrangler deploy` (계정 ID는 `CLOUDFLARE_ACCOUNT_ID`)
- 비밀값: `npx wrangler secret put GITHUB_TOKEN` — fine-grained, 이 레포만, Actions: Read and write.
- NYSE 휴장일 목록은 worker.js에 2027년까지 있다. **2028년 전에 추가할 것.**
- 비용: 잡 1회 약 30~40초(1분 과금) × 평일 33회 ≈ 월 700분 (private 레포 무료 2,000분).
  `timeout-minutes: 8`이 없으면 yfinance가 멈출 때 한 번에 360분이 사라진다.

## 알려진 제약

- **Options 점수는 항상 0.** 무료 옵션 데이터 소스가 없어 미연동(가중치는 재정규화돼 있음).
- **뉴스 기준선은 20샘플 이상 쌓여야 동작.** 그 전엔 절대 건수 폴백.
- **Google News는 실제 기사 URL을 주지 않는다**(2024년 이후). 리다이렉터 링크도 클릭하면 열린다.
  언론사 직링크는 SEC 공시에서만 나온다.
- **커뮤니티 소스 미연동** (Reddit, StockTwits 등).
- **`save_news()`는 정의만 있고 호출되지 않는다.** `news` 테이블의 297행은 구버전 잔재다.
- 조기 폐장일(추수감사절 다음날 등) 오후는 정규장으로 취급된다(재알림 규칙이 반복은 막는다).

## 작업 시 주의

- 워크플로는 `cd sentinel && python run_scan.py`로 실행한다. import는 `sentinel/` 기준 상대 경로다.
- Telegram은 Markdown v1(`*bold*`)이다. 동적 텍스트는 `sanitize_title()`을 거칠 것.
- `watchlist.json`은 루트에 있고 웹 UI(`index.html`)가 GitHub API로 직접 수정한다.
  UI는 base64를 **반드시 UTF-8로 디코딩**해야 한다(`b64utf8()`).
  UI는 항목을 제자리에서 수정하므로 `sector_etf` 같은 추가 필드는 보존된다.
- `related`에는 미국 티커만 넣을 것(MTK, SAMSUNG 같은 건 시세 조회가 실패한다 — 대문자 1~5자만 쓰인다).
- 표시명이 한글인 종목(예: PANW)은 `keywords`에 영문 명칭을 넣어야 영문 기사와 매칭된다.
- 짧은 티커(NET, MU)는 단어경계 + 대소문자 구분으로 매칭한다.
- **셸(sed/heredoc)로 정규식을 고치지 말 것.** `\b`가 백스페이스 문자로 바뀌어 조용히 매칭이 깨진 적이 있다.

## GitHub Secrets

`OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `FINNHUB_API_KEY`.
(Cloudflare 워커 쪽 비밀값 `GITHUB_TOKEN`은 GitHub Secrets가 아니라 wrangler로 넣는다.)

## 점검 쿼리

```sql
-- AI 폴백 비율 (높으면 모델/파라미터 문제)
SELECT model, ai_generated, COUNT(*) FROM alerts
WHERE timestamp >= date('now','-7 day') GROUP BY 1,2;

-- 하루 스캔 횟수 (평일 30회 이상이 정상. 한 자릿수면 스케줄러가 멈춘 것)
SELECT substr(timestamp,1,10) d, COUNT(*) FROM scan_log WHERE ticker='MU' GROUP BY d ORDER BY d DESC LIMIT 7;

-- 저변동 알림 비율
SELECT 100.0 * SUM(ABS(change_pct) < 2) / COUNT(*) FROM alerts WHERE timestamp >= date('now','-7 day');

-- 섹터 설명이 데이터와 맞았나 (market_context 저장분)
SELECT ticker, change_pct, event_type, json_extract(market_context,'$.sector') sector, headline
FROM alerts WHERE event_type IN ('sector_rotation','macro') ORDER BY timestamp DESC LIMIT 20;

-- 재알림 빈도 (종목·일자별 2건 이상)
SELECT ticker, substr(timestamp,1,10) d, COUNT(*) FROM alerts GROUP BY 1,2 HAVING COUNT(*) >= 2 ORDER BY d DESC;
```
