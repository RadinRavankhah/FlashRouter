# FlashRouter

**A local-first LLM router with automatic fallback, speaking the OpenAI and Anthropic APIs.**

Point any OpenAI-compatible client (OpenAI SDK, Cursor, Cline, OpenCode, Roo,
Continue, scripts…) **or any Anthropic-compatible client (Claude Code, Anthropic
SDK)** at one local endpoint and let FlashRouter route requests across your
providers with **combos**, **multi-account rotation**, **auto-fallback** and a
**token saver** — all managed from a local dashboard.

**Status:** `0.4.0` (pre-1.0). See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the roadmap and current status.

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
  z.ai, MiniMax, DeepSeek and Kimi, or any custom compatible base URL. Each
  provider can select the OpenAI Chat or Anthropic Messages protocol, send
  optional extra headers, set a priority, and declare its cache-marker support.
- **Multiple accounts per provider** — priority tiers with weighted rotation,
  per-account cooldown seconds, and automatic cooling when an account is
  rate-limited, unauthorized, or out of quota.
- **API key scopes** — restrict a key to specific combo/model names, and set a
  per-key prompt-cache policy and TTL.
- **Combos** — ordered fallback chains selected by the model name clients send.
  Individual targets and providers can be disabled without deleting them.
- **Auto-fallback** — on `429`, `401/403`, `402`, `5xx`, timeouts and connection
  failures it moves to the next eligible account or combo target. `429`,
  `401/403` and `402` also cool the account; `5xx`, timeouts and connection
  errors fall back without cooling. Fallback only happens before any response
  bytes reach the client, so a stream is never spliced with another model's
  output.
- **RTK token saver** — compresses large tool outputs (`git diff`, `grep`, `ls`,
  logs) before they are sent upstream. Fails open; never inflates a payload.
- **Prompt caching** — injects Anthropic `cache_control` breakpoints for clients
  that never send them, adds a stable `prompt_cache_key` for automatic-cache
  providers, and pins conversations to one account so rotation does not scatter
  their caches.
- **Usage & cost tracking** — records input/output **and cache read/write tokens**,
  with per-model pricing, discounted cache-read rates, cache-write pricing, and
  automatic price import during discovery when the provider exposes it.
- **Dashboard** — providers, accounts, combos, models/pricing, API keys, request
  search/filtering, request details, usage charts, and settings (token-saver
  toggle, browser-local admin token, storage health).
- **Local & private** — SQLite storage, binds to `127.0.0.1` by default, and the
  admin API is CSRF-protected with an optional shared admin token.

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
# Windows (PowerShell)
.\flashrouter.cmd run
# Windows (cmd.exe)
flashrouter.cmd run
# macOS / Linux
./flashrouter run
```

There is also a PowerShell-native launcher if you prefer it:
`.\flashrouter.ps1 run`. The launcher creates `.venv`, installs the project, and
starts the gateway.

#### Option B — standard install

```bash
python -m venv .venv
# Windows PowerShell: & .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
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
.\flashrouter.cmd run      # Windows PowerShell
flashrouter.cmd run        # Windows cmd.exe
./flashrouter run          # macOS / Linux
```

If dependencies changed, rerun `pip install -e .` in the environment you use
before restarting (the one-command launcher only installs when the project is not
yet importable). For the repo `.venv`:

```powershell
# PowerShell
& .venv\Scripts\python.exe -m pip install -e .
# macOS / Linux
.venv/bin/pip install -e .
```

Your database, config, backups, and request exports stay in the platform data
directory (see [Configuration](#configuration)) and survive updates.

## First-run walkthrough

1. **Connections → Add provider.** Pick a preset (or *Custom*), paste the base URL,
   choose the protocol (OpenAI Chat Completions or Anthropic Messages), and
   optionally add extra headers, a provider priority, and cache-marker settings.
2. **Add account.** Paste your provider API key (leave blank for local servers).
   Add more accounts for rotation if you like, with per-account weight, priority,
   and cooldown seconds. **Discover** then imports the provider's model list; when
   the provider includes pricing in its `/models` response (OpenRouter does),
   prices are filled in automatically.
3. **Combos → Create combo.** Give it a name such as `coding-fast` and add one or
   more `provider / model` targets. Requests try them top to bottom; disabled
   targets and disabled providers are skipped.
4. **Models → review prices.** Enter input/output prices per 1M tokens, plus
   optional cache-read and cache-write prices so prompt-caching costs show up in
   estimates. You can also add, edit, and remove catalog models here. Search,
   filter by provider, and page through the catalog.
5. **API keys → Create key.** Copy the token. Optionally restrict the key to
   specific combo names and choose its prompt-cache policy and TTL.
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
3. a **catalog model id** → all providers offering it, ordered by provider
   priority;
4. otherwise `404 model_not_found`.

If an API key has `allowed_combos` set, the requested model name must match one of
those entries before routing begins. Disabled combo targets and disabled
providers are skipped.

For each target, FlashRouter selects an eligible account (enabled, not cooling,
highest numeric priority first, then weighted rotation) and sends the request.
On `429`, `401/403` and `402` it cools the account and falls back. On `5xx`,
`408/504`, timeouts and connection errors it falls back without cooling. Lower
priority accounts remain available as fallbacks.

Client errors are returned as-is for `400`, `404` and `422`. Other non-retryable
4xx responses currently fall back to the next account or target, so prefer
`400/404/422` semantics when relying on a terminal client error.

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
     + cache_write   × price_cache_write   # defaults to 2 × price_in
     + output        × price_out
```

