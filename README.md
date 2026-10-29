# FlashRouter

FlashRouter is a lightweight, local-first gateway for OpenAI-compatible APIs. It is intended to become a practical replacement for a local 9router setup without Docker, a production Node process, or a large provider catalog.

This repository is at **v0.3** (completed): dashboard configuration, upstream/key/model management, full request history. **v0.7** (Responses/Codex) and **v0.8** (Anthropic/Claude Code) adapters wired with endpoints and tests. **v0.4** analytics backend completed (DB v4, paginated APIs, reconciliation, CSV/projections, usage accountant, tests). **v0.5** budgets/restrictions: schema v5, enforcement service, basic tests. **Remaining:** concurrent reservation logic, alerts, traffic controls, v0.6 routing, v0.9 packaging, v1.0 stable.
and a dashboard for upstreams, credentials, client keys, and models.

## What works in v0.3

- `POST /v1/chat/completions`
  - Streaming and non-streaming
  - Tool-call passthrough
  - Request-field preservation
  - Upstream status and error-body propagation
- `GET /v1/models`
  - Client-facing model aliases served from the dashboard
- Multiple upstream configurations managed from the dashboard
  - Name, base URL, protocol, custom headers, timeouts, enabled/disabled
- Upstream credential management
  - Add, rename, reveal, copy, replace, disable, delete (history preserved)
  - Test with a billable request via the dashboard
- Multiple gateway/client keys
  - Create per client or workflow, reveal/copy, rename, disable/revoke
  - Last-used timestamp; separately attributable request history
- Model configuration
  - Manual model entries and client-facing aliases
  - Choose which upstream serves each model
  - Model visibility in `/v1/models`
- Per-key log attribution
  - Gateway key, upstream credential, and actual model on every request
  - Filters and detail-page links
- Request-history dashboard
  - Request-history table, request-detail page, readable JSON/text views
  - Error details, duration and time to first token
  - Date, model, status, request ID, gateway key, and credential filters
- Persistent storage
  - SQLite with WAL mode and versioned migrations
  - Full request/attempt/payload body logging (secrets redacted)
  - Forever retention; database-size and free-space display
- Admin security baseline
  - Localhost binding by default
  - CSRF/origin protections on admin mutations
  - No secrets in browser local storage
  - Plaintext secret storage clearly disclosed

Not included yet:

- Budget enforcement
- Automatic rotation
- Fallback chains
- Encryption
- Responses API or Anthropic Messages compatibility
- Windows packaging, encryption, or backups

The existing `ui/` directory is still a mock frontend and is not served by v0.1.

## Requirements

- Python 3.11 or newer
- Windows, macOS, or Linux
- An OpenAI-compatible upstream endpoint and API key, or a local endpoint

## Installation

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

That installs the `flashrouter` command and development dependencies. On macOS/Linux, activate with `source .venv/bin/activate`.

## Configuration

FlashRouter reads TOML from:

1. `--config <path>`
2. `FLASHROUTER_CONFIG`
3. `%LOCALAPPDATA%\FlashRouter\config.toml` on Windows
4. `~/.local/share/flashrouter/config.toml` on other platforms

Create your local config from the example:

```powershell
$configDir = Join-Path $env:LOCALAPPDATA "FlashRouter"
New-Item -ItemType Directory -Path $configDir -Force | Out-Null
Copy-Item .\config.example.toml (Join-Path $configDir "config.toml")
notepad (Join-Path $configDir "config.toml")
```

Do not commit `config.toml`, `.env`, or any file containing real API keys.

### Configuration reference

```toml
[server]
host = "127.0.0.1"
port = 8787
log_level = "info"

[gateway]
api_key = "the-key-clients-send-as-a-bearer-token"

[upstream]
name = "openrouter"
base_url = "https://openrouter.ai/api/v1"
protocol = "openai-chat"
api_key = "the-upstream-provider-key"
connect_timeout_seconds = 10
read_timeout_seconds = 180
verify_tls = true
trust_env = false
follow_redirects = false

[upstream.headers]
HTTP-Referer = "https://example.invalid/flashrouter"
X-OpenRouter-Title = "FlashRouter"

[[models]]
id = "coding-fast"
upstream_model = "qwen/qwen3-coder"
owned_by = "openrouter"
```

`id` is the model name clients send and the name returned by `/v1/models`. `upstream_model` is what FlashRouter sends upstream. Unknown model IDs are rejected before any upstream request is made.

Model entries are managed entirely from the dashboard (Models & aliases page). `[[models]]` entries in `config.toml` are still read for backward compatibility but are no longer required.

`trust_env` is `false` by default so `HTTP_PROXY`/`HTTPS_PROXY` do not silently affect upstream requests. Set it to `true` only if the proxy environment is intentional.

