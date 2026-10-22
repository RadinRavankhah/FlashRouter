// The single seam between the UI and the backend.
// Today every method is served by mock data. When the backend exists, create
// an `httpApi` implementing `GatewayApi` with fetch() and export that instead.
import type {
  GatewayKey, LogRequest, Overview, RequestStatus, Route, Settings, Upstream,
} from "./types";

export interface GatewayApi {
  overview(): Promise<Overview>;
  requests(): Promise<LogRequest[]>;
  request(id: string): Promise<LogRequest | undefined>;
  keys(): Promise<GatewayKey[]>;
  upstreams(): Promise<Upstream[]>;
  routes(): Promise<Route[]>;
  settings(): Promise<Settings>;
  testUpstream(id: string): Promise<{ ok: boolean; latencyMs: number; message: string }>;
}

// ---------- mock data ----------

const pick = <T,>(xs: readonly T[]): T => xs[Math.floor(Math.random() * xs.length)];
const at = (minutes: number) => new Date(Date.now() + minutes * 60_000).toISOString();
const later = <T,>(make: () => T, ms = 280): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(make()), ms));

const KEYS: GatewayKey[] = [
  { id: "key_cc", name: "Claude Code — personal", secret: "gw_live_7f2c9a1e4b8d0c63", enabled: true, models: ["coding-fast", "coding-smart"], monthlyBudget: 40, spentMonth: 18.42, lastUsed: at(-4) },
  { id: "key_codex", name: "Codex CLI", secret: "gw_live_3d91be0f57a2c8e4", enabled: true, models: ["coding-fast"], monthlyBudget: 15, spentMonth: 6.1, lastUsed: at(-22) },
  { id: "key_scripts", name: "Local scripts", secret: "gw_live_c0ffee1234abcd99", enabled: false, models: ["local-draft"], monthlyBudget: null, spentMonth: 0, lastUsed: null },
];

const UPSTREAMS: Upstream[] = [
  {
    id: "up_or", name: "OpenRouter", baseUrl: "https://openrouter.ai/api/v1", protocol: "openai-chat", enabled: true, timeoutSec: 120,
    credentials: [
      { id: "cr_main", name: "personal-main", secret: "sk-or-v1-••••a9f2", enabled: true, cooldownUntil: null, lastError: null, spentMonth: 17.9 },
      { id: "cr_backup", name: "personal-backup", secret: "sk-or-v1-••••71be", enabled: true, cooldownUntil: at(12), lastError: "429 rate limited", spentMonth: 0.52 },
    ],
  },
  { id: "up_local", name: "Local inference", baseUrl: "http://127.0.0.1:1234/v1", protocol: "openai-chat", enabled: true, timeoutSec: 600, credentials: [] },
];

const ROUTES: Route[] = [
  { id: "r1", alias: "coding-fast", candidates: [{ upstreamId: "up_or", model: "qwen/qwen3-coder" }, { upstreamId: "up_or", model: "deepseek/deepseek-chat" }] },
  { id: "r2", alias: "coding-smart", candidates: [{ upstreamId: "up_or", model: "anthropic/claude-sonnet-4.5" }] },
  { id: "r3", alias: "local-draft", candidates: [{ upstreamId: "up_local", model: "llama-3.1-70b-instruct" }] },
];

const MODELS = [
  { id: "anthropic/claude-sonnet-4.5", alias: "coding-smart", upstream: "OpenRouter", inPerM: 3, outPerM: 15, local: false },
  { id: "qwen/qwen3-coder", alias: "coding-fast", upstream: "OpenRouter", inPerM: 0.3, outPerM: 1.2, local: false },
  { id: "deepseek/deepseek-chat", alias: "coding-fast", upstream: "OpenRouter", inPerM: 0.27, outPerM: 1.1, local: false },
  { id: "llama-3.1-70b-instruct", alias: "local-draft", upstream: "Local inference", inPerM: 0, outPerM: 0, local: true },
];

const PROMPTS = [
  "Refactor this React hook to remove the stale closure.",
  "Why does this SSE parser drop the final chunk?",
  "Write a pytest for the budget reservation logic.",
  "Explain this tool_use block and what the client should send back.",
  "Add retry with jitter to the upstream HTTP client.",
];

