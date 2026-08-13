# Stock Sentinel — 프로젝트 맥락

워치리스트 종목의 이상 징후를 감지해 원인을 AI로 분석하고 Telegram으로 한국어 알림을 보낸다.
GitHub Actions cron으로만 돌아가는 서버리스 구조다.

**이 파일이 유일한 최신 문서다.** 과거 핸드오프 문서나 대화 요약본은 대부분 낡았으니 코드를 근거로 삼을 것.

## 실행 구조

```
GitHub Actions cron (15분 간격, 평일 장중)
  └─ cd sentinel && python run_scan.py
       ├─ config/settings.py      watchlist.json 로드 (active만)
       └─ 종목별 scan_single():
            1. collectors/price_collector  yfinance 가격·거래량·장중반전
            2. collectors/news_collector   Google News RSS + Finnhub + SEC
                                           → 중복제거 → 관련성 필터 → 관련도순 정렬
            3. engines/psi_engine          PSI 0~10 + FlashReason 분류
            4. storage/database.save_scan  스캔 이력 (다음 스캔의 뉴스 기준선)
            5. alerts/alert_system         발송 판정 → AI 요약 → Telegram → DB 저장
  └─ sentinel/storage/sentinel.db 를 봇이 자동 커밋
```

## 반드시 알아야 할 것

### DB가 상태 저장소다
`sentinel/storage/sentinel.db`는 git에 커밋되며, **알림 쿨다운 판정의 유일한 근거**다.
- `init_db()`는 절대 `DROP TABLE` 하지 말 것. 컬럼 추가는 `ALTER TABLE`로만 한다
  (스키마 변경 시 `database.py`의 `ALERTS_COLUMNS` 리스트에 추가하면 자동 반영).
- `scan_log`는 30일치만 보관한다. 매 스캔 커밋되므로 안 지우면 레포가 부푼다.

### AI 요약 실패는 조용하다
`ai_summarizer`는 실패 시 예외를 던지지 않고 규칙 기반 폴백으로 넘어간다.
알림은 평소처럼 계속 오고 헤드라인만 "주가 6.4% 상승" 같은 껍데기가 된다.
- 그래서 폴백이 쓰이면 **알림 본문에 `⚠️ AI 요약 실패`가 찍히도록** 해뒀다. 이 표시를 없애지 말 것.
- `alerts.ai_generated` 컬럼으로 사후 집계도 가능하다.

### 모델
`gpt-5.6-luna` ($0.20/$1.20 per 1M). 워크플로의 `OPENAI_MODEL` 환경변수만 바꾸면 롤백된다.
- GPT-5 계열은 `temperature`를 받지 않고 `max_tokens` 대신 `max_completion_tokens`를 쓴다.
  `_build_request_body()`가 모델 접두사로 분기한다.
- `reasoning_effort`를 명시하지 않으면 기본값 medium으로 **추론 토큰이 출력 요금으로 과금된다.**
  이 작업엔 추론이 불필요하므로 `none`으로 고정.
- 응답은 `response_format: json_schema` (strict)로 강제한다.
- 모델이 특정 파라미터를 거부하면(`400` + `error.param`) 그 파라미터만 빼고 자동 재시도한다
  (`_post_with_param_recovery`). 로그에 `🔁 ... 미지원` 이 보이면 코드에 반영할 것.

### 시간대
`zoneinfo.ZoneInfo("America/New_York")`를 쓴다. EST/EDT를 직접 계산하지 말 것.
알림은 시간대별로 다르게 차단된다:
- 주말·야간: 전면 차단 (변동폭 무관)
- 프리/애프터마켓: 10%+ 급변동만
- 정규장: 단계별 임계치 (3→5→8→12%)

주말 차단이 필요한 이유: yfinance의 마지막 일봉이 금요일 종가라 토·일 내내 같은 변동률이 잡힌다.

### 알림 발송 경로는 두 개다
- `psi_critical`: PSI ≥ 7
- `price_surge` / `price_reversal`: ±3% 변동, 3%+ 장중반전, 또는 거래량 3배 + 1% 변동

### 발송 판정이 AI 호출보다 먼저다
`send_alert()`는 `should_send_alert()`를 통과한 뒤에만 OpenAI를 부른다.
순서를 바꾸면 주말·쿨다운으로 버려질 건에도 API 비용이 나간다.

## 알려진 제약

- **Options 점수는 항상 0.** 무료 옵션 데이터 소스가 없어 미연동. PSI 가중치 0.35가 통째로 놀고 있다.
- **뉴스 기준선은 20샘플 이상 쌓여야 동작.** 그 전엔 절대 건수 폴백을 쓴다(보수적).
  `scan_log`가 비어 있으면 배포 후 며칠간 폴백 경로다.
- **SEC EDGAR 수집이 실제로 되는지 미검증.** `efts.sec.gov/LATEST/search-index` 응답을 확인해야 한다.
- **커뮤니티 소스 미연동** (Reddit, StockTwits 등).
- **`save_news()`는 정의만 있고 호출되지 않는다.** `news` 테이블의 297행은 구버전 잔재다.
- **`SCAN_MODE` 환경변수는 `market_open`으로 하드코딩**돼 있고 코드에서 읽지 않는다.

## 작업 시 주의

- 워크플로는 `cd sentinel && python run_scan.py`로 실행한다. import는 `sentinel/` 기준 상대 경로다.
- Telegram은 Markdown v1(`*bold*`)이다. MarkdownV2 아님. 동적 텍스트는 `sanitize_title()`을 거칠 것.
- `watchlist.json`은 루트에 있고 웹 UI(`index.html`)가 GitHub API로 직접 수정한다.
  UI는 base64를 **반드시 UTF-8로 디코딩**해야 한다(`b64utf8()`). `atob()`만 쓰면 저장할 때마다 한글이 깨진다.
- 표시명이 한글인 종목(예: PANW)은 영문 기사와 대조할 수 없다. `keywords`에 영문 명칭을 넣어야
  `_aliases()`가 그것을 별칭으로 쓴다.
- 짧은 티커(NET, MU)는 단어경계 + 대소문자 구분으로 매칭한다. 안 그러면 "net income"에 전부 걸린다.

## GitHub Secrets

`OPENAI_API_KEY` (AI 요약), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `FINNHUB_API_KEY` (뉴스).
`GEMINI_API_KEY`는 더 이상 쓰지 않는다.

## 점검 쿼리

```sql
-- AI 폴백 비율 (높으면 모델/파라미터 문제)
SELECT model, ai_generated, COUNT(*) FROM alerts
WHERE timestamp >= date('now','-7 day') GROUP BY 1,2;

-- 저변동 알림 비율 (높으면 PSI가 과민)
SELECT COUNT(*) FILTER (WHERE ABS(change_pct) < 2) * 100.0 / COUNT(*)
FROM alerts WHERE timestamp >= date('now','-7 day');

-- 종목별 뉴스 기준선
SELECT ticker, COUNT(*), AVG(news_count) FROM scan_log GROUP BY ticker;
```
