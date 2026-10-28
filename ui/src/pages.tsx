import { useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import type { GatewayKey, LogRequest, RequestStatus } from "./types";
import {
  Badge,
  Card,
  PageHeader,
  ProgressBar,
  Skeleton,
  compact,
  fmtTime,
  money,
  useAsync,
  Field,
  Modal,
} from "./components";

// ============================================================================
// Setup page (shown when not configured)
// ============================================================================

export function SetupPage() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    gateway_api_key: "",
    upstream_name: "OpenRouter",
    upstream_base_url: "https://openrouter.ai/api/v1",
    upstream_api_key: "",
    models: [{ id: "cheap", upstream_model: "", owned_by: "" }],
  });

  useEffect(() => {
    api.setupStatus().then((s) => setConfigured(s.configured));
  }, []);

  if (configured === true) return null; // router will redirect
  if (loading) return <Skeleton />;

  const addModel = () =>
    setForm((f) => ({ ...f, models: [...f.models, { id: "", upstream_model: "", owned_by: "" }] }));
  const removeModel = (i: number) =>
    setForm((f) => ({ ...f, models: f.models.filter((_, j) => j !== i) }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await api.setupSave({
        gateway_api_key: form.gateway_api_key || undefined,
        upstream_name: form.upstream_name,
        upstream_base_url: form.upstream_base_url,
        upstream_api_key: form.upstream_api_key || undefined,
        models: form.models,
      });
      window.location.href = "/";
    } catch (err: any) {
      setError(err.message || "Setup failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="setup-page">
      <div className="setup-card">
        <div className="setup-head">
          <div className="logo">G</div>
          <h1>Gateway setup</h1>
          <p>Configure your first upstream provider and model aliases.</p>
        </div>

        {error && <div className="error-banner">{error}</div>}

        <form onSubmit={handleSubmit} className="setup-form">
          <Field label="Gateway API key" hint="Used by clients to reach this gateway (no auth enforced, for attribution only)">
            <input
              className="input"
              type="text"
              value={form.gateway_api_key}
              onChange={(e) => setForm((f) => ({ ...f, gateway_api_key: e.target.value }))}
              placeholder="e.g. gw_live_abc123"
            />
          </Field>

          <Field label="Provider name" hint="e.g. OpenRouter, OpenAI, Local inference">
            <input
              className="input"
              type="text"
              value={form.upstream_name}
              onChange={(e) => setForm((f) => ({ ...f, upstream_name: e.target.value }))}
            />
          </Field>

          <Field label="Upstream base URL" hint="e.g. https://openrouter.ai/api/v1">
            <input
              className="input"
              type="url"
              value={form.upstream_base_url}
              onChange={(e) => setForm((f) => ({ ...f, upstream_base_url: e.target.value }))}
            />
          </Field>

          <Field label="Upstream API key" hint="The provider API key (stored plaintext)">
            <input
              className="input"
              type="text"
              value={form.upstream_api_key}
              onChange={(e) => setForm((f) => ({ ...f, upstream_api_key: e.target.value }))}
            />
          </Field>

          <Field label="Model aliases" hint="Client-facing model names mapped to upstream models">
            {form.models.map((m, i) => (
              <div key={i} className="model-row">
                <input
                  className="input small"
                  type="text"
                  value={m.id}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      models: f.models.map((mm, j) =>
                        j === i ? { ...mm, id: e.target.value } : mm
                      ),
                    }))
                  }
                  placeholder="alias (e.g. cheap)"
                />
                <span className="arrow">→</span>
                <input
                  className="input small"
                  type="text"
                  value={m.upstream_model}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      models: f.models.map((mm, j) =>
                        j === i ? { ...mm, upstream_model: e.target.value } : mm
                      ),
                    }))
                  }
                  placeholder="upstream model (e.g. qwen/qwen3-coder)"
                />
                <button type="button" className="ghost" onClick={() => removeModel(i)}>
                  ✕
                </button>
              </div>
            ))}
            <button type="button" className="ghost" onClick={addModel}>
              + Add model
            </button>
          </Field>

          <div className="form-actions">
            <button
              type="submit"
              className="primary"
              disabled={loading}
            >
              {loading ? "Saving…" : "Initialize gateway"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ============================================================================
// Providers page
// ============================================================================

export function ProvidersPage() {
  const { data, error, reload } = useAsync(() => api.listProviders(), []);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);
  const [form, setForm] = useState<any>({});

  const providers: any[] = data?.providers ?? [];

  const openCreate = () => {
    setForm({
      name: "", base_url: "", protocol: "openai-chat", enabled: true,
    });
    setEditing(null);
    setOpen(true);
  };

  const openEdit = (p: any) => {
    setForm({ ...p, enabled: p.enabled === 1 || p.enabled === true });
    setEditing(p);
    setOpen(true);
  };

  const save = async () => {
    const body: any = {
      name: form.name,
      base_url: form.base_url,
      protocol: form.protocol,
      enabled: form.enabled,
    };
    if (form.headers) body.headers = form.headers;
    if (form.connect_timeout_seconds) body.connect_timeout_seconds = Number(form.connect_timeout_seconds);
    if (form.read_timeout_seconds) body.read_timeout_seconds = Number(form.read_timeout_seconds);
    if (form.verify_tls !== undefined) body.verify_tls = form.verify_tls;
    if (form.trust_env !== undefined) body.trust_env = form.trust_env;
    if (form.follow_redirects !== undefined) body.follow_redirects = form.follow_redirects;

    if (editing) {
      await api.updateProvider(editing.id, body);
    } else {
      await api.createProvider(body);
    }
    setOpen(false);
    reload();
  };

  return (
    <>
      <PageHeader
        title="Providers"
        subtitle="Upstream endpoints (OpenRouter, OpenAI, local inference, …)"
        actions={<button className="primary" onClick={openCreate}>+ Add provider</button>}
      />
      {error && <div className="error-banner">{error}</div>}
      <Card title="Providers">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Base URL</th>
              <th>Protocol</th>
              <th>Enabled</th>
              <th className="num">Actions</th>
            </tr>
          </thead>
          <tbody>
            {providers.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td className="mono small">{p.base_url}</td>
                <td>{p.protocol}</td>
                <td><Badge tone={p.enabled ? "success" : "neutral"}>{p.enabled ? "on" : "off"}</Badge></td>
                <td className="num">
                  <button className="ghost" onClick={() => openEdit(p)}>Edit</button>
                  <button className="ghost danger" onClick={() => api.deleteProvider(p.id).then(reload)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Modal
        title={editing ? "Edit provider" : "Add provider"}
        onClose={() => setOpen(false)}
      >
        <form onSubmit={(e) => { e.preventDefault(); save(); }} className="modal-form">
          <Field label="Name">
            <input className="input" type="text" value={form.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="Base URL" hint="e.g. https://openrouter.ai/api/v1">
            <input className="input" type="url" value={form.base_url ?? ""} onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
          </Field>
          <Field label="Protocol">
            <select className="input" value={form.protocol ?? "openai-chat"} onChange={(e) => setForm({ ...form, protocol: e.target.value })}>
              <option>openai-chat</option>
            </select>
          </Field>
          <Field label="Enabled">
            <label className="field"><input type="checkbox" checked={form.enabled !== false} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /> On</label>
          </Field>
          <div className="form-actions" style={{ marginTop: 16 }}>
            <button type="button" className="ghost" onClick={() => setOpen(false)}>Cancel</button>
            <button type="submit" className="primary">Save</button>
          </div>
        </form>
      </Modal>
    </>
  );
}

// ============================================================================
// Credentials page
// ============================================================================

export function CredentialsPage() {
  const { data, error, reload } = useAsync(() => api.listCredentials(), []);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);
  const [form, setForm] = useState<any>({});

  const credentials: any[] = data?.credentials ?? [];

  const mask = (s: string) => (s.length <= 8 ? "*".repeat(s.length) : `${s.slice(0, 4)}...${s.slice(-4)}`);

  const openCreate = () => {
    setForm({ provider_id: "", name: "", secret: "", enabled: true });
    setEditing(null);
    setOpen(true);
  };

  const openEdit = (c: any) => {
    setForm({ ...c, name: c.name, secret: c.secret, enabled: c.enabled === 1 || c.enabled === true });
    setEditing(c);
    setOpen(true);
  };

  const save = async () => {
    const body: any = {
      provider_id: form.provider_id,
      name: form.name,
      secret: form.secret,
      enabled: form.enabled,
    };
    if (editing) {
      await api.updateCredential(editing.id, body);
    } else {
      await api.createCredential(body);
    }
    setOpen(false);
    reload();
  };

  return (
    <>
      <PageHeader
        title="Provider credentials"
        subtitle="API keys for your upstream providers"
        actions={<button className="primary" onClick={openCreate}>+ Add credential</button>}
      />
      {error && <div className="error-banner">{error}</div>}
      <Card title="Credentials">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Provider</th>
              <th>Secret</th>
              <th>Enabled</th>
              <th className="num">Actions</th>
            </tr>
          </thead>
          <tbody>
            {credentials.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td>{c.provider_id}</td>
                <td>
                  <div className="secret-row">
                    <span className="mono small">{form?.id === c.id ? c.secret : mask(c.secret ?? "")}</span>
                    {form?.id !== c.id && (
                      <button className="ghost reveal-btn" onClick={() => setForm({ ...form, id: c.id, secret: c.secret })}>
                        Reveal
                      </button>
                    )}
                  </div>
                </td>
                <td><Badge tone={c.enabled ? "success" : "neutral"}>{c.enabled ? "on" : "off"}</Badge></td>
                <td className="num">
                  <button className="ghost" onClick={() => openEdit(c)}>Edit</button>
                  <button className="ghost danger" onClick={() => api.deleteCredential(c.id).then(reload)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Modal title={editing ? "Edit credential" : "Add credential"} onClose={() => setOpen(false)}>
        <form onSubmit={(e) => { e.preventDefault(); save(); }} className="modal-form">
          <Field label="Provider ID">
            <input className="input" type="text" value={form.provider_id ?? ""} onChange={(e) => setForm({ ...form, provider_id: e.target.value })} />
          </Field>
          <Field label="Name">
            <input className="input" type="text" value={form.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="API key" hint="Stored plaintext in the local database">
            <input className="input" type="text" value={form.secret ?? ""} onChange={(e) => setForm({ ...form, secret: e.target.value })} />
          </Field>
          <Field label="Enabled">
            <label className="field"><input type="checkbox" checked={form.enabled !== false} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /> On</label>
          </Field>
          <div className="form-actions" style={{ marginTop: 16 }}>
            <button type="button" className="ghost" onClick={() => setOpen(false)}>Cancel</button>
            <button type="submit" className="primary">Save</button>
          </div>
        </form>
      </Modal>
    </>
  );
}

// ============================================================================
// Gateway keys page
// ============================================================================

export function KeysPage() {
  const { data, error, reload } = useAsync(() => api.listKeys(), []);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);
  const [form, setForm] = useState<any>({});

  const keys: GatewayKey[] = data?.keys ?? [];

  const mask = (s: string) => (s.length <= 8 ? "*".repeat(s.length) : `${s.slice(0, 4)}...${s.slice(-4)}`);

  const openCreate = () => {
    setForm({ name: "", secret: "", enabled: true });
    setEditing(null);
    setOpen(true);
  };

  const openEdit = (k: any) => {
    setForm({ ...k, secret: k.secret, enabled: k.enabled === 1 || k.enabled === true });
    setEditing(k);
    setOpen(true);
  };

  const save = async () => {
    const body: any = { name: form.name, secret: form.secret, enabled: form.enabled };
    if (editing) {
      await api.updateKey(editing.id, body);
    } else {
      await api.createKey(body);
    }
    setOpen(false);
    reload();
  };

  return (
    <>
      <PageHeader
        title="Gateway keys"
        subtitle="Client keys used by your tools to reach this gateway"
        actions={<button className="primary" onClick={openCreate}>+ Add key</button>}
      />
      {error && <div className="error-banner">{error}</div>}
      <Card title="Gateway keys">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Secret</th>
              <th>Enabled</th>
              <th className="num">Actions</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id}>
                <td>{k.name}</td>
                <td>
                  <div className="secret-row">
                    <span className="mono small">{form?.id === k.id ? k.secret : mask(k.secret)}</span>
                    {form?.id !== k.id && (
                      <button className="ghost reveal-btn" onClick={() => setForm({ ...form, id: k.id, secret: k.secret })}>
                        Reveal
                      </button>
                    )}
                  </div>
                </td>
                <td><Badge tone={k.enabled ? "success" : "neutral"}>{k.enabled ? "on" : "off"}</Badge></td>
                <td className="num">
                  <button className="ghost" onClick={() => openEdit(k)}>Edit</button>
                  <button className="ghost danger" onClick={() => api.deleteKey(k.id).then(reload)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Modal title={editing ? "Edit key" : "Add key"} onClose={() => setOpen(false)}>
        <form onSubmit={(e) => { e.preventDefault(); save(); }} className="modal-form">
          <Field label="Name">
            <input className="input" type="text" value={form.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="Secret key">
            <input className="input" type="text" value={form.secret ?? ""} onChange={(e) => setForm({ ...form, secret: e.target.value })} />
          </Field>
          <Field label="Enabled">
            <label className="field"><input type="checkbox" checked={form.enabled !== false} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /> On</label>
          </Field>
          <div className="form-actions" style={{ marginTop: 16 }}>
            <button type="button" className="ghost" onClick={() => setOpen(false)}>Cancel</button>
            <button type="submit" className="primary">Save</button>
          </div>
        </form>
      </Modal>
    </>
  );
}

// ============================================================================
// Models & aliases page
// ============================================================================

export function RoutesPage() {
  const { data: modelsData, reload: reloadModels } = useAsync(() => api.listModels(), []);
  const { data: aliasesData, reload: reloadAliases } = useAsync(() => api.listAliases(), []);

  const models: any[] = modelsData?.models ?? [];
  const aliases: any[] = aliasesData?.aliases ?? [];

  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"model" | "alias">("model");
  const [editing, setEditing] = useState<any | null>(null);
  const [form, setForm] = useState<any>({});

  const openCreateModel = () => {
    setMode("model");
    setForm({ provider_id: "", credential_id: "", upstream_model: "", enabled: true });
    setEditing(null);
    setOpen(true);
  };

  const openCreateAlias = () => {
    setMode("alias");
    setForm({ alias: "", db_model_id: "", enabled: true });
    setEditing(null);
    setOpen(true);
  };

  const save = async () => {
    if (mode === "model") {
      const body = {
        provider_id: form.provider_id,
        credential_id: form.credential_id || undefined,
        upstream_model: form.upstream_model,
        enabled: form.enabled,
      };
      if (editing) await api.updateModel(editing.id, body);
      else await api.createModel(body);
    } else {
      const body = { alias: form.alias, db_model_id: form.db_model_id, enabled: form.enabled };
      if (editing) await api.updateAlias(editing.id, body);
      else await api.createAlias(body);
    }
    setOpen(false);
    reloadModels();
    reloadAliases();
  };

  return (
    <>
      <PageHeader
        title="Models & aliases"
        subtitle="Upstream models and client-facing aliases (e.g. cheap → qwen/qwen3-coder)"
        actions={
          <>
            <button className="ghost" onClick={openCreateModel}>+ Model</button>
            <button className="primary" onClick={openCreateAlias}>+ Alias</button>
          </>
        }
      />
      <div className="grid two">
        <Card title="Models">
          <table className="table">
            <thead>
              <tr>
                <th>Upstream model</th>
                <th>Provider</th>
                <th>Credential</th>
                <th>Enabled</th>
              </tr>
            </thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.id}>
                  <td>{m.upstream_model}</td>
                  <td>{m.provider_id}</td>
                  <td>{m.credential_id ?? "—"}</td>
                  <td><Badge tone={m.enabled ? "success" : "neutral"}>{m.enabled ? "on" : "off"}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title="Aliases">
          <table className="table">
            <thead>
              <tr>
                <th>Alias</th>
                <th>Maps to</th>
                <th>Enabled</th>
              </tr>
            </thead>
            <tbody>
              {aliases.map((a) => {
                const model = models.find((m) => m.id === a.db_model_id);
                return (
                  <tr key={a.id}>
                    <td>{a.alias}</td>
                    <td>{model?.upstream_model ?? a.db_model_id}</td>
                    <td><Badge tone={a.enabled ? "success" : "neutral"}>{a.enabled ? "on" : "off"}</Badge></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      </div>

      <Modal title={mode === "model" ? (editing ? "Edit model" : "Add model") : (editing ? "Edit alias" : "Add alias")} onClose={() => setOpen(false)}>
        <form onSubmit={(e) => { e.preventDefault(); save(); }} className="modal-form">
          {mode === "model" ? (
            <>
              <Field label="Provider ID">
                <input className="input" type="text" value={form.provider_id ?? ""} onChange={(e) => setForm({ ...form, provider_id: e.target.value })} />
              </Field>
              <Field label="Credential ID (optional)">
                <input className="input" type="text" value={form.credential_id ?? ""} onChange={(e) => setForm({ ...form, credential_id: e.target.value })} />
              </Field>
              <Field label="Upstream model">
                <input className="input" type="text" value={form.upstream_model ?? ""} onChange={(e) => setForm({ ...form, upstream_model: e.target.value })} />
              </Field>
            </>
          ) : (
            <>
              <Field label="Alias (client-facing name)">
                <input className="input" type="text" value={form.alias ?? ""} onChange={(e) => setForm({ ...form, alias: e.target.value })} />
              </Field>
              <Field label="Model ID">
                <select className="input" value={form.db_model_id ?? ""} onChange={(e) => setForm({ ...form, db_model_id: e.target.value })}>
                  <option value="">— select model —</option>
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.upstream_model}
                    </option>
                  ))}
                </select>
              </Field>
            </>
          )}
          <Field label="Enabled">
            <label className="field"><input type="checkbox" checked={form.enabled !== false} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /> On</label>
          </Field>
          <div className="form-actions" style={{ marginTop: 16 }}>
            <button type="button" className="ghost" onClick={() => setOpen(false)}>Cancel</button>
            <button type="submit" className="primary">Save</button>
          </div>
        </form>
      </Modal>
    </>
  );
}

// ============================================================================
// Requests page (updated to use real API)
// ============================================================================

const StatusBadge = ({ status }: { status: RequestStatus }) => {
  const tone = status === "success" ? "success" : status === "error" ? "danger" : "warning";
  return <Badge tone={tone}>{status}</Badge>;
};

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
              <td className="num">{compact(r.inputTokens ?? 0)} / {compact(r.outputTokens ?? 0)}</td>
              <td className="num"><CostCell r={r} /></td>
              <td className="num">{(r.durationMs / 1000).toFixed(1)}s</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const DETAIL_TABS = ["summary", "attempts", "request", "response"] as const;
type DetailTab = (typeof DETAIL_TABS)[number];

function RequestDetail({ req, onClose }: { req: LogRequest; onClose: () => void }) {
  const [tab, setTab] = useState<DetailTab>("summary");

  return (
    <Card className="detail" title={<span className="mono small">{req.id}</span>} action={<button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>}>
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
          <dt>Input tokens</dt><dd>{req.inputTokens?.toLocaleString() ?? "—"}</dd>
          <dt>Output tokens</dt><dd>{req.outputTokens?.toLocaleString() ?? "—"}</dd>
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
                  <span>{a.upstream}</span>
                  <Badge tone={a.httpStatus !== null && a.httpStatus < 400 ? "success" : "danger"}>{a.httpStatus ?? "no response"}</Badge>
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

export function RequestsPage() {
  const { data, reload } = useAsync(() => api.requests(), []);
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
      <PageHeader title="Requests" subtitle="Every logical request, with its upstream attempts" />
      <div className="toolbar">
        <input className="search" placeholder="Search model, key, error, or prompt text…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <div className="segmented">
          {(["all", "success", "error", "interrupted"] as const).map((s) => (
            <button key={s} className={status === s ? "active" : ""} onClick={() => setStatus(s)}>{s}</button>
          ))}
        </div>
        <button className="ghost" onClick={reload}>↻</button>
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

// ============================================================================
// Settings page
// ============================================================================

export function SettingsPage() {
  const { data } = useAsync(() => api.settings(), []);

  if (!data) return <><PageHeader title="Settings" subtitle="Loading…" /><Skeleton /></>;

  const used = data.diskTotalGb - data.diskFreeGb;

  return (
    <>
      <PageHeader title="Settings" subtitle="Storage, security, and logging" />
      <div className="grid two">
        <Card title="Storage">
          <Field label="Data directory"><code className="mono small">{data.dataDir}</code></Field>
          <Field label="Database"><span>{data.dbSizeMb.toFixed(1)} MB</span></Field>
          <Field label="Request bodies"><span>{data.bodySizeMb.toFixed(1)} MB</span></Field>
          <Field label="Disk">
            <div className="disk">
              <ProgressBar value={used} max={data.diskTotalGb} tone={data.diskFreeGb < 20 ? "danger" : undefined} />
              <span className="small muted">{data.diskFreeGb.toFixed(1)} GB free</span>
            </div>
          </Field>
        </Card>
        <Card title="Logging">
          <Field label="Write path"><Badge tone={data.loggingHealthy ? "success" : "danger"}>{data.loggingHealthy ? "healthy" : "failing"}</Badge></Field>
          <Field label="Last backup"><span className="small">{fmtTime(data.lastBackup)}</span></Field>
          <Field label="Retention"><span className="small">Forever</span></Field>
        </Card>
      </div>
    </>
  );
}
