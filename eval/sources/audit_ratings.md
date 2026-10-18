# 소스 감사 — 애널리스트 등급·리서치 계층 (audit_ratings)

작성 2026-10-18 · 대상: 15분 주기 GitHub Actions(파이썬) 봇, 월 몇 달러 예산 · 관심 종목 MU, AVGO, QCOM, PANW, NET, AMZN, NFLX 와 동종 종목

표기: **확인** = 이번에 직접 호출하거나 공식 문서로 확인함 / **미확인** = 기억이나 2차 출처에만 근거함

## 1. 결론 요약

- **1순위는 yfinance `upgrades_downgrades`다(무료, 이미 쓰는 의존성).** PANW의 2026-09-17 Bernstein 하향과 09-28 BTIG 목표가 상향이 **시각(초 단위)까지** 남아 있다. 2012년부터 기록이 있어 8~10월 백테스트를 바로 돌릴 수 있다.
- 유료 API(Finnhub, FMP, Benzinga)도 날짜는 주지만 **시각은 Benzinga만 확실하다.** 예산 안에서 Yahoo보다 나은 점이 없다.
- 무료 웹페이지(Finviz, MarketBeat)는 **날짜만** 주고 스크래핑 금지라서 교차 확인용으로만 쓴다.
- 신용등급, 공매도 리포트, TrendForce는 "등급 변경"과 계층이 다르다. 발생은 드물지만 영향이 크므로 저빈도 보조 채널로 둔다.

## 2. 애널리스트 등급 변경 소스

| 소스 | (a) 가격 | (b) 접근 방식·인증 | (c) 지연 | (d) 2026년 8~10월 이력(날짜/시각) | (e) GitHub Actions 사용 | (f) 판정 |
|---|---|---|---|---|---|---|
| **Yahoo / yfinance `Ticker.upgrades_downgrades`** | 무료 | 비공식 JSON(quoteSummary `upgradeDowngradeHistory`), 키 없음 | 거의 실시간으로 보임. PANW Bernstein 11:46 UTC(장전 07:46 ET), BTIG 10:15 UTC(06:15 ET)가 장전 보도 시각과 맞음. 정확한 반영 지연은 **미확인** | **확인**: PANW 936행(2012-07~2026-10-15), MU 896, NFLX 955, AMZN 988, AVGO 632, NET 360, QCOM 561. **날짜와 시각(초)**이 있음(naive datetime, UTC로 추정). 칼럼: Firm, ToGrade, FromGrade, Action(up/down/main/init/reit), priceTargetAction, current/priorPriceTarget | 이미 yfinance를 봇에서 사용 중. Yahoo의 429(YFRateLimitError)는 공유·클라우드 IP에서 자주 보고됨. 종목당 1회 호출이므로 15분 × 약 15종목이면 부담이 적음. ToS상 비공식 사용(개인용 회색지대) | **채택(주력)**. 15분마다 최신 행의 GradeDate가 직전 스캔 이후인지 보고 등급 변경 원인으로 태깅 |
| Finnhub `/stock/upgrade-downgrade` | **유료(Premium)**. 공식 문서 스펙에 `"premium":"Premium Access Required"` 명시(**확인**). 가격은 월 약 $50부터로 기억(**미확인**) | REST, 토큰 | 문서 제목은 "Real-time" | `from`/`to` 파라미터로 2000년부터 조회 가능. 응답 `gradeTime`(epoch)은 예시값이 00:00 UTC라 **날짜 수준**으로 보임 | 클라우드 친화적인 정식 API | 예산 초과에 시각도 없어 **비채택** |
| Financial Modeling Prep (`stable/grades`, `grades-historical`, 구 v4 `upgrades-downgrades`) | Basic $0 / Starter $29(연납 $19) / Premium $69 / Ultimate $139. 현재 연결된 FMP 키로 `grades`를 부르니 "higher plan" 거부(**확인**). 무료로는 안 됨. 어느 플랜부터 열리는지는 **미확인** | REST, apikey | 미확인 | 날짜 필드만 있는 것으로 기억(**미확인**) | 문제없음 | Yahoo 대체용 후보 정도. 지금은 **비채택**. FMP의 TipRanks 시점 데이터는 별도 유료 애드온 |
| Benzinga Analyst Ratings API | 기업용 견적제(공개 가격 없음). Massive(구 Polygon)의 `/benzinga/v1/ratings`도 "파트너십 접근"이 필요하고 가격 비공개(**확인**) | REST(+푸시) | 업계 최고 수준의 실시간(증권사 직접 제휴) | 13년 이상 이력, date+time 필드(시각은 **미확인**) | 문제없음 | 품질은 최고지만 **예산 밖** |
| Alpha Vantage | 무료 25회/일 | REST | — | 등급 **변경** 이벤트 엔드포인트는 없고 OVERVIEW에 등급 분포 수치만 있음(**미확인**) | — | **해당 없음** |
| Massive(구 Polygon) 자체 | $0~$199/월 | REST | — | 자체 등급 데이터는 없고 Benzinga 파트너 데이터뿐(위 참고) | — | **해당 없음** |
| Tiingo | 무료~$30 | REST | — | 등급 데이터 없음(**미확인**) | — | **해당 없음** |
| EODHD | $20~ | REST | — | 펀더멘털에 컨센서스 스냅샷(AnalystRatings)만 있고 이력 엔드포인트는 찾지 못함(**미확인**) | — | **해당 없음** |

