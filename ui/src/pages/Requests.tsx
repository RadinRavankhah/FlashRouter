import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import { api } from "../api";
import {
  Button,
  Card,
  EmptyState,
  PageHeader,
  Spinner,
  formatCost,
  formatMs,
  formatNumber,
  formatRelative,
  useToast,
} from "../components";
import type { RequestSummary } from "../types";

export function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "success"
      ? "success"
      : status === "error" || status === "interrupted"
        ? "danger"
        : "muted";
  return <span className={`badge badge-${tone}`}>{status}</span>;
}

const PAGE_SIZE = 50;

export default function Requests() {
  const toast = useToast();
  const navigate = useNavigate();
  const [items, setItems] = useState<RequestSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState("");
  const [model, setModel] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(offset),
    });
    if (status) params.set("status", status);
    if (model) params.set("model", model);
    try {
      const data = await api.get<{ total: number; items: RequestSummary[] }>(
        `/admin/api/requests?${params.toString()}`,
      );
      setItems(data.items);
      setTotal(data.total);
    } catch {
      toast("Failed to load requests", "error");
    } finally {
      setLoading(false);
    }
  }, [offset, status, model, toast]);

  useEffect(() => {
    load();
  }, [load]);

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <PageHeader
        title="Requests"
        subtitle="Every dispatched request, its attempts and fallback history."
        actions={
          <Button onClick={load}>
            <RefreshCw size={15} /> Refresh
          </Button>
        }
      />

      <Card className="section">
        <div className="row">
          <select
            value={status}
            onChange={(event) => {
              setOffset(0);
              setStatus(event.target.value);
            }}
            style={{ width: 170 }}
          >
            <option value="">All statuses</option>
            <option value="success">success</option>
            <option value="error">error</option>
            <option value="interrupted">interrupted</option>
          </select>
          <input
            value={model}
            onChange={(event) => {
              setOffset(0);
              setModel(event.target.value);
            }}
            placeholder="Filter by requested model"
            style={{ maxWidth: 260 }}
          />
          <span className="muted">{formatNumber(total)} total</span>
        </div>
      </Card>

      <div className="section">
        {loading ? (
          <Spinner label="Loading requests…" />
        ) : items.length === 0 ? (
          <EmptyState
            title="No requests"
            description="Requests will appear here once clients start using the gateway."
          />
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Requested</th>
                    <th>Routed to</th>
                    <th>Status</th>
                    <th>Attempts</th>
                    <th>Tokens</th>
                    <th>Cost</th>
                    <th>Latency</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row) => (
                    <tr
                      key={row.request_id}
                      className="clickable"
                      onClick={() => navigate(`/requests/${row.request_id}`)}
                    >
                      <td>{formatRelative(row.created_at)}</td>
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
                      <td>{formatCost(row.cost)}</td>
                      <td>{formatMs(row.duration_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="row-between" style={{ marginTop: 14 }}>
              <span className="muted">
                Page {page} of {pages}
              </span>
              <div className="row">
                <Button
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  disabled={offset === 0}
                >
                  <ChevronLeft size={15} /> Prev
                </Button>
                <Button
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  disabled={offset + PAGE_SIZE >= total}
                >
                  Next <ChevronRight size={15} />
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}
