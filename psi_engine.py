name: "📡 Stock Sentinel Scan"

on:
  # ── 장중 (ET 09:00-16:00 = UTC 14:00-21:00): 15분 간격, 평일만 ──
  schedule:
    - cron: '*/15 14-20 * * 1-5'   # 정규장 + 장전
    
    # ── 장후 (ET 16:00-18:00 = UTC 21:00-23:00): 30분 간격 ──
    - cron: '0,30 21-22 * * 1-5'
    
    # ── 장외 야간 (ET 18:00-09:00 = UTC 23:00-14:00): 1시간 간격 ──
    - cron: '0 23 * * 1-5'
    - cron: '0 0-13 * * 1-5'
    
    # ── 주말: 4시간 간격 (뉴스 모니터링만) ──
    - cron: '0 */4 * * 0,6'

  # 수동 실행
  workflow_dispatch:
    inputs:
      ticker:
        description: '스캔할 종목 (비우면 전체 워치리스트)'
        required: false
        default: ''
      force_alert:
        description: '강제 알림 발송 (테스트용)'
        required: false
        type: boolean
        default: false

permissions:
  contents: write

jobs:
  scan:
    runs-on: ubuntu-latest
    
    steps:
      - name: 📥 Checkout
        uses: actions/checkout@v4
      
      - name: 🐍 Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      
      - name: 📦 Install Dependencies
        run: |
          pip install -r requirements.txt
      
      - name: 📡 Determine Scan Mode
        id: mode
        run: |
          python3 -c "
          from datetime import datetime, timezone, timedelta
          
          et = timezone(timedelta(hours=-5))
          now_et = datetime.now(et)
          hour = now_et.hour
          minute = now_et.minute
          weekday = now_et.weekday()  # 0=Mon, 6=Sun
          
          if weekday >= 5:
              mode = 'weekend'
              interval = '4h'
          elif 9 <= hour < 16 or (hour == 16 and minute == 0):
              mode = 'market_open'
              interval = '15m'
          elif 16 <= hour < 18:
              mode = 'after_hours'
              interval = '30m'
          else:
              mode = 'off_hours'
              interval = '1h'
          
          print(f'Mode: {mode} | Interval: {interval} | ET: {now_et.strftime(\"%H:%M\")}')
          
          with open('$GITHUB_OUTPUT', 'a') as f:
              f.write(f'mode={mode}\n')
              f.write(f'interval={interval}\n')
              f.write(f'et_time={now_et.strftime(\"%H:%M\")}\n')
          " 2>/dev/null || echo "mode=market_open" >> $GITHUB_OUTPUT
      
      - name: 📡 Run Sentinel Scan
        env:
          FINNHUB_API_KEY: ${{ secrets.FINNHUB_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          SCAN_MODE: ${{ steps.mode.outputs.mode }}
          SCAN_TICKER: ${{ github.event.inputs.ticker || '' }}
          FORCE_ALERT: ${{ github.event.inputs.force_alert || 'false' }}
        run: |
          cd sentinel
          python run_scan.py
      
      - name: 💾 Commit scan results
        run: |
          git config user.name "Stock Sentinel Bot"
          git config user.email "sentinel@bot"
          
          # DB 파일과 로그 커밋
          git add -f sentinel/storage/sentinel.db sentinel/logs/ || true
          
          if git diff --cached --quiet; then
            echo "No changes to commit"
          else
            git commit -m "📡 Scan: ${{ steps.mode.outputs.mode }} @ ET ${{ steps.mode.outputs.et_time }}"
            git push
          fi
