# FlashRouter

**A local-first, OpenAI-compatible LLM router with automatic fallback.**

Point any OpenAI-compatible client (OpenAI SDK, Cursor, Cline, OpenCode, Roo,
Continue, scripts…) at one local endpoint and let FlashRouter route requests
across your providers with **combos**, **multi-account rotation**, **auto-fallback**
and a **token saver** — all managed from a local dashboard.

```text
   Your client                         FlashRouter (localhost:20128)
  ─────────────                       ─────────────────────────────
  OpenAI SDK / Cursor / Cline  ──▶  /v1/chat/completions
  any OpenAI-compatible tool         │
                                     ├─ resolve "coding-fast" → combo
                                     ├─ pick an eligible account (rotation)
                                     ├─ RTK: compress huge tool outputs
                                     ├─ request provider #1 ──▶ 429 / 5xx / timeout
                                     ├─ fall back to provider #2 ──▶ 200 OK
                                     └─ stream back to the client, log usage
```

## Features

- **One OpenAI endpoint** — `/v1/chat/completions`, `/v1/models`, `/v1/responses`.
- **Providers** — OpenRouter, Groq, DeepSeek, GLM, MiniMax, Mistral, Gemini
  (OpenAI endpoint), OpenAI, Together, Cerebras, Fireworks, NVIDIA, xAI,
  Ollama / LM Studio / llama.cpp, or any custom OpenAI-compatible base URL.
- **Multiple accounts per provider** — weighted, priority-based rotation and
  automatic cooldown when an account is rate-limited or out of quota.
- **Combos** — ordered fallback chains selected by the model name clients send.
- **Auto-fallback** — retries transient failures, honors `Retry-After`, and moves
  to the next target only before any response bytes reach the client.
- **RTK token saver** — compresses large tool outputs (`git diff`, `grep`, `ls`,
  logs) before they are sent upstream. Fails open; never inflates a payload.
- **Dashboard** — providers, accounts, combos, API keys, request logs and usage.
- **Local & private** — SQLite storage, binds to `127.0.0.1` by default.

> Scope: FlashRouter speaks the **OpenAI Chat Completions API**. It does not
> translate Anthropic Messages or Gemini-native protocols, and does not use
> subscription OAuth. Anything that talks OpenAI-compatible HTTP works.

## Quick start

Requires **Python 3.11+**. Node is only needed if you rebuild the dashboard.

### Option A — one command (bootstraps a venv)

```bash
git clone <your-repo-url> FlashRouter
cd FlashRouter

# Windows
flashrouter.cmd run
# macOS / Linux
./flashrouter run
```

The launcher creates `.venv`, installs the project, and starts the gateway.

### Option B — standard install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -e .
flashrouter run
```

Then open the URL printed by the CLI (**http://127.0.0.1:20128** by default) in
your browser.

## First-run walkthrough

1. **Connections → Add provider.** Pick a preset (or *Custom*), paste the base URL.
2. **Add account.** Paste your provider API key (leave blank for local servers).
   Add more accounts for rotation if you like.
3. **Combos → Create combo.** Give it a name such as `coding-fast` and add one or
   more `provider / model` targets. Requests try them top to bottom.
4. **API keys → Create key.** Copy the token.
5. Point your client at `http://127.0.0.1:20128/v1` with that token and use the
   combo name as the model.

## Connecting clients

Any OpenAI-compatible client works. Example with the OpenAI Python SDK:

```python
from openai import OpenAI

client = OpenAI(
    api_key="YOUR_FLASHROUTER_KEY",
    base_url="http://127.0.0.1:20128/v1",
)

response = client.chat.completions.create(
    model="coding-fast",          # a combo name
    messages=[{"role": "user", "content": "Hello"}],
)
print(response.choices[0].message.content)
```

Or with `curl`:

```bash
curl http://127.0.0.1:20128/v1/chat/completions \
  -H "Authorization: Bearer YOUR_FLASHROUTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"coding-fast","messages":[{"role":"user","content":"hi"}]}'
```

In GUI/CLI tools, set:

- **Base URL / endpoint:** `http://127.0.0.1:20128/v1`
- **API key:** a key from the dashboard
- **Model:** a combo name (or `provider/model`)

## How routing works

A client `model` value is resolved, in order, as:

1. a **combo** name → its ordered targets;
2. **`provider/model`** (provider name prefix; the model may contain slashes);
3. a **catalog model id** → all providers offering it;
4. otherwise `404 model_not_found`.

