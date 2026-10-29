import { useCallback, useEffect, useState } from "react";
import { KeyRound, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "../api";
import {
  Badge,
  Button,
  Card,
  CopyButton,
  EmptyState,
  Field,
  Modal,
  PageHeader,
  Spinner,
  Toggle,
  formatRelative,
  useToast,
} from "../components";
import type { ApiKey, Combo } from "../types";

function CreateKeyModal({
  combos,
  onClose,
  onCreated,
}: {
  combos: Combo[];
  onClose: () => void;
  onCreated: (token: string) => void;
}) {
  const toast = useToast();
  const [name, setName] = useState("Claude Code");
  const [allowed, setAllowed] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  const toggleCombo = (comboName: string) => {
    setAllowed((prev) =>
      prev.includes(comboName) ? prev.filter((item) => item !== comboName) : [...prev, comboName],
    );
  };

  const create = async () => {
    setSaving(true);
    try {
      const created = await api.post<{ id: number; name: string; token: string }>(
        "/admin/api/keys",
        { name: name.trim() || "API key", allowed_combos: allowed },
      );
      onCreated(created.token);
      onClose();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Failed to create key", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="Create API key"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={create} disabled={saving}>
            {saving ? "Creating…" : "Create key"}
          </Button>
        </>
      }
    >
      <Field label="Name" hint="For example: Claude Code, Cursor, a script">
        <input value={name} onChange={(event) => setName(event.target.value)} />
      </Field>
      {combos.length > 0 && (
        <Field label="Allowed combos" hint="Leave empty to allow every combo.">
          <div className="stack">
            {combos.map((combo) => (
              <label key={combo.id} className="row" style={{ gap: 8 }}>
                <input
                  type="checkbox"
                  style={{ width: 16, height: 16 }}
                  checked={allowed.includes(combo.name)}
                  onChange={() => toggleCombo(combo.name)}
                />
                {combo.name}
              </label>
            ))}
          </div>
        </Field>
      )}
    </Modal>
  );
}

export default function Keys() {
  const toast = useToast();
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [combos, setCombos] = useState<Combo[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newToken, setNewToken] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [keyList, comboList] = await Promise.all([
      api.get<ApiKey[]>("/admin/api/keys"),
      api.get<Combo[]>("/admin/api/combos"),
    ]);
    setKeys(keyList);
    setCombos(comboList);
  }, []);

  useEffect(() => {
    load()
      .catch(() => toast("Failed to load keys", "error"))
      .finally(() => setLoading(false));
  }, [load, toast]);

  const refresh = () => load().catch(() => toast("Refresh failed", "error"));

  const toggle = async (key: ApiKey, enabled: boolean) => {
    try {
      await api.put(`/admin/api/keys/${key.id}`, {
        name: key.name,
        enabled,
        allowed_combos: key.allowed_combos,
      });
      refresh();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Update failed", "error");
    }
  };

  const reveal = async (key: ApiKey) => {
    try {
      const result = await api.get<{ token: string }>(`/admin/api/keys/${key.id}/reveal`);
      await navigator.clipboard.writeText(result.token);
      toast("Token copied to clipboard");
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Reveal failed", "error");
    }
  };

  const remove = async (key: ApiKey) => {
    if (!window.confirm(`Delete API key "${key.name}"?`)) return;
    try {
      await api.del(`/admin/api/keys/${key.id}`);
      toast("Key deleted");
      refresh();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "Delete failed", "error");
    }
  };

  const baseUrl = `${window.location.origin}/v1`;
  const curl = `curl ${baseUrl}/chat/completions \\
  -H "Authorization: Bearer YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"model":"coding-fast","messages":[{"role":"user","content":"hi"}]}'`;

  if (loading) return <Spinner label="Loading keys…" />;

  return (
    <>
      <PageHeader
        title="API keys"
        subtitle="Bearer tokens that clients send to the gateway. These are not your upstream provider keys."
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus size={16} /> Create key
          </Button>
        }
      />

      <Card className="section" >
        <div className="code-head">
          <span>Point any OpenAI-compatible client at</span>
          <CopyButton value={baseUrl} />
        </div>
        <div className="code-block">{baseUrl}</div>
        <div className="code-head" style={{ marginTop: 14 }}>
          <span>Example request</span>
          <CopyButton value={curl} />
        </div>
        <div className="code-block payload-block">{curl}</div>
      </Card>

      <div className="section">
        {keys.length === 0 ? (
          <Card>
            <EmptyState
              title="No API keys yet"
              description="Create a key and use it as the bearer token for /v1 requests."
              action={
                <Button variant="primary" onClick={() => setCreating(true)}>
                  <KeyRound size={16} /> Create key
                </Button>
              }
            />
          </Card>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Token</th>
                  <th>Enabled</th>
                  <th>Allowed combos</th>
                  <th>Last used</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {keys.map((key) => (
                  <tr key={key.id}>
                    <td>{key.name}</td>
                    <td>
                      <span className="account-meta">{key.token_masked}</span>
                    </td>
                    <td>
                      <Toggle checked={key.enabled} onChange={(value) => toggle(key, value)} />
                    </td>
                    <td>
                      {key.allowed_combos.length === 0 ? (
                        <Badge tone="muted">all</Badge>
                      ) : (
                        <span className="muted">{key.allowed_combos.join(", ")}</span>
                      )}
                    </td>
                    <td className="muted">{formatRelative(key.last_used_at)}</td>
                    <td>
                      <div className="row" style={{ justifyContent: "flex-end" }}>
                        <Button variant="ghost" onClick={() => reveal(key)}>
                          Copy
                        </Button>
                        <Button variant="ghost" onClick={() => remove(key)}>
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
      </div>

      {creating && (
        <CreateKeyModal
          combos={combos}
          onClose={() => setCreating(false)}
          onCreated={(token) => {
            setNewToken(token);
            refresh();
          }}
        />
      )}

      {newToken && (
        <Modal
          title="Your new API key"
          onClose={() => setNewToken(null)}
          footer={<Button variant="primary" onClick={() => setNewToken(null)}>Done</Button>}
        >
          <p className="muted" style={{ marginTop: 0 }}>
            Copy this token now — you can reveal it later from the list.
          </p>
          <div className="code-head">
            <span>Bearer token</span>
            <CopyButton value={newToken} />
          </div>
          <div className="code-block">{newToken}</div>
        </Modal>
      )}
    </>
  );
}
