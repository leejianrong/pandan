# pandan-client

The shared, synchronous `httpx` wrapper over the Pandan REST API
(`/api/v1`). It is the **single source of truth** for talking to the API so the
thin adapters that sit on top of it — the [MCP server](../mcp) and (later) a CLI
— never drift (DRY; API-first, ADR 0005).

- `PandanClient(base_url, token=None, *, transport=None, timeout=...)` — one
  method per endpoint (boards / cards / epics CRUD + `move_card`). Config is
  passed in by the caller; this package reads **no environment**, so each adapter
  owns its own env parsing (`pandan_mcp.config`, etc.).
- `PandanApiError` — raised on any non-2xx response, carrying the API's own
  `detail` string plus a friendly hint for `401`/`403`.

## Consumed via a path dependency

`pandan-client` is a standalone `uv` package. `mcp` depends on it with a path
source (`[tool.uv.sources] pandan-client = { path = "../pandan-client", editable
= true }`), **not** a repo-root `uv` workspace — that keeps `backend/`, `mcp/`,
and `pandan-client/` each independently locked, so no package's
`uv run --frozen` flow is disturbed.

## Develop

```bash
cd pandan-client
uv sync                 # install deps (incl. dev group)
uv run ruff check .     # lint (matches the CI client job)
uv run pytest -q        # unit tests — every method vs. a mocked httpx transport
```
