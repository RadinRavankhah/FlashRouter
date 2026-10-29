import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Plus } from "lucide-react";
import { api } from "../api";
import {
  Card,
  EmptyState,
  PageHeader,
  Sparkline,
  Spinner,
  StatCard,
  formatCost,
  formatMs,
  formatNumber,
  formatRelative,
} from "../components";
import type { Stats } from "../types";

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "success"
      ? "success"
      : status === "error" || status === "interrupted"
        ? "danger"
        : "muted";
  return <span className={`badge badge-${tone}`}>{status}</span>;
}

export default function Overview() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<Stats>("/admin/api/stats")
      .then(setStats)
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner label="Loading overview…" />;
  if (!stats) return <EmptyState title="Could not load overview" />;

  const totalRequests = stats.totals.requests || 0;
  const successRate = totalRequests
    ? Math.round(((stats.totals.success || 0) / totalRequests) * 100)
    : 0;
  const todayTokens = (stats.today.input_tokens || 0) + (stats.today.output_tokens || 0);

  if (stats.counts.providers === 0) {
    return (
      <>
        <PageHeader
          title="Welcome to FlashRouter"
          subtitle="Route any OpenAI-compatible client through one local endpoint with automatic fallback."
        />
        <Card>
          <EmptyState
            title="Add your first provider"
            description="Connect OpenRouter, Groq, DeepSeek, a local model server, or any OpenAI-compatible endpoint. Then create a combo to enable fallback."
            action={
              <Link to="/connections" className="btn btn-primary">
                <Plus size={16} /> Add a provider
              </Link>
            }
          />
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Usage, spend and routing health at a glance."
      />

      <div className="stat-grid">
        <StatCard label="Requests today" value={formatNumber(stats.today.requests)} />
        <StatCard
          label="Success rate"
          value={`${successRate}%`}
          hint={`${formatNumber(totalRequests)} total requests`}
        />
        <StatCard label="Tokens today" value={formatNumber(todayTokens)} hint="input + output" />
        <StatCard label="Est. cost today" value={formatCost(stats.today.cost)} hint="savings tracker" />
        <StatCard label="Providers" value={String(stats.counts.providers)} hint={`${stats.counts.accounts} accounts`} />
        <StatCard label="Combos" value={String(stats.counts.combos)} hint={`${stats.counts.keys} API keys`} />
      </div>

      <div className="grid-2">
        <Card>
          <div className="section-head">
            <span className="section-title">Requests · last 14 days</span>
            <span className="muted">{formatNumber(totalRequests)} total</span>
          </div>
          <Sparkline values={stats.timeseries.map((row) => row.requests)} />
          <div className="section" style={{ marginTop: 18 }}>
            <div className="section-head">
              <span className="section-title">Estimated spend</span>
              <span className="muted">{formatCost(stats.totals.cost)}</span>
            </div>
            <Sparkline values={stats.timeseries.map((row) => row.cost)} color="var(--success)" />
          </div>
        </Card>

        <Card>
          <div className="section-head">
            <span className="section-title">By provider</span>
          </div>
          {stats.by_provider.length === 0 ? (
            <p className="muted">No requests yet.</p>
          ) : (
            <div className="stack">
              {stats.by_provider.slice(0, 6).map((row) => (
                <div key={row.provider} className="row-between">
                  <span>{row.provider}</span>
                  <span className="muted">
                    {formatNumber(row.requests)} · {formatCost(row.cost)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="section">
        <div className="section-head">
          <span className="section-title">Recent requests</span>
          <Link to="/requests" className="nav-link" style={{ padding: "4px 8px" }}>
            View all <ArrowRight size={14} />
          </Link>
        </div>
        {stats.recent.length === 0 ? (
          <EmptyState title="No requests yet" description="Send a request to /v1/chat/completions to see it here." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Model</th>
                  <th>Routed to</th>
                  <th>Status</th>
                  <th>Tokens</th>
                  <th>Cost</th>
                  <th>Latency</th>
                </tr>
              </thead>
              <tbody>
                {stats.recent.map((row) => (
                  <tr key={row.request_id}>
                    <td>{formatRelative(row.created_at)}</td>
                    <td>{row.requested_model}</td>
                    <td className="muted">
                      {row.resolved_provider ? `${row.resolved_provider} · ${row.resolved_model}` : "—"}
                    </td>
                    <td>
                      <StatusBadge status={row.status} />
                    </td>
                    <td>
                      {formatNumber((row.input_tokens || 0) + (row.output_tokens || 0))}
                    </td>
                    <td>{formatCost(row.cost)}</td>
                    <td>{formatMs(row.duration_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
