#!/bin/bash
# Phase 1 패치 적용 스크립트
# 사용법: stockemergent 레포 루트에서 실행

echo "📡 Stock Sentinel Phase 1 패치 적용"
echo "=================================="

# 1. 백업
cp sentinel/alerts/alert_system.py sentinel/alerts/alert_system.py.bak
cp sentinel/engines/ai_summarizer.py sentinel/engines/ai_summarizer.py.bak
cp sentinel/collectors/news_collector.py sentinel/collectors/news_collector.py.bak
echo "✅ 기존 파일 백업 완료"

# 2. 패치 파일 복사
cp sentinel-patch/sentinel/alerts/alert_system.py sentinel/alerts/alert_system.py
cp sentinel-patch/sentinel/engines/ai_summarizer.py sentinel/engines/ai_summarizer.py
cp sentinel-patch/sentinel/collectors/news_collector.py sentinel/collectors/news_collector.py
echo "✅ 패치 파일 복사 완료"

# 3. Git 커밋
git add sentinel/alerts/alert_system.py sentinel/engines/ai_summarizer.py sentinel/collectors/news_collector.py
git commit -m "🔧 Phase 1: Top-3 원인 표시 + AI 환각 방지 + 매체명 추출

- alert_system.py v4: Top-3 기사 제목+출처+URL 필수 표시
- ai_summarizer.py v2: 환각 방지 프롬프트 (팩트만, 추측 금지)
- news_collector.py: Google News에서 매체명 추출, URL 리졸빙 개선"

echo ""
echo "✅ 커밋 완료. 'git push'로 배포하세요."
echo "테스트: Actions → sentinel-scan → Run workflow → force_alert ✅"
