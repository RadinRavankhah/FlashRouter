# FlashRouter — Roadmap & Session Status

> Living document. Update the **Status** and **Changelog** sections at the end of every
> work session so the next session can continue without re-discovery.

## Goal

A Python, local-first **OpenAI-compatible LLM gateway** that is a practical clone of
[9router](https://github.com/decolua/9router): point Claude Code / Codex / Cursor / Cline /
any OpenAI SDK at `http://127.0.0.1:20128/v1`, and FlashRouter routes requests across
configured providers with **auto-fallback**, **multi-account rotation**, **token saving**,
and a **management dashboard**.

First-run experience target:

```bash
git clone <repo>
cd FlashRouter
./flashrouter run          # bootstrap launcher: creates .venv, installs, runs
# or: pip install -e .  &&  flashrouter run
```

Open `http://127.0.0.1:20128` → add a provider → create a combo → use `/v1`.

## Scope decisions (locked)

- **OpenAI-compatible providers only.** No Anthropic/Gemini native protocol translation.
  Presets point at providers' OpenAI-compatible endpoints (OpenRouter, Groq, DeepSeek,
  GLM/Zhipu, MiniMax, Mistral, Google Gemini OpenAI endpoint, Together, Cerebras, OpenAI,
  local llama.cpp/LM Studio/Ollama, custom OpenAI-compatible).
- **Legit only.** No subscription OAuth (Claude Code/Codex/Copilot/Cursor/Kiro). Provider
  plugin interface is left extensible for later.
- **Install UX:** standard `pip install -e .` + `flashrouter run`, plus one-command
  bootstrap launchers (`flashrouter.cmd` / `flashrouter.ps1` / POSIX `flashrouter`).
- **Dashboard:** React + Vite, redesigned, built `ui/dist` committed so runtime needs no Node.
- **Default port:** `20128`. Configurable via config/env/`--port`.
- **Storage:** SQLite (WAL) under the user data dir; versioned migrations.

## Core concepts

- **Provider** — an upstream base URL + protocol (`openai-chat`) + optional headers.
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
   - Dispatch to `base_url` + `/chat/completions` (or `/responses`) with account secret.
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
  services/usage.py      # usage normalization + cost estimate
  savers/rtk.py          # tool_result compression
  storage/database.py    # aiosqlite connect + migrate
  storage/migrations.py  # schema versions
  storage/repository.py  # CRUD, request log, stats
  api/inference.py       # /v1/chat/completions, /v1/models, /v1/responses
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
- `GET /admin/api/requests`, `GET /admin/api/requests/{id}`
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

## Definition of done

`git clone` → `./flashrouter run` → dashboard at `:20128` → add provider → create combo →
OpenAI SDK / Claude Code (via OpenAI endpoint) works with streaming + tool calls →
auto-fallback observable in request logs → usage/cost shown. `ruff` clean, `pytest` green,
`npm run build` succeeds and `ui/dist` is committed.

## Status

- **Phase:** M0–M7 complete.
- **Working now:**
  - New core package (config, storage/migrations, repository, providers presets,
    router, engine, RTK saver, usage).
  - `/v1/chat/completions` (stream + non-stream), `/v1/models`, `/v1/responses`
    pass-through, `/healthz`.
  - Auto-fallback across combo targets with account cooldown + weighted rotation.
  - Full admin API + redesigned React dashboard (built into `ui/dist`).
  - Cache read/write token tracking, per-model pricing (including cache-read price)
    and a Models page with search, provider filtering, and pagination.
  - Provider discovery imports model prices when the upstream `/models` payload
    includes them.
  - CLI: run/doctor/backup/restore/reset-admin/version/open + bootstrap launchers.
  - 40 tests passing; ruff clean; `ui` builds.
- **Known gaps / next:**
  - Add more tests (cooldown, admin CRUD, RTK edge cases, restore CLI).
  - `/v1/responses` is pass-through only (no chat↔responses translation).
  - Version still `0.3.0`; bump to `1.0.0` when accepted.

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