## 3. 무료 웹페이지

| 소스 | 가격/접근 | 날짜·시각 | 8~10월 이력 | Actions 사용 | 판정 |
|---|---|---|---|---|---|
| Finviz 종목 페이지 등급표 | 무료 HTML. 로컬에서 HTTP 200 확인. Elite $39.5/월은 CSV 내보내기 | **날짜만**(`Sep-17-26 Downgrade Bernstein Outperform → Mkt Perform $351` **확인**). 페이지 안 JSON `chartEvent/ratings`의 `dateTimestamp`도 자정(날짜) 기준 | 최근 수십 건 | 스크래핑 금지(ToS), 클라우드 IP 차단 가능성(**미확인**) | 교차 확인용으로만 |
| MarketBeat forecast 페이지 | 무료 HTML(200). 애널리스트명은 유료 All Access 뒤에 가려짐 | **날짜만**(9/17/2026 Sanford C. Bernstein 하향 **확인**) | 약 1년 | 스크래핑 금지, 봇 차단 있음 | 백테스트 정답지 보강용(수동) |
| TipRanks | 웹 403(로컬에서도 차단 **확인**). 데이터는 FMP 유료 애드온으로 판매 | 날짜 | — | 사실상 불가 | **비채택** |
| Nasdaq.com `api.nasdaq.com/api/analyst/{sym}/ratings` | 무료 JSON, 키 없음 | `upgradesDowngrades: []` 빈 배열(**확인**). 컨센서스와 증권사 목록만 있음 | 없음 | — | **비채택** |
| Yahoo 웹 페이지 | yfinance와 같은 데이터 | 시각 있음 | 있음 | — | yfinance로 대체 |

### yfinance 직접 테스트 (2026-10-18, yfinance 1.1.0)

```
PANW 2026-09-17 11:46:08  Bernstein  Outperform → Market Perform  down  PT 253 → 351
PANW 2026-09-21 17:54:45  Morgan Stanley  Overweight 유지  PT 394 → 410
PANW 2026-09-28 10:15:10  BTIG  Buy 유지  PT 404 → 425
```

- 테스트에서 찾던 Bernstein 하향(09-17)과 BTIG(09-28)가 둘 다 나왔고 **시각이 들어 있다.**
- 시간대는 UTC로 추정한다. yfinance가 epoch 값을 naive datetime으로 바꾸기 때문이다. 이 추정을 따르면 Bernstein 하향은 장전 07:46 ET가 되어 보도 시각과 맞는다.
- 주의할 점 두 가지:
  - 인덱스가 정렬되어 있지 않아 기간을 잘라 쓰기 전에 `sort_index()`가 필요하다.
  - "Amerx"처럼 이름이 낯선 리서치사도 섞여 있다. 정렬된 증권사 화이트리스트나 가중치로 거르는 것을 권한다.
- 8월 이후 행 수: PANW 약 30, NET 22, AVGO 17, NFLX 13, AMZN 6, QCOM 3. AVGO와 QCOM은 최신 행이 09-10에 멈춰 있어 커버리지가 듬성하다.

## 4. 신용평가사 (Moody's, S&P, Fitch)

- **무료 실시간 피드가 없다.**
  - Fitch와 Moody's의 보도자료는 무료 회원가입 후 웹에서 볼 수 있다. S&P는 로그인이 필요하다. 셋 다 공식 RSS나 API가 무료로 있는지는 **미확인**이다.
  - SEC Rule 17g-7에 따라 공개되는 등급 이력 XBRL 파일은 지연이 커서 실시간 알림에는 쓸 수 없다.
