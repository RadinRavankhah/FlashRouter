import { Fragment, useEffect, useState, type FormEvent } from "react";
import { ArrowDown, ArrowUp, Plus, Save, Trash2, Zap } from "lucide-react";
import { api } from "./api";
import type {
  NewUpstreamInput, Protocol, Route, RouteCandidate, Strategy, Upstream, UpstreamModel,
} from "./types";
import { Badge, Card, Field, Modal, PageHeader, ProgressBar, Skeleton, useAsync } from "./components";

const PROTOCOLS: { value: Protocol; label: string }[] = [
  { value: "openai-chat", label: "OpenAI Chat Completions" },
  { value: "openai-responses", label: "OpenAI Responses" },
  { value: "anthropic-messages", label: "Anthropic Messages" },
];
const protocolLabel = (p: Protocol) => PROTOCOLS.find((x) => x.value === p)?.label ?? p;
const num = (s: string) => (s.trim() === "" ? null : Number(s));

function Avatar({ name }: { name: string }) {
  const hue = [...name].reduce((h, c) => h + c.charCodeAt(0), 0) % 360;
  return (
    <div className="avatar" style={{ background: `linear-gradient(135deg, hsl(${hue} 85% 62%), hsl(${(hue + 50) % 360} 80% 55%))` }}>
      {name.charAt(0).toUpperCase()}
    </div>
  );
}

// ---------- Upstreams ----------

export function UpstreamsPage() {
  const { data, reload } = useAsync(() => api.upstreams(), []);
  const [adding, setAdding] = useState(false);
  return (
    <>
      <PageHeader
        title="Upstreams"
        subtitle="Providers and local endpoints the gateway forwards to, and the models each one exposes"
        actions={<button className="primary" onClick={() => setAdding(true)}><Plus size={16} /> Add upstream</button>}
      />
      {!data ? <Skeleton /> : (
        <div className="grid cards-wide">
          {data.map((u) => <UpstreamCard key={u.id} upstream={u} onChanged={reload} />)}
        </div>
      )}
      {adding && (
        <AddUpstreamModal
          onClose={() => setAdding(false)}
          onCreated={() => { setAdding(false); reload(); }}
        />
      )}
    </>
  );
}

