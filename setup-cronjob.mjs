// Будильники на cron-job.org: каждый день просят GitHub запустить publish.yml (mode=next).
// Расписание GitHub бывает с пропусками (13.11 не сработало ни разу), а cron-job.org срабатывает точно.
// Дубли не страшны: если сегодня рилс уже вышел, запуск сразу заканчивается.
//
// Запуск:  node setup-cronjob.mjs          создать или обновить задания
//          node setup-cronjob.mjs --list   показать задания и последний ответ
//
// Ключи берутся из соседних проектов и сюда не копируются:
//   CRONJOB_API_KEY   — ../khl-reels/.env (аккаунт cron-job.org)
//   ALINA_DISPATCH_TOKEN — .env этой папки (fine-grained токен: только alina-reels, Actions: Read and write; .env не в git)

import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
for (const env of [join(here, ".env"), join(here, "..", "khl-reels", ".env")]) {
  if (existsSync(env)) process.loadEnvFile(env);
}

const API = "https://api.cron-job.org";
const REPO = "romandarkcox-hue/alina-reels";
const POST = 1; // код метода POST в API cron-job.org

const JOBS = [
  { title: "Алина: публикация 15:10", hours: [15], minutes: [10] },
  { title: "Алина: публикация 18:10", hours: [18], minutes: [10] },
];

const key = process.env.CRONJOB_API_KEY;
const ghToken = process.env.ALINA_DISPATCH_TOKEN;
if (!key) throw new Error("Нет CRONJOB_API_KEY (ожидается в khl-reels/.env)");

async function api(method, path, body) {
  const res = await fetch(API + path, {
    method,
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`cron-job.org ответил ${res.status} на ${method} ${path}: ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : {};
}

const jobBody = (job) => ({
  url: `https://api.github.com/repos/${REPO}/actions/workflows/publish.yml/dispatches`,
  title: job.title,
  enabled: true,
  saveResponses: true,
  requestMethod: POST,
  schedule: {
    timezone: "Europe/Moscow",
    expiresAt: 0,
    hours: job.hours,
    minutes: job.minutes,
    mdays: [-1],
    months: [-1],
    wdays: [-1],
  },
  extendedData: {
    headers: {
      Authorization: `Bearer ${ghToken}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: "main", inputs: { mode: "next" } }),
  },
  // Письмо на почту аккаунта, если GitHub перестал принимать запуск (например, истёк токен).
  notification: { onFailure: true, onSuccess: false, onDisable: true },
});

const { jobs } = await api("GET", "/jobs");

if (process.argv.includes("--list")) {
  for (const j of jobs.filter((j) => j.title.startsWith("Алина"))) {
    const next = j.nextExecution ? new Date(j.nextExecution * 1000).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" }) : "—";
    console.log(`${j.title}: ${j.enabled ? "включено" : "выключено"}, следующий запуск ${next} МСК, последний ответ ${j.lastStatus}`);
  }
  process.exit(0);
}

if (!ghToken) throw new Error("Нет ALINA_DISPATCH_TOKEN в alina-reels/.env");
// Проверка: токен должен уметь запускать alina-reels (пробный запуск без публикации).
const probe = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/publish.yml/dispatches`, {
  method: "POST",
  headers: { Authorization: `Bearer ${ghToken}`, Accept: "application/vnd.github+json" },
  body: JSON.stringify({ ref: "main", inputs: { mode: "dry-run" } }),
});
if (probe.status !== 204) throw new Error(`GitHub ответил ${probe.status}: у токена нет доступа к ${REPO} (добавьте репозиторий в токен)`);

for (const job of JOBS) {
  const existing = jobs.find((j) => j.title === job.title);
  if (existing) {
    await api("PATCH", `/jobs/${existing.jobId}`, { job: jobBody(job) });
    console.log(`Обновлено: ${job.title}`);
  } else {
    const { jobId } = await api("PUT", "/jobs", { job: jobBody(job) });
    console.log(`Создано: ${job.title} (№ ${jobId})`);
    await new Promise((r) => setTimeout(r, 1500)); // не больше одного создания в секунду
  }
}
