import { Fragment, useEffect, useState } from "react";
import { ArrowRight, Check, Copy, Eye, EyeOff, Plus, X } from "lucide-react";
import { api } from "./api";
import type { GatewayKey, LogRequest, RequestStatus } from "./types";
import { Badge, Card, PageHeader, ProgressBar, Skeleton, compact, fmtTime, money, useAsync } from "./components";

// ---------- shared pieces ----------

function StatusBadge({ status }: { status: RequestStatus }) {
  const tone = status === "success" ? "success" : status === "error" ? "danger" : "warning";
  return <Badge tone={tone}>{status}</Badge>;
}

function CostCell({ r }: { r: LogRequest }) {
  if (r.costState === "unpriced") return <Badge tone="neutral">local</Badge>;
  return (
    <>
      {money(r.cost)} <span className="muted small">{r.costState}</span>
    </>
  );
}

export function RequestTable({ rows, selectedId, onSelect }: { rows: LogRequest[]; selectedId?: string | null; onSelect?: (id: string) => void }) {
  if (rows.length === 0) return <div className="empty">No requests match these filters.</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Client key</th>
            <th>Model</th>
            <th>Status</th>
            <th className="num">Tokens in / out</th>
            <th className="num">Cost</th>
            <th className="num">Duration</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className={selectedId === r.id ? "selected" : ""} onClick={() => onSelect?.(r.id)}>
              <td className="muted">{fmtTime(r.time)}</td>
              <td>{r.clientKey}</td>
              <td>
                <div className="model">{r.model}</div>
                <div className="muted small">{r.alias}</div>
              </td>
              <td><StatusBadge status={r.status} /></td>
              <td className="num">{compact(r.inputTokens)} / {compact(r.outputTokens)}</td>
              <td className="num"><CostCell r={r} /></td>
              <td className="num">{(r.durationMs / 1000).toFixed(1)}s</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------- Requests ----------

const DETAIL_TABS = ["summary", "attempts", "request", "response"] as const;
type DetailTab = (typeof DETAIL_TABS)[number];

export function RequestsPage() {
  const { data } = useAsync(() => api.requests(), []);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"all" | RequestStatus>("all");
  const [selected, setSelected] = useState<string | null>(null);

  const rows = (data ?? []).filter(
    (r) =>
      (status === "all" || r.status === status) &&
      (!query || JSON.stringify(r).toLowerCase().includes(query.toLowerCase()))
  );
  const detail = data?.find((r) => r.id === selected) ?? null;

  return (
    <>
      <PageHeader
        title="Requests"
        subtitle="Every logical request, with its upstream attempts"
        actions={<button className="ghost">Export CSV</button>}
      />
      <div className="toolbar">
        <input
          className="search"
          placeholder="Search model, key, error, or prompt text…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="segmented">
          {(["all", "success", "error", "interrupted"] as const).map((s) => (
            <button key={s} className={status === s ? "active" : ""} onClick={() => setStatus(s)}>{s}</button>
          ))}
        </div>
      </div>
      <div className={`split ${detail ? "has-detail" : ""}`}>
        <Card className="table-card">
          {!data ? <Skeleton /> : <RequestTable rows={rows} selectedId={selected} onSelect={setSelected} />}
        </Card>
        {detail && <RequestDetail req={detail} onClose={() => setSelected(null)} />}
      </div>
    </>
  );
}

function RequestDetail({ req, onClose }: { req: LogRequest; onClose: () => void }) {
  const [tab, setTab] = useState<DetailTab>("summary");
  return (
    <Card
      className="detail"
      title={<span className="mono small">{req.id}</span>}
      action={<button className="icon-btn" onClick={onClose} aria-label="Close"><X size={16} /></button>}
    >
      <div className="segmented small">
        {DETAIL_TABS.map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      {tab === "summary" && (
        <dl className="kv">
          <dt>Status</dt><dd><StatusBadge status={req.status} /></dd>
          <dt>Client key</dt><dd>{req.clientKey}</dd>
          <dt>Alias → model</dt><dd className="mono small">{req.alias} → {req.model}</dd>
          <dt>Protocol</dt><dd className="mono small">{req.protocol}</dd>
          <dt>Input tokens</dt><dd>{req.inputTokens.toLocaleString()}</dd>
          <dt>Cached input</dt><dd>{req.cachedTokens === null ? "unknown" : req.cachedTokens.toLocaleString()}</dd>
          <dt>Output tokens</dt><dd>{req.outputTokens.toLocaleString()}</dd>
          <dt>Time to first token</dt><dd>{req.ttftMs ? `${req.ttftMs} ms` : "—"}</dd>
          <dt>Total duration</dt><dd>{(req.durationMs / 1000).toFixed(2)} s</dd>
          <dt>Cost</dt><dd><CostCell r={req} /></dd>
        </dl>
      )}

      {tab === "attempts" && (
        <ol className="timeline">
          {req.attempts.map((a) => (
            <li key={a.n}>
              <span className="n">{a.n}</span>
              <div style={{ flex: 1 }}>
                <div className="between">
                  <span>{a.upstream} · {a.credential}</span>
                  <Badge tone={a.httpStatus !== null && a.httpStatus < 400 ? "success" : "danger"}>
                    {a.httpStatus ?? "no response"}
                  </Badge>
                </div>
                <div className="muted small">{a.model} · {a.durationMs} ms</div>
                {a.error && <div className="small danger-text">{a.error}</div>}
              </div>
            </li>
          ))}
        </ol>
      )}

      {tab === "request" && <pre className="json">{JSON.stringify(req.requestBody, null, 2)}</pre>}
      {tab === "response" && <pre className="json">{JSON.stringify(req.responseBody, null, 2)}</pre>}
    </Card>
  );
}

// ---------- Gateway keys ----------

export function KeysPage() {
  const [keys, setKeys] = useState<GatewayKey[] | null>(null);
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [copiedId, setCopiedId] = useState<string | null>(null);

  useEffect(() => {
    api.keys().then(setKeys);
  }, []);

  const copy = async (k: GatewayKey) => {
    await navigator.clipboard?.writeText(k.secret);
    setCopiedId(k.id);
    setTimeout(() => setCopiedId(null), 1400);
  };

  const addKey = () =>
    setKeys((ks) => [
      {
        id: `key_${Date.now()}`,
        name: "New gateway key",
        secret: `gw_live_${Math.random().toString(36).slice(2, 18)}`,
        enabled: true,
        models: ["coding-fast"],
        monthlyBudget: 20,
        spentMonth: 0,
        lastUsed: null,
      },
      ...(ks ?? []),
    ]);

  return (
    <>
      <PageHeader
        title="Gateway keys"
        subtitle="Credentials your tools use to reach the gateway"
        actions={<button className="primary" onClick={addKey}><Plus size={16} /> New key</button>}
      />
      {!keys ? <Skeleton /> : (
        <div className="grid cards">
          {keys.map((k) => {
            const shown = !!revealed[k.id];
            return (
              <Card
                key={k.id}
                title={k.name}
                action={<Badge tone={k.enabled ? "success" : "neutral"}>{k.enabled ? "active" : "disabled"}</Badge>}
              >
                <div className="secret">
                  <code className="mono">{shown ? k.secret : `gw_live_••••••••${k.secret.slice(-4)}`}</code>
                  <button className="icon-btn" title={shown ? "Hide" : "Reveal"} onClick={() => setRevealed((r) => ({ ...r, [k.id]: !shown }))}>
                    {shown ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                  <button className="icon-btn" title="Copy" onClick={() => copy(k)}>
                    {copiedId === k.id ? <Check size={16} /> : <Copy size={16} />}
                  </button>
                </div>
                <div className="chips" style={{ marginTop: 14 }}>
                  {k.models.map((m) => <span className="chip" key={m}>{m}</span>)}
                </div>
                <div style={{ marginTop: 16 }}>
                  <div className="between small">
                    <span className="muted">Monthly spend</span>
                    <span>{money(k.spentMonth)} / {k.monthlyBudget === null ? "no limit" : money(k.monthlyBudget)}</span>
                  </div>
                  {k.monthlyBudget !== null && (
                    <div style={{ marginTop: 8 }}>
                      <ProgressBar
                        value={k.spentMonth}
                        max={k.monthlyBudget}
                        tone={k.spentMonth / k.monthlyBudget > 0.8 ? "warning" : undefined}
                      />
                    </div>
                  )}
                </div>
                <div className="small muted" style={{ marginTop: 14 }}>
                  Last used {k.lastUsed ? fmtTime(k.lastUsed) : "never"}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </>
  );
}

// ---------- Settings ----------

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="row">
      <span className="muted">{label}</span>
      <div>{children}</div>
    </div>
  );
}

import type { ReactNode } from "react";

export function SettingsPage() {
  const { data } = useAsync(() => api.settings(), []);
  if (!data) return (<><PageHeader title="Settings" subtitle="Loading…" /><Skeleton /></>);
  const used = data.diskTotalGb - data.diskFreeGb;

  return (
    <>
      <PageHeader title="Settings" subtitle="Storage, security, and logging" />
      <div className="grid two">
        <Card title="Storage">
          <Row label="Data directory"><code className="mono small">{data.dataDir}</code></Row>
          <Row label="Database"><span>{data.dbSizeMb.toFixed(1)} MB</span></Row>
          <Row label="Request bodies"><span>{data.bodySizeMb.toFixed(1)} MB</span></Row>
          <Row label="Disk">
            <div className="disk">
              <ProgressBar value={used} max={data.diskTotalGb} tone={data.diskFreeGb < 20 ? "danger" : undefined} />
              <span className="small muted">{data.diskFreeGb.toFixed(1)} GB free</span>
            </div>
          </Row>
        </Card>
        <Card title="Security">
          <Row label="Secret storage">
            <Badge tone={data.encryption === "unlocked" ? "success" : data.encryption === "locked" ? "danger" : "warning"}>
              {data.encryption === "off" ? "plaintext" : data.encryption}
            </Badge>
          </Row>
          <Row label="Dashboard bind"><code className="mono small">{data.bindAddress}:{data.port}</code></Row>
          <Row label="Admin session"><Badge tone="success">active</Badge></Row>
        </Card>
        <Card title="Logging">
          <Row label="Write path">
            <Badge tone={data.loggingHealthy ? "success" : "danger"}>{data.loggingHealthy ? "healthy" : "failing"}</Badge>
          </Row>
          <Row label="Last backup"><span className="small">{fmtTime(data.lastBackup)}</span></Row>
          <Row label="Retention"><span className="small">Forever</span></Row>
        </Card>
      </div>
    </>
  );
}
