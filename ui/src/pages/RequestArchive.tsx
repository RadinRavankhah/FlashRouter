import { useState } from "react";
import { Archive, Download, Trash2 } from "lucide-react";
import { api } from "../api";
import {
  Button,
  Field,
  Modal,
  Toggle,
  formatNumber,
  useToast,
} from "../components";
import type { PurgePreview, PurgeResult } from "../types";

export type RequestFilters = Record<string, string | number>;

function defaultCutoff(): string {
  return new Date(Date.now() - 30 * 24 * 3600_000).toISOString().slice(0, 10);
}

function queryString(
  filters: RequestFilters,
  extra: Record<string, string | number | boolean>,
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== "" && value !== undefined && value !== null) {
      params.set(key, String(value));
    }
  }
  for (const [key, value] of Object.entries(extra)) {
    params.set(key, String(value));
  }
  return params.toString();
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function FilterNote({ filters }: { filters: RequestFilters }) {
  const entries = Object.entries(filters);
  if (entries.length === 0) {
    return <p className="muted">No filters — every stored request is in scope.</p>;
  }
  return (
    <p className="muted">
      Active filters: {entries.map(([key, value]) => `${key}=${value}`).join(", ")}
    </p>
  );
}

export function ExportDialog({
  onClose,
  filters,
  total,
}: {
  onClose: () => void;
  filters: RequestFilters;
  total: number;
}) {
  const toast = useToast();
  const [includePayloads, setIncludePayloads] = useState(true);
  const [busy, setBusy] = useState<"jsonl" | "csv" | null>(null);

  const run = async (format: "jsonl" | "csv") => {
    setBusy(format);
    try {
      const query = queryString(filters, {
        format,
        include_payloads: includePayloads,
      });
      const blob = await api.download(`/admin/api/requests/export?${query}`);
      saveBlob(blob, `requests-export.${format}`);
      toast(`${format.toUpperCase()} export downloaded`, "ok");
    } catch (error) {
      toast((error as Error).message || "Export failed", "error");
    } finally {
      setBusy(null);
    }
  };

  const disabled = busy !== null || total === 0;

  return (
    <Modal
      title="Export requests"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={busy !== null}>
            Done
          </Button>
          <Button onClick={() => run("csv")} disabled={disabled}>
            <Download size={15} /> {busy === "csv" ? "Downloading…" : "Download CSV"}
          </Button>
          <Button variant="primary" onClick={() => run("jsonl")} disabled={disabled}>
            <Download size={15} /> {busy === "jsonl" ? "Downloading…" : "Download JSONL"}
          </Button>
        </>
      }
    >
      <div className="stack">
        <p className="muted">
          {formatNumber(total)} matching request{total === 1 ? "" : "s"} will be exported.
          Nothing is deleted. Each format downloads separately.
        </p>
        <FilterNote filters={filters} />
        <Toggle
          checked={includePayloads}
          onChange={setIncludePayloads}
          label="Include raw request/response payloads"
        />
        <p className="muted" style={{ fontSize: 12 }}>
          JSONL keeps every stored payload, including raw streams. CSV is a flat
          one-row-per-request summary and never includes payload bodies.
        </p>
      </div>
    </Modal>
  );
}

