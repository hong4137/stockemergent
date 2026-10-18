# 공식 사실·공시 계층 소스 감사 (audit_official)

조사일: 2026-10-18 (토). 기준: 15분 간격 GitHub Actions(Python) + 월 몇 달러 예산.
"실측" = 이번 조사에서 로컬 PC(가정용 IP)에서 curl 로 직접 호출해 확인. "미확인" = 공식 문서나 실호출로 확인하지 못함.
GitHub Actions(Azure 데이터센터 IP)에서는 따로 시험하지 않았다. 그래서 (e) 칸은 전부 추정이다. 첫 배포 때 시험 워크플로를 한 번 돌려 확인해야 한다.

## 요약 표

| # | 소스 | (a) 비용 | (b) 기계 접근 | (c) 지연 | (d) 2026-08~10 과거 기록 + 정확한 시각 | (e) GitHub Actions | (f) 판정 |
|---|---|---|---|---|---|---|---|
| 1a | SEC EDGAR 최신 공시 Atom (`browse-edgar?action=getcurrent&type=8-K&output=atom`) | 무료 | Atom, 인증 없음. User-Agent 에 연락처 필수 | 초~1분 | 최신 피드라 과거 없음. 회사별 Atom(`action=getcompany&CIK=..&type=8-K&output=atom`)은 과거 목록 제공, `<updated>`=접수시각(ET, 오프셋 표기) **실측** | UA 넣으면 될 가능성 높음. 미확인 | **핵심 채택**. 8-K 항목 번호(Item 2.02 등)가 summary 에 들어 있음 |
| 1b | SEC submissions JSON (`data.sec.gov/submissions/CIK##########.json`) | 무료 | JSON, 인증 없음. 10 req/s 상한 | 공식: 보통 1초 미만 | 있음. 필드 `items`(예 `2.02,9.01`), `acceptanceDateTime`, `form`, `primaryDocument` **실측**. ⚠️ 시각 함정은 아래 노트 1 | 위와 같음 | **핵심 채택**. 관심 종목 12개를 15분마다 = 호출 12회. 한도 걱정 없음 |
| 1c | SEC 전문검색 (`efts.sec.gov/LATEST/search-index?q=..&forms=8-K&startdt=..`) | 무료 | JSON(Elasticsearch 형식), 인증 없음 | 수 분~수십 분(색인 지연, 미확인) | 있음(2001~). `file_date` 는 날짜만 | 위와 같음 | 보조. "export controls" 같은 주제로 동종업체 공시를 찾을 때 |
| 2a | PR Newswire 전체 RSS (`prnewswire.com/rss/news-releases-list.rss`) | 무료 | RSS, 인증 없음 **실측 200** | 초~분 | 없음(최근 약 20건만). 과거는 기사 페이지를 긁어야 함 | 될 가능성 높음 | 채택 가능. 단 회사별 필터 없음 → 회사명 키워드로 거르기. S&P 지수 편입 발표도 여기로 나감 |
| 2b | GlobeNewswire RSS | 무료 | RSS 가 있다고 문서에 나옴. 그러나 **실측 403(Akamai)** | — | — | 막힐 가능성 큼 | 보류 |
| 2c | Business Wire RSS (`feed.businesswire.com`) | 무료(맞춤 피드는 PressPass 계정) | **실측**: 옛 피드는 "deactivated by the administrator". 새 피드 주소는 미확인 | — | — | 미확인 | 보류. 회사 IR RSS 도 Micron·Broadcom·NVIDIA·Netflix 모두 **403** 이었다 |
| 2d | Accesswire(ACCESS Newswire) RSS | 무료 | **실측 403**(Cloudflare 챌린지) | — | — | 막힘 | 제외 |
| 3a | 한국 OpenDART 공시검색 (`opendart.fss.or.kr/api/list.json`) | 무료(키 발급) | JSON, `crtfc_key` 필요. 보통 하루 20,000건 초과 시 오류 020 | 분 단위(미확인) | 있음. 단 `rcept_dt` 는 **날짜만**(YYYYMMDD), 시각 없음(공식 가이드) | 해외 IP 차단 여부 미확인 | 삼성·하이닉스 "무엇이 나왔나" 는 OK, "몇 시에" 는 안 됨 |
| 3b | DART 오늘의공시 RSS (`dart.fss.or.kr/api/todayRSS.xml`) | 무료 | RSS **실측 200**(주말이라 항목 0) | 분 | 당일분만 | 미확인 | 실시간 시각 보완용. 항목 pubDate 형식은 평일에 재확인 필요 |
| 3c | 대만 TWSE OpenAPI 월매출 `t187ap05_L` / 중대공시 `t187ap04_L` | 무료 | JSON, 인증 없음 **실측 200** | 당일 | 최신 회차만. 월매출은 날짜만. 중대공시엔 `發言時間`(예 70003=07:00:03) 있음 | 미확인 | TSMC 월매출은 **EDGAR 6-K 가 더 낫다**(노트 3). MOPS 웹은 리디렉트·스크래핑 전용 |
| 4a | Federal Register API (`federalregister.gov/api/v1/documents.json`, `public-inspection-documents`) | 무료 | JSON, 인증 없음 **실측**(BIS 2026-08 이후 16건) | 관보 게재는 하루 단위. Public Inspection 은 게재 전날 공개 | 있음. `publication_date` 는 날짜. PI PDF URL 쿼리 `?1791549922` 가 epoch 시각(추정) | 될 가능성 높음 | 채택. BIS 규칙은 보통 BIS 보도자료나 언론이 먼저 나오므로 "확인용" |
| 4b | BIS 보도자료 | 무료 | 공식 RSS 없음(`bis.gov/rss.xml` **404**). 이메일 구독만. 페이지 스크래핑 | 분~시간 | 페이지 날짜만 | 미확인 | 스크래핑 1페이지면 충분(주 1회 미만 게시) |
| 4c | DOJ 보도 RSS (`justice.gov/news/rss?type=press_release`) | 무료 | RSS **실측 200** | 시간 | pubDate 가 전부 `12:00:00` → **사실상 날짜만** | 미확인 | 약함. 반독점 소송처럼 큰 건만 키워드로 |
| 4d | FTC 보도 RSS | 무료 | `ftc.gov/feeds/press-release.xml` **실측 404**. 새 주소 미확인 | — | — | — | 보류 |
| 4e | CISA KEV JSON (`cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json`) | 무료 | JSON, 인증 없음 **실측**(1,748건) | 수 시간(CISA 추가 시점 기준) | 있음. `dateAdded` **날짜만**. 예: Palo Alto CVE-2026-0322(2026-10-14), Broadcom(2026-08-18) | 될 가능성 높음 | PANW·NET·ZS·CRWD 용으로 채택(하루 1~2회 비교로 충분) |
| 5a | S&P DJI 지수 변경 | 무료 | 보도자료는 PR Newswire + `press.spglobal.com`(Cision 뉴스룸, RSS `index.php?s=2429&pagetemplate=rss` **실측**, 정확한 시각 포함). S&P DJI 전용 섹션 ID 는 미확인. 공지 PDF 는 spglobal.com/spdji(스크래핑) | 보통 장 마감 후 발표(시각 미확인) | 기사 페이지에 날짜. 2026-09-04 S&P 500 편입 발표 확인 | 될 가능성 높음 | 2a 키워드 "Set to Join S&P" 로 충분 |
| 5b | Nasdaq 지수 공지 | 무료 | Nasdaq-100 변경은 GlobeNewswire 보도자료. indexes.nasdaq.com 공지는 미확인 | — | 미확인 | GNW 403 위험 | 연 1회 12월 재구성 + 수시 교체. 우선순위 낮음 |
| 6 | CourtListener API v4 (RECAP) | 무료(기부형) | REST JSON. 검색은 비인증도 **실측 200**. 토큰 권장 | PACER 업로드에 의존(수 시간~수 일) | 있음(`dateFiled` 날짜) | 될 가능성 높음 | 인증 사용자 한도 **5/분·50/시간·125/일**. 15분 폴링은 불가 → 하루 1회 또는 웹훅 알림(Alert API) |
| 7a | FRED release dates (`api.stlouisfed.org/fred/releases/dates`) | 무료(키) | JSON, api_key 필요 | 사전 일정 | 과거·미래 날짜 있음. **시각 없음**(날짜만) | 될 가능성 높음 | 날짜 캘린더로만 |
| 7b | BLS 일정 ICS (`bls.gov/schedule/news_release/bls.ics`) | 무료 | ICS. **실측**: 연락처 포함 UA 는 200, 일반 UA 는 Akamai 봇 차단 페이지 | 사전 일정 | 있음. `DTSTART;TZID=US-Eastern:20261014T083000` 처럼 **시각 포함**(10/14 CPI 확인) | 봇 차단 위험 있음 | 주 1회 받아 캐시. 채택 |
| 7c | BEA 일정 ICS (`bea.gov/news/schedule/ics/online-calendar-subscription.ics`) | 무료 | ICS **실측 200**, `DTSTART:...T133000Z`(UTC 시각) | 사전 일정 | 있음(2027년까지) | 될 가능성 높음 | 채택 |
| 7d | Fed 보도자료 RSS (`federalreserve.gov/feeds/press_all.xml`) | 무료 | RSS **실측 200**, pubDate 시각 포함(예 15:00 GMT) | 분 | 최근분만. FOMC 일정은 `fomccalendars.htm` 스크래핑 | 될 가능성 높음 | 채택(FOMC 성명 14:00 ET 등) |

