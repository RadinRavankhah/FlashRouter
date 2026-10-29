import { useCallback, useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2, Waypoints } from "lucide-react";
import { api, ApiError } from "../api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Modal,
  PageHeader,
  Spinner,
  Toggle,
  useToast,
} from "../components";
import type { Combo, ComboTarget, ModelEntry, Provider } from "../types";

function ComboModal({
  combo,
  providers,
  models,
  onClose,
  onSaved,
}: {
  combo?: Combo;
  providers: Provider[];
  models: ModelEntry[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = Boolean(combo);
  const toast = useToast();
  const [name, setName] = useState(combo?.name ?? "");
  const [description, setDescription] = useState(combo?.description ?? "");
  const [enabled, setEnabled] = useState(combo?.enabled ?? true);
  const [targets, setTargets] = useState<ComboTarget[]>(
    combo?.targets?.map((target) => ({ ...target })) ?? [],
  );
  const [saving, setSaving] = useState(false);

  const update = (index: number, patch: Partial<ComboTarget>) => {
    setTargets((prev) => prev.map((target, i) => (i === index ? { ...target, ...patch } : target)));
  };

  const move = (index: number, direction: -1 | 1) => {
    setTargets((prev) => {
      const next = [...prev];
      const swap = index + direction;
      if (swap < 0 || swap >= next.length) return prev;
      [next[index], next[swap]] = [next[swap], next[index]];
      return next;
    });
  };

  const addTarget = () => {
    if (providers.length === 0) {
      toast("Add a provider first", "error");
      return;
    }
    setTargets((prev) => [...prev, { provider_id: providers[0].id, model: "", enabled: true }]);
  };

  const save = async () => {
    if (!name.trim()) {
      toast("Combo name is required", "error");
      return;
    }
    if (targets.some((target) => !target.model.trim())) {
      toast("Every target needs a model", "error");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: name.trim(),
        description,
        enabled,
        targets: targets.map((target) => ({
          provider_id: target.provider_id,
          model: target.model.trim(),
          enabled: target.enabled,
        })),
      };
      if (editing && combo) {
        await api.put(`/admin/api/combos/${combo.id}`, payload);
      } else {
        await api.post("/admin/api/combos", payload);
      }
      toast(editing ? "Combo updated" : "Combo created");
      onSaved();
      onClose();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Failed to save combo", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={editing ? "Edit combo" : "Create combo"}
      onClose={onClose}
      wide
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save combo"}
          </Button>
        </>
      }
    >
      <Field label="Name" hint="Clients send this as the model name, e.g. coding-fast">
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="coding-fast" />
      </Field>
      <Field label="Description">
        <input
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Subscription → cheap → free fallback"
        />
      </Field>
      <Field label="Enabled">
        <Toggle checked={enabled} onChange={setEnabled} label={enabled ? "On" : "Off"} />
      </Field>

      <div className="section-head">
        <span className="section-title">Fallback order</span>
        <Button variant="ghost" onClick={addTarget}>
          <Plus size={14} /> Add target
        </Button>
      </div>

      {targets.length === 0 ? (
        <p className="muted">Add at least one target. Requests try them top to bottom.</p>
      ) : (
        <div className="stack">
          {targets.map((target, index) => {
            const providerModels = models.filter((m) => m.provider_id === target.provider_id);
            const listId = `models-${index}`;
            return (
              <div className="combo-target" key={index}>
                <span className="order-index">{index + 1}</span>
                <select
                  value={target.provider_id}
                  onChange={(event) => update(index, { provider_id: Number(event.target.value) })}
                >
                  {providers.map((provider) => (
                    <option key={provider.id} value={provider.id}>
                      {provider.name}
                    </option>
                  ))}
                </select>
                <input
                  list={listId}
                  value={target.model}
                  onChange={(event) => update(index, { model: event.target.value })}
                  placeholder="model id"
                />
                <datalist id={listId}>
                  {providerModels.map((model) => (
                    <option key={model.id} value={model.model} />
                  ))}
                </datalist>
                <div className="row">
                  <button className="icon-btn" onClick={() => move(index, -1)} title="Move up">
                    <ArrowUp size={14} />
                  </button>
                  <button className="icon-btn" onClick={() => move(index, 1)} title="Move down">
                    <ArrowDown size={14} />
                  </button>
                  <button
                    className="icon-btn"
                    onClick={() => setTargets((prev) => prev.filter((_, i) => i !== index))}
                    title="Remove"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Modal>
  );
}

export default function Combos() {
  const toast = useToast();
  const [combos, setCombos] = useState<Combo[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState<{ combo?: Combo } | null>(null);

  const load = useCallback(async () => {
    const [comboList, providerList, modelList] = await Promise.all([
      api.get<Combo[]>("/admin/api/combos"),
      api.get<Provider[]>("/admin/api/providers"),
      api.get<ModelEntry[]>("/admin/api/models"),
    ]);
    setCombos(comboList);
    setProviders(providerList);
    setModels(modelList);
  }, []);

  useEffect(() => {
    load()
      .catch(() => toast("Failed to load combos", "error"))
      .finally(() => setLoading(false));
  }, [load, toast]);

  const refresh = () => load().catch(() => toast("Refresh failed", "error"));

  const toggle = async (combo: Combo, enabled: boolean) => {
    try {
      await api.put(`/admin/api/combos/${combo.id}`, {
        name: combo.name,
        description: combo.description,
        enabled,
        targets: combo.targets.map((target) => ({
          provider_id: target.provider_id,
          model: target.model,
          enabled: target.enabled,
        })),
      });
      refresh();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Update failed", "error");
    }
  };

  const remove = async (combo: Combo) => {
    if (!window.confirm(`Delete combo "${combo.name}"?`)) return;
    try {
      await api.del(`/admin/api/combos/${combo.id}`);
      toast("Combo deleted");
      refresh();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Delete failed", "error");
    }
  };

  if (loading) return <Spinner label="Loading combos…" />;

  return (
    <>
      <PageHeader
        title="Combos"
        subtitle="Ordered fallback chains. When a target fails or is rate-limited, the next one is tried."
        actions={
          <Button variant="primary" onClick={() => setModal({})}>
            <Plus size={16} /> Create combo
          </Button>
        }
      />

      {combos.length === 0 ? (
        <Card>
          <EmptyState
            title="No combos yet"
            description="A combo is a model name clients send that resolves to an ordered list of provider/model targets."
            action={
              <Button variant="primary" onClick={() => setModal({})}>
                <Plus size={16} /> Create combo
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="stack">
          {combos.map((combo) => (
            <Card key={combo.id}>
              <div className="provider-head">
                <div>
                  <div className="provider-title">
                    <Waypoints size={16} />
                    {combo.name}
                    <Badge tone={combo.enabled ? "success" : "muted"}>
                      {combo.enabled ? "enabled" : "disabled"}
                    </Badge>
                  </div>
                  {combo.description && <div className="muted">{combo.description}</div>}
                </div>
                <div className="row">
                  <Toggle checked={combo.enabled} onChange={(value) => toggle(combo, value)} />
                  <Button onClick={() => setModal({ combo })}>Edit</Button>
                  <Button variant="danger" onClick={() => remove(combo)}>
                    <Trash2 size={14} />
                  </Button>
                </div>
              </div>

              {combo.targets.length === 0 ? (
                <p className="muted">No targets configured.</p>
              ) : (
                <div className="stack">
                  {combo.targets.map((target, index) => (
                    <div key={target.id ?? index} className="account-row">
                      <div className="account-main">
                        <span className="account-name">
                          {index + 1}. {target.provider_name} · {target.model}
                        </span>
                        <span className="account-meta">provider #{target.provider_id}</span>
                      </div>
                      {index === 0 && <Badge tone="accent">primary</Badge>}
                      {!target.enabled && <Badge tone="muted">disabled</Badge>}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {modal && (
        <ComboModal
          combo={modal.combo}
          providers={providers}
          models={models}
          onClose={() => setModal(null)}
          onSaved={refresh}
        />
      )}
    </>
  );
}
