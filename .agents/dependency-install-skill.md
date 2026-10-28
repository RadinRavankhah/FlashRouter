# FlashRouter dependency installation skill

When working in this repo (E:\Github\Personal\FlashRouter), do NOT attempt to install Python packages yourself. The virtual environment at `.venv\` may lack build tooling or network access for `pip install -e ".[dev]"` (build isolation needs setuptools which can fail offline).

Instead, ask the user to install dependencies with:

```
.venv\Scripts\python -m pip install fastapi httpx pydantic uvicorn aiosqlite pytest anyio ruff
```

If the package itself needs to be importable for tests, rely on `pyproject.toml`'s `pythonpath = ["src"]` — pytest adds `src/` to the path automatically. Do not run `pip install -e .` unless the user confirms network/build tooling is available.

Runtime deps: fastapi, httpx, pydantic, uvicorn, aiosqlite
Dev deps: pytest, anyio, ruff