Leave the cache-read price blank to bill cached input at the normal input price.
Set it to the provider's discounted rate (for example `0.25` when cached input is
a quarter of the normal price) to see realistic savings. Leave the cache-write
price blank to bill writes at 2× input, or set it to match a provider that uses a
different rate. Costs are still estimates, not billing.

## Prompt caching

DeepSeek, OpenAI and Gemini cache prompt prefixes automatically. Anthropic-
compatible providers only cache blocks marked with `cache_control`; if a client
(for example an OpenAI-only coding agent) never sends those markers, nothing is
cached.

FlashRouter is cache-optimized by default for every provider:

- **Anthropic-compatible providers** get up to four `cache_control` breakpoints:
  the last system block and last cacheable tool (1h when configured), the last
  assistant turn (or the final message on the first turn), and a tool loop's
  final `tool_result` turn. Requests that already carry client markers in an
  Anthropic-shaped body are sanitized and capped at four.
- **Non-Anthropic providers** under `auto` have client `cache_control` markers
  stripped so the request stays valid, unless `cache_markers=anthropic` opts them
  in or `force` is used. `off` strips markers everywhere.
- **OpenAI-compatible providers** keep their automatic caching, receive a stable
  hashed `prompt_cache_key` (for `chat/completions` and `responses`), and are
  pinned to the account that last served the conversation. If an upstream rejects
  the key, FlashRouter retries without it and stops sending it to that provider.
- Provider `cache_markers=anthropic` opts an OpenAI-shaped proxy into explicit
  `cache_control` markers. Only enable it for proxies that preserve
  `cache_control`. `cache_markers=none` disables explicit markers and the
  `prompt_cache_key` hint under `auto` (a key/request `force` override still
  injects).

| Layer | Setting | Default |
|---|---|---|
| Request header | `x-flashrouter-cache: auto \| force \| off` (cacheable endpoints) | inherit |
| Model | **Prompt cache** (Auto / Force / Off) + **Cache TTL** | `auto` |
| API key | **Prompt cache** + **Cache TTL** (Auto / Force / Off) | `auto` |
| Provider | **Cache markers** (`auto`, `anthropic`, `none`) + **Cache TTL** | `auto` |

- `auto` uses explicit markers for Anthropic-capable providers (and for providers
  whose `cache_markers` is `anthropic`); everything else gets automatic-cache
  optimization (`prompt_cache_key`, affinity, stable prefix).
- `force` injects `cache_control` markers even through an OpenAI-compatible
  provider, using that provider's request shape. Only enable it for upstreams
  that preserve `cache_control`.
- `off` removes markers and disables the routing hint and account affinity.
- A model set to `off` is a hard off: it wins over key and request overrides, and
  FlashRouter also removes cache-related HTTP headers and any client-supplied
  `prompt_cache_key` from the upstream request.
