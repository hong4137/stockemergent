# 소스 감사 — 예정 이벤트 · 프리뷰 · 대체 데이터

작성일 2026-10-18. 대상: 15분마다 도는 GitHub Actions 파이썬 앱(월 몇 달러 예산). 감시 종목은 MU, AVGO, QCOM, PANW, NET, AMZN, NFLX이고, 비교 종목은 CRWD, ZS, WDC, SNDK, NVDA, MRVL, ARM이다.

표기 규칙
- **실측**: 2026-10-18에 이 PC에서 직접 호출해 응답을 확인했다.
- **문서**: 공식 문서나 공식 발표에서 확인했다.
- **2차**: 제3자 글에서만 확인했다.
- **미확인**: 기억에 의존했거나 확인하지 못했다.
- GitHub Actions(이하 GHA) 접근성은 로컬에서 실측한 결과다. GHA 러너는 데이터센터 IP라서 봇 차단에 더 잘 걸린다. "로컬 OK"가 곧 "GHA OK"를 뜻하지는 않는다.

## 1. 요약 표

| # | 소스 | (a) 비용 | (b) 접근·인증 | (c) 지연 | (d) 2026년 8~10월 백테스트 기록 | (e) GHA | (f) 판정 |
|---|---|---|---|---|---|---|---|
| 1a | **Nasdaq 실적 캘린더** `api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD` | 무료(비공식) | 키 없음. 브라우저 User-Agent 필요 | 일 단위 갱신 | **부분.** 날짜와 종목은 남지만, 지난 날짜는 `time`이 전부 `time-not-supplied`로 바뀐다(실측: 08-05 474건, 10-14 17건 모두 해당). 미래 날짜에만 `time-pre-market`/`time-after-hours`가 붙는다(10-21 90건 중 87건) | 로컬 OK. 비공식이라 차단 위험 | **채택(전방용).** 매일 스냅샷을 떠서 BMO/AMC를 직접 저장해야 한다. 백테스트용 시각으로는 쓸 수 없다 |
| 1b | **yfinance `get_earnings_dates`** | 무료(비공식) | 키 없음 | 일 단위 | **있음.** 과거 실적 발표의 날짜와 시각이 타임스탬프로 남는다(실측: MU 2026-09-30 16:00 ET, NVDA 2026-08-26 16:00 ET). 미래 일정은 15:00 같은 추정값이 나온다(MU 2026-12-23 15:00 → 미확정 신호로 취급) | 로컬 OK(yfinance 1.1.0). Yahoo 레이트리밋 위험 | **채택(백테스트 기준값).** 8~10월 정답지의 발표 시각 1순위 |
| 1c | **Finnhub `/calendar/earnings`** | 무료 키 있음. 무료는 60콜/분, "1 month Earnings Calendar" 수준(2차) | `token` 파라미터. 프로젝트가 이미 `FINNHUB_API_KEY` 사용 중 | 일 단위 | `hour` 필드(bmo/amc/dmh)가 있다(2차: 커뮤니티 README). 무료 키로 과거 범위가 얼마나 나오는지는 **미확인**. 키로 `from=2026-08-01`을 호출해 확인 필요 | OK(공식 API) | **채택(보조).** 이미 키가 있으므로 Nasdaq과 교차검증용 |
| 1d | **Alpha Vantage `EARNINGS_CALENDAR`** | 무료 키(하루 25콜, 미확인) | `apikey`. CSV | 일 단위 | 전방 전용(horizon 3/6/12개월). `timeOfTheDay` 열(pre-market/post-market)이 있다(실측, demo 키) | OK | **보조.** 하루 1콜이면 충분하다. Nasdaq이 막힐 때 대체용 |
| 1e | **Earnings Whispers Data API** | 유료 등급(Member, Investor, Trader). 가격은 공개 페이지에 없음 | `X-EW-Key` 헤더 | 확정 일정이 빠르다(강점) | `/history/{ticker}` 최근 20회(Investor는 워치리스트만, Member는 없음)(문서) | OK(공식 API) | **보류.** 확정 BMO/AMC 품질은 최상급이다. 가격을 확인한 뒤 Member(10종목·100회/일)로 충분한지 판단 |
| 1f | **Zacks 실적 캘린더** | 웹 무료. API 정보 없음 | 스크래핑만 가능 | — | 미확인 | 페이지는 200 응답. ToS 위험 | **제외** |
| 2a | **회사 IR 사이트 이벤트 RSS(Q4/Notified)** | 무료 | 키 없음 | 실시간 | 이벤트 페이지에 과거 웹캐스트가 남아 있다(미확인) | **차단.** micron, nvidia, qualcomm, amazon, netflix IR은 Cloudflare 403. broadcom, PANW는 Akamai 403. marvell은 404(실측) | **제외(자동 수집 불가).** 수동 확인용 링크로만 쓴다 |
| 2b | **Quartr API / Quartr MCP** | 유료(데모 예약, 가격 비공개). MCP도 "Quartr Pro subscription is required"(실측) | API 키(문서상) | 라이브 오디오와 전사 지연이 "near-zero"(문서) | 컨퍼런스, 파이어사이드챗, 애널리스트데이가 이벤트 유형으로 있다 | OK(유료라면) | **제외(예산 초과).** 컨퍼런스 일정의 정답 소스로는 가장 좋다 |
| 2c | **보도자료 와이어(BusinessWire, GlobeNewswire 등)의 "to present at …"** | 무료 | RSS나 검색 | 행사 1~3주 전에 공지 | 있다. 예: Communacopia 2026은 9/8~9/10 샌프란시스코이고 다수 기업이 시각까지 공지했다(문서) | 대체로 OK | **조건부.** 감시 종목 중 대형사는 보도자료 없이 IR에만 올리는 경우가 많다(미확인). 커버리지가 낮다 |
| 2d | **Finnhub `/press-releases`** | 유료(Premium로 기억, 미확인) | token | 실시간 | — | OK | 보류 |
| 2e | **Catacal(카탈리스트 캘린더)** | 웹 무료, "Updated daily" | API나 피드 언급 없음 | 일 | 컨퍼런스 항목이 있으나 커버리지가 듬성듬성하다 | 스크래핑만 | 제외 |
| 3a | **Nasdaq RSS `nasdaq.com/feed/rssoutbound?category=Earnings`** | 무료 | 키 없음 | 수시 | "Pre-Market Earnings Report for October 19, 2026", "Q3 Earnings Season Preview" 같은 프리뷰 글이 있다(실측) | 로컬 OK | **보조.** 비정형 텍스트라서 일정 힌트는 LLM으로 뽑아야 한다 |
| 3b | **Nasdaq 경제지표 캘린더** `api.nasdaq.com/api/calendar/economicevents?date=` | 무료(비공식) | 키 없음 | 일 | 과거 날짜를 넣어도 이벤트 시각(GMT), 실제치, 컨센서스가 나온다(실측) | 로컬 OK | **채택.** CPI·FOMC 같은 거시 이벤트를 시장 전체 원인 후보로 쓴다 |
| 3c | Finnhub `/calendar/economic` | 과거 데이터는 Enterprise 전용(문서) | token | — | 무료로는 과거 없음 | OK | 제외 |
| 4a | **Federal Register API** `federalregister.gov/api/v1/documents.json` | 무료 | 키 없음 | 게재 전날 Public Inspection으로 먼저 공개된다 | 있다. `publication_date`, `effective_on`, 문서 유형(실측: 2026-08-01 이후 "tariff" 536건) | OK(정부 API) | **채택.** 관세와 수출통제 문서의 시행일(effective_on)을 미래 일정으로 저장 |
| 4b | **Congress.gov API v3** | 무료(api.data.gov 키, DEMO_KEY로 응답 확인) | `api_key` | 일 단위 | 법안 액션 날짜가 있다 | OK | 보조 |
| 4c | **하원 주간 본회의 일정 XML** `docs.house.gov/floor/Download.aspx?file=/billsthisweek/YYYYMMDD/YYYYMMDD.xml` | 무료 | 키 없음 | 전주 금요일~당일 갱신 | 2026-09-14 주간 XML 실측(생성·갱신 시각 포함) | OK | 보조(표결 예정 힌트) |
| 4d | 관세 데드라인 통합 캘린더 | — | — | — | **찾지 못했다.** 정형 캘린더는 없다 | — | 4a와 백악관 발표에서 직접 만든다 |
| 5a | **옵션 만기·쿼드러플 위칭** | 무료(규칙으로 계산) | — | — | 계산값: 8/21, **9/18(쿼드)**, 10/16. 다음은 11/20, 12/18(쿼드) | OK | **채택(코드 내장).** 금요일 오후의 거래량 급증과 "핀"을 이상징후에서 할인할 때 쓴다 |
| 5b | **S&P DJI 지수 편입·리밸런싱** | 무료(보도자료) | press.spglobal.com 등 | 발표는 보통 금요일 장 마감 후 | 2026-09-04 발표, **9/21 개장 전 시행**. **PANW, SNDK(그리고 DELL, ANET) S&P 100 편입**(문서·2차). 감시 종목과 직접 관련된다 | 대체로 OK(미확인) | **채택.** 분기 리밸런싱 날짜는 규칙으로 계산하고, 편입 발표는 와이어 RSS나 뉴스로 잡는다 |
| 5c | MSCI·Nasdaq-100 리밸런싱 | 무료(규칙과 발표) | — | — | MSCI 8월 리뷰는 8월 마지막 영업일 종가 시행, NDX 연례 재구성은 12월 셋째 금요일(미확인) | — | 규칙만 내장 |
| 5d | **락업 만료** | Nasdaq IPO 캘린더 `api.nasdaq.com/api/ipo/calendar?date=YYYY-MM` 무료(실측) | 키 없음 | — | IPO 날짜에서 180일을 더해 계산 | 로컬 OK | **낮은 우선순위.** 감시 종목은 모두 상장한 지 오래돼 해당 없음. 피어 IPO에만 의미가 있다 |
| 6a | **삼성전자·SK하이닉스 장중 데이터(yfinance `005930.KS`, `000660.KS`)** | 무료(비공식) | 키 없음 | 지연 미확인(통상 약 20분 추정) | **있다.** 5분봉이 2026-07-20부터(60일), 1시간봉이 2023-10부터, 1분봉은 최근 8일(실측). 마감 직전 06:00~06:30 UTC 봉이 비는 것으로 보인다(확인 필요) | 로컬 OK | **채택.** KRX는 미국장 전(02:30 ET)에 끝나므로 "프리마켓 원인" 후보로 쓴다. TSMC `2330.TW`도 같은 방식 |
| 6b | KRX 정보데이터시스템 / KRX Open API | 무료 | Open API는 키와 승인 필요(미확인) | 일별 | 일별만 있다 | 미확인 | 보조(일별 검증용) |
| 6c | **관세청 10일·20일 수출 잠정치** | 무료 | 보도자료(관세청 사이트). 공공데이터포털 API 여부 미확인 | **11일(1~10일), 21일(1~20일), 09:00 KST 전후**(2026-09-21 발표 확인: 9/1~20 반도체 341.2억달러, +259.4%) | 날짜는 규칙으로 정해지고, 기사로 검증 가능 | 보도자료 스크래핑은 미확인 | **채택(일정만).** 미국 시각으로 전날 20시경(ET)에 나와 다음 날 메모리주 프리마켓 원인 후보가 된다 |
| 6d | **산업통상부 월간 수출입동향** | 무료 | motir.go.kr 보도자료 | **매월 1일 09:00 KST**(2026-10-01 9월분 발표, 반도체 603억달러 +263%) | 날짜는 규칙 | 미확인 | **채택(일정만)** |
| 6e | **TSMC 월매출** | 무료 | pr.tsmc.com, MOPS, **SEC EDGAR 6-K**(TSMC CIK 0001046179) | **매월 10일 이전.** 9월분은 2026-10-08에 발표(6-K 파일명 `tsm-revenue20261008`). 발표 시각은 대만 오후로 기억(미확인) | EDGAR에 날짜가 남는다 | EDGAR는 연락처를 담은 User-Agent가 필요하다. 그러면 OK | **채택.** EDGAR 6-K 폴링이 가장 안정적이다 |
| 6f | 삼성전자 잠정실적(DART) | 무료(OpenDART 키) | API | 분기 첫 주. 3분기는 **2026-10-08 오전 8시대 KST** | DART 공시 시각이 남는다 | OK(미확인) | **채택(보너스).** 메모리 피어(MU, WDC, SNDK)의 원인 후보 |
| 7a | **Barchart 비정상 옵션 거래** | 웹 일부 무료. 과거와 당일 전체는 Premier 회원 전용(2차) | 스크래핑만(비공식 PyPI는 헤드리스 브라우저) | 장중 | 유료 | 202(봇 챌린지로 추정, 실측) | **제외** |
| 7b | **Cboe 일별 통계** | 무료 웹 | CSV 경로 불명확. 302 리다이렉트 | 일 | 종목별 과거 put/call은 2019년 10월에서 끊긴다(2차) | 미확인 | 제외 |
| 7c | **yfinance 옵션 체인 스냅샷**(volume, openInterest, IV) | 무료(비공식) | 키 없음 | 15분 이상 지연 추정 | **과거 기록 없음**(현재 스냅샷만) | 로컬 OK(MU 만기 25개 실측) | **채택(자가 축적).** 15분마다 vol/OI 상위 계약을 저장해 직접 UOA를 만든다. 8~10월 백테스트는 불가 |
| 7d | 앱스토어 순위 — **Apple RSS** `rss.marketingtools.apple.com/api/v2/us/apps/top-free/...` | 무료 | 키 없음 | 일 단위(추정) | 과거 없음. 직접 축적해야 한다 | 로컬 OK(실측) | 낮은 우선순위(NFLX, AMZN 정도). 15분 주기에는 과하다 |
| 7e | Sensor Tower / data.ai | 유료(엔터프라이즈) | — | — | — | — | 제외 |
| 7f | **Google Trends** | 공식 API는 2025-07 알파, 신청제, 가격과 GA 미정(2차). pytrends는 2025-04 아카이브(2차) | — | — | — | 비공식 스크래핑은 429 위험 | **제외** |
| 7g | **실적 콜 전사 — Alpha Vantage `EARNINGS_CALL_TRANSCRIPT`** | 무료 키(하루 콜 제한) | `apikey` | 분기 단위. 게시 지연 미확인 | 화자별 JSON 실측(IBM 2024Q1, demo 키) | OK | **채택(사후 설명용).** 발표 당일 실시간 용도로는 부적합 |
| 7h | 전사 — Motley Fool | 무료 웹 | 스크래핑 | 콜 후 수 시간(미확인) | 웹에 남는다 | 로컬 200 | 보조(ToS 확인 필요) |
| 7i | 전사 — Finnhub `/stock/transcripts`, API Ninjas | Finnhub는 Premium(2차), API Ninjas는 유료(공식 페이지) | — | — | — | — | 제외 |

