import { useCallback, useEffect, useState } from "react";
import { Coins, Pencil, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "../api";
import {
  Button,
  Card,
  EmptyState,
  Field,
  Modal,
  PageHeader,
  Spinner,
  useToast,
} from "../components";
import type { ModelEntry, Provider } from "../types";

interface ModelForm {
  provider_id: number;
  model: string;
  display_name: string;
  price_in: string;
  price_out: string;
  price_cache_in: string;
}

const EMPTY_FORM: ModelForm = {
  provider_id: 0,
  model: "",
  display_name: "",
  price_in: "0",
  price_out: "0",
  price_cache_in: "",
};

function price(value: number | null): string {
  if (value === null) return "same as input";
  return `$${value.toFixed(value === 0 ? 0 : 4)}`;
}

function numberOrZero(value: string): number {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function optionalNumber(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export default function Models() {
  const toast = useToast();
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<ModelEntry | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<ModelForm>(EMPTY_FORM);

  const load = useCallback(async () => {
    try {
      const [modelList, providerList] = await Promise.all([
        api.get<ModelEntry[]>("/admin/api/models"),
        api.get<Provider[]>("/admin/api/providers"),
      ]);
      setModels(modelList);
      setProviders(providerList);
    } catch {
      toast("Failed to load models", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setForm({ ...EMPTY_FORM, provider_id: providers[0]?.id ?? 0 });
    setCreating(true);
  };

  const openEdit = (model: ModelEntry) => {
    setForm({
      provider_id: model.provider_id,
      model: model.model,
      display_name: model.display_name ?? "",
      price_in: String(model.price_in),
      price_out: String(model.price_out),
      price_cache_in: model.price_cache_in === null ? "" : String(model.price_cache_in),
    });
    setEditing(model);
  };

  const close = () => {
    setEditing(null);
    setCreating(false);
    setForm(EMPTY_FORM);
  };

  const save = async () => {
    if (!editing && (!form.provider_id || !form.model.trim())) {
      toast("Pick a provider and enter a model id", "error");
      return;
    }
    try {
      if (editing) {
        await api.put(`/admin/api/models/${editing.id}`, {
          price_in: numberOrZero(form.price_in),
          price_out: numberOrZero(form.price_out),
          price_cache_in: optionalNumber(form.price_cache_in),
        });
        toast("Pricing updated");
      } else {
        await api.post("/admin/api/models", {
          provider_id: form.provider_id,
          model: form.model.trim(),
          display_name: form.display_name.trim() || null,
          price_in: numberOrZero(form.price_in),
          price_out: numberOrZero(form.price_out),
          price_cache_in: optionalNumber(form.price_cache_in),
        });
        toast("Model added");
      }
      close();
      await load();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Save failed", "error");
    }
  };

  const remove = async (model: ModelEntry) => {
    if (!window.confirm(`Remove ${model.model} from ${model.provider_name}?`)) return;
    try {
      await api.del(`/admin/api/models/${model.id}`);
      toast("Model removed");
      await load();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Delete failed", "error");
    }
  };

  if (loading) return <Spinner label="Loading models…" />;

  const dialogOpen = creating || editing !== null;

  return (
    <>
      <PageHeader
        title="Models"
        subtitle="Per-model pricing drives the estimated cost. Set a cache-read price to reflect provider prompt caching."
        actions={
          <Button variant="primary" onClick={openCreate}>
            <Plus size={14} /> Add model
          </Button>
        }
      />

      <Card>
        {models.length === 0 ? (
          <EmptyState
            title="No models yet"
            description="Add an account and use Discover in Connections, or add a model manually."
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Model</th>
                  <th>Input / 1M</th>
                  <th>Output / 1M</th>
                  <th>Cached / 1M</th>
                  <th>Source</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {models.map((model) => (
                  <tr key={model.id}>
                    <td>{model.provider_name}</td>
                    <td>
                      <span>{model.display_name || model.model}</span>
                      {model.display_name && <span className="muted"> · {model.model}</span>}
                    </td>
                    <td>{price(model.price_in)}</td>
                    <td>{price(model.price_out)}</td>
                    <td className={model.price_cache_in === null ? "muted" : ""}>
                      {price(model.price_cache_in)}
                    </td>
                    <td className="muted">{model.source}</td>
                    <td>
                      <div className="row" style={{ justifyContent: "flex-end" }}>
                        <Button variant="ghost" onClick={() => openEdit(model)} title="Edit pricing">
                          <Pencil size={14} />
                        </Button>
                        <Button variant="ghost" onClick={() => remove(model)} title="Remove model">
                          <Trash2 size={14} />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {dialogOpen && (
        <Modal
          title={editing ? "Edit pricing" : "Add model"}
          onClose={close}
          footer={
            <>
              <Button onClick={close}>Cancel</Button>
              <Button variant="primary" onClick={save}>
                <Coins size={14} /> Save
              </Button>
            </>
          }
        >
          <div className="stack">
            {editing ? (
              <p className="muted">
                {editing.provider_name} · {editing.model}
              </p>
            ) : (
              <>
                <Field label="Provider">
                  <select
                    value={form.provider_id}
                    onChange={(event) =>
                      setForm({ ...form, provider_id: Number(event.target.value) })
                    }
                  >
                    {providers.map((provider) => (
                      <option key={provider.id} value={provider.id}>
                        {provider.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Model id" hint="Exactly what the provider expects upstream.">
                  <input
                    value={form.model}
                    onChange={(event) => setForm({ ...form, model: event.target.value })}
                    placeholder="e.g. gpt-4o-mini"
                  />
                </Field>
                <Field label="Display name (optional)">
                  <input
                    value={form.display_name}
                    onChange={(event) => setForm({ ...form, display_name: event.target.value })}
                  />
                </Field>
              </>
            )}
            <Field label="Input price (USD per 1M tokens)">
              <input
                type="number"
                min="0"
                step="0.0001"
                value={form.price_in}
                onChange={(event) => setForm({ ...form, price_in: event.target.value })}
              />
            </Field>
            <Field label="Output price (USD per 1M tokens)">
              <input
                type="number"
                min="0"
                step="0.0001"
                value={form.price_out}
                onChange={(event) => setForm({ ...form, price_out: event.target.value })}
              />
            </Field>
            <Field
              label="Cache-read price (USD per 1M tokens)"
              hint="Leave blank to bill cached input at the normal input price."
            >
              <input
                type="number"
                min="0"
                step="0.0001"
                value={form.price_cache_in}
                onChange={(event) => setForm({ ...form, price_cache_in: event.target.value })}
                placeholder="same as input"
              />
            </Field>
            <p className="muted" style={{ fontSize: 12 }}>
              Cached tokens are already included in the reported input count; FlashRouter bills the
              cached portion at the cache-read price and the remainder at the input price.
            </p>
          </div>
        </Modal>
      )}
    </>
  );
}