## 노트

1. **EDGAR submissions JSON 의 `acceptanceDateTime` 은 "Z"(UTC) 표기를 믿으면 안 된다(실측 3건).**
   - MU 8-K(실적, 0000723125-26-000018): 헤더 `ACCEPTANCE-DATETIME 20260930160222`(ET 16:02:22). JSON 은 `2026-10-01T00:02:22.000Z`.
   - MU 8-K(0001104659-26-101067): 헤더 08:06:55 ET. JSON 은 `16:06:55Z`.
   - TSMC 6-K: Atom `06:40:56-04:00`. JSON 은 `14:40:56Z`.
   - 세 건 모두 JSON 값이 ET 시계 + 8시간이었다(EDT 기준 실제 UTC 보다 4시간 늦음). 원인은 모른다. 겨울(EST)에도 +8 이 유지되는지는 미확인이다.
   - 백테스트에서는 회사별 Atom `<updated>`(오프셋 포함)나 `-index-headers.html` 의 `ACCEPTANCE-DATETIME`(ET)을 정본으로 쓰자. JSON 은 `items` 를 읽는 용도로만.
2. **EDGAR 이용 수칙**: 공식 상한은 10 req/s. 분류되지 않은 봇은 차단될 수 있다(공식 fair access). UA 는 `앱이름 이메일` 형식으로. 클라우드 IP 대역 차단 주장은 블로그 한 곳뿐이라 미확인이다. 403 이 나오면 약 10분~24시간 차단이라는 서드파티 보고가 있다.
3. **TSMC 월매출은 EDGAR 6-K 로 받는다.** TSMC(CIK 1046179)는 6-K 를 낸다(2026-08-10, 09-10, 10-08 등, 대략 06:00~06:30 ET). 6-K 가 매번 월매출이라는 점은 제목만 봐서는 미확인이다. 대만 현지 발표(보통 매월 10일 전후 오후)보다 몇 시간 늦을 수 있다. 그래도 같은 EDGAR 파이프라인 하나로 처리되고 정확한 시각이 남는다.
4. **삼성전자·SK하이닉스**: OpenDART 는 접수일만 준다. 시각이 필요하면 DART 오늘의공시 RSS 를 15분마다 저장해 두는 수밖에 없다(과거분 복원 불가). KRX KIND 는 공시 시각을 보여주지만 스크래핑 전용이다(미확인).
5. **보도자료 배포사는 대부분 봇 차단이다**(GNW 403, Accesswire Cloudflare, 회사 IR RSS 403). 대신 미국 상장사는 실적·중대 발표를 같은 시각에 8-K(Item 2.02/7.01/8.01, Ex-99.1)로 내는 경우가 많다. 그래서 **EDGAR 가 배포사 RSS 를 상당 부분 대신한다.** 예외는 8-K 를 내지 않는 제품·제휴 발표이고, 이건 PR Newswire 키워드나 일반 뉴스 계층이 맡아야 한다.
6. **과거 기록(8~10월 백테스트)이 정확한 시각과 함께 남는 곳**: EDGAR(헤더/Atom), BLS·BEA ICS, press.spglobal.com 기사. 날짜만 남는 곳: DART, CISA KEV, Federal Register, DOJ, CourtListener, FRED. 날짜만 있는 소스는 "그날 장중 급변의 후보 원인" 정도로만 매칭해야 한다.
7. 비용: 표의 소스는 전부 무료다. 키가 필요한 곳은 OpenDART, FRED, CourtListener(권장)이다.

