export interface Provider {
  id: number;
  name: string;
  preset: string;
  base_url: string;
  protocol: string;
  headers: Record<string, string>;
  enabled: boolean;
  priority: number;
  cache_markers: string;
  cache_ttl: string;
  account_count: number;
  model_count: number;
}

export interface Preset {
  id: string;
  name: string;
  base_url: string;
  protocol?: string;
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
  cache_read_tokens: number;
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
  cache_policy: string;
  cache_ttl: string;
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
  price_cache_in: number | null;
  price_cache_write: number | null;
  cache_policy: string;
  cache_ttl: string;
  enabled: boolean;
  source: string;
}

export interface RequestSummary {
  request_id: string;
  created_at: string;
  finished_at: string | null;
  key_id: number | null;
  key_name: string | null;
  requested_model: string;
  resolved_provider: string | null;
  resolved_model: string | null;
  endpoint: string;
  status: string;
  http_status: number | null;
  error_type: string | null;
  error_message: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cache_read_tokens: number | null;
  cache_write_tokens: number | null;
  cost: number | null;
  duration_ms: number | null;
  ttft_ms: number | null;
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
  cache_read_tokens: number | null;
  cache_write_tokens: number | null;
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
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cache_write_tokens: number;
    cost: number;
  };
  today: {
    requests: number;
    cost: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cache_write_tokens: number;
  };
  timeseries: {
    day: string;
    requests: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cost: number;
  }[];
  by_provider: {
    provider: string;
    requests: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cost: number;
  }[];
  recent: RequestSummary[];
  counts: { providers: number; accounts: number; combos: number; keys: number };
}

export interface ArchiveFile {
  format: string;
  file: string;
  path: string;
  bytes: number;
  count: number;
}

export interface PurgePreview {
  matched: number;
  before: string;
  format: string;
  dry_run: true;
}

export interface PurgeResult {
  matched: number;
  exported: number;
  deleted: number;
  format: string;
  bytes: number;
  file: string;
  path: string;
  files: ArchiveFile[];
  vacuumed: boolean;
  dry_run: false;
}

export interface Health {
  version: string;
  database: string;
  database_bytes: number;
  free_bytes: number;
  counts: { providers: number; accounts: number; combos: number; keys: number };
}