## 2. 핵심 발견

1. **Nasdaq 캘린더의 함정.** 지난 날짜를 조회하면 BMO/AMC 정보가 사라진다(`time-not-supplied`로 바뀜). 그래서 백테스트의 발표 시각은 **yfinance `get_earnings_dates`**(과거 타임스탬프 보존)로 정답지를 만든다. 실시간 운영에서는 **매일 Nasdaq(+Finnhub) 스냅샷을 레포에 커밋**해 시각을 보존한다.
2. **IR 사이트는 자동 수집이 막혀 있다.** 주요 IR 사이트가 전부 Cloudflare나 Akamai 403이다. 컨퍼런스 일정의 정답 소스(Quartr)는 유료다. 현실적인 방법은 두 가지다. 하나는 큰 컨퍼런스 날짜(Communacopia 9/8~10, Citi·BofA·Jefferies 등)를 **수동 YAML로 관리**하는 것이고, 다른 하나는 뉴스에서 "presents at" 문구를 잡는 것이다.
3. **감시 종목에 실제로 영향을 준 8~10월 예정 이벤트 예시**
   - 8/26 NVDA 실적(AMC)
   - 9/4 금요일 장 마감 후 S&P 100 편입 발표(PANW, SNDK)와 9/21 시행
   - 9/18 쿼드러플 위칭
   - 9/21 관세청 1~20일 수출(반도체 +259%)
   - 9/30 MU 실적(AMC)
   - 10/1 산업통상부 9월 수출
   - 10/8 삼성전자 잠정실적, TSMC 9월 매출
   - 10/16 월간 옵션 만기