function buildLogs(count: number): LogRequest[] {
  const out: LogRequest[] = [];
  let t = Date.now();
  for (let i = 0; i < count; i++) {
    t -= (3 + Math.random() * 22) * 60_000;
    const m = pick(MODELS);
    const r = Math.random();
    const status: RequestStatus = r < 0.07 ? "error" : r < 0.09 ? "interrupted" : "success";
    const inputTokens = Math.round(800 + Math.random() * 30000);
    const cachedTokens = Math.random() < 0.5 ? Math.round(inputTokens * Math.random() * 0.85) : null;
    const outputTokens = status === "success" ? Math.round(80 + Math.random() * 3000) : Math.round(Math.random() * 200);
    const cost = m.local
      ? null
      : ((inputTokens - (cachedTokens ?? 0)) * m.inPerM + (cachedTokens ?? 0) * m.inPerM * 0.1 + outputTokens * m.outPerM) / 1_000_000;
    const durationMs = Math.round(1200 + Math.random() * 14000);
    const id = Math.random().toString(36).slice(2, 10);
    out.push({
      id: `req_${id}`,
      time: new Date(t).toISOString(),
      clientKey: pick(KEYS).name,
      alias: m.alias,
      model: m.id,
      protocol: "openai-chat",
      status,
      inputTokens,
      outputTokens,
      cachedTokens,
      cost,
      costState: m.local ? "unpriced" : Math.random() < 0.6 ? "reported" : "estimated",
      durationMs,
      ttftMs: status === "error" ? null : Math.round(300 + Math.random() * 1600),
      attempts: [{
        n: 1,
        upstream: m.upstream,
        credential: m.local ? "none" : "personal-main",
        model: m.id,
        httpStatus: status === "error" ? 403 : 200,
        durationMs: Math.round(durationMs * 0.98),
        error: status === "error" ? "403 · request denied by upstream security policy"
          : status === "interrupted" ? "client disconnected mid-stream" : null,
      }],
      requestBody: {
        model: m.alias,
        stream: true,
        max_tokens: 4096,
        messages: [
          { role: "system", content: "You are a careful coding assistant." },
          { role: "user", content: pick(PROMPTS) },
        ],
      },
      responseBody: status === "error"
        ? { error: { code: 403, message: "Request denied by upstream security policy" } }
        : {
            id: `gen-${id}`,
            model: m.id,
            choices: [{ finish_reason: status === "interrupted" ? null : "stop", message: { role: "assistant", content: "…" } }],
            usage: { prompt_tokens: inputTokens, completion_tokens: outputTokens, prompt_tokens_details: { cached_tokens: cachedTokens ?? 0 } },
          },
    });
  }
  return out;
}

const LOGS = buildLogs(120);

const SETTINGS: Settings = {
  dataDir: "%LOCALAPPDATA%\\Gateway\\data",
  dbSizeMb: 84.2,
  bodySizeMb: 412.7,
  diskTotalGb: 512,
  diskFreeGb: 128.4,
  encryption: "off",
  bindAddress: "127.0.0.1",
  port: 8787,
  loggingHealthy: true,
  lastBackup: at(-60 * 9),
};

function computeOverview(): Overview {
  const startOfDay = new Date();
  startOfDay.setHours(0, 0, 0, 0);
  const spendToday = LOGS.filter((r) => new Date(r.time) >= startOfDay).reduce((s, r) => s + (r.cost ?? 0), 0);

  const cachedRows = LOGS.filter((r) => r.cachedTokens !== null);
  const cachedSum = cachedRows.reduce((s, r) => s + (r.cachedTokens ?? 0), 0);
  const cachedInput = cachedRows.reduce((s, r) => s + r.inputTokens, 0);

  const byModel = new Map<string, number>();
  for (const r of LOGS) byModel.set(r.model, (byModel.get(r.model) ?? 0) + (r.cost ?? 0));

  const daily = Array.from({ length: 14 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (13 - i));
    return { label: d.toLocaleDateString(undefined, { month: "short", day: "numeric" }), value: 4 + Math.random() * 9 };
  });

  return {
    spendToday,
    spendMonth: KEYS.reduce((s, k) => s + k.spentMonth, 0),
    inputTokens: LOGS.reduce((s, r) => s + r.inputTokens, 0),
    outputTokens: LOGS.reduce((s, r) => s + r.outputTokens, 0),
    cacheReadFraction: cachedInput ? cachedSum / cachedInput : null,
    successRate: LOGS.filter((r) => r.status === "success").length / LOGS.length,
    active: 2,
    budgetRemaining: KEYS.reduce((s, k) => s + Math.max(0, (k.monthlyBudget ?? 0) - k.spentMonth), 0),
    daily,
    modelShare: [...byModel].map(([model, cost]) => ({ model, cost })).sort((a, b) => b.cost - a.cost),
    recent: LOGS.slice(0, 6),
  };
}

export const api: GatewayApi = {
  overview: () => later(computeOverview),
  requests: () => later(() => LOGS),
  request: (id) => later(() => LOGS.find((r) => r.id === id)),
  keys: () => later(() => KEYS.map((k) => ({ ...k }))),
  upstreams: () => later(() => UPSTREAMS),
  routes: () => later(() => ROUTES),
  settings: () => later(() => SETTINGS),
  testUpstream: () => later(() => ({ ok: true, latencyMs: 180 + Math.round(Math.random() * 400), message: "Connected" }), 900),
};
