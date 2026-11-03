import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, RefreshCw, Search, X } from "lucide-react";
import { api } from "../api";
import {
  Button,
  Card,
  EmptyState,
  PageHeader,
  Spinner,
  StatusBadge,
  formatCost,
  formatMs,
  formatNumber,
  formatRelative,
  useToast,
} from "../components";
import type { RequestSummary } from "../types";

const PAGE_SIZES = [25, 50, 100, 200];
const RANGE_PRESETS = [
  { value: "1h", label: "Last hour", hours: 1 },
  { value: "24h", label: "Last 24 hours", hours: 24 },
  { value: "7d", label: "Last 7 days", hours: 24 * 7 },
  { value: "30d", label: "Last 30 days", hours: 24 * 30 },
];

interface FilterOptions {
  providers: string[];
  endpoints: string[];
  error_types: string[];
  keys: { key_id: number; key_name: string | null }[];
  accounts: { account_id: number; account_name: string | null }[];
}

function apiLabel(endpoint: string): string {
  switch (endpoint) {
    case "messages":
      return "messages";
    case "messages/count_tokens":
      return "count tokens";
    case "responses":
      return "responses";
    default:
      return "chat";
  }
}

function dateValue(value: string | null): string {
  if (!value) return "";
  return value.slice(0, 10);
}