## Client authentication

FlashRouter authenticates clients with a bearer gateway API key:

- `Authorization: Bearer <gateway-key>` is required on `/v1/chat/completions` and `/v1/models`.
- Keys are created and managed from the dashboard (Gateway keys page).
- A missing or invalid key returns `401`; a disabled key returns `403`.
- Each request is attributed to the key used, so history is separately attributable per key.

For backward compatibility, the single gateway API key from `[gateway].api_key` (or `FLASHROUTER_GATEWAY_API_KEY`) continues to work even before any dashboard key is created.

### Environment overrides

Secrets should normally come from the environment rather than the config file:

| Variable | Purpose |
|---|---|
| `FLASHROUTER_CONFIG` | Config file path |
| `FLASHROUTER_DATA_DIR` | Data root directory |
| `FLASHROUTER_HOST` | Bind address |
| `FLASHROUTER_PORT` | Port |
| `FLASHROUTER_LOG_LEVEL` | `debug`, `info`, `warning`, or `error` |
| `FLASHROUTER_GATEWAY_API_KEY` | Gateway/client key |
| `FLASHROUTER_UPSTREAM_NAME` | Upstream display name |
| `FLASHROUTER_UPSTREAM_BASE_URL` | Upstream API root |
| `FLASHROUTER_UPSTREAM_API_KEY` | Upstream credential |
| `FLASHROUTER_UPSTREAM_CONNECT_TIMEOUT_SECONDS` | Connect timeout |
| `FLASHROUTER_UPSTREAM_READ_TIMEOUT_SECONDS` | Read/idle timeout |
| `FLASHROUTER_UPSTREAM_VERIFY_TLS` | TLS verification |
| `FLASHROUTER_UPSTREAM_TRUST_ENV` | Use proxy environment variables |
| `FLASHROUTER_UPSTREAM_FOLLOW_REDIRECTS` | Follow upstream redirects |
| `FLASHROUTER_UPSTREAM_HTTP_REFERER` | Adds `HTTP-Referer` |
| `FLASHROUTER_UPSTREAM_TITLE` | Adds `X-OpenRouter-Title` |

## Running

```powershell
flashrouter run
```

Or with an explicit config and overrides:

```powershell
flashrouter run --config .\config.toml --host 127.0.0.1 --port 8787 --log-level info
```

Check configuration without starting the server:

```powershell
flashrouter doctor
flashrouter doctor --probe   # non-billable GET to the upstream /models endpoint
```

## Connecting clients

Point any OpenAI-compatible Chat Completions client at:

```text
http://127.0.0.1:8787/v1
```

Use the configured gateway key as the API key. For example, with the OpenAI Python SDK:

```python
from openai import OpenAI

client = OpenAI(
    api_key="your-gateway-key",
    base_url="http://127.0.0.1:8787/v1",
)

response = client.chat.completions.create(
    model="coding-fast",
    messages=[{"role": "user", "content": "Hello"}],
)
print(response.choices[0].message.content)
```

A smoke test is included:

```powershell
$env:FLASHROUTER_GATEWAY_API_KEY = "your-gateway-key"
$env:FLASHROUTER_MODEL = "coding-fast"
python .\scripts\smoke_openai.py
```

The script checks `/v1/models`, non-streaming chat, streaming chat, and a tool-call request.

## OpenRouter diagnostics

If an upstream request fails with a security-policy or unexpected `403`, run the sanitized diagnostic before changing the proxy blindly:

```powershell
$env:OPENROUTER_API_KEY = "your-openrouter-key"
$env:OPENROUTER_MODEL = "openrouter/auto"

python .\scripts\diagnose_openrouter.py --model openrouter/auto --output .\diagnostics\openrouter.json
```

Compare a direct request with a request through FlashRouter:

```powershell
$env:FLASHROUTER_GATEWAY_API_KEY = "your-gateway-key"
python .\scripts\diagnose_openrouter.py `
  --model openrouter/auto `
  --via-url http://127.0.0.1:8787/v1 `
  --via-model coding-fast `
  --output .\diagnostics\openrouter-compare.json
```

The report includes the URL, sanitized headers, request body, proxy environment settings, status, response body, and provider/edge request IDs. API keys, cookies, and proxy credentials are redacted. It is a diagnostic tool, not a policy bypass.

## Endpoints

### `POST /v1/chat/completions`

Requires:

```http
Authorization: Bearer <gateway-key>
Content-Type: application/json
```

The `model` field must match a configured client-facing model alias (managed from the dashboard). FlashRouter resolves the alias to an upstream model and provider, then preserves the rest of the JSON body.

Streaming requests use `"stream": true`. SSE chunks are forwarded incrementally without parsing or buffering the complete response.

