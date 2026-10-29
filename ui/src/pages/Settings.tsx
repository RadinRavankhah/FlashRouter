import { useEffect, useState } from "react";
import { api, ApiError, getAdminToken, setAdminToken } from "../api";
import {
  Button,
  Card,
  Field,
  PageHeader,
  Spinner,
  Toggle,
  formatBytes,
  formatNumber,
  useToast,
} from "../components";
import type { Health } from "../types";

export default function Settings() {
  const toast = useToast();
  const [health, setHealth] = useState<Health | null>(null);
  const [tokenSaver, setTokenSaver] = useState(true);
  const [adminToken, setAdminTokenValue] = useState(getAdminToken());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get<Health>("/admin/api/health"),
      api.get<{ token_saver: boolean }>("/admin/api/settings"),
    ])
      .then(([healthData, settings]) => {
        setHealth(healthData);
        setTokenSaver(settings.token_saver);
      })
      .catch(() => toast("Failed to load settings", "error"))
      .finally(() => setLoading(false));
  }, [toast]);

  const toggleSaver = async (value: boolean) => {
    setTokenSaver(value);
    try {
      await api.put("/admin/api/settings", { token_saver: value });
      toast(`Token saver ${value ? "enabled" : "disabled"}`);
    } catch (error) {
      setTokenSaver(!value);
      toast(error instanceof ApiError ? error.message : "Update failed", "error");
    }
  };

  const saveToken = () => {
    setAdminToken(adminToken.trim());
    toast(adminToken.trim() ? "Admin token saved locally" : "Admin token cleared");
  };

  if (loading) return <Spinner label="Loading settings…" />;

  return (
    <>
      <PageHeader title="Settings" subtitle="Runtime, token saving and connection details." />

      <div className="grid-2">
        <Card>
          <div className="section-head">
            <span className="section-title">Token saver (RTK)</span>
          </div>
          <p className="muted" style={{ marginTop: 0 }}>
            Compresses large tool outputs (git diff, grep, logs) before sending them upstream.
            Fails open and never inflates a payload.
          </p>
          <Toggle
            checked={tokenSaver}
            onChange={toggleSaver}
            label={tokenSaver ? "Enabled" : "Disabled"}
          />
        </Card>

        <Card>
          <div className="section-head">
            <span className="section-title">Admin token</span>
          </div>
          <p className="muted" style={{ marginTop: 0 }}>
            Only needed if you set <code>FLASHROUTER_ADMIN_TOKEN</code> on the server. Stored in
            this browser only.
          </p>
          <Field label="X-Admin-Token">
            <input
              type="password"
              value={adminToken}
              onChange={(event) => setAdminTokenValue(event.target.value)}
              placeholder="optional"
            />
          </Field>
          <Button onClick={saveToken}>Save locally</Button>
        </Card>
      </div>

      {health && (
        <Card className="section">
          <div className="section-head">
            <span className="section-title">Storage & health</span>
          </div>
          <dl className="kv">
            <dt>Version</dt>
            <dd>{health.version}</dd>
            <dt>Database</dt>
            <dd>{health.database}</dd>
            <dt>Database size</dt>
            <dd>{formatBytes(health.database_bytes)}</dd>
            <dt>Free disk</dt>
            <dd>{formatBytes(health.free_bytes)}</dd>
            <dt>Providers</dt>
            <dd>{formatNumber(health.counts.providers)}</dd>
            <dt>Accounts</dt>
            <dd>{formatNumber(health.counts.accounts)}</dd>
            <dt>Combos</dt>
            <dd>{formatNumber(health.counts.combos)}</dd>
            <dt>API keys</dt>
            <dd>{formatNumber(health.counts.keys)}</dd>
          </dl>
        </Card>
      )}

      <Card className="section">
        <div className="section-head">
          <span className="section-title">Maintenance</span>
        </div>
        <p className="muted" style={{ marginTop: 0 }}>
          Backups and restores are handled by the CLI.
        </p>
        <div className="code-block">{`flashrouter backup
flashrouter restore <file>
flashrouter doctor --probe`}</div>
      </Card>
    </>
  );
}
