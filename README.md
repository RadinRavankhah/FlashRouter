# FlashRouter

**A local-first LLM router with automatic fallback, speaking the OpenAI and Anthropic APIs.**

Point any OpenAI-compatible client (OpenAI SDK, Cursor, Cline, OpenCode, Roo,
Continue, scripts…) **or any Anthropic-compatible client (Claude Code, Anthropic
SDK)** at one local endpoint and let FlashRouter route requests across your
providers with **combos**, **multi-account rotation**, **auto-fallback** and a
**token saver** — all managed from a local dashboard.

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the roadmap and current status.

```text
   Your client                         FlashRouter (localhost:20128)
  ─────────────                       ─────────────────────────────
  OpenAI SDK / Cursor / Cline  ──▶  /v1/chat/completions
  Claude Code / Anthropic SDK  ──▶  /v1/messages
  any OpenAI/Anthropic tool         │
                                     ├─ resolve "coding-fast" → combo
                                     ├─ pick an eligible account (rotation)
                                     ├─ RTK: compress huge tool outputs
                                     ├─ request provider #1 ──▶ 429 / 5xx / timeout
                                     ├─ fall back to provider #2 ──▶ 200 OK
                                     └─ stream back to the client, log usage
```

## Features

- **OpenAI + Anthropic endpoints** — `/v1/chat/completions`, `/v1/messages`,
  `/v1/messages/count_tokens`, `/v1/models`, `/v1/responses`.
- **Providers** — OpenRouter, Groq, DeepSeek, GLM, MiniMax, Mistral, Gemini
  (OpenAI endpoint), OpenAI, Together, Cerebras, Fireworks, NVIDIA, xAI,
  Ollama / LM Studio / llama.cpp, plus Anthropic-native presets for Anthropic,
  z.ai, MiniMax, DeepSeek and Kimi, or any custom compatible base URL.
- **Multiple accounts per provider** — weighted, priority-based rotation and
  automatic cooldown when an account is rate-limited or out of quota.
- **Combos** — ordered fallback chains selected by the model name clients send.
- **Auto-fallback** — on `429`, `401/403`, `402`, `5xx`, timeouts and connection
  failures it cools the account as needed and moves to the next eligible account
  or combo target. Fallback only happens before any response bytes reach the
  client, so a stream is never spliced with another model's output.
- **RTK token saver** — compresses large tool outputs (`git diff`, `grep`, `ls`,
  logs) before they are sent upstream. Fails open; never inflates a payload.
- **Prompt caching** — injects Anthropic `cache_control` breakpoints for clients
  that never send them, strips them from providers that do not accept them, and
  pins a conversation to one account so rotation does not scatter its cache.
- **Usage & cost tracking** — records input/output **and cache read/write tokens**,
  with per-model pricing, discounted cache-read rates, and automatic price import
  during discovery when the provider exposes it.
- **Dashboard** — providers, accounts, combos, models/pricing, API keys, request
  logs, usage, and settings (token-saver toggle, admin token, storage health).
- **Local & private** — SQLite storage, binds to `127.0.0.1` by default.

> Scope: FlashRouter speaks the **OpenAI Chat Completions API** and mirrors the
> **Anthropic Messages API** (`/v1/messages`) without translating between them.
> The provider you route to must expose the same API style. It does not
> translate Anthropic ↔ OpenAI payloads or Gemini-native protocols, and does
> not use subscription OAuth. Anything that talks OpenAI- or
> Anthropic-compatible HTTP works.

## Clone and run

Requires **Python 3.11+**. Node 18+ is only needed if you rebuild the dashboard.

### 1. Clone the repository

```bash
git clone https://github.com/RadinRavankhah/FlashRouter.git FlashRouter
cd FlashRouter
```

### 2. Install and start

#### Option A — one command (bootstraps a venv)

```bash
# Windows
flashrouter.cmd run
# macOS / Linux
./flashrouter run
```

The launcher creates `.venv`, installs the project, and starts the gateway.