export default function Requests() {
  const toast = useToast();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [items, setItems] = useState<RequestSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [options, setOptions] = useState<FilterOptions | null>(null);

  const q = searchParams.get("q") ?? "";
  const status = searchParams.get("status") ?? "";
  const endpoint = searchParams.get("endpoint") ?? "";
  const provider = searchParams.get("provider") ?? "";
  const keyId = searchParams.get("key") ?? "";
  const accountId = searchParams.get("account") ?? "";
  const errorType = searchParams.get("error") ?? "";
  const from = searchParams.get("from") ?? "";
  const to = searchParams.get("to") ?? "";
  const sortParam = searchParams.get("sort") ?? "newest";
  const sort = ["newest", "oldest", "slowest", "cost"].includes(sortParam)
    ? sortParam
    : "newest";
  const rangeValue = searchParams.get("range") ?? (from || to ? "custom" : "");
  const sizeParam = Number(searchParams.get("size"));
  const size = PAGE_SIZES.includes(sizeParam) ? sizeParam : PAGE_SIZES[1];
  const page = Math.max(1, Number(searchParams.get("page")) || 1);
  const offset = (page - 1) * size;

  const [queryInput, setQueryInput] = useState(q);
  useEffect(() => {
    setQueryInput(q);
  }, [q]);

  const updateParams = useCallback(
    (patch: Record<string, string | number | null>, resetPage = true) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [name, value] of Object.entries(patch)) {
            if (value === null || value === "") next.delete(name);
            else next.set(name, String(value));
          }
          if (resetPage) next.delete("page");
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  useEffect(() => {
    const handle = window.setTimeout(() => {
      const trimmed = queryInput.trim();
      if (trimmed !== q) updateParams({ q: trimmed || null });
    }, 300);
    return () => window.clearTimeout(handle);
  }, [queryInput, q, updateParams]);

  useEffect(() => {
    api
      .get<FilterOptions>("/admin/api/requests/filters")
      .then(setOptions)
      .catch(() => {
        /* filters are optional */
      });
  }, []);

  const load = useCallback(
    async (signal: AbortSignal) => {
      setLoading(true);
      const params = new URLSearchParams({
        limit: String(size),
        offset: String(offset),
        sort,
      });
      if (q) params.set("q", q);
      if (status) params.set("status", status);
      if (endpoint) params.set("endpoint", endpoint);
      if (provider) params.set("provider", provider);
      if (keyId) params.set("key_id", keyId);
      if (accountId) params.set("account_id", accountId);
      if (errorType) params.set("error_type", errorType);
      if (from) params.set("from", from);
      if (to) params.set("to", to);
      try {
        const data = await api.get<{ total: number; items: RequestSummary[] }>(
          `/admin/api/requests?${params.toString()}`,
          { signal },
        );
        setItems(data.items);
        setTotal(data.total);
      } catch (error) {
        if ((error as Error).name === "AbortError") return;
        toast("Failed to load requests", "error");
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    },
    [
      accountId,
      endpoint,
      errorType,
      from,
      keyId,
      offset,
      provider,
      q,
      size,
      sort,
      status,
      to,
      toast,
    ],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, reloadKey]);

  const pages = Math.max(1, Math.ceil(total / size));

  useEffect(() => {
    if (!loading && total > 0 && offset >= total) {
      updateParams({ page: Math.max(1, Math.ceil(total / size)) }, false);
    }
  }, [loading, offset, size, total, updateParams]);

  const endpointOptions = useMemo(() => {
    const values = new Set(options?.endpoints ?? []);
    values.add("chat/completions");
    values.add("responses");
    values.add("messages");
    values.add("messages/count_tokens");
    if (endpoint) values.add(endpoint);
    return Array.from(values).sort();
  }, [endpoint, options]);

  const providerOptions = useMemo(() => {
    const values = new Set(options?.providers ?? []);
    if (provider) values.add(provider);
    return Array.from(values).sort();
  }, [options, provider]);

  const errorOptions = useMemo(() => {
    const values = new Set(options?.error_types ?? []);
    if (errorType) values.add(errorType);
    return Array.from(values).sort();
  }, [errorType, options]);

  const chips = useMemo(() => {
    const result: { key: string; label: string; clear: () => void }[] = [];
    if (q) result.push({ key: "q", label: `“${q}”`, clear: () => updateParams({ q: null }) });
    if (status)
      result.push({ key: "status", label: `status: ${status}`, clear: () => updateParams({ status: null }) });
    if (endpoint)
      result.push({
        key: "endpoint",
        label: `API: ${apiLabel(endpoint)}`,
        clear: () => updateParams({ endpoint: null }),
      });
    if (provider)
      result.push({
        key: "provider",
        label: `provider: ${provider}`,
        clear: () => updateParams({ provider: null }),
      });
    if (keyId) {
      const label = options?.keys.find((item) => String(item.key_id) === keyId)?.key_name;
      result.push({
        key: "key",
        label: `key: ${label ?? `#${keyId}`}`,
        clear: () => updateParams({ key: null }),
      });
    }
    if (accountId) {
      const label = options?.accounts.find(
        (item) => String(item.account_id) === accountId,
      )?.account_name;
      result.push({
        key: "account",
        label: `account: ${label ?? `#${accountId}`}`,
        clear: () => updateParams({ account: null }),
      });
    }
    if (errorType)
      result.push({
        key: "error",
        label: `error: ${errorType}`,
        clear: () => updateParams({ error: null }),
      });
    if (from || to)
      result.push({
        key: "range",
        label: `date: ${from ? dateValue(from) : "…"} → ${to ? dateValue(to) : "now"}`,
        clear: () => updateParams({ from: null, to: null, range: null }),
      });
    if (sort !== "newest")
      result.push({
        key: "sort",
        label: `sort: ${sort}`,
        clear: () => updateParams({ sort: null }),
      });
    return result;
  }, [
    accountId,
    endpoint,
    errorType,
    from,
    keyId,
    options,
    provider,
    q,
    sort,
    status,
    to,
    updateParams,
  ]);

  const clearFilters = () => {
    updateParams({
      q: null,
      status: null,
      endpoint: null,
      provider: null,
      key: null,
      account: null,
      error: null,
      from: null,
      to: null,
      range: null,
      sort: null,
    });
  };

  const selectRange = (value: string) => {
    if (!value) {
      updateParams({ range: null, from: null, to: null });
      return;
    }
    if (value === "custom") {
      updateParams({ range: "custom" });
      return;
    }
    const preset = RANGE_PRESETS.find((item) => item.value === value);
    const nextFrom = preset
      ? new Date(Date.now() - preset.hours * 3600_000).toISOString()
      : null;
    updateParams({ range: value, from: nextFrom, to: null });
  };

  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + items.length, total);

  return (
    <>
      <PageHeader
        title="Requests"
        subtitle="Every dispatched request, its attempts and fallback history."
        actions={
          <Button onClick={() => setReloadKey((value) => value + 1)}>
            <RefreshCw size={15} /> Refresh
          </Button>
        }
      />

      <Card className="section">
        <div className="row">
          <div style={{ position: "relative", flex: "1 1 280px", maxWidth: 420 }}>
            <Search
              size={15}
              style={{
                position: "absolute",
                left: 11,
                top: "50%",
                transform: "translateY(-50%)",
                color: "var(--muted)",
                pointerEvents: "none",
              }}
            />
            <input
              value={queryInput}
              onChange={(event) => setQueryInput(event.target.value)}
              placeholder="Search model, request ID, provider, key, error…"
              aria-label="Search requests"
              style={{ paddingLeft: 34, paddingRight: queryInput ? 34 : 11 }}
            />
            {queryInput && (
              <button
                className="icon-btn"
                style={{
                  position: "absolute",
                  right: 4,
                  top: "50%",
                  transform: "translateY(-50%)",
                }}
                onClick={() => setQueryInput("")}
                aria-label="Clear search"
              >
                <X size={14} />
              </button>
            )}
          </div>

          <select
            value={status}
            onChange={(event) => updateParams({ status: event.target.value || null })}
            aria-label="Filter by status"
            style={{ width: 150 }}
          >
            <option value="">All statuses</option>
            <option value="success">success</option>
            <option value="error">error</option>
            <option value="interrupted">interrupted</option>
          </select>

          <select
            value={endpoint}
            onChange={(event) => updateParams({ endpoint: event.target.value || null })}
            aria-label="Filter by endpoint"
            style={{ width: 170 }}
          >
            <option value="">All endpoints</option>
            {endpointOptions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>

          <select
            value={provider}
            onChange={(event) => updateParams({ provider: event.target.value || null })}
            aria-label="Filter by provider"
            style={{ width: 170 }}
          >
            <option value="">All providers</option>
            {providerOptions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>

          <select
            value={keyId}
            onChange={(event) => updateParams({ key: event.target.value || null })}
            aria-label="Filter by API key"
            style={{ width: 170 }}
          >
            <option value="">All keys</option>
            {(options?.keys ?? []).map((item) => (
              <option key={item.key_id} value={item.key_id}>
                {item.key_name || `Key #${item.key_id}`}
              </option>
            ))}
          </select>

          <select
            value={accountId}
            onChange={(event) => updateParams({ account: event.target.value || null })}
            aria-label="Filter by account"
            style={{ width: 180 }}
          >
            <option value="">All accounts</option>
            {(options?.accounts ?? []).map((item) => (
              <option key={item.account_id} value={item.account_id}>
                {item.account_name || `Account #${item.account_id}`}
              </option>
            ))}
          </select>

          <select
            value={errorType}
            onChange={(event) => updateParams({ error: event.target.value || null })}
            aria-label="Filter by error type"
            style={{ width: 160 }}
          >
            <option value="">All errors</option>
            {errorOptions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>

        <div className="row" style={{ marginTop: 10 }}>
          <select
            value={rangeValue}
            onChange={(event) => selectRange(event.target.value)}
            aria-label="Filter by date range"
            style={{ width: 150 }}
          >
            <option value="">Any time</option>
            {RANGE_PRESETS.map((preset) => (
              <option key={preset.value} value={preset.value}>
                {preset.label}
              </option>
            ))}
            <option value="custom">Custom…</option>
          </select>

          <input
            type="date"
            value={dateValue(from)}
            onChange={(event) =>
              updateParams({ range: "custom", from: event.target.value || null })
            }
            aria-label="From date (UTC)"
            title="From date (UTC)"
            style={{ width: 145 }}
          />
          <span className="muted">to</span>
          <input
            type="date"
            value={dateValue(to)}
            onChange={(event) =>
              updateParams({ range: "custom", to: event.target.value || null })
            }
            aria-label="To date (UTC)"
            title="To date (UTC)"
            style={{ width: 145 }}
          />

          <select
            value={sort}
            onChange={(event) =>
              updateParams({ sort: event.target.value === "newest" ? null : event.target.value })
            }
            aria-label="Sort requests"
            style={{ width: 160 }}
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="slowest">Slowest first</option>
            <option value="cost">Highest cost</option>
          </select>

          <select
            value={size}
            onChange={(event) =>
              updateParams({ size: Number(event.target.value) === 50 ? null : event.target.value })
            }
            aria-label="Page size"
            style={{ width: 120 }}
          >
            {PAGE_SIZES.map((value) => (
              <option key={value} value={value}>
                {value} / page
              </option>
            ))}
          </select>

          <span className="muted">
            {loading ? "Loading…" : `${formatNumber(total)} total`}
          </span>
        </div>

        {chips.length > 0 && (
          <div className="chip-row">
            {chips.map((chip) => (
              <button
                key={chip.key}
                className="chip"
                onClick={chip.clear}
                title="Remove filter"
              >
                {chip.label}
                <X size={12} />
              </button>
            ))}
            <Button variant="ghost" className="btn-sm" onClick={clearFilters}>
              Clear all
            </Button>
          </div>
        )}
      </Card>

      <div className="section">
        {loading && items.length === 0 ? (
          <Spinner label="Loading requests…" />
        ) : items.length === 0 ? (
          <EmptyState
            title={chips.length > 0 ? "No matching requests" : "No requests"}
            description={
              chips.length > 0
                ? "Try widening the search or clearing some filters."
                : "Requests will appear here once clients start using the gateway."
            }
            action={
              chips.length > 0 ? <Button onClick={clearFilters}>Clear filters</Button> : undefined
            }
          />
        ) : (
          <>
            <div className="table-wrap" style={{ opacity: loading ? 0.65 : 1 }}>
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>API</th>
                    <th>Requested</th>
                    <th>Routed to</th>
                    <th>Status</th>
                    <th>Attempts</th>
                    <th>Tokens</th>
                    <th>Cached</th>
                    <th>Cost</th>
                    <th>Latency</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row) => (
                    <tr
                      key={row.request_id}
                      className="clickable"
                      title={row.error_message ?? undefined}
                      onClick={() => navigate(`/requests/${row.request_id}`)}
                    >
                      <td>{formatRelative(row.created_at)}</td>
                      <td className="muted">{apiLabel(row.endpoint)}</td>
                      <td>{row.requested_model}</td>
                      <td className="muted">
                        {row.resolved_provider
                          ? `${row.resolved_provider} · ${row.resolved_model}`
                          : "—"}
                      </td>
                      <td>
                        <StatusBadge status={row.status} />
                      </td>
                      <td>{row.attempts || 1}</td>
                      <td>{formatNumber((row.input_tokens || 0) + (row.output_tokens || 0))}</td>
                      <td className="muted">{formatNumber(row.cache_read_tokens)}</td>
                      <td>{formatCost(row.cost)}</td>
                      <td>{formatMs(row.duration_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="row-between" style={{ marginTop: 14 }}>
              <span className="muted">
                Showing {start}–{end} of {formatNumber(total)} · page {page} of {pages}
              </span>
              <div className="row">
                <Button
                  onClick={() => updateParams({ page: 1 }, false)}
                  disabled={page <= 1}
                >
                  First
                </Button>
                <Button
                  onClick={() => updateParams({ page: page - 1 }, false)}
                  disabled={page <= 1}
                >
                  <ChevronLeft size={15} /> Prev
                </Button>
                <Button
                  onClick={() => updateParams({ page: page + 1 }, false)}
                  disabled={page >= pages}
                >
                  Next <ChevronRight size={15} />
                </Button>
                <Button
                  onClick={() => updateParams({ page: pages }, false)}
                  disabled={page >= pages}
                >
                  Last
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}
