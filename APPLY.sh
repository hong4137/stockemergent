#!/bin/bash
echo "📡 Stock Sentinel Phase 1.1 패치 적용"
echo "=================================="

cp sentinel/alerts/alert_system.py sentinel/alerts/alert_system.py.bak
cp sentinel/alerts/telegram.py sentinel/alerts/telegram.py.bak
cp sentinel/engines/ai_summarizer.py sentinel/engines/ai_summarizer.py.bak
cp sentinel/collectors/news_collector.py sentinel/collectors/news_collector.py.bak
cp sentinel/run_scan.py sentinel/run_scan.py.bak
echo "✅ 백업 완료"

cp sentinel-patch/sentinel/alerts/alert_system.py sentinel/alerts/
cp sentinel-patch/sentinel/alerts/telegram.py sentinel/alerts/
cp sentinel-patch/sentinel/engines/ai_summarizer.py sentinel/engines/
cp sentinel-patch/sentinel/collectors/news_collector.py sentinel/collectors/
cp sentinel-patch/sentinel/run_scan.py sentinel/

echo "✅ 패치 복사 완료"

git add sentinel/alerts/alert_system.py sentinel/alerts/telegram.py \
       sentinel/engines/ai_summarizer.py sentinel/collectors/news_collector.py \
       sentinel/run_scan.py

git commit -m "🔧 Phase 1.1: 전종목 알림 + Markdown 안정화

- run_scan.py v2: 종목별 try/except (1종목 에러→다른 종목 계속), 에러 텔레그램 알림
- telegram.py v2: sanitize_title (뉴스제목 *_[] 제거), 연속발송 1.5s 딜레이
- alert_system.py v4.1: Top-3 기사 제목 sanitize, source별 건수 표시
- ai_summarizer.py v2: 환각방지 프롬프트
- news_collector.py: Google News 매체명 추출"

echo ""
echo "✅ 커밋 완료! git push 후 Actions에서 force_alert 테스트"