4. **한국과 대만 지표는 모두 미국장이 열리기 전에 나온다.** 관세청과 산업통상부는 09:00 KST(전날 20:00 ET), KRX 마감은 02:30 ET다. 그래서 "갭 상승이나 하락, 프리마켓 이상"의 원인 후보로 묶어 다룬다. yfinance로 KRX와 TWSE 5분봉을 60일, 1시간봉을 2년 이상 구할 수 있어 8~10월 백테스트가 가능하다.
5. **비정상 옵션 거래는 무료로 과거 기록을 구할 수 없다.** 무료 소스 중 과거 기록이 있는 곳이 없다. yfinance 체인을 15분마다 스냅샷으로 떠서 직접 축적하는 것만 가능하고, 8~10월 백테스트에서는 이 축을 빼야 한다.

## 3. 권장 구성(예산 0달러)

- **scheduled_events.json**(매일 1회 생성): Nasdaq 실적 캘린더 + yfinance + Finnhub를 합치고, 시각이 서로 다르면 표시한다. 여기에 Nasdaq 경제지표 캘린더, Federal Register의 `effective_on`, 규칙으로 계산한 OPEX·리밸런싱·관세청(11·21일)·산업통상부(1일)·TSMC(10일 이전) 일정을 더한다.
- **15분 루프**: 급변이 감지되면 ±1거래일 안의 예정 이벤트를 먼저 매칭한다. 그다음 KRX·TWSE 피어의 당일 움직임을 확인하고, 마지막으로 뉴스를 본다.
- **수동 YAML**: 증권사 주최 테크 컨퍼런스 일정과 각사 애널리스트데이 일정을 분기마다 갱신한다.
- **재확인 필요(키 필요)**: Finnhub 무료 키의 과거 범위(`from=2026-08-01`), Earnings Whispers Member 가격, 관세청 공공데이터 API 유무, GHA 러너에서 Nasdaq과 Yahoo 호출이 차단되는지.

