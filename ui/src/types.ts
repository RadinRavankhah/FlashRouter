// Shared domain types. When the real backend exists, these should mirror its API responses.

export type Protocol = "openai-chat" | "openai-responses" | "anthropic-messages";
export type RequestStatus = "success" | "error" | "interrupted";
export type CostState = "reported" | "estimated" | "unpriced";
export type Strategy = "priority" | "weighted" | "round-robin";

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

export interface UpstreamModel {
  id: string;
  enabled: boolean;
  inPerM: number | null;
  outPerM: number | null;
  contextK: number | null;
}

export interface Upstream {
  id: string;
  name: string;
  baseUrl: string;
  protocol: Protocol;
  enabled: boolean;
  timeoutSec: number;
  credentials: Credential[];
  models: UpstreamModel[];
}

export interface NewUpstreamInput {
  name: string;
  baseUrl: string;
  protocol: Protocol;
  timeoutSec: number;
  apiKey: string;
}

export interface NewModelInput {
  id: string;
  inPerM: number | null;
  outPerM: number | null;
  contextK: number | null;
}

export interface RouteCandidate {
  id: string;
  upstreamId: string;
  model: string;
  weight: number;
  enabled: boolean;
}

export interface Route {
  id: string;
  alias: string;
  strategy: Strategy;
  candidates: RouteCandidate[];
}

export interface Overview {
  spendToday: number | null;
  spendMonth: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  cacheReadFraction: number | null;
  successRate: number;
  active: number;
  budgetRemaining: number | null;
  daily: { label: string; value: number }[];
  modelShare: { model: string; cost: number }[];
  recent: LogRequest[];
}

export interface Settings {
  dataDir: string | null;
  dbSizeMb: number | null;
  bodySizeMb: number | null;
  diskTotalGb: number | null;
  diskFreeGb: number | null;
  encryption: "off" | "locked" | "unlocked";
  bindAddress: string;
  port: number;
  loggingHealthy: boolean;
  lastBackup: string | null;
}
