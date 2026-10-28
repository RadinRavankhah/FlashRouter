# FlashRouter

FlashRouter is a lightweight, local-first gateway for OpenAI-compatible APIs. It is intended to become a practical replacement for a local 9router setup without Docker, a production Node process, or a large provider catalog.

This repository is at **v0.1**: a small, reliable proxy for OpenAI Chat Completions.

## What works in v0.1

- `POST /v1/chat/completions`
  - Streaming and non-streaming
  - Tool-call passthrough
  - Request-field preservation
  - Upstream status and error-body propagation
- `GET /v1/models`
  - Manually configured, client-facing model IDs
- One configurable upstream
  - Base URL, upstream API key, timeouts, custom headers
  - OpenAI-compatible local endpoints
- One gateway API key
- Shared `httpx.AsyncClient` connection pool
- Clean outbound headers (client auth, cookies, and forwarding headers are not forwarded)
- Unbuffered streaming and client-disconnect cleanup
- Operational terminal logs and sanitized diagnostics

Not included yet:

- Dashboard integration
- Persistent request history or SQLite
- Multiple upstreams, key rotation, retries, or fallbacks
- Budgets, pricing, or analytics
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

`trust_env` is `false` by default so `HTTP_PROXY`/`HTTPS_PROXY` do not silently affect upstream requests. Set it to `true` only if the proxy environment is intentional.

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

The `model` field must match a configured `[[models]].id`. FlashRouter replaces it with `upstream_model` and preserves the rest of the JSON body.

Streaming requests use `"stream": true`. SSE chunks are forwarded incrementally without parsing or buffering the complete response.

### `GET /v1/models`

Requires the same bearer token and returns the configured client-facing model IDs in OpenAI list format.

### `GET /healthz`

Unauthenticated liveness check. It does not contact upstream or reveal configuration.

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