- `1h` TTL survives long agent turns; it applies to the head anchors (system and
  tools). The tail marker stays at 5 minutes. The default overall TTL is 5
  minutes. Model TTL wins over key and provider TTL.

FlashRouter pins a conversation to the account that served its previous request
for 15 minutes (1 hour when explicit 1h marker injection is active), keyed by
`session_id`, `prompt_cache_key`, or the opening system + first non-system
message. This keeps weighted rotation from scattering a cache across credentials.
Affinity is in-memory and resets when the process restarts. The RTK token saver
still runs for automatic-cache providers; it is skipped only when explicit marker
injection is active.

Cache reads/writes still count toward the reported input usage; check the
request's outgoing payload to see the exact breakpoints and `prompt_cache_key`.

**Discover** imports prices from the provider's `/models` payload when present
(OpenRouter most reliably; some Together/Fireworks entries too) and normalizes
them to USD per 1M tokens, including cache-read and cache-write prices when
exposed. Most providers (OpenAI, Groq, DeepSeek, Mistral, etc.) return IDs only, so
those models are added with zero prices and can be edited manually. Re-running
Discover fills prices only for models whose input and output prices are both
still zero, and does not overwrite existing non-zero prices.

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
X-FlashRouter-Token-Saver: off   # or: on / true / false / 1 / 0 / yes / no
```

The header wins over the global setting. RTK is lossy and intentionally scoped to
chat completions - `/v1/responses`, `/v1/messages` and `/v1/messages/count_tokens`
are passed through untouched. It is skipped when explicit prompt-cache marker
injection is active, because rewriting historical tool output could invalidate
the cached prefix. Automatic-cache providers still get RTK compression. It does
not count tokens; savings are inferred from the smaller payload, not measured.

## Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/chat/completions` | OpenAI Chat Completions (streaming + tools) |
| `POST` | `/v1/messages` | Anthropic Messages, passed through to an Anthropic-compatible upstream |
| `POST` | `/v1/messages/count_tokens` | Anthropic token counting, passed through |
| `POST` | `/v1/responses` | Pass-through for Responses-compatible upstreams |
| `GET` | `/v1/models` | Combos and catalog models (OpenAI and Anthropic listing shapes) |
| `GET` | `/healthz` | Liveness check (includes the running version) |
| `GET` | `/` · `/dashboard` | Dashboard (static build in `ui/dist`) |
| `GET` | `/api/docs` | Interactive OpenAPI docs (and `/api/openapi.json`) |
| `*` | `/admin/api/*` | Dashboard/admin API (localhost-oriented, CSRF-protected, optional admin token) |

Inference requests, including `GET /v1/models`, require
`Authorization: Bearer <key>` (or `x-api-key`) once at least one API key exists.
The client credential is never forwarded upstream; the selected account's secret
is used instead. Only the client's `anthropic-version` and `anthropic-beta`
headers are forwarded on `/v1/messages`. The account secret is sent as both
`x-api-key` and `Authorization: Bearer`, so native Anthropic and
Anthropic-compatible aggregators both work. Responses include an
`X-FlashRouter-Request-ID` header for troubleshooting.

Errors use the OpenAI envelope on OpenAI endpoints:

```json
{ "error": { "message": "...", "type": "invalid_request_error", "code": "..." } }
```

and the Anthropic envelope on `/v1/messages` and `/v1/messages/count_tokens`:

```json
{ "type": "error", "error": { "type": "not_found_error", "message": "..." } }
```

## Requests and archiving

The dashboard **Requests** page lists every dispatched request with free-text
search (`q`), status, endpoint, provider, API-key, account, error-type, and
date-range filters, plus sorting by newest, oldest, slowest, or highest cost.
Stats are computed live from the request log, so deleted rows stop counting
immediately.

The same page can export the current filtered set as JSONL and CSV separately
(optionally excluding payload bodies), and **Clean up** archives both formats
from one snapshot, then deletes requests older than the chosen cutoff. It
requires a preview and typing `DELETE` to confirm, and can optionally `VACUUM`
the database afterwards.

