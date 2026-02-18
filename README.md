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
| `FINNHUB_API_KEY` | finnhub.io 무료 키 | 권장 |
| `GEMINI_API_KEY` | Google AI Studio 키 | 선택 |

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
`sentinel/config/settings.py`에서 `WATCHLIST`에 추가:
```python
WatchItem(
    ticker="NVDA",
    name="NVIDIA",
    sector="Semiconductor",
    related=["AMD", "AVGO", "TSM"],
    keywords=["GPU", "AI", "Blackwell", "data center"],
)
```

## 비용
**$0/월** — 모든 구성요소 무료
- GitHub Actions (public 레포): 무제한
- yfinance / Google News RSS / SEC EDGAR: 무료
- Telegram Bot API: 무료
- Gemini Flash (선택): 무료 티어