export function PurgeDialog({
  onClose,
  filters,
  onDone,
}: {
  onClose: () => void;
  filters: RequestFilters;
  onDone: () => void;
}) {
  const toast = useToast();
  const [cutoff, setCutoff] = useState(defaultCutoff);
  const [includePayloads, setIncludePayloads] = useState(true);
  const [vacuum, setVacuum] = useState(false);
  const [preview, setPreview] = useState<PurgePreview | null>(null);
  const [result, setResult] = useState<PurgeResult | null>(null);
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);

  const body = (dryRun: boolean) => ({
    before: cutoff,
    format: "both",
    include_payloads: includePayloads,
    vacuum,
    dry_run: dryRun,
    ...filters,
  });

  const runPreview = async () => {
    setLoading(true);
    setResult(null);
    try {
      const data = await api.post<PurgePreview>(
        "/admin/api/requests/purge",
        body(true),
      );
      setPreview(data);
    } catch (error) {
      setPreview(null);
      toast((error as Error).message || "Preview failed", "error");
    } finally {
      setLoading(false);
    }
  };

  const runPurge = async () => {
    setLoading(true);
    try {
      const data = await api.post<PurgeResult>(
        "/admin/api/requests/purge",
        body(false),
      );
      setResult(data);
      onDone();
      toast(`Deleted ${formatNumber(data.deleted)} requests`, "ok");
    } catch (error) {
      toast((error as Error).message || "Clean up failed", "error");
    } finally {
      setLoading(false);
    }
  };

  const canDelete =
    preview !== null &&
    preview.matched > 0 &&
    confirm.trim() === "DELETE" &&
    !loading &&
    result === null;

  return (
    <Modal
      title="Archive & clean up requests"
      onClose={onClose}
      wide
      footer={
        result ? (
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        ) : (
          <>
            <Button onClick={onClose} disabled={loading}>
              Cancel
            </Button>
            <Button onClick={runPreview} disabled={loading || !cutoff}>
              Preview
            </Button>
            <Button variant="danger" onClick={runPurge} disabled={!canDelete}>
              <Trash2 size={15} /> Archive & delete
            </Button>
          </>
        )
      }
    >
      <div className="stack">
        <p className="muted">
          Requests older than the cutoff are archived as JSONL and CSV first, then
          permanently deleted from the database. Pending requests are never touched.
        </p>
        <FilterNote filters={filters} />

        <div className="row">
          <Field label="Delete requests created before (UTC)">
            <input
              type="date"
              value={cutoff}
              onChange={(event) => {
                setCutoff(event.target.value);
                setPreview(null);
                setResult(null);
                setConfirm("");
              }}
            />
          </Field>
        </div>

        <Toggle
          checked={includePayloads}
          onChange={setIncludePayloads}
          label="Include raw payloads in the archive"
        />
        <Toggle
          checked={vacuum}
          onChange={setVacuum}
          label="VACUUM the database after deleting (reclaims disk, can be slow)"
        />

        {preview && (
          <div className="card" style={{ padding: 12 }}>
            <strong>
              {preview.matched === 0
                ? "No requests match these filters."
                : `${formatNumber(preview.matched)} request${preview.matched === 1 ? "" : "s"} will be archived and deleted.`}
            </strong>
            <p className="muted" style={{ margin: "6px 0 0" }}>
              The archive is written before anything is deleted.
            </p>
          </div>
        )}

        {result && (
          <div className="card" style={{ padding: 12 }}>
            <div className="row">
              <Archive size={16} />
              <strong>Archive complete</strong>
            </div>
            <p className="muted" style={{ margin: "6px 0 0" }}>
              Exported {formatNumber(result.exported)} · deleted{" "}
              {formatNumber(result.deleted)} · {formatNumber(result.bytes)} bytes
              {result.vacuumed ? " · database vacuumed" : ""}
            </p>
            <div className="stack" style={{ marginTop: 6, gap: 4 }}>
              {result.files.map((file) => (
                <p
                  key={file.file}
                  className="muted"
                  style={{ margin: 0, fontSize: 12 }}
                >
                  {file.format.toUpperCase()}: {file.path} ({formatNumber(file.bytes)} bytes)
                </p>
              ))}
            </div>
            <div className="row" style={{ marginTop: 10 }}>
              {result.files.map((file) => (
                <Button
                  key={file.file}
                  disabled={downloading !== null}
                  onClick={async () => {
                    setDownloading(file.file);
                    try {
                      const blob = await api.download(
                        `/admin/api/requests/exports/${encodeURIComponent(file.file)}`,
                      );
                      saveBlob(blob, file.file);
                    } catch (error) {
                      toast((error as Error).message || "Download failed", "error");
                    } finally {
                      setDownloading(null);
                    }
                  }}
                >
                  <Download size={15} />
                  {downloading === file.file
                    ? "Downloading…"
                    : `Download ${file.format.toUpperCase()}`}
                </Button>
              ))}
            </div>
          </div>
        )}

        {!result && (
          <Field
            label="Type DELETE to confirm"
            hint="Preview first, then confirm. This cannot be undone."
          >
            <input
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              placeholder="DELETE"
              autoComplete="off"
            />
          </Field>
        )}
      </div>
    </Modal>
  );
}