- The archive is always written before anything is deleted. Files live in
  `<data_dir>/exports/` and remain downloadable from the dashboard.
- Pending requests are never deleted. The API defaults to a dry run; the CLI
  requires `--yes` to delete.
- JSONL is the full-fidelity format (`request`, `attempts`, and `payloads`
  including raw stream frames); CSV is a flat one-row-per-request summary.
  The dashboard Clean up dialog writes both formats; the API and CLI default to
  JSONL unless `format=both` / `--format both` is requested.
- New payloads are stored without truncation by default. Set
  `gateway.payload_max_chars` (or `FLASHROUTER_PAYLOAD_MAX_CHARS`) to a positive
  value to cap large prompts/responses again.

## Configuration

Configuration is optional — providers, accounts, combos, models/pricing, keys and
the token-saver toggle are managed from the dashboard. To change the bind
address, timeouts, or the optional admin token, copy `config.example.toml` to
`config.toml` **inside the data directory**, or point `--config` /
`FLASHROUTER_CONFIG` at a file elsewhere:

```toml
[server]
host = "127.0.0.1"
port = 20128
log_level = "info"

[gateway]
token_saver = true
connect_timeout = 10.0
request_timeout = 300.0
payload_max_chars = 0   # 0 = store full prompts/responses

[admin]
token = ""   # optional X-Admin-Token for /admin/api
```

The dashboard **Settings** token-saver toggle is stored in SQLite and overrides
the `token_saver` default above. The same page stores the admin token in the
browser only; if `[admin] token` / `FLASHROUTER_ADMIN_TOKEN` is set, enter it
there to use the dashboard. `/admin/api/health` is exempt from the token check.
Admin writes are also CSRF-protected by comparing the `Origin`/`Referer` header
against the request host.

Data lives in the platform data directory:

- Windows: `%LOCALAPPDATA%\FlashRouter`
- macOS/Linux: `~/.local/share/flashrouter`

Override the data directory with `FLASHROUTER_DATA_DIR`; use `--config` or
`FLASHROUTER_CONFIG` to load a different TOML file. When the file named by
`FLASHROUTER_CONFIG` exists and `FLASHROUTER_DATA_DIR` is unset, the config
file's folder is used as the data directory. A path passed with `--config` does
not move the data directory.

Environment overrides: `FLASHROUTER_HOST`, `FLASHROUTER_PORT`,
`FLASHROUTER_LOG_LEVEL`, `FLASHROUTER_DATA_DIR`, `FLASHROUTER_CONFIG`,
`FLASHROUTER_ADMIN_TOKEN`, `FLASHROUTER_TOKEN_SAVER`,
`FLASHROUTER_PAYLOAD_MAX_CHARS`.

## CLI

```bash
flashrouter                # same as `flashrouter run`
flashrouter run --host 127.0.0.1 --port 20128 --log-level info
flashrouter doctor         # inspect config/storage
flashrouter doctor --probe # also test each provider's /models endpoint
flashrouter backup         # write a consistent SQLite backup
flashrouter restore <file> # restore (saves the current DB first)
flashrouter reset-admin    # delete client keys + settings
flashrouter reset-admin --all  # also delete providers, accounts, combos, models
flashrouter requests export --before 2026-01-01   # export without deleting
flashrouter requests export --before 2026-01-01 --format both
flashrouter requests purge --before 2026-01-01 --yes  # archive then delete
flashrouter requests purge --before 2026-01-01 --yes --format both
flashrouter open           # open the dashboard
flashrouter version
```

`requests export` and `requests purge` also accept the request filters
`--status`, `--model`, `--key-id`, `--account-id`, `--endpoint`, `--provider`,
`--error-type`, `--q`, `--from`, and `--to`. Both support `--output` (a file for
export, a folder for purge) and `--no-payloads` (metadata-only JSONL).
`requests purge` defaults to JSONL,
supports `--dry-run`, requires `--yes` to delete, and accepts `--vacuum` to
reclaim disk space. `--before` is a required, exclusive UTC cutoff. Note that
`reset-admin --all` does **not** delete request history, attempts, payloads, or
usage records.

## Project layout