### `GET /v1/models`

Requires the same bearer token and returns the configured client-facing model aliases in OpenAI list format.

### `GET /healthz`

Unauthenticated liveness check. It does not contact upstream or reveal configuration.

## Admin API

All admin endpoints are under `/admin` and are protected by CSRF/origin checks on state-changing requests. The dashboard calls these directly.

### Setup

- `GET /admin/setup/status` — whether the gateway has been configured.
- `POST /admin/setup` — create the first gateway key, upstream, credential, model, and alias.

### Providers (`/admin/v1/providers`)

- `GET`, `POST`, `GET /{id}`, `PUT /{id}`, `DELETE /{id}` — full CRUD.
- `POST /{id}/test` — send a minimal (potentially billable) chat request through the provider's stored credential; returns status, duration, and a sanitized response.

### Provider credentials (`/admin/v1/credentials`)

- `GET`, `POST`, `GET /{id}`, `PUT /{id}`, `DELETE /{id}` — full CRUD. Secrets are masked in list views and can be revealed/copy from the dashboard.

### Gateway keys (`/admin/v1/keys`)

- `GET`, `POST`, `GET /{id}`, `PUT /{id}`, `DELETE /{id}` — full CRUD. Disabled keys return `403` on inference requests.

### Models and aliases (`/admin/v1/dbmodels`, `/admin/v1/aliases`)

- Full CRUD for upstream models and client-facing aliases. Aliases are what clients send in `model` and what `/v1/models` exposes.

### Requests (`/admin/v1/requests`)

- `GET` — list requests with filters: `model`, `status`, `gateway_key`, `credential`, `date_from`, `date_to`, `request_id`, `limit`, `offset`.
- `GET /{id}` — full request detail with attempts and payloads.

### Stats and health

- `GET /admin/v1/stats` — request totals by status.
- `GET /admin/v1/health` — storage health, database and disk sizes.

## Error behavior

Locally generated errors use an OpenAI-style envelope:

```json
{
  "error": {
    "message": "Model 'unknown' is not configured on this gateway",
    "type": "invalid_request_error",
    "param": "model",
    "code": "model_not_found"
  }
}
```

Upstream error statuses and bodies are passed through when possible. Connection failures return `502`; timeouts return `504`. Responses include an `X-FlashRouter-Request-ID` header.

## Security notes

- The gateway binds to `127.0.0.1` by default.
- Client `Authorization`, `Cookie`, `Host`, forwarding headers, and hop-by-hop headers are never forwarded upstream.
- Upstream credentials come only from configuration.
- Secrets are not written to operational logs.
- v0.1 stores no request history, so prompts and responses are not persisted.
- `config.toml` is ignored by Git. Keep it private.
- TLS verification is on by default.
- Do not expose the gateway to a network until admin authentication, HTTPS, and deployment hardening exist.

## Development

Run the test suite:

```powershell
pytest
```

Run linting:

```powershell
ruff check .
```

The dashboard is a Vite/React SPA. Build it before running the server so FastAPI can serve it:

```powershell
cd ui
npm install
npm run build   # tsc --noEmit && vite build
cd ..
```

Project layout:

```text
src/flashrouter/
  app.py                 FastAPI app factory
  cli.py                 flashrouter run / doctor
  config.py              TOML loading, validation, env overrides
  auth.py                Gateway bearer-key authentication
  errors.py              OpenAI-compatible errors
  logging.py             Operational logging
  diagnostics.py         Sanitized upstream comparison
  api/                   Inference and model endpoints
  core/                  Small future-facing interfaces
  protocols/             Protocol adapters
  routing/               Model resolution
  services/              Chat Completions proxy
  transport/             httpx transport, headers, URL joining
scripts/
  diagnose_openrouter.py
  smoke_openai.py
tests/
  unit/
  integration/
```

## Troubleshooting

**The server says the config file is missing.**  
Copy `config.example.toml` to `%LOCALAPPDATA%\FlashRouter\config.toml` or pass `--config`.

**Clients receive 401.**  
The gateway key is the key in `[gateway].api_key`, not the upstream provider key. Send it as `Authorization: Bearer ...`.

**A model is rejected.**  
Add its client-facing ID under `[[models]]`. Unknown IDs are intentionally blocked before dispatch.

**OpenRouter returns 403 or a security-policy error.**  
Run the diagnostic with and without `--trust-env`. Capture the sanitized report and provider request IDs. Do not assume a Python rewrite fixes the issue without comparing requests.

**Streaming hangs or a client disconnects.**  
v0.1 closes the upstream stream when the client disconnects and logs an incomplete stream. There are no retries or fallbacks yet.

## License

MIT
