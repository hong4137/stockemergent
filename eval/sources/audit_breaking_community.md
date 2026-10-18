# 속보·커뮤니티 소스 감사 (2026-10-18 기준)

대상: GitHub Actions(15분 주기, 미국 장중)에서 돌아가는 개인용 "왜 움직였나" 알림.
감시 종목은 MU, AVGO, QCOM, PANW, NET, AMZN, NFLX와 동종 종목이고, 월 예산은 몇 달러다.

**검증 방식**
- **[실측]**: 2026-10-18에 직접 호출한 결과다. 로컬 PC(가정용 회선)에서 curl을 썼고, 일부는 클라우드 쪽 WebFetch로도 호출했다.
- **[문서]**: 공식 문서나 가격 페이지로 확인한 내용이다.
- **[2차]**: 제3자 블로그 기준이다.
- **[미검증]**: 확인하지 못했다.

GitHub Actions(Azure IP)에서 직접 돌려 본 결과는 없다. 표의 "GHA" 칸은 추정이므로 첫 배포 때 꼭 확인해야 한다.

---

## A. 속보 (움직임·원인을 빠르게 말해 주는 헤드라인)

| 소스 | (a) 가격 | (b) 접근·인증 | (c) 지연 | (d) 2026년 8~10월 기록·타임스탬프 | (e) GHA 사용 | (f) 판정 |
|---|---|---|---|---|---|---|
| **X API (공식)** | 사용량 과금: 글 1건 읽기 $0.005, 유저 조회 $0.010, 월 300만 건 상한 [문서 docs.x.com/x-api/getting-started/pricing]. 무료 티어는 없음(첫 결제 시 $20 크레딧). 기존 Basic $200, Pro $5,000은 구독자만 [2차] | REST, Bearer 토큰, 선불 크레딧 | 초 단위 | 타임라인·검색으로 과거 조회는 가능하다. 단, 사용량 과금에서 full-archive 검색을 쓸 수 있는지는 [미검증]. ID 기반 ms 타임스탬프 | 가능(공식 API, ToS 준수) | **조건부 채택.** 계정 4~5개 × 15분 폴링 × `since_id`로 신규 글만 받으면 하루 수백 건, 월 $3~10 수준으로 추정된다. 예산 상한(spending limit)을 반드시 걸 것 |
| Nitter / xcancel RSS | 무료 | RSS 스크래핑 | – | 없음 | 불가 | **폐기.** nitter.net은 410 [실측]. 2026-08-24 X사의 내용증명으로 프로젝트가 중단됐다 [2차]. xcancel은 451 [실측] |
| **Bluesky 미러** | 무료 | 공개 AppView `public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed`, 인증 없음 [실측] | 원 계정과 거의 동시(봇 미러) | cursor로 거슬러 페이징 가능. `createdAt`이 ms 단위 ISO [실측] | 가능(공개 API) | **채택(보조).** `skybrg.bsky.social`(Bloomberg식 *헤드라인, 10/17 활동), `livesquawknews.bsky.social`(10/16 활동), `unusualwhales.bsky.social`(팔로워 11.5만, 10/17 활동)은 살아 있다. `walterbloomberg.bsky.social`은 2025-11-06 이후 중단, `wallstreet.bsky.social`은 2023년 중단. FirstSquawk 계정은 없다 [실측] |
| **Telegram 공개 채널 웹 미리보기** | 무료 | `https://t.me/s/<채널>` HTML 스크래핑, 인증 없음. `?before=<msgid>`로 과거 페이징 [실측: 앞의 것만 확인] | 원 소스와 거의 동시 | 메시지마다 `datetime` ISO 초 단위 [실측] | 가능할 것으로 봄 [미검증] | **채택(보조).** `t.me/s/WalterBloomberg`(10/17 글, 공식 여부는 미확인)와 `t.me/s/financialjuice`(10/18 글)가 동작한다. FirstSquawk, unusual_whales, DeItaone 채널은 없다 [실측] |
| **Truth Social (트럼프)** | 무료 | 공식 API `truthsocial.com/api/v1/...`은 403 [실측]. 대안 ① CNN 아카이브 JSON `ix.cnn.io/data/truth-social/truth_archive.json`(20MB, 36,942건, 2022-02 ~ 2026-10-17) [실측] ② `www.trumpstruth.org/feed` RSS(최근 100건) [실측] | CNN 아카이브는 수 분 내외로 갱신되는 것으로 보임 [미검증]. RSS도 비슷 | **CNN 아카이브에 `created_at` ms 단위 전 기록이 있다** → 백테스트에 최적 [실측] | 가능(정적 JSON·RSS). 15분마다 20MB 받기는 부담이므로 실시간은 RSS, 백테스트는 CNN JSON | **채택.** 관세·반도체·특정 기업 언급을 매크로 원인 후보로 쓴다 |
| **Finnhub company-news / news** | 무료 키, 분당 60회 [2차] | REST, 무료 API 키. `/company-news?symbol=&from=&to=`, `/news?category=general` | 수 분 (Yahoo·SeekingAlpha 등 재배포) | `datetime`이 UNIX 초 단위 [문서 swagger.json]. 무료는 회사 뉴스 1년치 [2차 NexusFi] → 8~10월 백테스트 가능 | 가능 | **채택(1순위 헤드라인).** 종목 7개+동종 종목을 15분마다 돌려도 분당 한도 안에 든다. 북미 기업만 지원 [문서] |
| Alpha Vantage NEWS_SENTIMENT | 무료 하루 25회 [2차, 공식 support 페이지 인용]. 유료 분당 75회부터(약 $50/월, [미검증]) | REST, 키. `tickers`, `time_from=YYYYMMDDTHHMM` | 수 분 | `time_published`가 `20261017T231217` 형식(초 단위) [실측 demo 키] | 가능 | **백테스트용만.** 하루 25회로는 실시간 15분 폴링이 불가능하다. 감성 점수가 붙어 있다 |
| Marketaux | 무료: 하루 100회 × 요청당 3건. Basic $29(하루 2,500회, 20건) [문서 marketaux.com/pricing] | REST, 키 | 수 분 | `published_at` 있음. 무료 플랜의 과거 조회 범위는 [미검증] | 가능 | **보류.** 무료는 요청당 3건이라 부족하고 $29는 예산 초과 |
| Massive(구 Polygon) 뉴스 | Stocks Basic 무료(분당 5회). 다만 Benzinga 뉴스는 별도 데이터셋 $99/월 [문서 massive.com/pricing] | REST, 키. `/v2/reference/news` | 수 분 | `published_utc`. 무료 티어 기본 뉴스 포함 여부는 [미검증] | 가능 | **보류.** 무료 분당 5회는 감시 종목 14개쯤에 빠듯하다. Benzinga는 예산 초과 |
| Tiingo News | 무료 Starter(시간당 50회, 하루 1,000회). Power $30/월 [문서 tiingo.com/about/pricing] | REST, 키 | 수 분 | 표준 뉴스 접근은 "최근 3개월 + 이후"만 조회 [문서] → 지금 백테스트를 하면 7/18 이후만 가능하니 서둘러야 함. 무료 플랜에 뉴스가 포함되는지는 [미검증] | 가능 | **보조 후보.** 키를 받아 무료로 뉴스 엔드포인트가 열리는지 확인할 것 |
| Benzinga API | 개발자 API 공식 가격 미확인. 무료 티어 존재 여부도 [미검증]. 공개 RSS `benzinga.com/feed`는 동작 [실측] | RSS | RSS는 지연이 큼(10/17 14:12가 최신 [실측]) | RSS 최근 10건만 | 가능 | **RSS 보조만.** 정식 API는 영업 문의 대상이라 예산 밖 |
| **Yahoo Finance 종목별 RSS** | 무료 | `feeds.finance.yahoo.com/rss/2.0/headline?s=MU&region=US&lang=en-US` [실측: 로컬·클라우드 모두 200] | 수 분 ~ 수십 분 | 최근 16~20건만(약 1~2일) [실측]. 과거 기록 없음 | 가능할 가능성 높음(클라우드 WebFetch에서 성공) | **채택(무료 보조).** 실시간 전용 |
| **Google News RSS 검색** | 무료 | `news.google.com/rss/search?q=Micron+when:1d` [실측]. `after:YYYY-MM-DD before:...` 연산자로 과거 검색 가능 [실측] | 수 분 | 과거 검색은 되지만 **pubDate가 대부분 `07:00:00 GMT`로 뭉개져 날짜 단위**다 [실측] → 분 단위 백테스트에는 부적합 | 가능할 것으로 봄. 대량 호출 시 429 가능 [미검증] | **실시간 보조로 채택.** 백테스트에는 날짜 매칭 정도로만 사용 |
| CNBC RSS | 무료 | `cnbc.com/id/100003114/device/rss/rss.html` 등 [실측 200, 30건] | 수 분 | 최근 30건(약 1~2일) | 가능 | 채택(매크로 헤드라인) |
| MarketWatch RSS | 무료 | `feeds.content.dowjones.io/public/rss/mw_topstories` [실측 200, 10건] | 수 분 | 최근 10건 | 가능 | 보조 |
| Investing.com RSS | 무료 | `investing.com/rss/news_25.rss` [실측 200, 10건] | 수 분 | 최근 10건. 시간대 표기 없는 `2026-10-17 21:20:03`(UTC로 추정) | 가능. Cloudflare 차단 위험 [미검증] | 보조 |
| **Seeking Alpha** | 무료 RSS | 전체: `seekingalpha.com/market_currents.xml`(7건) / 종목별: `seekingalpha.com/api/sa/combined/MU.xml`(30건, 약 10일치) [실측] | 수 분. Market Currents는 "왜 움직였나"형 단신이 많다 | 종목별 피드는 약 10일 거슬러 감. 그 이전은 없음 | 가능할 것으로 봄. 봇 차단(PerimeterX) 이력이 있으니 [미검증] | **채택(종목별 RSS가 쓸모 큼)** |