#### Option B — standard install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -e .
flashrouter run
```

### 3. Open the dashboard

Open the URL printed by the CLI (**http://127.0.0.1:20128** by default).
The first-run walkthrough below configures a provider, account, combo, and API
key, after which any OpenAI- or Anthropic-compatible client can use it.

### Update an existing clone

Pull the latest code and restart:

```bash
git pull
flashrouter.cmd run        # Windows
# ./flashrouter run        # macOS / Linux
```

If dependencies changed, rerun `pip install -e .` in the environment you use
before restarting (the one-command launcher only installs when the project is not
yet importable). For the repo `.venv`:

```bash
# Windows
.venv\Scripts\pip install -e .
# macOS / Linux
.venv/bin/pip install -e .
```

Your database, config, and backups stay in the platform data directory
(see [Configuration](#configuration)) and survive updates.

## First-run walkthrough

1. **Connections → Add provider.** Pick a preset (or *Custom*), paste the base URL.
2. **Add account.** Paste your provider API key (leave blank for local servers).
   Add more accounts for rotation if you like. **Discover** then imports the
   provider's model list; when the provider includes pricing in its `/models`
   response (OpenRouter does), prices are filled in automatically.
3. **Combos → Create combo.** Give it a name such as `coding-fast` and add one or
   more `provider / model` targets. Requests try them top to bottom.
4. **Models → review prices.** Enter input/output prices per 1M tokens, plus an
   optional cache-read price so prompt-caching discounts show up in cost estimates.
   Search, filter by provider, and page through the catalog.
5. **API keys → Create key.** Copy the token.
6. Point an OpenAI-compatible client at `http://127.0.0.1:20128/v1` (or an
   Anthropic-compatible client at `http://127.0.0.1:20128`) with that token and
   use the combo name as the model.

## Connecting clients

Any OpenAI-compatible client works (Anthropic-compatible clients use the root
URL; see below). Example with the OpenAI Python SDK:

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

### Anthropic Messages / Claude Code

FlashRouter mirrors the Anthropic Messages API at the same host. The upstream
provider must expose an Anthropic-compatible `/v1/messages` endpoint (Anthropic
itself, or providers such as z.ai, MiniMax, DeepSeek and Kimi — several
Anthropic presets are built in). No payload translation is performed.

```python
from anthropic import Anthropic

client = Anthropic(
    api_key="YOUR_FLASHROUTER_KEY",
    base_url="http://127.0.0.1:20128",
)

response = client.messages.create(
    model="coding-fast",          # a combo name
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}],
)
print(response.content[0].text)
```

For Claude Code:

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:20128
export ANTHROPIC_API_KEY=YOUR_FLASHROUTER_KEY
# or: export ANTHROPIC_AUTH_TOKEN=YOUR_FLASHROUTER_KEY
```

Use a combo name (or `provider/model`) as the model. `count_tokens` calls are
passed through to the same upstream as well.

In GUI/CLI tools, set:

- **OpenAI base URL:** `http://127.0.0.1:20128/v1`
- **Anthropic base URL:** `http://127.0.0.1:20128`
- **API key:** a key from the dashboard (Bearer or `x-api-key`)
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
and falls back to the next eligible account or target. Client errors such as
`400`, `404` and `422` are returned as-is; it does not silently swap models for a
bad request.

## Usage, cache tokens, and cost

Every successful request and attempt stores the full token breakdown:

- **input tokens** — total prompt size;
- **output tokens** — completion tokens;
- **cache read tokens** — prompt tokens served from the provider's cache;
- **cache write tokens** — prompt tokens written to a cache, when reported.

FlashRouter reads the common OpenAI-compatible shapes:
`prompt_tokens_details.cached_tokens` (Chat), `input_tokens_details.cached_tokens`
(Responses), DeepSeek's `prompt_cache_hit_tokens`, and native Anthropic
`cache_read_input_tokens` / `cache_creation_input_tokens` from both
`/v1/messages` responses and streaming `message_start` / `message_delta`
events. Anthropic-style values are normalized so input always includes the
cached portion.

Cost is estimated per model from **Models → pricing** (USD per 1M tokens):

```text
uncached_input = input - cache_read - cache_write
cost = uncached_input × price_in
     + cache_read    × price_cache_in
     + cache_write   × price_cache_write   # defaults to 1.25 × price_in
     + output        × price_out
```