## 출처
- SEC EDGAR API 문서: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC 개발자 자료·fair access: https://www.sec.gov/about/developer-resources
- edgartools 문제 해결(403 원인): https://edgartools.readthedocs.io/en/latest/resources/troubleshooting/
- OpenDART 공시검색 가이드: https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001
- CourtListener API v4 개요: https://wiki.free.law/c/courtlistener/help/api/rest/v4/overview
- FRED releases/dates: https://fred.stlouisfed.org/docs/api/fred/releases_dates.html
- BLS iCal 안내: https://www.bls.gov/help/hlpiCAL.htm
- BIS 이메일 알림: https://bis.gov/forms/email-notifications
- GlobeNewswire 미디어 파트너(RSS 언급): https://www.notified.com/GNW-PR/media-partners
- S&P 500 편입 발표 예(2026-09-04): https://press.spglobal.com/2026-09-04-Bloom-Energy,-Illumina,-and-Everpure-Set-to-Join-S-P-500-Others-to-Join-S-P-100,-S-P-MidCap-400,-and-S-P-SmallCap-600
- 그 밖의 엔드포인트(Federal Register, CISA KEV, TWSE OpenAPI, DART RSS, Fed RSS, BEA ICS, PR Newswire RSS)는 2026-10-18 에 curl 로 직접 실측했다.
