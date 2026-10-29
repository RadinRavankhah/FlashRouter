export interface Provider {
  id: number;
  name: string;
  preset: string;
  base_url: string;
  protocol: string;
  headers: Record<string, string>;
  enabled: boolean;
  priority: number;
  account_count: number;
  model_count: number;
}

export interface Preset {
  id: string;
  name: string;
  base_url: string;
  local: boolean;
  docs: string;
}

export interface Account {
  id: number;
  provider_id: number;
  name: string;
  secret_masked: string;
  has_secret: boolean;
  weight: number;
  priority: number;
  enabled: boolean;
  cooling_until: string | null;
  last_error: string | null;
  cooldown_seconds: number;
  requests: number;
  input_tokens: number;
  output_tokens: number;
}

export interface ComboTarget {
  id?: number;
  provider_id: number;
  provider_name?: string;
  model: string;
  position?: number;
  enabled: boolean;
}

export interface Combo {
  id: number;
  name: string;
  description: string;
  enabled: boolean;
  targets: ComboTarget[];
}

export interface ApiKey {
  id: number;
  name: string;
  token_masked: string;
  enabled: boolean;
  allowed_combos: string[];
  last_used_at: string | null;
  created_at: string;
}

export interface ModelEntry {
  id: number;
  provider_id: number;
  provider_name: string;
  model: string;
  display_name: string | null;
  price_in: number;
  price_out: number;
  enabled: boolean;
  source: string;
}

export interface RequestSummary {
  request_id: string;
  created_at: string;
  requested_model: string;
  resolved_provider: string | null;
  resolved_model: string | null;
  status: string;
  http_status: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost: number | null;
  duration_ms: number | null;
  stream: number;
  attempts: number;
}

export interface Attempt {
  id: number;
  request_id: string;
  attempt_n: number;
  provider_name: string | null;
  account_name: string | null;
  model: string | null;
  started_at: string;
  finished_at: string | null;
  http_status: number | null;
  status: string;
  error_type: string | null;
  error_message: string | null;
  retry_reason: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost: number | null;
}

export interface Payload {
  id: number;
  request_id: string;
  attempt_n: number | null;
  kind: string;
  body: string;
  created_at: string;
}

export interface RequestDetail extends Omit<RequestSummary, "attempts"> {
  finished_at: string | null;
  key_name: string | null;
  error_type: string | null;
  error_message: string | null;
  ttft_ms: number | null;
  attempts: Attempt[];
  payloads: Payload[];
}

export interface Stats {
  totals: {
    requests: number;
    success: number;
    errors: number;
    input_tokens: number;
    output_tokens: number;
    cost: number;
    avg_duration_ms: number | null;
    avg_ttft_ms: number | null;
  };
  today: {
    requests: number;
    cost: number;
    input_tokens: number;
    output_tokens: number;
  };
  timeseries: {
    day: string;
    requests: number;
    input_tokens: number;
    output_tokens: number;
    cost: number;
    errors: number;
  }[];
  by_provider: { provider: string; requests: number; input_tokens: number; output_tokens: number; cost: number }[];
  by_model: { model: string; requests: number; input_tokens: number; output_tokens: number; cost: number }[];
  recent: RequestSummary[];
  counts: { providers: number; accounts: number; combos: number; keys: number };
}

export interface Health {
  version: string;
  database: string;
  database_bytes: number;
  free_bytes: number;
  counts: { providers: number; accounts: number; combos: number; keys: number };
}