## B. 커뮤니티 (매크로 이슈·회사 루머 여론)

| 소스 | (a) 가격 | (b) 접근·인증 | (c) 지연 | (d) 2026년 8~10월 기록·타임스탬프 | (e) GHA 사용 | (f) 판정 |
|---|---|---|---|---|---|---|
| Reddit 공식 API | 비상업 무료, OAuth 클라이언트당 분당 100회 [2차]. 상업 가격은 비공개 | OAuth. **2025-11-11 Responsible Builder Policy 시행 후 셀프 등록이 폐지돼 신규 앱은 승인제**이고 거절 사례가 많다 [2차, r/redditdev 공지 미러] | 실시간 | `created_utc` 초 단위. 검색 범위는 제한적 | 승인을 받아야 가능 | **보류.** 신청은 해 볼 만하지만 승인을 기대하기 어렵다 |
| Reddit `.json` / `.rss` | 무료 | 비인증 엔드포인트. **로컬 가정용 회선에서도 403 "Blocked"** [실측]. 클라우드 WebFetch도 거부됨 [실측] | – | – | 불가(클라우드 IP는 더 강하게 차단) | **폐기** |
| StockTwits | 공식 API 신규 개발자 접수는 사실상 중단된 것으로 보임 [미검증, 2024 OneUp 공지: 포스팅 API 회수] | `api.stocktwits.com/api/2/streams/symbol/MU.json`은 **Cloudflare 챌린지로 403**(로컬·클라우드 모두) [실측] | – | – | 불가 | **폐기.** 굳이 쓰려면 Apify 스크래퍼(유료, ToS 회색지대) |
| **LunarCrush** | Light $90/월(분당 10회, 하루 2,000회), Medium $300, Heavy $900 [문서 lunarcrush.com/pricing]. 무료 Discover는 API 없음 | REST·MCP, 키 | 수 분 ~ 1시간 [미검증] | **X 글을 분 단위 타임스탬프로 과거 조회 가능.** `creator_posts`(DeItaone, 2026-08-12 12:30Z CPI 헤드라인 확인), `topic_posts`(`$mu`, 2026-09-23 글 확인) [실측, 이 환경의 LunarCrush MCP 제한 모드]. 다만 **참여도 상위 글만 반환**하므로 전수가 아니다. 일 단위 지표는 2020-01부터 [문서] | 가능(공식 API) | **백테스트 보조로 유용, 실시간 채택은 예산 초과.** "그 시각 DeItaone이 뭐라 했나"를 사후 검증하는 데는 최고. $90/월은 예산의 10배를 넘는다. 이미 MCP 구독이 있다면 백테스트 라벨링에만 활용 |
| **네이버 해외주식 토론방** | 무료 | 비공식 JSON `m.stock.naver.com/front-api/discussion/list?discussionType=foreignStock&itemCode=MU.O&pageSize=50&offset=<lastOffset>`, 인증 없음 [실측] | 실시간 | **`offset` 페이징으로 2025년까지 거슬러 감**(offset -400000000 → 2025-07-02) [실측]. `writtenAt` 초 단위(KST로 추정, 확인 필요). 조회수·추천수 포함 | 가능할 것으로 봄 [미검증]. 비공식 API라 ToS·변경 위험 있음 | **채택(한국 개인투자자 여론).** 티커 코드는 `MU.O`(나스닥) 형식. 글 수 급증을 이상 신호로 활용 가능 |
| Teamblind | 무료 열람(일부 로그인) | 공식 API 없음. 사이트는 200 응답 [실측]. 스크래핑은 ToS 위반 소지 | – | 글 날짜는 있으나 상대 표기 [미검증] | 비권장 | **폐기.** 직원 루머(감원 등)는 느리고 노이즈가 많다 |
| Discord 공개 서버 | 무료 | 봇은 서버 관리자가 초대해야 함. 사용자 토큰 셀프봇은 ToS 위반 | – | – | 불가 | **폐기** |
| Telegram 공개 채널 | 무료 | `t.me/s/` 미리보기(위 A 참조). 정식 MTProto(Telethon)는 전화번호 인증 필요 | 실시간 | 페이징 가능 | 가능할 것으로 봄 | A의 속보 미러 용도로 채택 |
| Google Trends | 무료 | **pytrends는 2025-04-17 아카이브.** 탐색은 부분 동작하지만 429가 잦다 [2차]. 공식 Trends API는 2025-07 알파, 신청제 [2차]. `dailytrends` 엔드포인트 404 [실측] | 시간 단위 | 탐색 API로 과거 시계열 가능(정규화 지수) | 클라우드 IP에서 429 위험이 큼 | **폐기(또는 trendspy 실험).** 15분 경보에는 해상도·안정성 모두 부족 |