Leave the cache-read price blank to bill cached input at the normal input price.
Set it to the provider's discounted rate (for example `0.25` when cached input is
a quarter of the normal price) to see realistic savings. Leave the cache-write
price blank to use Anthropic's 1.25× 5-minute write rate, or set it to match a
provider that writes for free. Costs are still estimates, not billing.

## Prompt caching

DeepSeek, OpenAI and Gemini cache prompt prefixes automatically, so routed
traffic benefits with no configuration. Anthropic-compatible providers only
cache blocks marked with `cache_control`; if a client (for example an OpenAI-only
coding agent) never sends those markers, nothing is cached.

FlashRouter fills that gap. For Anthropic-protocol providers it injects up to
four breakpoints per request: the last system block and last cacheable tool (1h
when configured), the last assistant turn, and a tool loop's final `tool_result`
turn. Requests that already carry client markers are sanitized and capped at
four rather than rewritten. For OpenAI-shaped `/v1/chat/completions` requests it
marks the system and last assistant text blocks — but only when the provider is
opted in, because non-Anthropic upstreams may reject the field.

| Layer | Setting | Default |
|---|---|---|
| Request header | `x-flashrouter-cache: auto \| force \| off` | inherit |
| API key | **Prompt cache** + **Cache TTL** (Auto / Force / Off) | `auto` |
| Provider | **Cache markers** (`auto`, `anthropic`, `none`) + **Cache TTL** | `auto` |

- `auto` uses breakpoints only for `anthropic-messages` providers and strips
  them elsewhere. Use it for chat/testing keys where a one-off prompt should not
  pay the cache-write premium.
- `force` injects Anthropic breakpoints even through an OpenAI-compatible
  Claude proxy. Only enable it for proxies that preserve `cache_control`
  (verify with the provider Test button).
- `off` removes markers from the outgoing request.
- `1h` TTL survives long agent turns but writes cost 2× input; the default is
  5 minutes.

FlashRouter also pins a conversation to the account that served its previous
request for 10 minutes (keyed by `session_id`, `prompt_cache_key`, or the opening
system + user message), so weighted account rotation does not scatter a cache
across credentials. The RTK token saver is skipped while injection is active,
since rewriting historical tool output would invalidate the cached prefix.

Cache reads/writes still count toward the reported input usage; check the
request's outgoing payload to see exactly which breakpoints were sent.

**Discover** imports prices from the provider's `/models` payload when present
(OpenRouter most reliably; some Together/Fireworks entries too) and normalizes
them to USD per 1M tokens. Most providers (OpenAI, Groq, DeepSeek, Mistral, …)
return IDs only, so those models are added with zero prices and can be edited
manually. Re-running Discover fills prices for models that are still at zero and
does not overwrite existing non-zero prices.