function UpstreamCard({ upstream: u, onChanged }: { upstream: Upstream; onChanged: () => void }) {
  const blank = { id: "", inPerM: "", outPerM: "", contextK: "" };
  const [showAdd, setShowAdd] = useState(false);
  const [draft, setDraft] = useState(blank);
  const [testMsg, setTestMsg] = useState<string | null>(null);
  const enabledCount = u.models.filter((m) => m.enabled).length;

  const test = async () => {
    setTestMsg("Testing…");
    const r = await api.testUpstream(u.id);
    setTestMsg(r.ok ? `Reachable · ${r.latencyMs} ms` : r.message);
  };
  const toggle = async (m: UpstreamModel) => {
    await api.setUpstreamModelEnabled(u.id, m.id, !m.enabled);
    onChanged();
  };
  const remove = async (m: UpstreamModel) => {
    await api.removeUpstreamModel(u.id, m.id);
    onChanged();
  };
  const addModel = async (e: FormEvent) => {
    e.preventDefault();
    if (!draft.id.trim()) return;
    await api.addUpstreamModel(u.id, {
      id: draft.id.trim(),
      inPerM: num(draft.inPerM),
      outPerM: num(draft.outPerM),
      contextK: num(draft.contextK),
    });
    setDraft(blank);
    setShowAdd(false);
    onChanged();
  };

  return (
    <section className="card provider">
      <div className="provider-head">
        <Avatar name={u.name} />
        <div className="provider-meta">
          <div className="between">
            <h3>{u.name}</h3>
            <Badge tone={u.enabled ? "success" : "neutral"}>{u.enabled ? "enabled" : "disabled"}</Badge>
          </div>
          <div className="url" title={u.baseUrl}>{u.baseUrl}</div>
        </div>
      </div>

      <div className="tags">
        <Badge tone="accent">{protocolLabel(u.protocol)}</Badge>
        <span className="tag">timeout {u.timeoutSec}s</span>
        <span className="tag">{u.credentials.length === 0 ? "no credentials" : `${u.credentials.length} credential${u.credentials.length > 1 ? "s" : ""}`}</span>
      </div>

      <div className="section-label">
        <span>Models</span>
        <span>{enabledCount} of {u.models.length} enabled</span>
      </div>

      {u.models.length === 0 ? (
        <div className="empty-soft">No models yet. Add one below.</div>
      ) : (
        <div className="model-list">
          {u.models.map((m) => (
            <div key={m.id} className={`model-row ${m.enabled ? "" : "off"}`}>
              <div className="model-id" title={m.id}>{m.id}</div>
              <div className="price">
                {m.inPerM === null ? "local" : <>${m.inPerM} in · ${m.outPerM} out <span>/M</span></>}
              </div>
              <span className="ctx">{m.contextK ? `${m.contextK}k` : "—"}</span>
              <div className="row-actions">
                <button className={`switch ${m.enabled ? "on" : ""}`} onClick={() => toggle(m)} aria-label={`Toggle ${m.id}`} />
                <button className="icon-btn danger" onClick={() => remove(m)} aria-label={`Remove ${m.id}`}>
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showAdd ? (
        <form className="add-model" onSubmit={addModel}>
          <input className="input" placeholder="model id" value={draft.id} onChange={(e) => setDraft({ ...draft, id: e.target.value })} autoFocus />
          <input className="input" placeholder="$ in / M" inputMode="decimal" value={draft.inPerM} onChange={(e) => setDraft({ ...draft, inPerM: e.target.value })} />
          <input className="input" placeholder="$ out / M" inputMode="decimal" value={draft.outPerM} onChange={(e) => setDraft({ ...draft, outPerM: e.target.value })} />
          <input className="input" placeholder="ctx (k)" inputMode="numeric" value={draft.contextK} onChange={(e) => setDraft({ ...draft, contextK: e.target.value })} />
          <div className="row-actions">
            <button type="button" className="ghost" onClick={() => setShowAdd(false)}>Cancel</button>
            <button className="primary" type="submit" disabled={!draft.id.trim()}>Add</button>
          </div>
        </form>
      ) : (
        <button className="ghost add-btn" onClick={() => setShowAdd(true)}><Plus size={15} /> Add model</button>
      )}

      <div className="card-foot">
        <span className="test-result">{testMsg ?? "Last checked: not yet"}</span>
        <button className="ghost" onClick={test}><Zap size={15} /> Test connection</button>
      </div>
    </section>
  );
}

function AddUpstreamModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState<NewUpstreamInput>({ name: "", baseUrl: "", protocol: "openai-chat", timeoutSec: 120, apiKey: "" });
  const [saving, setSaving] = useState(false);
  const set = <K extends keyof NewUpstreamInput>(key: K, value: NewUpstreamInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));
  const valid = form.name.trim().length > 0 && /^https?:\/\/.+/.test(form.baseUrl);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setSaving(true);
    await api.createUpstream(form);
    onCreated();
  };

  return (
    <Modal
      title="Add upstream"
      subtitle="Point the gateway at a compatible endpoint. Credentials stay on the gateway and are never sent back to the browser."
      onClose={onClose}
    >
      <form onSubmit={submit}>
        <div className="form-grid">
          <Field label="Display name">
            <input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="My OpenRouter" autoFocus />
          </Field>
          <Field label="Protocol">
            <select className="select" value={form.protocol} onChange={(e) => set("protocol", e.target.value as Protocol)}>
              {PROTOCOLS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </Field>
          <Field label="Base URL" hint="Endpoint paths are appended exactly as configured." className="wide">
            <input className="input mono" value={form.baseUrl} onChange={(e) => set("baseUrl", e.target.value)} placeholder="https://openrouter.ai/api/v1" />
          </Field>
          <Field label="Timeout (seconds)">
            <input className="input" type="number" min={5} value={form.timeoutSec} onChange={(e) => set("timeoutSec", Number(e.target.value))} />
          </Field>
          <Field label="API key" hint="Leave empty for local endpoints.">
            <input className="input" type="password" autoComplete="off" value={form.apiKey} onChange={(e) => set("apiKey", e.target.value)} />
          </Field>
        </div>
        <div className="modal-foot">
          <button type="button" className="ghost" onClick={onClose}>Cancel</button>
          <button className="primary" type="submit" disabled={!valid || saving}>{saving ? "Adding…" : "Add upstream"}</button>
        </div>
      </form>
    </Modal>
  );
}

// ---------- Models & routes ----------

const HINTS: Record<Strategy, string> = {
  priority: "Tries candidates top to bottom. Falls back only before the first streamed byte.",
  weighted: "Traffic is split by weight across enabled candidates.",
  "round-robin": "Rotates evenly across enabled candidates.",
};

export function RoutesPage() {
  const { data, reload } = useAsync(
    async () => ({ routes: await api.routes(), upstreams: await api.upstreams() }),
    []
  );
  const [drafts, setDrafts] = useState<Route[]>([]);
  if (!data) return (<><PageHeader title="Models & routes" subtitle="Loading…" /><Skeleton /></>);

  const newAlias = () =>
    setDrafts((d) => [{ id: `new_${Date.now()}`, alias: "new-alias", strategy: "priority", candidates: [] }, ...d]);

  return (
    <>
      <PageHeader
        title="Models & routes"
        subtitle="Aliases resolve to ordered candidates. Reorder, weight, and toggle them here."
        actions={<button className="primary" onClick={newAlias}><Plus size={16} /> New alias</button>}
      />
      <div className="grid routes">
        {[...drafts, ...data.routes].map((r) => (
          <RouteCard
            key={r.id}
            route={r}
            upstreams={data.upstreams}
            onSaved={() => {
              setDrafts((d) => d.filter((x) => x.id !== r.id));
              reload();
            }}
          />
        ))}
      </div>
    </>
  );
}

function RouteCard({ route, upstreams, onSaved }: { route: Route; upstreams: Upstream[]; onSaved: () => void }) {
  const [draft, setDraft] = useState<Route>(route);
  const [pick, setPick] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => setDraft(route), [route]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(route);
  const upstreamName = (id: string) => upstreams.find((u) => u.id === id)?.name ?? id;
  const enabled = draft.candidates.filter((c) => c.enabled);
  const totalWeight = enabled.reduce((s, c) => s + c.weight, 0) || 1;

  const update = (candidates: RouteCandidate[]) => setDraft((d) => ({ ...d, candidates }));
  const patch = (i: number, p: Partial<RouteCandidate>) =>
    update(draft.candidates.map((c, k) => (k === i ? { ...c, ...p } : c)));
  const move = (i: number, dir: -1 | 1) => {
    const c = [...draft.candidates];
    const j = i + dir;
    if (j < 0 || j >= c.length) return;
    [c[i], c[j]] = [c[j], c[i]];
    update(c);
  };
  const remove = (i: number) => update(draft.candidates.filter((_, k) => k !== i));
  const add = () => {
    const [upstreamId, model] = pick.split("|");
    if (!upstreamId || !model) return;
    update([...draft.candidates, { id: `c_${Date.now()}`, upstreamId, model, weight: 1, enabled: true }]);
    setPick("");
  };
  const save = async () => {
    setSaving(true);
    await api.saveRoute(draft);
    setSaving(false);
    onSaved();
  };

  const shareOf = (c: RouteCandidate, i: number) => {
    if (!c.enabled) return null;
    if (draft.strategy === "weighted") return c.weight / totalWeight;
    if (draft.strategy === "round-robin") return 1 / Math.max(enabled.length, 1);
    return null;
  };

  return (
    <section className="card route-card">
      <div className="route-top">
        <input
          className="alias-input"
          value={draft.alias}
          onChange={(e) => setDraft({ ...draft, alias: e.target.value })}
          aria-label="Alias"
        />
        <div className="segmented small">
          {(["priority", "weighted", "round-robin"] as Strategy[]).map((s) => (
            <button key={s} className={draft.strategy === s ? "active" : ""} onClick={() => setDraft({ ...draft, strategy: s })}>
              {s}
            </button>
          ))}
        </div>
      </div>
      <div className="route-hint">{HINTS[draft.strategy]}</div>

      {draft.candidates.length === 0 && <div className="empty-soft">No candidates yet. Add a model below.</div>}

      <ol className="candidates">
        {draft.candidates.map((c, i) => {
          const share = shareOf(c, i);
          const isPrimary = enabled[0]?.id === c.id;
          return (
            <Fragment key={c.id}>
              {i > 0 && (
                <li className="then" aria-hidden>
                  <ArrowDown size={12} /> falls back to
                </li>
              )}
              <li className={`candidate-row ${c.enabled ? "" : "off"}`}>
                <span className={`rank ${isPrimary || draft.strategy !== "priority" ? "" : "fallback"}`}>{i + 1}</span>
                <div className="cand-meta">
                  <div className="mono small model-id" title={c.model}>{c.model}</div>
                  <div className="muted small">{upstreamName(c.upstreamId)}</div>
                </div>
                {draft.strategy === "weighted" ? (
                  <div className="weight">
                    <ProgressBar value={(share ?? 0) * 100} max={100} />
                    <span className="small num">{Math.round((share ?? 0) * 100)}%</span>
                    <input
                      className="input weight-input"
                      type="number"
                      min={0}
                      value={c.weight}
                      onChange={(e) => patch(i, { weight: Number(e.target.value) })}
                      aria-label="Weight"
                    />
                  </div>
                ) : (
                  <Badge tone={isPrimary && c.enabled ? "accent" : "neutral"}>
                    {!c.enabled ? "disabled" : draft.strategy === "round-robin" ? `${Math.round((share ?? 0) * 100)}%` : isPrimary ? "primary" : `fallback ${i}`}
                  </Badge>
                )}
                <div className="row-actions">
                  <button className={`switch ${c.enabled ? "on" : ""}`} onClick={() => patch(i, { enabled: !c.enabled })} aria-label="Enable candidate" />
                  <button className="icon-btn" onClick={() => move(i, -1)} disabled={i === 0} aria-label="Move up"><ArrowUp size={15} /></button>
                  <button className="icon-btn" onClick={() => move(i, 1)} disabled={i === draft.candidates.length - 1} aria-label="Move down"><ArrowDown size={15} /></button>
                  <button className="icon-btn danger" onClick={() => remove(i)} aria-label="Remove candidate"><Trash2 size={15} /></button>
                </div>
              </li>
            </Fragment>
          );
        })}
      </ol>

      <div className="add-candidate">
        <select className="select" value={pick} onChange={(e) => setPick(e.target.value)}>
          <option value="">Add a model…</option>
          {upstreams
            .filter((u) => u.models.some((m) => m.enabled))
            .map((u) => (
              <optgroup key={u.id} label={u.name}>
                {u.models.filter((m) => m.enabled).map((m) => (
                  <option key={m.id} value={`${u.id}|${m.id}`}>{m.id}</option>
                ))}
              </optgroup>
            ))}
        </select>
        <button className="ghost" onClick={add} disabled={!pick}><Plus size={15} /> Add</button>
      </div>

      {dirty && (
        <div className="savebar">
          <span className="muted small">Unsaved changes</span>
          <div className="row-actions">
            <button className="ghost" onClick={() => setDraft(route)}>Discard</button>
            <button className="primary" onClick={save} disabled={saving}><Save size={15} /> {saving ? "Saving…" : "Save route"}</button>
          </div>
        </div>
      )}
    </section>
  );
}
