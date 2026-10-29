import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api } from "../api";
import {
  Badge,
  Card,
  CopyButton,
  EmptyState,
  PageHeader,
  Spinner,
  formatCost,
  formatDateTime,
  formatMs,
  formatNumber,
  useToast,
} from "../components";
import type { RequestDetail as RequestDetailType } from "../types";

function pretty(body: string): string {
  try {
    return JSON.stringify(JSON.parse(body), null, 2);
  } catch {
    return body;
  }
}

function PayloadBlock({ label, body }: { label: string; body: string }) {
  return (
    <div>
      <div className="code-head">
        <span>{label}</span>
        <CopyButton value={body} />
      </div>
      <pre className="code-block payload-block">{pretty(body)}</pre>
    </div>
  );
}

export default function RequestDetail() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const [record, setRecord] = useState<RequestDetailType | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    api
      .get<RequestDetailType>(`/admin/api/requests/${id}`)
      .then(setRecord)
      .catch(() => toast("Failed to load request", "error"))
      .finally(() => setLoading(false));
  }, [id, toast]);

  if (loading) return <Spinner label="Loading request…" />;
  if (!record) return <EmptyState title="Request not found" />;

  const incoming = record.payloads.filter((payload) => payload.kind === "incoming");
  const outgoing = record.payloads.filter((payload) => payload.kind === "outgoing");
  const responses = record.payloads.filter((payload) => payload.kind === "response");

  return (
    <>
      <Link to="/requests" className="nav-link" style={{ padding: "4px 0", width: "fit-content" }}>
        <ArrowLeft size={15} /> Back to requests
      </Link>
      <PageHeader
        title="Request detail"
        subtitle={record.request_id}
        actions={
          <Badge
            tone={
              record.status === "success"
                ? "success"
                : record.status === "error" || record.status === "interrupted"
                  ? "danger"
                  : "muted"
            }
          >
            {record.status}
          </Badge>
        }
      />

      <Card>
        <dl className="kv">
          <dt>Created</dt>
          <dd>{formatDateTime(record.created_at)}</dd>
          <dt>API key</dt>
          <dd>{record.key_name ?? "—"}</dd>
          <dt>Requested model</dt>
          <dd>{record.requested_model}</dd>
          <dt>Resolved</dt>
          <dd>
            {record.resolved_provider ? `${record.resolved_provider} · ${record.resolved_model}` : "—"}
          </dd>
          <dt>HTTP status</dt>
          <dd>{record.http_status ?? "—"}</dd>
          <dt>Attempts</dt>
          <dd>{record.attempts.length}</dd>
          <dt>Tokens</dt>
          <dd>
            {formatNumber(record.input_tokens)} in / {formatNumber(record.output_tokens)} out
          </dd>
          <dt>Cost</dt>
          <dd>{formatCost(record.cost)}</dd>
          <dt>Latency</dt>
          <dd>
            {formatMs(record.duration_ms)}
            {record.ttft_ms ? ` · first byte ${formatMs(record.ttft_ms)}` : ""}
          </dd>
          {record.error_message && (
            <>
              <dt>Error</dt>
              <dd style={{ color: "var(--danger)" }}>{record.error_message}</dd>
            </>
          )}
        </dl>
      </Card>

      <div className="section">
        <div className="section-head">
          <span className="section-title">Attempts</span>
        </div>
        <div className="timeline">
          {record.attempts.map((attempt) => (
            <div
              key={attempt.id}
              className={`timeline-item ${attempt.status === "success" ? "" : "error"}`}
            >
              <div className="row-between">
                <strong>
                  Attempt {attempt.attempt_n} · {attempt.provider_name ?? "—"} / {attempt.model}
                </strong>
                <Badge tone={attempt.status === "success" ? "success" : "danger"}>
                  {attempt.status}
                </Badge>
              </div>
              <div className="muted" style={{ fontSize: 12 }}>
                account {attempt.account_name ?? "—"} · HTTP {attempt.http_status ?? "—"} ·{" "}
                {formatNumber((attempt.input_tokens || 0) + (attempt.output_tokens || 0))} tok ·{" "}
                {formatCost(attempt.cost)}
              </div>
              {attempt.error_message && (
                <div style={{ color: "var(--danger)", fontSize: 12, marginTop: 4 }}>
                  {attempt.error_message}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="section stack">
        {incoming.map((payload) => (
          <PayloadBlock key={payload.id} label="Incoming request" body={payload.body} />
        ))}
        {outgoing.map((payload) => (
          <PayloadBlock
            key={payload.id}
            label={`Outgoing request (attempt ${payload.attempt_n ?? 1})`}
            body={payload.body}
          />
        ))}
        {responses.map((payload) => (
          <PayloadBlock
            key={payload.id}
            label={`Response (attempt ${payload.attempt_n ?? 1})`}
            body={payload.body}
          />
        ))}
      </div>
    </>
  );
}