Cache read tokens appear on the Overview (today's cache reads and hit rate), in
the Requests table, on each request/attempt detail, and in per-account counters.

## Token saver (RTK)

Large tool results are the biggest hidden token cost in agent workloads:
`git diff`, `grep`, `ls`, build logs and test output can dwarf the actual
conversation. The RTK (Reduced-Token-Kit-style) saver shrinks **only**
`role: "tool"` messages in `/v1/chat/completions` before they are sent upstream.
User, system and assistant text is never modified.

It runs three best-effort passes:

1. **ANSI strip** — removes terminal colour/escape sequences.
2. **Duplicate collapse** — consecutive identical lines become
   `... (N identical line(s) omitted)`.
3. **Smart truncate** — above 480 lines it keeps the first 160 and last 120 with
   an omission marker; above 24,000 characters it keeps the first and last halves
   with a character-count marker. Keeping both ends preserves the start of a diff
   and the final error/result.

Safety rules:

- Text shorter than 600 characters is left alone.
- If compression does not make the text strictly smaller, the original is used.
- The request body is deep-copied, so the client's payload and the streamed
  response are untouched.
- Fully **fail-open**: any error returns the original text unchanged.

The compressed body is what gets logged and sent on every fallback attempt, so
the request detail view always shows exactly what went upstream.

Enable or disable globally in **Settings** (stored in SQLite, overriding the
`token_saver = true` default in `[gateway]` or `FLASHROUTER_TOKEN_SAVER`). Override
per request with:

```http
X-FlashRouter-Token-Saver: off   # or: on
```

The header wins over the global setting. RTK is lossy and intentionally scoped to
chat completions — `/v1/responses`, `/v1/messages` and `/v1/messages/count_tokens`
are passed through untouched. It is also skipped when prompt-cache injection is
active for the request (see above), because rewriting tool output in the cached
prefix would invalidate the cache. It does not count tokens; savings are inferred
from the smaller payload, not measured.

## Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/chat/completions` | OpenAI Chat Completions (streaming + tools) |
| `POST` | `/v1/messages` | Anthropic Messages, passed through to an Anthropic-compatible upstream |
| `POST` | `/v1/messages/count_tokens` | Anthropic token counting, passed through |
| `POST` | `/v1/responses` | Pass-through for Responses-compatible upstreams |
| `GET` | `/v1/models` | Combos and catalog models (OpenAI and Anthropic listing shapes) |
| `GET` | `/healthz` | Liveness check |
| `GET` | `/` · `/dashboard` | Dashboard (static build in `ui/dist`) |
| `GET` | `/api/docs` | Interactive OpenAPI docs (and `/api/openapi.json`) |

Inference requests require `Authorization: Bearer <key>` (or `x-api-key`) once at
least one API key exists. The client credential is never forwarded upstream; the
selected account's secret is used instead. For `/v1/messages` it is sent as both
`x-api-key` and `Authorization: Bearer`, so native Anthropic and
Anthropic-compatible aggregators both work.

Errors use the OpenAI envelope on OpenAI endpoints:

```json
{ "error": { "message": "...", "type": "invalid_request_error", "code": "..." } }
```

and the Anthropic envelope on `/v1/messages`:

```json
{ "type": "error", "error": { "type": "not_found_error", "message": "..." } }
```

## Configuration

Configuration is optional — providers, accounts, combos, keys and the token-saver
toggle are managed from the dashboard. To change the bind address, timeouts, or
the optional admin token, copy `config.example.toml` to `config.toml` **inside the
data directory**, or point `--config` / `FLASHROUTER_CONFIG` at a file elsewhere:

```toml
[server]
host = "127.0.0.1"
port = 20128
log_level = "info"

[gateway]
token_saver = true
connect_timeout = 10.0
request_timeout = 300.0

[admin]
token = ""   # optional X-Admin-Token for /admin/api
```

The dashboard **Settings** token-saver toggle is stored in SQLite and overrides
the `token_saver` default above.

Data lives in the platform data directory:

- Windows: `%LOCALAPPDATA%\FlashRouter`
- macOS/Linux: `~/.local/share/flashrouter`

Override the data directory with `FLASHROUTER_DATA_DIR`; use `--config` or
`FLASHROUTER_CONFIG` to load a different TOML file. If you set
`FLASHROUTER_CONFIG` without `FLASHROUTER_DATA_DIR`, the config file's folder is
used as the data directory.

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
  providers/presets.py   built-in OpenAI- and Anthropic-compatible presets
  providers/pricing.py   upstream model-price extraction
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

`scripts/smoke_openai.py` exercises a running instance with the official OpenAI
SDK (models list, streaming, tool calls). It needs the `dev` extra:

```bash
python scripts/smoke_openai.py --api-key <flashrouter-key> --model <combo>
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

- No payload translation between API styles. `/v1/messages` only works when the
  selected provider exposes an Anthropic-compatible `/v1/messages` endpoint;
  `/v1/responses` is pass-through only. Gemini-native protocols are unsupported.
- There is no separate retry/backoff loop for the same upstream target; transient
  failures move on to the next eligible account or combo target.
- Costs are **estimates** based on optional per-model prices (USD per 1M tokens),
  including an optional discounted cache-read price. Intended as a savings tracker,
  not billing.
- Provider secrets are stored in the local SQLite database. This is a single-user
  local tool; bind to `127.0.0.1` and do not expose it publicly.

## License

MIT
