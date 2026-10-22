// Shared domain types. When the real backend exists, these should mirror its API responses.

export type Protocol = "openai-chat" | "openai-responses" | "anthropic-messages";
export type RequestStatus = "success" | "error" | "interrupted";
export type CostState = "reported" | "estimated" | "unpriced";

export interface Attempt {
  n: number;
  upstream: string;
  credential: string;
  model: string;
  httpStatus: number | null;
  durationMs: number;
  error: string | null;
}

export interface LogRequest {
  id: string;
  time: string;
  clientKey: string;
  alias: string;
  model: string;
  protocol: Protocol;
  status: RequestStatus;
  inputTokens: number;
  outputTokens: number;
  cachedTokens: number | null;
  cost: number | null;
  costState: CostState;
  durationMs: number;
  ttftMs: number | null;
  attempts: Attempt[];
  requestBody: unknown;
  responseBody: unknown;
}

export interface GatewayKey {
  id: string;
  name: string;
  secret: string;
  enabled: boolean;
  models: string[];
  monthlyBudget: number | null;
  spentMonth: number;
  lastUsed: string | null;
}

export interface Credential {
  id: string;
  name: string;
  secret: string;
  enabled: boolean;
  cooldownUntil: string | null;
  lastError: string | null;
  spentMonth: number;
}

export interface Upstream {
  id: string;
  name: string;
  baseUrl: string;
  protocol: Protocol;
  enabled: boolean;
  timeoutSec: number;
  credentials: Credential[];
}

export interface Route {
  id: string;
  alias: string;
  candidates: { upstreamId: string; model: string }[];
}

export interface Overview {
  spendToday: number;
  spendMonth: number;
  inputTokens: number;
  outputTokens: number;
  cacheReadFraction: number | null;
  successRate: number;
  active: number;
  budgetRemaining: number;
  daily: { label: string; value: number }[];
  modelShare: { model: string; cost: number }[];
  recent: LogRequest[];
}

export interface Settings {
  dataDir: string;
  dbSizeMb: number;
  bodySizeMb: number;
  diskTotalGb: number;
  diskFreeGb: number;
  encryption: "off" | "locked" | "unlocked";
  bindAddress: string;
  port: number;
  loggingHealthy: boolean;
  lastBackup: string;
}
