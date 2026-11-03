# FlashRouter — Roadmap & Session Status

> Living document. Update the **Status** and **Changelog** sections at the end of every
> work session so the next session can continue without re-discovery.

## Goal

A Python, local-first **OpenAI- and Anthropic-compatible LLM gateway** that is a
practical clone of [9router](https://github.com/decolua/9router): point Claude Code /
Codex / Cursor / Cline / any OpenAI or Anthropic SDK at `http://127.0.0.1:20128`
(`/v1` for OpenAI, root for Anthropic), and FlashRouter routes requests across
configured providers with **auto-fallback**, **multi-account rotation**, **token
saving**, and a **management dashboard**.

First-run experience target:

```bash
git clone <repo>
cd FlashRouter
./flashrouter run          # bootstrap launcher: creates .venv, installs, runs
# or: pip install -e .  &&  flashrouter run
```

Open `http://127.0.0.1:20128` → add a provider → create a combo → use `/v1`.

## Scope decisions (locked)

- **Endpoint mirroring, no translation.** OpenAI Chat Completions
  (`/v1/chat/completions`, `/v1/responses`) and Anthropic Messages
  (`/v1/messages`, `/v1/messages/count_tokens`) are proxied to the matching
  upstream endpoint. There is no payload translation between API styles and no
  Gemini-native protocol. Presets point at both OpenAI-compatible and
  Anthropic-compatible roots.
- **Legit only.** No subscription OAuth (Claude Code/Codex/Copilot/Cursor/Kiro). Provider
  plugin interface is left extensible for later.
- **Install UX:** standard `pip install -e .` + `flashrouter run`, plus one-command
  bootstrap launchers (`flashrouter.cmd` / `flashrouter.ps1` / POSIX `flashrouter`).
- **Dashboard:** React + Vite, redesigned, built `ui/dist` committed so runtime needs no Node.
- **Default port:** `20128`. Configurable via config/env/`--port`.
- **Storage:** SQLite (WAL) under the user data dir; versioned migrations.

## Core concepts

- **Provider** — an upstream base URL + protocol (`openai-chat` or
  `anthropic-messages`) + optional headers.
- **Account** — an API key (or no-auth) attached to a provider; multiple per provider;
  has `weight`, `priority`, `enabled`, `cooldown_until`, usage counters.
- **Model** — optional catalog entry per provider (`provider_id` + `model`), used for
  discovery/listing; request `model` can also be a raw `provider/model` or a combo name.
- **Combo** — ordered list of fallback targets `(provider, model)`; the value clients send
  as `model`. Fallback order = combo target order.
- **Client key** — bearer token clients authenticate with (`Authorization: Bearer ...`).
- **Request / Attempt / Payload / Usage** — full observability.

## Request lifecycle

1. Authenticate client key.
2. Resolve `model` → ordered candidate targets:
   combo name → `provider/model` → catalog entry → `404 model_not_found`.
3. For each candidate (fallback order):
   - Choose eligible account (enabled, not cooling, under quota): priority then weighted
     round-robin.
   - Apply RTK token saver to `role: "tool"` message content.
   - Dispatch to `base_url` + the mirrored endpoint (`/chat/completions`,
     `/responses`, `/messages`, `/messages/count_tokens`) with the account secret.
   - **Streaming:** pass through SSE incrementally; never buffer the whole response for
     the client.
4. Failure handling:
   - Before any bytes to client: retry transient (429 / 5xx / timeout / connect) with
     backoff + jitter, honor `Retry-After`; put account in cooldown on auth/quota; fall
     back to the next target.
   - After bytes streamed: abort/close only — never splice another model's output.
   - `400`-class = client error; surface, do not blindly swap models.
5. Persist request (before dispatch), attempts, payloads, usage/cost. Storage failures
   never break a response but are surfaced in health.

## Modules (target layout)

```
src/flashrouter/
  __init__.py            # single-source version
  __main__.py
  cli.py                 # run/doctor/backup/restore/reset-admin/version/open
  config.py              # minimal TOML + env: server, admin token, data dir, seeds
  app.py                 # FastAPI factory, lifespan, middleware, static/SPA
  errors.py              # OpenAI-style error envelopes
  logging.py             # operation logging + request ids
  providers/presets.py   # built-in OpenAI-compatible presets
  routing/engine.py      # resolve model -> candidates, account selection
  services/engine.py     # orchestration: proxy, fallback, logging, usage
  services/archive.py    # request export (JSONL/CSV) + archive-then-delete
  services/usage.py      # usage normalization + cost estimate
  savers/rtk.py          # tool_result compression
  storage/database.py    # aiosqlite connect + migrate
  storage/migrations.py  # schema versions
  storage/repository.py  # CRUD, request log, stats
  api/inference.py       # /v1/chat/completions, /v1/messages, /v1/models, /v1/responses
  api/admin.py           # /admin/api/*
  transport/http.py      # pooled httpx clients
  transport/headers.py   # header allowlist/filtering
  transport/urls.py      # safe URL joining
tests/                   # unit + integration (mock upstream) + e2e smoke
ui/                      # React/Vite dashboard -> committed ui/dist
docs/ROADMAP.md          # this file
```

## Admin API (localhost-only, origin/CSRF protected, optional admin token)

- `GET /admin/api/health`
- `GET/POST /admin/api/providers`, `PUT/DELETE /admin/api/providers/{id}`,
  `GET /admin/api/providers/presets`
- `POST /admin/api/providers/{id}/test`, `POST /admin/api/providers/{id}/discover`
- `GET/POST /admin/api/providers/{id}/accounts`, `PUT/DELETE /admin/api/accounts/{id}`,
  `GET .../accounts/{id}/reveal`, `POST .../accounts/{id}/test`
- `GET/POST /admin/api/combos`, `PUT/DELETE /admin/api/combos/{id}`
  (target order is the `targets` array on update)
- `GET/POST /admin/api/models`, `PUT/DELETE /admin/api/models/{id}` (pricing)
- `GET/POST /admin/api/keys`, `PUT/DELETE /admin/api/keys/{id}`,
  `GET .../keys/{id}/reveal`
- `GET /admin/api/requests` (free-text `q`, status, model substring, endpoint,
  provider, `key_id`, `account_id`, error type, `from`/`to`, sort, pagination),
  `GET /admin/api/requests/filters`, `GET /admin/api/requests/{id}`
- `GET /admin/api/requests/export` (JSONL/CSV download, same filters),
  `POST /admin/api/requests/purge` (dry-run by default; archives before deleting),
  `GET /admin/api/requests/exports/{file}`
- `GET /admin/api/stats` (overview, usage, cache reads, cost, success, timeseries)
- `GET/PUT /admin/api/settings`

## Milestones

| # | Scope | Status |
|---|---|---|
| M0 | Repo cleanup, CLI, bootstrap launchers, first-run boot | done |
| M1 | SQLite schema + migrations + repository; providers/accounts | done |
| M2 | Routing/fallback/accounts engine; logging + usage | done |
| M3 | Inference API (chat/models/responses) + RTK saver | done |
| M4 | Admin API (providers/accounts/combos/keys/requests/stats) | done |
| M5 | Dashboard redesign + committed dist | done |
| M6 | README rewrite, tests, ruff + tsc, version bump | done |
| M7 | Cache read/write token tracking, cache-aware pricing, Models page | done |
| M8 | Anthropic Messages pass-through (`/v1/messages`, `count_tokens`), presets, hybrid models | done |
| M9 | Prompt-cache injection, key/provider cache policy, cache affinity, cache-write pricing | done |
| M10 | Cache-optimized defaults, stable `prompt_cache_key`, 2x write pricing, discovery write prices | done |
| M11 | Lossless payload capture, request export, archive-then-delete, CLI | done |

## Archiving requests

Stored requests can be exported and removed without losing history:

- `GET /admin/api/requests/export?format=jsonl|csv` (plus the normal list filters)
  downloads one file; it does not delete anything. The dashboard offers JSONL and
  CSV as separate downloads.
- `POST /admin/api/requests/purge` always writes an archive first, then deletes
  exactly the exported ids. `format=both` writes JSONL and CSV from the same
  snapshot. `dry_run` defaults to `true`, `before` is required and exclusive, and
  pending requests are never deleted.
- Files land in `<data_dir>/exports/` and can be downloaded through
  `/admin/api/requests/exports/{file}` or moved with the CLI.
- CLI, usable with the server stopped:
  `flashrouter requests export --before YYYY-MM-DD [--format jsonl|csv|both]` and
  `flashrouter requests purge --before YYYY-MM-DD --yes [--format jsonl|csv|both]`.

JSONL is the full-fidelity format: each line is
`{"request": {...}, "attempts": [...], "payloads": [...], "payloads_included": bool}`.
Streamed responses store both a readable `response` payload and the exact
`response_raw` SSE frames. CSV is a flat one-row-per-request summary.

Since stats are computed live from `requests`, purged rows stop contributing to
all-time totals immediately. New payloads are stored without truncation by default
(`gateway.payload_max_chars = 0`); set a positive value to cap capture again.
Deletes reclaim space only after `VACUUM` (off by default in the API, `--vacuum`
in the CLI).

## Definition of done

`git clone` → `./flashrouter run` → dashboard at `:20128` → add provider → create combo →
OpenAI SDK and Claude Code (native `/v1/messages`) work with streaming + tool calls →
auto-fallback observable in request logs → usage/cost shown. `ruff` clean, `pytest` green,
`npm run build` succeeds and `ui/dist` is committed.

## Status

- **Phase:** M0–M11 complete.
- **Working now:**
  - New core package (config, storage/migrations, repository, providers presets,
    router, engine, RTK saver, usage).
  - `/v1/chat/completions` (stream + non-stream), `/v1/models`, `/v1/responses`
    pass-through, `/v1/messages` + `/v1/messages/count_tokens` pass-through,
    `/healthz`.
  - Anthropic-style streaming usage accounting and Anthropic error envelopes.
  - Hybrid `/v1/models` response usable by both OpenAI and Anthropic SDKs.
  - Auto-fallback across combo targets with account cooldown + weighted rotation.
  - Full admin API + redesigned React dashboard (built into `ui/dist`).
  - Cache read/write token tracking, per-model pricing (including cache-read price)
    and a Models page with search, provider filtering, and pagination.
  - Automatic Anthropic `cache_control` injection (system/tools/assistant/final tool
    results, four-breakpoint budget), provider cache-marker capability, per-key
    cache policy/TTL, cache-aware account affinity, and cache-write pricing
    (schema v5: `providers.cache_markers/cache_ttl`, `keys.cache_policy/cache_ttl`,
    `models.price_cache_write`). Automatic-cache providers get a stable hashed
    `prompt_cache_key` and 15-minute affinity; cache writes default to 2x input.
  - Provider discovery imports model prices when the upstream `/models` payload
    includes them.
  - Lossless payload capture (no 200k/64k caps by default; `payload_max_chars`
    opt-in cap), raw stream capture (`response_raw`), upstream error bodies stored,
    export/purge API + dashboard dialogs, and `flashrouter requests export|purge`.
  - CLI: run/doctor/backup/restore/reset-admin/requests/version/open + bootstrap launchers.
  - 111 tests passing; ruff clean; `ui` builds.
- **Known gaps / next:**
  - Add more tests (cooldown, admin CRUD, RTK edge cases, restore CLI).
  - No chat↔messages translation; `/v1/responses` and `/v1/messages` are
    pass-through only.
  - Cache affinity is in-memory (15-minute TTL, 1 hour for explicit 1h markers); it resets when the process restarts.
  - Payloads stored before session 11 remain truncated; recovery is impossible.
  - Version now `0.4.0`; bump to `1.0.0` when accepted.

## Changelog

- (session 1) Investigated repo; confirmed drift from 9router. Agreed scope: OpenAI-only,
  pip+bootstrap install, redesigned committed dashboard. Added this roadmap.
- (session 2) Full rewrite: new storage schema v2, repository, router, engine with
  fallback/streaming/usage, RTK saver, presets, inference + admin API, CLI + launchers,
  redesigned React dashboard, README. Removed legacy stubs and stale plan files.
  Backend + UI verified end-to-end against a mock upstream (21 tests green).
- (session 3) Fix startup crash on databases created by the old prototype: detect a
  legacy DB (no `flashrouter_meta`/`combo_targets`) and archive it to
  `flashrouter.legacy-<timestamp>.db` before creating the new schema. All DDL is now
  `IF NOT EXISTS`. Removed automatic browser launch from `flashrouter run` (the CLI
  prints the URL instead). Added migration/legacy tests (25 total).
- (session 4) Removed dead admin endpoints (`setup/status`, single provider/combo
  GETs) and the unused `by_model` stats query; de-duplicated `StatusBadge`; dropped
  the unused `--warn` CSS variable; marked the POSIX launcher executable; removed a
  stale `.agents` dependency note. Added schema v3 cache columns (`cache_read_tokens`,
  `cache_write_tokens`, `price_cache_in`), cache-aware usage extraction for
  OpenAI/Responses/DeepSeek/Anthropic-style payloads, discounted cost estimation,
  cache counters in the dashboard, and a Models pricing page (33 tests).
- (session 5) Models page now has search, provider filtering, and 25-per-page
  pagination; fixed the page background gradient so it stays put while scrolling.
  Discover imports upstream prices (OpenRouter `pricing.prompt`/`completion`,
  Together-style per-token values, generic per-1M values), normalizes them to USD
  per 1M, backfills unpriced models, and preserves manual prices. Added pricing
  parser unit tests and a discovery integration test (40 tests).
- (session 6) Added Anthropic Messages pass-through:
  `POST /v1/messages` and `/v1/messages/count_tokens` mirror the incoming API to
  `{base_url}/messages` with model remapping only. Dual `x-api-key`/Bearer auth,
  forwarded `anthropic-version`/`anthropic-beta` and `?beta=true`, Anthropic
  error envelopes, streaming usage capture (`message_start`/`message_delta`),
  hybrid `/v1/models`, `requests.endpoint` (schema v4) with dashboard filter,
  Anthropic-compatible presets, and a provider protocol selector (55 tests).
- (session 7) Fixed requests left blank on "pending"/"interrupted" in the dashboard.
  A client disconnect cancels the streaming response (Starlette/uvicorn spec 2.3),
  which aborted the cleanup awaits and skipped `finish_attempt`/`finish_request`;
  transport errors (`httpx.HTTPError`, pre-stream cancellations, unhandled
  exceptions) had the same effect. Stream/attempt bookkeeping is now shielded with
  `anyio.CancelScope(shield=True)`, disconnects are recorded as `interrupted` with
  `client_disconnect`, transport failures fall back to the next target and are
  recorded, and startup recovery backfills interrupted rows from their successful
  attempt instead of leaving them empty (59 tests).
- (session 8) Prompt caching for any client, any provider. Added
  `services/caching.py` (Anthropic breakpoint anchoring with a four-marker budget,
  OpenAI-shaped system/assistant markers, strip/passthrough modes), provider
  `cache_markers`/`cache_ttl`, per-key `cache_policy`/`cache_ttl`, the
  `x-flashrouter-cache` override, cache-aware account affinity (10-minute
  conversation pinning), RTK skipped while injection is active, and
  `models.price_cache_write` with a 1.25x input default (now 2x). Schema v5; 77 tests.
- (session 9) Made caching cache-optimized by default for every provider. `auto`
  now keeps automatic caching on OpenAI/DeepSeek/Gemini, adds a stable hashed
  `prompt_cache_key` (with 400 fallback), and pins conversations for 15 minutes
  (1 hour for explicit 1h markers); explicit `cache_control` remains opt-in for
  OpenAI-shaped proxies and automatic for Anthropic. RTK is skipped only when
  markers are injected. Cache writes now default to 2x input, and discovery
  imports cache-write prices when the provider exposes them. 83 tests.
- (session 10) Requests page search and filtering overhaul. The list endpoint
  now supports free-text metadata search (`q`, including attempt account/provider/
  error text), substring model matching, provider, account, error-type, key, and
  date-range filters, plus `newest`/`oldest`/`slowest`/`cost` sorting.
  Added `GET /admin/api/requests/filters` for observed filter values and schema v6
  indexes for the new filter columns. The dashboard gained URL-synced filters,
  300ms debounced search, filter chips, date presets/custom range, page-size
   selection, First/Prev/Next/Last pagination, and stale-request cancellation.
   95 tests.
- (session 11) Lossless payloads and request archiving. Removed the 200k payload and
   64k stream caps by default (new `gateway.payload_max_chars`, 0 = unlimited), store
   non-stream responses as raw text, record the exact SSE stream as `response_raw`,
   and persist upstream error bodies. Added `services/archive.py` with a temp-table
   id snapshot, JSONL/CSV export, archive-before-delete purging (dry-run by default,
   pending excluded, batched child/request deletes, optional VACUUM), the
   export/purge/exports admin endpoints, Requests-page Export and Clean up dialogs
   with separate JSONL/CSV downloads, and `flashrouter requests export|purge`.
   Clean-up writes both formats from one snapshot before deleting. 111 tests, ruff
   clean, `ui` builds.