For each target, FlashRouter selects an eligible account (enabled, not cooling,
highest priority then weighted rotation) and sends the request. On `429`, `401/403`,
`402`, `5xx`, timeouts or connection errors it cools the account down as needed
and falls back to the next account/target. A `400`-class client error is returned
as-is; it does not silently swap models.

## Token saver (RTK)

Large tool results are the biggest hidden token cost. FlashRouter detects oversized
`role: "tool"` messages, strips ANSI, collapses identical lines and truncates very
large output with a marker. It is enabled by default and toggleable in
**Settings**. To bypass it for one request:

```http
X-FlashRouter-Token-Saver: off
```

## Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/chat/completions` | OpenAI Chat Completions (streaming + tools) |
| `POST` | `/v1/responses` | Pass-through for Responses-compatible upstreams |
| `GET` | `/v1/models` | Combos and catalog models |
| `GET` | `/healthz` | Liveness check |
| `GET` | `/` · `/dashboard` | Dashboard (static build in `ui/dist`) |

Inference requests require `Authorization: Bearer <key>` (or `x-api-key`) once at
least one API key exists.

Errors use the OpenAI envelope:

```json
{ "error": { "message": "...", "type": "invalid_request_error", "code": "..." } }
```

## Configuration

Configuration is optional — everything is managed from the dashboard. To change
defaults, copy `config.example.toml` to `config.toml`:

```toml
[server]
host = "127.0.0.1"
port = 20128
log_level = "info"

[gateway]
token_saver = true
max_retries = 2
connect_timeout = 10.0
request_timeout = 300.0

[admin]
token = ""   # optional X-Admin-Token for /admin/api
```

Data lives in the platform data directory:

- Windows: `%LOCALAPPDATA%\FlashRouter`
- macOS/Linux: `~/.local/share/flashrouter`

Override with `FLASHROUTER_DATA_DIR` or `--config`.

Environment overrides: `FLASHROUTER_HOST`, `FLASHROUTER_PORT`,
`FLASHROUTER_LOG_LEVEL`, `FLASHROUTER_DATA_DIR`, `FLASHROUTER_CONFIG`,
`FLASHROUTER_ADMIN_TOKEN`, `FLASHROUTER_TOKEN_SAVER`.

## CLI

```bash
flashrouter run            # start gateway + dashboard
flashrouter doctor --probe # inspect config/storage and test providers
flashrouter backup         # write a consistent SQLite backup
flashrouter restore <file> # restore (saves the current DB first)
flashrouter reset-admin    # delete client keys + settings (--all wipes everything)
flashrouter open           # open the dashboard
flashrouter version
```

## Project layout

```text
src/flashrouter/
  app.py                 FastAPI factory, middleware, static dashboard
  cli.py                 command-line entry point
  config.py              optional TOML + env configuration
  providers/presets.py   built-in OpenAI-compatible presets
  routing/engine.py      model resolution + account selection
  services/engine.py     request orchestration, fallback, streaming, logging
  services/usage.py      usage normalization + cost estimate
  savers/rtk.py          tool-output compression
  storage/               SQLite schema, migrations, repository
  api/inference.py       /v1 endpoints
  api/admin.py           dashboard API
  transport/             httpx client, headers, URL building
ui/                      React + Vite dashboard (built into ui/dist)
tests/                   unit + integration tests (mock upstream)
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

Rebuild the dashboard after UI changes (the built `ui/dist` is committed so the
server does not need Node):

```bash
cd ui
npm install
npm run build
```

## Troubleshooting

- **Port already in use** — `flashrouter run --port 20228`.
- **401 from the gateway** — use a key created in *API keys*, not your upstream key.
- **404 model_not_found** — create a combo with that name, or use `provider/model`.
- **Upstream 429/403** — the provider key/quota; check the account in *Connections*.
  FlashRouter will cool it down and fall back automatically.
- **No dashboard** — build it once with `cd ui && npm install && npm run build`.

## Limitations

- OpenAI Chat Completions clients only (no Anthropic/Claude Code or Responses
  translation; `/v1/responses` is pass-through only).
- Costs are **estimates** (price per 1M tokens is optional, per model) intended as
  a savings tracker, not billing.
- Provider secrets are stored in the local SQLite database. This is a single-user
  local tool; bind to `127.0.0.1` and do not expose it publicly.

## License

MIT