## 4. 출처

- Nasdaq API, yfinance, Federal Register, Congress.gov, House floor XML, Apple RSS, Alpha Vantage, Nasdaq RSS: 2026-10-18 직접 호출해 실측
- Finnhub 엔드포인트 정의: finnhub.io/static/swagger.json(실측). 무료 등급: [NexusFi](https://nexusfi.com/d/data-providers/finnhub/)(2차), [Finnhub MCP README](https://glama.ai/mcp/servers/@ach968/finnhub-mcp/blob/2ac82a5705d3239c79a794f60ae59252863f3f2d/README.md)(2차)
- [Earnings Whispers Data API](https://earningswhispers.com/data-api)
- [Quartr API](https://quartr.com/products/quartr-api)
- Communacopia 2026: [Upstart BusinessWire](https://secure.businesswire.com/news/home/20260825087809/en/Upstart-Co-founder-and-CEO-to-Participate-in-Fireside-Chat-at-the-Goldman-Sachs-Communacopia-and-Technology-Conference-2026), [Chime](https://www.chime.com/newsroom/chime-to-participate-in-goldman-sachs-communacopia-technology-conference/)
- S&P 2026년 9월 리밸런싱: [S&P DJI 보도자료](https://press.spglobal.com/2026-09-04-Bloom-Energy,-Illumina,-and-Everpure-Set-to-Join-S-P-500-Others-to-Join-S-P-100,-S-P-MidCap-400,-and-S-P-SmallCap-600)
- 관세청 9월 1~20일: [MTN](https://news.mtn.co.kr/news-detail/2026092110234362698). 9월 수출입동향: [MTN](https://news.mtn.co.kr/news-detail/2026100109075980661)
- TSMC 9월 매출: [SEC 6-K](https://www.sec.gov/Archives/edgar/data/0001046179/000104617926000680/tsm-revenue20261008.htm), [pr.tsmc.com](https://pr.tsmc.com/english/news/3343)
- 삼성전자 3분기 잠정실적: [YTN](https://www.ytn.co.kr/_ln/0102_202610080945200200)
- Google Trends API 알파: [ppc.land](https://ppc.land/google-opens-alpha-testing-for-new-trends-api-targeting-developers-and-journalists/), [dev.to](https://dev.to/esteban_ortega/pytrends-is-dead-heres-how-to-get-google-trends-data-in-2026-1a18)
- Cboe 과거 데이터: [Cboe historical](https://ww2.cboe.com/us/options/market_statistics/historical_data). Barchart: [PyPI barchart](https://pypi.org/project/barchart)
- API Ninjas 유료: [api-ninjas.com](https://api-ninjas.com/use-cases/financial-research)
