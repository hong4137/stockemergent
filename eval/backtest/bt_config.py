"""
백테스트 데이터셋 선택. 환경변수 EVAL_SET으로 고른다.
  main (기본) — eval/events_blind.csv (2026-08~10, 109건)
  h4          — eval/holdout4/events_blind.csv (2026-03~07, 새 홀드아웃 45건)
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
SET = os.environ.get("EVAL_SET", "main")

if SET == "h4":
    ROOT = os.path.join(EVAL, "holdout4")
    EVENTS = os.path.join(ROOT, "events_blind.csv")
    SINCE = "2026-02-20"          # 공시·의견 변경·속보·기사 수집 시작일
    UNTIL = "2026-08-01"
    H_PERIOD = "1y"               # 3월 사건까지 1시간봉이 닿도록
    TAG = "h4"
    PREFIX = "H"
else:
    ROOT = HERE
    EVENTS = os.path.join(EVAL, "events_blind.csv")
    SINCE = "2026-07-01"
    UNTIL = "2026-10-18"
    H_PERIOD = "6mo"
    TAG = ""
    PREFIX = "E"


def path(*parts):
    """데이터셋별 산출물 경로 (main은 기존 위치 그대로)."""
    p = os.path.join(ROOT, *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p