```text
src/flashrouter/
  __init__.py            single-source version
  __main__.py            python -m flashrouter entry point
  app.py                 FastAPI factory, middleware, static dashboard
  cli.py                 command-line entry point
  config.py              optional TOML + env configuration
  errors.py              OpenAI/Anthropic error envelopes
  logging.py             operation logging + request IDs
  providers/presets.py   built-in OpenAI- and Anthropic-compatible presets
  providers/pricing.py   upstream model-price extraction
  routing/engine.py      model resolution + account selection
  services/engine.py     request orchestration, fallback, streaming, logging
  services/caching.py    prompt-cache policy + cache_control injection
  services/archive.py    request export (JSONL/CSV) + archive-then-delete
  services/usage.py      usage normalization + cost estimate
  savers/rtk.py          tool-output compression
  storage/               SQLite schema, migrations, repository
  api/inference.py       /v1 endpoints
  api/admin.py           dashboard/admin API
  transport/http.py      pooled httpx clients
  transport/headers.py   header allowlist/filtering
  transport/urls.py      safe URL joining
ui/                      React + Vite dashboard (built into ui/dist)
tests/                   unit + integration tests (mock upstream)
scripts/smoke_openai.py  end-to-end smoke test with the OpenAI SDK
flashrouter               POSIX bootstrap launcher
flashrouter.cmd          Windows cmd.exe bootstrap launcher
flashrouter.ps1          Windows PowerShell bootstrap launcher
config.example.toml      optional configuration example
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
# Windows PowerShell:
& .venv\Scripts\pytest.exe -q
```

`scripts/smoke_openai.py` exercises a running instance with the official OpenAI
SDK (models list, streaming, tool calls). It needs the `dev` extra:

```bash
python scripts/smoke_openai.py --api-key <flashrouter-key> --model <combo>
```

It also reads `FLASHROUTER_BASE_URL` (default
`http://127.0.0.1:20128/v1`), `FLASHROUTER_API_KEY`, and `FLASHROUTER_MODEL`
(default `coding-fast`).

Rebuild the dashboard after UI changes (the built `ui/dist` is committed so the
server does not need Node):

```bash
cd ui
npm install
npm run build      # tsc --noEmit && vite build
npm run typecheck  # type-check only
```

## Troubleshooting

- **Port already in use** — `flashrouter run --port 20228`.
- **401 from the gateway** — use a key created in *API keys*, not your upstream key.
- **404 model_not_found** — create a combo with that name, or use `provider/model`.
- **401 admin_token_required** — the server has `FLASHROUTER_ADMIN_TOKEN` (or
  `[admin] token`) set. Enter it in **Settings → Admin token**; it is stored in
  this browser only.
- **Anthropic request fails with 400/404** — the selected provider must use the
  `anthropic-messages` protocol and expose an Anthropic-compatible `/v1/messages`
  endpoint. OpenAI-compatible providers cannot serve `/v1/messages` by
  translation.
- **Upstream 429/403** — the provider key/quota; check the account in *Connections*.
  FlashRouter will cool it down and fall back automatically.
- **No dashboard** — build it once with `cd ui && npm install && npm run build`.

## Limitations

- No payload translation between API styles. `/v1/messages` only works when the
  selected provider exposes an Anthropic-compatible `/v1/messages` endpoint;
  `/v1/responses` is pass-through only. Gemini-native protocols are unsupported.
- There is no separate retry/backoff loop for the same upstream target; transient
  failures move on to the next eligible account or combo target.
- Cache affinity (conversation-to-account pinning) is in-memory. It resets when
  the process restarts.
- Payloads stored before the lossless-capture change may still be truncated;
  older truncation cannot be recovered.
- The admin API is a localhost-oriented, single shared-token surface, not
  multi-user authentication. Keep the bind address on `127.0.0.1` unless you add
  your own access control.
- Costs are **estimates** based on optional per-model prices (USD per 1M tokens),
  including optional cache-read and cache-write prices. Intended as a savings
  tracker, not billing.
- Provider secrets are stored unencrypted in the local SQLite database. This is a
  single-user local tool; bind to `127.0.0.1` and do not expose it publicly.

## License

MIT
