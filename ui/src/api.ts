// The single seam between the UI and the backend.
// Implements GatewayApi with fetch() against the FastAPI admin API.
// No authentication: this is a local dev tool bound to localhost by default.
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
  setupStatus(): Promise<{ configured: boolean }>;
  setupSave(body: {
    gateway_api_key?: string;
    upstream_name?: string;
    upstream_base_url: string;
    upstream_api_key?: string;
    models: Array<{ id: string; upstream_model?: string; owned_by?: string }>;
  }): Promise<{ ok: boolean; message: string }>;

  // Providers
  listProviders(): Promise<{ providers: any[] }>;
  createProvider(body: any): Promise<{ id: string; ok: boolean }>;
  getProvider(id: string): Promise<any>;
  updateProvider(id: string, body: any): Promise<{ ok: boolean }>;
  deleteProvider(id: string): Promise<{ ok: boolean }>;

  // Credentials
  listCredentials(): Promise<{ credentials: any[] }>;
  createCredential(body: any): Promise<{ id: string; ok: boolean }>;
  getCredential(id: string): Promise<any>;
  updateCredential(id: string, body: any): Promise<{ ok: boolean }>;
  deleteCredential(id: string): Promise<{ ok: boolean }>;

  // Gateway keys
  listKeys(): Promise<{ keys: any[] }>;
  createKey(body: any): Promise<{ id: string; ok: boolean }>;
  getKey(id: string): Promise<any>;
  updateKey(id: string, body: any): Promise<{ ok: boolean }>;
  deleteKey(id: string): Promise<{ ok: boolean }>;

  // DB models
  listModels(): Promise<{ models: any[] }>;
  createModel(body: any): Promise<{ id: string; ok: boolean }>;
  getModel(id: string): Promise<any>;
  updateModel(id: string, body: any): Promise<{ ok: boolean }>;
  deleteModel(id: string): Promise<{ ok: boolean }>;

  // Aliases
  listAliases(): Promise<{ aliases: any[] }>;
  createAlias(body: any): Promise<{ id: string; ok: boolean }>;
  getAlias(id: string): Promise<any>;
  updateAlias(id: string, body: any): Promise<{ ok: boolean }>;
  deleteAlias(id: string): Promise<{ ok: boolean }>;

  // Requests / stats / health
  overview(): Promise<Overview>;
  requests(): Promise<LogRequest[]>;
  request(id: string): Promise<LogRequest | undefined>;
  settings(): Promise<Settings>;
}

// ---------- http helper ----------

async function json<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const res = await fetch(input, init);
  if (!res.ok) {
    let detail = "";
    try {
      const err = await res.json();
      detail = err.message || err.detail || JSON.stringify(err);
    } catch {
      detail = res.statusText;
    }
    throw new Error(`HTTP ${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
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
      upstream: a.provider_name ?? row.model_id,
      credential: a.credential_id ?? "default",
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

export const api: GatewayApi = {
  async setupStatus() {
    return json<{ configured: boolean }>("/admin/setup/status");
  },

  async setupSave(body) {
    return json<{ ok: boolean; message: string }>("/admin/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  // Providers
  async listProviders() {
    return json<{ providers: any[] }>("/admin/v1/providers");
  },
  async createProvider(body) {
    return json<{ id: string; ok: boolean }>("/admin/v1/providers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  async getProvider(id: string) {
    return json<any>(`/admin/v1/providers/${id}`);
  },
  async updateProvider(id: string, body: any) {
    return json<{ ok: boolean }>(`/admin/v1/providers/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  async deleteProvider(id: string) {
    return json<{ ok: boolean }>(`/admin/v1/providers/${id}`, { method: "DELETE" });
  },

  // Credentials
  async listCredentials() {
    return json<{ credentials: any[] }>("/admin/v1/credentials");
  },
  async createCredential(body: any) {
    return json<{ id: string; ok: boolean }>("/admin/v1/credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  async getCredential(id: string) {
    return json<any>(`/admin/v1/credentials/${id}`);
  },
  async updateCredential(id: string, body: any) {
    return json<{ ok: boolean }>(`/admin/v1/credentials/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  async deleteCredential(id: string) {
    return json<{ ok: boolean }>(`/admin/v1/credentials/${id}`, {
      method: "DELETE",
    });
  },

  // Gateway keys
  async listKeys() {
    return json<{ keys: any[] }>("/admin/v1/keys");
  },
  async createKey(body: any) {
    return json<{ id: string; ok: boolean }>("/admin/v1/keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  async getKey(id: string) {
    return json<any>(`/admin/v1/keys/${id}`);
  },
  async updateKey(id: string, body: any) {
    return json<{ ok: boolean }>(`/admin/v1/keys/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  async deleteKey(id: string) {
    return json<{ ok: boolean }>(`/admin/v1/keys/${id}`, { method: "DELETE" });
  },

  // DB models
  async listModels() {
    return json<{ models: any[] }>("/admin/v1/dbmodels");
  },
  async createModel(body: any) {
    return json<{ id: string; ok: boolean }>("/admin/v1/dbmodels", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  async getModel(id: string) {
    return json<any>(`/admin/v1/dbmodels/${id}`);
  },
  async updateModel(id: string, body: any) {
    return json<{ ok: boolean }>(`/admin/v1/dbmodels/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  async deleteModel(id: string) {
    return json<{ ok: boolean }>(`/admin/v1/dbmodels/${id}`, { method: "DELETE" });
  },

  // Aliases
  async listAliases() {
    return json<{ aliases: any[] }>("/admin/v1/aliases");
  },
  async createAlias(body: any) {
    return json<{ id: string; ok: boolean }>("/admin/v1/aliases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  async getAlias(id: string) {
    return json<any>(`/admin/v1/aliases/${id}`);
  },
  async updateAlias(id: string, body: any) {
    return json<{ ok: boolean }>(`/admin/v1/aliases/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  async deleteAlias(id: string) {
    return json<{ ok: boolean }>(`/admin/v1/aliases/${id}`, { method: "DELETE" });
  },

  // Requests / stats / health
  async overview(): Promise<Overview> {
    const stats = await json<{ total: number; success: number; interrupted: number; error: number }>(
      "/admin/v1/stats",
    );
    const total = stats.total ?? 0;
    const success = stats.success ?? 0;
    return {
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
    };
  },

  async requests(): Promise<LogRequest[]> {
    const data = await json<{ requests: any[] }>("/admin/v1/requests?limit=100&offset=0");
    const rows: any[] = data.requests ?? [];
    return rows.map(mapRequest);
  },

  async request(id: string): Promise<LogRequest | undefined> {
    const res = await fetch(`/admin/v1/requests/${id}`);
    if (res.status === 404) return undefined;
    const data = await json<{ request: any }>(res as any);
    const row = data.request;
    if (!row) return undefined;
    return mapRequest(row);
  },

  async settings(): Promise<Settings> {
    const health = await json<any>("/admin/v1/health");
    return {
      dataDir: "",
      dbSizeMb: health.db_size_mb ?? 0,
      bodySizeMb: 0,
      diskTotalGb: health.disk_total_gb ?? 0,
      diskFreeGb: health.disk_free_gb ?? 0,
      encryption: "off",
      bindAddress: "127.0.0.1",
      port: 8787,
      loggingHealthy: health.logging_healthy ?? false,
      lastBackup: new Date().toISOString(),
    };
  },
};
