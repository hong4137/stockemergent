# Stock Sentinel v3 — 배포 가이드

## 변경 파일 (8개)

레포에서 아래 파일들을 **덮어쓰기** 하세요:

| 파일 | 변경 내용 |
|---|---|
| `sentinel/config/settings.py` | watchlist.json 자동 로드 |
| `sentinel/collectors/price_collector.py` | 장중 반전 감지 추가 |
| `sentinel/engines/ai_summarizer.py` | **신규** OpenAI 한국어 요약 |
| `sentinel/engines/psi_engine.py` | 가격 부스트 + 반전 반영 |
| `sentinel/alerts/alert_system.py` | v3: 한글 + 단계별 임계치 + 반전 |
| `sentinel/storage/database.py` | change_pct 컬럼 + get_last_alert_psi |
| `sentinel/run_scan.py` | watchlist 로드 + 반전 트리거 + 올바른 파라미터 |
| `.github/workflows/sentinel-scan.yml` | OPENAI_API_KEY 추가 |

## GitHub Secrets 추가

Settings → Secrets → New repository secret:
- `OPENAI_API_KEY`: OpenAI API 키

## requirements.txt 확인

아래가 포함되어 있는지 확인:
```
httpx
```
(OpenAI API 호출에 사용)

## 기존 DB 호환

`database.py`가 자동으로 `change_pct` 컬럼을 마이그레이션합니다.
기존 `sentinel.db`를 삭제할 필요 없습니다.
