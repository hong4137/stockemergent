# 📡 Stock Sentinel v1.0

종목 이상징후 감시 & 실시간 원인 규명 시스템  
GitHub Actions로 자동 스캔 + Telegram 알림

## 작동 방식

```
GitHub Actions (자동 스케줄)
    ├─ 장중 (ET 09:00-16:00): 15분 간격
    ├─ 장후 (ET 16:00-18:00): 30분 간격  
    ├─ 장외 (ET 18:00-09:00): 1시간 간격
    └─ 주말: 4시간 간격

    수집 → 점수 계산 → 이상 감지 → Telegram 알림
```

## 빠른 시작

### 1. 레포 생성
이 코드를 GitHub에 public 레포로 push

### 2. GitHub Secrets 설정
레포 → Settings → Secrets and variables → Actions → New repository secret

| Secret 이름 | 설명 | 필수 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather에서 발급 | ✅ |
| `TELEGRAM_CHAT_ID` | 봇 대화 Chat ID | ✅ |
| `OPENAI_API_KEY` | AI 한국어 요약 (gpt-5.6-luna) | ✅ |
| `FINNHUB_API_KEY` | finnhub.io 무료 키 | 권장 |

### 3. Telegram 봇 만들기
1. 텔레그램에서 `@BotFather` 검색 → `/newbot`
2. 봇 이름: `Stock Sentinel` (자유)
3. 봇 username: `my_sentinel_bot` (자유, _bot으로 끝나야 함)
4. 발급된 토큰 → `TELEGRAM_BOT_TOKEN`으로 저장
5. 생성된 봇에게 아무 메시지 전송
6. 브라우저에서 `https://api.telegram.org/bot<토큰>/getUpdates` 접속
7. `"chat":{"id":123456789}` 에서 숫자 → `TELEGRAM_CHAT_ID`로 저장

### 4. 테스트
Actions → `📡 Stock Sentinel Scan` → Run workflow → `force_alert` 체크 → Run

## 구조
```
sentinel/
├── run_scan.py          # 엔트리포인트
├── config/settings.py   # 워치리스트, 가중치, 키워드
├── collectors/
│   ├── news_collector.py    # Google News RSS, Finnhub, SEC EDGAR
│   └── price_collector.py   # yfinance
├── engines/psi_engine.py    # Pre-signal Index + Flash Reason
├── storage/database.py      # SQLite
└── alerts/
    ├── alert_system.py      # 알림 생성/발송
    └── telegram.py          # Telegram API
```

## Pre-signal Index (0~10)
| 요소 | 가중치 | 측정 대상 |
|---|---|---|
| Options Anomaly | 35% | OTM 거래량, 단기만기, OI, IV 스큐 |
| Attention Accel | 30% | 소셜 언급 가속도, 키워드, 트렌드 |
| Disclosure/Fact | 35% | SEC Filing, 규제 발표, 실적 |

## 알림 등급
- 🟢 **Normal** (0~3): 모니터링 유지
- 🟡 **Watch** (3~5): 주의 관찰
- 🟠 **Alert** (5~7): 경계, Flash Reason 실행
- 🔴 **Critical** (7~10): 즉시 알림 + 원인 규명

## 워치리스트 추가
레포 루트의 `watchlist.json`을 편집하거나, `index.html`을 열어 웹 UI로 관리한다
(GitHub Fine-grained token의 Contents Read/Write 권한 필요).

`active: true`인 종목만 스캔한다. 표시명을 한글로 넣는 경우 `keywords`에 **영문 명칭을
반드시 포함**해야 영문 기사와 매칭된다.

## 비용
**월 $0.3 내외** — OpenAI API 외에는 전부 무료
- OpenAI gpt-5.6-luna: 알림 발송 건에 대해서만 호출 (~$0.3/월)
- GitHub Actions / yfinance / Google News RSS / SEC EDGAR / Telegram: 무료

## 개발자 문서
아키텍처, 함정, 점검 쿼리는 [CLAUDE.md](CLAUDE.md) 참고.
