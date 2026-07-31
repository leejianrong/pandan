# syntax=docker/dockerfile:1
# Package the MCP server (V5, board-scoped in V10) as an OCI image (KAN-47) so an
# agent can `docker run` it with no local Python/uv. The server is a thin stdio
# adapter over the shared `pandan-client`, which lives in a SIBLING directory
# (../pandan-client) and is a uv *path* dependency — so BOTH mcp/ and
# pandan-client/ must be in the image and the docker BUILD CONTEXT must be the
# REPO ROOT, not mcp/:
#
#     docker build -f mcp/Dockerfile -t kanban-mcp .     # run from the repo root
#
# The `../pandan-client` path source is resolved at build time by `uv sync`,
# exactly as it is for a local `uv sync` in mcp/.
FROM python:3.12-slim AS runtime

# uv for fast, reproducible dependency installs (same pattern as the backend
# Dockerfile). Doing the sync in the final image (not a separate build stage)
# keeps the venv's interpreter and the runtime interpreter identical.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/mcp/.venv/bin:$PATH"

# The sibling path dep changes rarely — copy it first so its layer caches well.
COPY pandan-client/ ./pandan-client/
# Then the MCP project, and install against the lockfile (no dev group).
COPY mcp/ ./mcp/
WORKDIR /app/mcp
RUN uv sync --frozen --no-dev

# The MCP server speaks over stdio, so an agent launches it with `docker run -i`.
# It needs only PANDAN_API_URL / PANDAN_TOKEN / PANDAN_BOARD_ID at runtime.
ENTRYPOINT ["python", "-m", "pandan_mcp"]
