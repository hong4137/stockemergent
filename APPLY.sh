#!/bin/bash
echo "📡 Stock Sentinel Phase 1.2 패치 적용"
echo "=================================="

for f in sentinel/alerts/alert_system.py sentinel/alerts/telegram.py \
         sentinel/engines/ai_summarizer.py sentinel/collectors/news_collector.py \
         sentinel/run_scan.py sentinel/config/settings.py; do
    [ -f "$f" ] && cp "$f" "${f}.bak"
done
echo "✅ 백업 완료"

cp sentinel-patch/sentinel/alerts/alert_system.py sentinel/alerts/
cp sentinel-patch/sentinel/alerts/telegram.py sentinel/alerts/
cp sentinel-patch/sentinel/engines/ai_summarizer.py sentinel/engines/
cp sentinel-patch/sentinel/collectors/news_collector.py sentinel/collectors/
cp sentinel-patch/sentinel/run_scan.py sentinel/
cp sentinel-patch/sentinel/config/settings.py sentinel/config/

echo "✅ 패치 복사 완료"

git add sentinel/
git commit -m "🔧 Phase 1.2: watchlist.json 경로 수정 + 전종목 알림

핵심 수정:
- settings.py: watchlist.json 경로 탐색 (sentinel/ + 레포루트 + CWD 모두 검색)
- run_scan.py v2: 종목별 try/except, 에러 텔레그램 알림
- telegram.py v2: Markdown sanitize, 연속발송 딜레이
- alert_system.py v4.1: Top-3 기사 필수 표시
- ai_summarizer.py v2: 환각방지 프롬프트"

echo ""
echo "✅ git push 후 Actions → force_alert 테스트"
echo "   이번에는 MU, AMAT, PANW 3개 모두 알림이 와야 합니다"
