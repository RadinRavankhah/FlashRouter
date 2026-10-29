import { useCallback, useEffect, useState } from "react";
import { Plus, RefreshCw, Trash2, Zap } from "lucide-react";
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
  formatNumber,
  useToast,
} from "../components";
import type { Account, Preset, Provider } from "../types";

function ProviderModal({
  presets,
  provider,
  onClose,
  onSaved,
}: {
  presets: Preset[];
  provider?: Provider;
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = Boolean(provider);
  const toast = useToast();
  const [presetId, setPresetId] = useState(provider?.preset ?? "openrouter");
  const [name, setName] = useState(provider?.name ?? "");
  const [baseUrl, setBaseUrl] = useState(provider?.base_url ?? "");
  const [priority, setPriority] = useState(provider?.priority ?? 100);
  const [enabled, setEnabled] = useState(provider?.enabled ?? true);
  const [headers, setHeaders] = useState(JSON.stringify(provider?.headers ?? {}, null, 2));
  const [saving, setSaving] = useState(false);

  const changePreset = (id: string) => {
    setPresetId(id);
    const preset = presets.find((item) => item.id === id);
    if (preset) {
      setName(preset.name);
      setBaseUrl(preset.base_url);
    }
  };

  const save = async () => {
    let parsedHeaders: Record<string, string> = {};
    try {
      parsedHeaders = headers.trim() ? JSON.parse(headers) : {};
    } catch {
      toast("Headers must be valid JSON", "error");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: name.trim() || "Provider",
        base_url: baseUrl.trim(),
        preset: presetId,
        protocol: "openai-chat",
        headers: parsedHeaders,
        enabled,
        priority: Number(priority) || 100,
      };
      if (editing && provider) {
        await api.put(`/admin/api/providers/${provider.id}`, payload);
      } else {
        await api.post("/admin/api/providers", payload);
      }
      toast(editing ? "Provider updated" : "Provider added");
      onSaved();
      onClose();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Failed to save provider", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={editing ? "Edit provider" : "Add provider"}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </>
      }
    >
      <Field label="Preset">
        <select value={presetId} onChange={(event) => changePreset(event.target.value)}>
          {presets.map((preset) => (
            <option key={preset.id} value={preset.id}>
              {preset.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Name">
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="My provider" />
      </Field>
      <Field label="Base URL" hint="OpenAI API root, usually ending in /v1">
        <input
          value={baseUrl}
          onChange={(event) => setBaseUrl(event.target.value)}
          placeholder="https://openrouter.ai/api/v1"
        />
      </Field>
      <div className="row">
        <Field label="Priority">
          <input
            type="number"
            value={priority}
            onChange={(event) => setPriority(Number(event.target.value))}
          />
        </Field>
        <Field label="Enabled">
          <div style={{ paddingTop: 8 }}>
            <Toggle checked={enabled} onChange={setEnabled} label={enabled ? "On" : "Off"} />
          </div>
        </Field>
      </div>
      <Field label="Extra headers (JSON)" hint="Optional. Sent to the upstream on every request.">
        <textarea value={headers} onChange={(event) => setHeaders(event.target.value)} />
      </Field>
    </Modal>
  );
}

function AccountModal({
  provider,
  onClose,
  onSaved,
}: {
  provider: Provider;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState("Account 1");
  const [secret, setSecret] = useState("");
  const [weight, setWeight] = useState(1);
  const [priority, setPriority] = useState(100);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await api.post(`/admin/api/providers/${provider.id}/accounts`, {
        name: name.trim() || "Account",
        secret,
        weight: Number(weight) || 1,
        priority: Number(priority) || 100,
      });
      toast("Account added");
      onSaved();
      onClose();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Failed to add account", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`Add account · ${provider.name}`}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Add account"}
          </Button>
        </>
      }
    >
      <Field label="Name">
        <input value={name} onChange={(event) => setName(event.target.value)} />
      </Field>
      <Field label="API key" hint="Leave blank for local endpoints that need no key.">
        <input
          type="password"
          value={secret}
          onChange={(event) => setSecret(event.target.value)}
          placeholder="sk-…"
        />
      </Field>
      <div className="row">
        <Field label="Weight" hint="Higher = more traffic within a priority tier">
          <input
            type="number"
            value={weight}
            onChange={(event) => setWeight(Number(event.target.value))}
          />
        </Field>
        <Field label="Priority">
          <input
            type="number"
            value={priority}
            onChange={(event) => setPriority(Number(event.target.value))}
          />
        </Field>
      </div>
    </Modal>
  );
}

export default function Connections() {
  const toast = useToast();
  const [presets, setPresets] = useState<Preset[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [accounts, setAccounts] = useState<Record<number, Account[]>>({});
  const [loading, setLoading] = useState(true);
  const [providerModal, setProviderModal] = useState<{ provider?: Provider } | null>(null);
  const [accountProvider, setAccountProvider] = useState<Provider | null>(null);

  const load = useCallback(async () => {
    const list = await api.get<Provider[]>("/admin/api/providers");
    setProviders(list);
    const entries = await Promise.all(
      list.map(async (provider) => {
        const rows = await api.get<Account[]>(`/admin/api/providers/${provider.id}/accounts`);
        return [provider.id, rows] as const;
      }),
    );
    setAccounts(Object.fromEntries(entries));
  }, []);

  useEffect(() => {
    Promise.all([api.get<Preset[]>("/admin/api/providers/presets"), load()])
      .then(([presetList]) => setPresets(presetList))
      .catch(() => toast("Failed to load connections", "error"))
      .finally(() => setLoading(false));
  }, [load, toast]);

  const refresh = () => load().catch(() => toast("Refresh failed", "error"));

  const testProvider = async (provider: Provider) => {
    try {
      const result = await api.post<{ ok: boolean; status: number; error?: string; models: string[] }>(
        `/admin/api/providers/${provider.id}/test`,
      );
      if (result.ok) toast(`${provider.name}: ${result.models.length} models reachable`);
      else toast(`${provider.name}: HTTP ${result.status} ${result.error ?? ""}`, "error");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Test failed", "error");
    }
  };

  const discover = async (provider: Provider) => {
    try {
      const result = await api.post<{ ok: boolean; imported?: number; error?: string }>(
        `/admin/api/providers/${provider.id}/discover`,
      );
      if (result.ok) {
        toast(`Imported ${result.imported ?? 0} models from ${provider.name}`);
        refresh();
      } else {
        toast(`Discover failed: ${result.error ?? "unknown error"}`, "error");
      }
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Discover failed", "error");
    }
  };

  const toggleProvider = async (provider: Provider, enabled: boolean) => {
    try {
      await api.put(`/admin/api/providers/${provider.id}`, {
        name: provider.name,
        base_url: provider.base_url,
        preset: provider.preset,
        protocol: provider.protocol,
        headers: provider.headers,
        enabled,
        priority: provider.priority,
      });
      refresh();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Update failed", "error");
    }
  };

  const deleteProvider = async (provider: Provider) => {
    if (!window.confirm(`Delete provider "${provider.name}" and its accounts?`)) return;
    try {
      await api.del(`/admin/api/providers/${provider.id}`);
      toast("Provider deleted");
      refresh();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Delete failed", "error");
    }
  };

  const revealAccount = async (account: Account) => {
    try {
      const result = await api.get<{ secret: string }>(`/admin/api/accounts/${account.id}/reveal`);
      await navigator.clipboard.writeText(result.secret || "");
      toast("Secret copied to clipboard");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Reveal failed", "error");
    }
  };

  const testAccount = async (account: Account) => {
    try {
      const result = await api.post<{ ok: boolean; status: number; models: string[] }>(
        `/admin/api/accounts/${account.id}/test`,
      );
      toast(result.ok ? "Account OK" : `Account failed: HTTP ${result.status}`, result.ok ? "ok" : "error");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Test failed", "error");
    }
  };

  const toggleAccount = async (account: Account, enabled: boolean) => {
    try {
      await api.put(`/admin/api/accounts/${account.id}`, {
        name: account.name,
        weight: account.weight,
        priority: account.priority,
        enabled,
        cooldown_seconds: account.cooldown_seconds,
      });
      refresh();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Update failed", "error");
    }
  };

  const deleteAccount = async (account: Account) => {
    if (!window.confirm(`Delete account "${account.name}"?`)) return;
    try {
      await api.del(`/admin/api/accounts/${account.id}`);
      toast("Account deleted");
      refresh();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Delete failed", "error");
    }
  };

  if (loading) return <Spinner label="Loading connections…" />;

  return (
    <>
      <PageHeader
        title="Connections"
        subtitle="Providers and their API keys. Add multiple accounts for rotation."
        actions={
          <>
            <Button onClick={refresh}>
              <RefreshCw size={15} /> Refresh
            </Button>
            <Button variant="primary" onClick={() => setProviderModal({})}>
              <Plus size={16} /> Add provider
            </Button>
          </>
        }
      />

      {providers.length === 0 ? (
        <Card>
          <EmptyState
            title="No providers yet"
            description="Add an OpenAI-compatible provider to start routing requests."
            action={
              <Button variant="primary" onClick={() => setProviderModal({})}>
                <Plus size={16} /> Add provider
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="stack">
          {providers.map((provider) => {
            const accountList = accounts[provider.id] ?? [];
            return (
              <Card key={provider.id} className="provider-card">
                <div className="provider-head">
                  <div>
                    <div className="provider-title">
                      {provider.name}
                      <Badge tone={provider.enabled ? "success" : "muted"}>
                        {provider.enabled ? "enabled" : "disabled"}
                      </Badge>
                      <Badge tone="accent">priority {provider.priority}</Badge>
                    </div>
                    <div className="provider-url">{provider.base_url}</div>
                  </div>
                  <div className="row">
                    <Toggle
                      checked={provider.enabled}
                      onChange={(value) => toggleProvider(provider, value)}
                    />
                    <Button onClick={() => testProvider(provider)}>
                      <Zap size={14} /> Test
                    </Button>
                    <Button onClick={() => discover(provider)}>
                      <RefreshCw size={14} /> Discover
                    </Button>
                    <Button onClick={() => setProviderModal({ provider })}>Edit</Button>
                    <Button variant="danger" onClick={() => deleteProvider(provider)}>
                      <Trash2 size={14} />
                    </Button>
                  </div>
                </div>

                <div className="row-between">
                  <span className="muted">
                    {accountList.length} account(s) · {provider.model_count} models
                  </span>
                  <Button variant="ghost" onClick={() => setAccountProvider(provider)}>
                    <Plus size={14} /> Add account
                  </Button>
                </div>

                {accountList.length === 0 ? (
                  <p className="muted">No accounts yet. Add an API key to use this provider.</p>
                ) : (
                  <div className="stack">
                    {accountList.map((account) => (
                      <div key={account.id} className="account-row">
                        <div className="account-main">
                          <span className="account-name">
                            {account.name}{" "}
                            {!account.enabled && <Badge tone="muted">off</Badge>}
                            {account.cooling_until && <Badge tone="warn">cooling</Badge>}
                          </span>
                          <span className="account-meta">
                            {account.secret_masked || "no key"} · {formatNumber(account.requests)} req ·{" "}
                            {formatNumber(account.input_tokens + account.output_tokens)} tok
                          </span>
                        </div>
                        <div className="row">
                          <Toggle
                            checked={account.enabled}
                            onChange={(value) => toggleAccount(account, value)}
                          />
                          <Button variant="ghost" onClick={() => revealAccount(account)}>
                            Reveal
                          </Button>
                          <Button variant="ghost" onClick={() => testAccount(account)}>
                            Test
                          </Button>
                          <Button variant="ghost" onClick={() => deleteAccount(account)}>
                            <Trash2 size={14} />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}

      {providerModal && (
        <ProviderModal
          presets={presets}
          provider={providerModal.provider}
          onClose={() => setProviderModal(null)}
          onSaved={refresh}
        />
      )}
      {accountProvider && (
        <AccountModal
          provider={accountProvider}
          onClose={() => setAccountProvider(null)}
          onSaved={refresh}
        />
      )}
    </>
  );
}
