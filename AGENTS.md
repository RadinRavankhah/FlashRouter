# AGENTS.md

Project: FlashRouter — a local-first OpenAI-compatible LLM router (Python/FastAPI + React dashboard).
See `docs/ROADMAP.md` for the current plan and session status.

## Environment

- Python **3.11+** (tests run on 3.12). Use the repo virtualenv: `.venv`.
- Node **18+** only needed to rebuild the dashboard.

## Commands

```bash
# Backend
.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Windows
pytest                                                 # run tests
ruff check .                                           # lint

# Dashboard (built ui/dist is committed so runtime needs no Node)
cd ui && npm install && npm run build                  # tsc --noEmit && vite build
```

Windows PowerShell uses `& .venv\Scripts\pytest.exe -q` etc.

## Layout

- `src/flashrouter/` — FastAPI app, CLI, config, storage, routing, engine, savers.
- `ui/` — React + Vite dashboard; production build in `ui/dist`.
- `tests/` — unit + integration (mock upstream via `httpx.MockTransport`).
- `docs/ROADMAP.md` — keep updated at the end of each session.

## Conventions

- Scope is **OpenAI-compatible providers only** (no Anthropic/Gemini-native translation).
- Never forward client `Authorization`/cookies upstream; use the selected account secret.
- Fall back to another target only **before** any bytes are streamed to the client.
- Cost values are estimates, not billing. Cost uses per-model input/output prices
  plus an optional discounted `price_cache_in`; cache tokens are subsets of input.