- 관심 종목들은 대부분 투자등급 대형주라 등급 조정이 주가 급변의 원인이 되는 일은 드물다.
- **판정: 비채택.** 뉴스 헤드라인 키워드("Moody's upgrades", "S&P raises … rating")로 대신 잡는다.

## 5. 행동주의 공매도 리포트

- Hindenburg는 2025년 1월에 해산했다.
- 현역: Muddy Waters(X @muddywatersre), Citron(@CitronResearch), Kerrisdale(@KerrisdaleCap), Spruce Point(@sprucepointcap), Grizzly, Fuzzy Panda, Culper, Wolfpack.
- 웹사이트 RSS 실측(2026-10-18):

| 사이트 | 결과 |
|---|---|
| grizzlyreports.com/feed | 정상(최신 2026-10-14) |
| fuzzypandaresearch.com/feed | 응답 정상(최신 2026-06-18) |
| kerrisdalecap.com/feed | RSS는 오지만 항목 0 |
| citronresearch.com, culperresearch.com | 403 |
| sprucepointcap.com, wolfpackresearch.com | 404 |
| muddywatersresearch.com | 응답 없음 |

- X API는 Basic 플랜이 월 $200 수준이라 예산 밖이다(**미확인**).
- 리포트는 보통 장중 X 게시와 동시에 나오고, 그 직후 Benzinga/Reuters 헤드라인으로 퍼진다.
- **판정**: 전용 피드보다 **뉴스 헤드라인 키워드**("short report", "short seller", 회사명 + Citron/Muddy Waters 등)로 잡는 것이 현실적이다. 살아 있는 RSS 2개(Grizzly, Fuzzy Panda)는 하루 1회 폴링하는 보조 채널로 둔다. 다만 관심 종목 같은 대형주가 표적이 된 경우는 드물다(Citron의 과거 사례 정도).

## 6. 산업 리서치 가격 데이터

- **TrendForce / DRAMeXchange**(MU 등 메모리 종목에 중요):
  - DRAMeXchange 첫 화면에 현물가가 무료로 공개되고 매일 갱신된다(화면에 "Last Update: Oct.16 2026 18:10 (GMT+8)" 확인). 계약가 칸은 월 단위로 갱신되며, 화면에는 Oct.5가 찍혀 있다. 상세 이력은 유료 회원 전용이다.
  - TrendForce 뉴스 피드(trendforce.com/news/feed/)는 응답하지만 항목이 2026-07-01에서 멈춰 있었다. 캐시 우회 쿼리를 붙이면 404가 나서 **신뢰할 수 없다.** 뉴스 HTML 페이지는 2026-10-16자까지 갱신되어 있다.
  - 발표 주기:
    - 매주 수요일경 "[Insights] Memory Spot Price Update"
    - 월말·월초 계약가
    - 분기 전환 직전 다음 분기 DRAM/NAND 계약가 전망 보도자료. 시장을 가장 크게 움직이는 것이 이것이다.
  - 아시아 시간(GMT+8)에 발표되므로 미국 장 시작 전에 이미 알려진 상태다.
- **IDC / Gartner** 출하량 보도자료:
  - 무료 보도자료가 있다.
  - RSS는 Gartner 403, IDC 404로 막혀 있다.
  - 분기 종료 후 약 2주 뒤 PC/스마트폰 출하량이 발표된다(1월·4월·7월·10월 중순). 날짜는 보도자료에 있다.
- **판정**:
  - TrendForce: 하루 1회 뉴스 HTML 헤드라인을 스크래핑하거나, 일반 뉴스 피드에서 "TrendForce" 키워드로 잡는다.
  - IDC/Gartner: 분기 캘린더로 "예정된 이벤트" 태그만 단다. 15분 루프에는 넣지 않는다.

## 7. 구현 권고

1. 15분 스캔에서 이상 징후가 있는 종목에 한해 `yf.Ticker(t).upgrades_downgrades`를 부른다. 결과를 `sort_index()`로 정렬하고 직전 영업일 16:00 ET 이후의 행을 원인 후보로 붙인다. Action이 up/down/init이면 강한 후보, main+PT 변경이면 약한 후보로 본다.
2. 백테스트할 때는 같은 데이터에서 2026-08-01~10-15 행을 뽑아 기존 이상 징후 이벤트와 ±1 거래일 안에서 매칭해 놓친 원인 비율을 잰다. MarketBeat/Finviz 날짜로 표본을 교차 검증한다.
3. 429에 대비해 결과를 하루 단위로 캐시하고, 실패해도 스캔 전체가 멈추지 않게 처리한다. 유료로 바꾸는 것은 Yahoo가 막혔을 때만 검토한다(FMP Starter급이 최소 비용).