---

## 권장 구성 (예산 수 달러/월)

1. **실시간 헤드라인(무료)**: Finnhub company-news(종목별) + Seeking Alpha 종목별 RSS + Yahoo 종목별 RSS + Google News RSS(`when:1h`)를 쓴다. 매크로 쪽은 CNBC/MarketWatch RSS를 붙인다.
2. **속보 스쿼크**: Bluesky(`skybrg`, `livesquawknews`, `unusualwhales`)와 Telegram(`t.me/s/WalterBloomberg`, `t.me/s/financialjuice`)은 무료다. 원본이 필요하면 X API 사용량 과금으로 DeItaone·FirstSquawk·LiveSquawk·unusual_whales 4개 계정만 `since_id`로 폴링한다(월 $5~10 상한).
3. **트럼프 발언**: trumpstruth.org RSS로 실시간, CNN 아카이브 JSON으로 백테스트.
4. **커뮤니티**: 네이버 해외주식 토론방(글 수 급증 + 제목)만 무료로 실용적이다. Reddit과 StockTwits는 차단돼 있다.
5. **백테스트(2026년 8~10월)에서 분 단위 타임스탬프가 있는 것**: Finnhub(1년), Alpha Vantage(하루 25회로 천천히 수집), CNN Truth 아카이브, Bluesky·Telegram 페이징, 네이버 토론방, LunarCrush(상위 글만, 유료). Tiingo는 3개월 창이라 **지금 수집하지 않으면 8월분이 사라진다.** Google News는 날짜 단위뿐이다.

