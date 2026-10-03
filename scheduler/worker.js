/**
 * Stock Sentinel — 스캔 스케줄러 (Cloudflare Worker, Cron Trigger)
 *
 * 왜 필요한가
 *   GitHub Actions의 schedule(cron)은 보장되지 않는 best-effort 기능이라
 *   15분 간격 스케줄이 대량으로 지연·누락됐다. 실측(2026-09): 평일 스캔 6~7회,
 *   그중 정규장(09:30~16:00) 스캔은 하루 2~3회뿐이었다.
 *   이 워커가 15분마다 깨어나 시장 시간이면 workflow_dispatch API로 스캔을 직접 실행한다.
 *
 * 언제 실행하나 (미 동부시간, 평일, NYSE 휴장일 제외)
 *   정규장  09:30~16:00  15분마다
 *   프리마켓 08:00~09:30  30분마다 (시간외는 10%+ 급변만 알리므로 촘촘할 필요 없음)
 *   애프터  16:00~18:00  30분마다 (16:00 실행이 일일 요약을 보낸다)
 *   그 외(야간·주말)는 실행하지 않는다 — 어차피 알림이 전면 차단되는 시간대라
 *   Actions 무료 분(private 레포 월 2,000분)만 쓴다.
 *
 * 왜 크론 트리거가 아니라 Durable Object 알람인가
 *   계정의 Workers 무료 플랜 크론 트리거 한도(5개)가 다른 프로젝트로 이미 차 있다.
 *   DO 알람은 이 한도에 포함되지 않는다. 알람이 울릴 때마다 다음 15분 정각 알람을
 *   스스로 다시 예약하는 방식으로 크론을 대신한다.
 *
 *   알람 체인이 끊기면(예외 등) GET 요청 한 번으로 다시 무장된다. 스캔 워크플로가
 *   매 실행마다 이 URL을 호출하므로(백업 cron 포함) 끊겨도 스스로 복구된다.
 *   GET은 무장만 하고 스캔을 직접 실행하지 않으므로 공개돼도 Actions 분을 소진시킬 수 없다.
 *
 * 필요한 비밀값 (wrangler secret put GITHUB_TOKEN)
 *   GitHub fine-grained token — 이 레포에 대해 Actions: Read and write 권한만.
 */
import { DurableObject } from "cloudflare:workers";

const QUARTER_MS = 15 * 60 * 1000;

/** 다음 15분 정각 + 5초 (정각 직전에 깨어 이전 슬롯으로 판정되는 것을 막는다) */
export function nextQuarter(ms) {
  return Math.floor(ms / QUARTER_MS) * QUARTER_MS + QUARTER_MS + 5000;
}

// NYSE 휴장일 (조기 폐장일은 정상 실행 — 파이썬 쪽이 '오늘 일봉 없음'으로 한 번 더 거른다)
const NYSE_HOLIDAYS = new Set([
  // 2026
  "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
  "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
  // 2027
  "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
  "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
]);

/** UTC Date → 미 동부시간 구성요소 (서머타임은 Intl이 처리) */
export function easternParts(date) {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", weekday: "short", hour12: false,
  });
  const p = Object.fromEntries(fmt.formatToParts(date).map((x) => [x.type, x.value]));
  return {
    ymd: `${p.year}-${p.month}-${p.day}`,
    weekday: p.weekday,             // Mon..Sun
    minutes: (Number(p.hour) % 24) * 60 + Number(p.minute),
  };
}

/** 이 시각에 스캔을 돌릴지. cron은 15분 간격(:00 :15 :30 :45)으로 깨운다. */
export function decide(date) {
  const et = easternParts(date);
  if (et.weekday === "Sat" || et.weekday === "Sun") return { run: false, why: "주말" };
  if (NYSE_HOLIDAYS.has(et.ymd)) return { run: false, why: "NYSE 휴장일" };

  const m = et.minutes;
  // cron 지연으로 :01, :16 처럼 깨어날 수 있으니 15분 슬롯으로 내림
  const slot = m - (m % 15);
  const OPEN = 9 * 60 + 30, CLOSE = 16 * 60;

  if (slot >= OPEN && slot < CLOSE) return { run: true, why: "정규장" };
  if (slot >= 8 * 60 && slot < OPEN && slot % 30 === 0) return { run: true, why: "프리마켓" };
  if (slot >= CLOSE && slot < 18 * 60 && slot % 30 === 0) return { run: true, why: "애프터마켓" };
  return { run: false, why: "시장 시간 아님" };
}

async function dispatch(env, why) {
  if (!env.GITHUB_TOKEN) {
    console.error("GITHUB_TOKEN 비밀값이 없습니다 — `wrangler secret put GITHUB_TOKEN`");
    return;
  }
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${env.WORKFLOW_FILE}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "stock-sentinel-scheduler",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: env.GITHUB_REF || "main" }),
  });
  if (res.status === 204) {
    console.log(`dispatched (${why})`);
  } else {
    // 401/403: 토큰 만료 또는 권한 부족, 404: 레포·워크플로 경로 오류
    console.error(`dispatch 실패 ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
}

/** 단일 인스턴스 시계. 알람 → (시장 시간이면) dispatch → 다음 알람 예약 */
export class Clock extends DurableObject {
  async arm() {
    const current = await this.ctx.storage.getAlarm();
    if (current != null) return { state: "already armed", next: current };
    const next = nextQuarter(Date.now());
    await this.ctx.storage.setAlarm(next);
    return { state: "armed", next };
  }

  async alarm() {
    const d = decide(new Date());
    if (d.run) {
      // dispatch 실패로 예외가 나면 런타임이 alarm()을 재시도해 중복 실행될 수 있으므로
      // 여기서 삼키고 로그만 남긴다. 다음 슬롯은 아래에서 반드시 예약한다.
      try {
        await dispatch(this.env, d.why);
      } catch (e) {
        console.error(`dispatch 예외: ${e}`);
      }
    }
    await this.ctx.storage.setAlarm(nextQuarter(Date.now()));
  }
}

function clock(env) {
  return env.CLOCK.get(env.CLOCK.idFromName("main"));
}

export default {
  // 무장 전용. 스캔을 직접 실행하지 않는다 — 외부에서 호출해도 Actions 분을 쓰지 않는다.
  async fetch(request, env) {
    const { state, next } = await clock(env).arm();
    const d = decide(new Date());
    const body = [
      `stock-sentinel scheduler: ${state}`,
      `next alarm (UTC): ${new Date(next).toISOString()}`,
      `now: ${d.run ? "scan window (" + d.why + ")" : d.why}`,
      `token: ${env.GITHUB_TOKEN ? "set" : "MISSING — wrangler secret put GITHUB_TOKEN"}`,
    ].join("\n");
    return new Response(body + "\n", { headers: { "content-type": "text/plain; charset=utf-8" } });
  },

  // 나중에 크론 슬롯이 생겨 [triggers]를 추가하더라도 '무장'만 한다 (이중 실행 방지)
  async scheduled(event, env, ctx) {
    ctx.waitUntil(clock(env).arm());
  },
};
