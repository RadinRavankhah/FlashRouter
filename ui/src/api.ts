// The single seam between the UI and the backend.
// Implements GatewayApi with fetch() against the FastAPI admin API.
// Admin endpoints require a JWT obtained via POST /admin/login with the
// gateway API key. The token is held in memory (not localStorage).
import type {
  GatewayKey,
  LogRequest,
  NewModelInput,
  NewUpstreamInput,
  Overview,
  RequestStatus,
  Route,
  Settings,
  Upstream,
  UpstreamModel,
} from "./types";

export interface GatewayApi {
  login(apiKey: string): Promise<{ access_token: string; token_type: string }>;
  logout(): void;
  isAuthenticated(): boolean;
  overview(): Promise<Overview>;
  requests(): Promise<LogRequest[]>;
  request(id: string): Promise<LogRequest | undefined>;
  keys(): Promise<GatewayKey[]>;
  upstreams(): Promise<Upstream[]>;
  createUpstream(input: NewUpstreamInput): Promise<Upstream>;
  addUpstreamModel(upstreamId: string, input: NewModelInput): Promise<UpstreamModel>;
  setUpstreamModelEnabled(upstreamId: string, modelId: string, enabled: boolean): Promise<void>;
  removeUpstreamModel(upstreamId: string, modelId: string): Promise<void>;
  routes(): Promise<Route[]>;
  saveRoute(route: Route): Promise<Route>;
  settings(): Promise<Settings>;
  testUpstream(id: string): Promise<{ ok: boolean; latencyMs: number; message: string }>;
}

// ---------- auth ----------

let token: string | null = null;

export function setAuthToken(value: string | null) {
  token = value;
}

export function getAuthToken(): string | null {
  return token;
}

async function http(input: RequestInfo, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers ?? {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(input, { ...init, headers });
  if (res.status === 401) {
    token = null;
    throw new Error("Unauthorized");
  }
  return res;
}

function mapStatus(
  completed: number | null | undefined,
  error: string | null | undefined,
): RequestStatus {
  if (completed === 0) return "interrupted";
  if (error) return "error";
  return "success";
}

function mapRequest(row: any): LogRequest {
  const attempts: any[] = (row && row.attempts) || [];
  const payloads: any[] = (row && row.payloads) || [];
  const incoming = payloads.find((p: any) => p.kind === "request_incoming");
  const clientResponse = payloads.find((p: any) => p.kind === "response_client");
  let requestBody: unknown = null;
  let responseBody: unknown = null;
  if (incoming?.body) {
    try {
      requestBody = JSON.parse(incoming.body);
    } catch {
      requestBody = incoming.body;
    }
  }
  if (clientResponse?.body) {
    try {
      responseBody = JSON.parse(clientResponse.body);
    } catch {
      responseBody = clientResponse.body;
    }
  }
  return {
    id: row.request_id,
    time: row.created_at,
    clientKey: row.gateway_key_id,
    alias: row.model_id,
    model: row.upstream_model ?? row.model_id,
    protocol: row.protocol,
    status: mapStatus(row.completed, row.error),
    inputTokens: 0,
    outputTokens: 0,
    cachedTokens: null,
    cost: null,
    costState: "unpriced",
    durationMs: row.duration_ms ?? 0,
    ttftMs: row.ttft_ms,
    attempts: attempts.map((a: any, i: number) => ({
      n: i + 1,
      upstream: row.model_id,
      credential: row.gateway_key_id,
      model: a.upstream_model ?? row.model_id,
      httpStatus: a.status_code,
      durationMs: a.duration_ms ?? 0,
      error: a.error,
    })),
    requestBody,
    responseBody,
  };
}

// ---------- httpApi ----------

const later = <T>(make: () => T, ms = 0): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(make()), ms));

export const api: GatewayApi = {
  async login(apiKey: string) {
    const res = await fetch("/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`Login failed: ${res.status} ${text}`);
    }
    const data = await res.json();
    token = data.access_token;
    return { access_token: data.access_token, token_type: data.token_type ?? "bearer" };
  },

  logout() {
    token = null;
  },

  isAuthenticated() {
    return token !== null;
  },

  async overview(): Promise<Overview> {
    if (!token) {
      return later(() => ({
        spendToday: 0,
        spendMonth: 0,
        inputTokens: 0,
        outputTokens: 0,
        cacheReadFraction: null,
        successRate: 0,
        active: 0,
        budgetRemaining: 0,
        daily: [],
        modelShare: [],
        recent: [],
      }));
    }
    const res = await http("/admin/v1/stats");
    const data = await res.json();
    const total = data.total ?? 0;
    const success = data.success ?? 0;
    const interrupted = data.interrupted ?? 0;
    const errors = data.error ?? 0;
    const nonError = total - errors;
    return later(() => ({
      spendToday: 0,
      spendMonth: 0,
      inputTokens: 0,
      outputTokens: 0,
      cacheReadFraction: null,
      successRate: total > 0 ? success / total : 0,
      active: 0,
      budgetRemaining: 0,
      daily: [],
      modelShare: [],
      recent: [],
    }));
  },

  async requests(): Promise<LogRequest[]> {
    if (!token) return later(() => []);
    const res = await http("/admin/v1/requests?limit=100&offset=0");
    const data = await res.json();
    const rows: any[] = data.requests ?? [];
    return later(() => rows.map(mapRequest));
  },

  async request(id: string): Promise<LogRequest | undefined> {
    if (!token) return later(() => undefined);
    const res = await http(`/admin/v1/requests/${id}`);
    if (res.status === 404) return later(() => undefined);
    const data = await res.json();
    const row = data.request;
    if (!row) return later(() => undefined);
    return later(() => mapRequest(row));
  },

  async keys(): Promise<GatewayKey[]> {
    return later(() => []);
  },

  async upstreams(): Promise<Upstream[]> {
    return later(() => []);
  },

  async createUpstream() {
    throw new Error("Upstream management is not available in v0.2");
  },

  async addUpstreamModel() {
    throw new Error("Upstream model management is not available in v0.2");
  },

  async setUpstreamModelEnabled() {
    throw new Error("Upstream model management is not available in v0.2");
  },

  async removeUpstreamModel() {
    throw new Error("Upstream model management is not available in v0.2");
  },

  async routes(): Promise<Route[]> {
    return later(() => []);
  },

  async saveRoute() {
    throw new Error("Route management is not available in v0.2");
  },

  async settings(): Promise<Settings> {
    if (!token) {
      return later(() => ({
        dataDir: "",
        dbSizeMb: 0,
        bodySizeMb: 0,
        diskTotalGb: 0,
        diskFreeGb: 0,
        encryption: "off",
        bindAddress: "127.0.0.1",
        port: 8787,
        loggingHealthy: false,
        lastBackup: new Date().toISOString(),
      }));
    }
    const res = await http("/admin/v1/health");
    const data = await res.json();
    return later(() => ({
      dataDir: "",
      dbSizeMb: data.db_size_mb ?? 0,
      bodySizeMb: 0,
      diskTotalGb: data.disk_total_gb ?? 0,
      diskFreeGb: data.disk_free_gb ?? 0,
      encryption: "off",
      bindAddress: "127.0.0.1",
      port: 8787,
      loggingHealthy: data.logging_healthy ?? false,
      lastBackup: new Date().toISOString(),
    }));
  },

  async testUpstream() {
    return later(() => ({ ok: false, latencyMs: 0, message: "Not available in v0.2" }));
  },
};