## 주의
- 이번 실측은 로컬 회선 또는 Anthropic 클라우드에서 했다. **Azure(GitHub Actions) IP에서는 Yahoo, Investing, Seeking Alpha가 막힐 수 있다.** 첫 워크플로에서 소스별 HTTP 상태를 로그로 남길 것.
- RSS 날짜 형식이 소스마다 다르다(RFC822, 시간대 없는 문자열, ISO). Investing.com은 시간대 표기가 없고, 네이버는 KST로 추정된다. 파서에서 UTC로 정규화할 것.
- X 사용량 과금의 월 상한은 공식 문서상 300만 건이다(블로그는 200만이라고도 함). 사용량 과금에서 full-archive 검색을 쓸 수 있는지는 미검증이다.

## 출처
- X 가격: https://docs.x.com/x-api/getting-started/pricing , https://opentweet.io/how-to/x-api-pay-per-use-explained , https://www.postproxy.dev/blog/x-api-pricing-2026/
- Nitter 중단: https://twitterapi.io/blog/nitter-alternative , https://www.getxapi.com/alternatives/nitter
- Marketaux: https://www.marketaux.com/pricing
- Massive: https://massive.com/pricing
- Tiingo: https://www.tiingo.com/about/pricing
- LunarCrush: https://lunarcrush.com/pricing
- Finnhub: https://finnhub.io/static/swagger.json , https://nexusfi.com/d/data-providers/finnhub/
- Alpha Vantage: https://www.macroption.com/alpha-vantage-api-limits/
- Reddit RBP: https://r.datuan.dev/r/redditdev/s/gquSJqMgrM (r/redditdev 2025-11-11 공지 미러), https://www.socialcrawl.dev/blog/reddit-api-key-limits-alternatives-2026
- StockTwits: https://help.oneupapp.io/en-us/article/does-oneup-support-stocktwits-1fxjlx0/
- pytrends·Trends API: https://dev.to/esteban_ortega/pytrends-is-dead-heres-how-to-get-google-trends-data-in-2026-1a18 , https://ppc.land/google-opens-alpha-testing-for-new-trends-api-targeting-developers-and-journalists/
