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
#
# BUILD INPUTS ARE FLOATING BY DEFAULT, PINNED PER RELEASE (KAN-475).
# The two ARGs below default to moving tags, so a plain
# `docker build -f mcp/Dockerfile .` from a checkout keeps working with no
# arguments. But a floating input means two builds of the SAME COMMIT can embed a
# different interpreter and a different uv — which would make KAN-452's
# `org.opencontainers.image.revision` label true-but-weaker-than-it-looks (the
# gate compares label values, so it cannot see a toolchain difference).
#
# `publish-mcp-image.yml` therefore RESOLVES both tags to immutable digests once
# per release, passes them here, and records them as labels on the image. So:
# floating for local dev, digest-pinned within a release, and always
# self-reporting which toolchain it actually got. We deliberately do NOT commit
# digest pins — see the KAN-475 note in mcp/README.md for why (short version:
# Dependabot cannot bump a `COPY --from` ref at all, so a committed pin here
# would have no watcher and would rot into a stale-security-patch).
ARG PYTHON_BASE=python:3.12-slim
ARG UV_SOURCE=ghcr.io/astral-sh/uv:latest

# `COPY --from=${UV_SOURCE}` does NOT work: BuildKit refuses variable expansion
# in `--from` ("variable expansion is not supported for --from") and points at
# exactly this workaround — name a stage whose FROM does the expansion, then copy
# out of the stage. Verified by building it both ways (KAN-475).
FROM ${UV_SOURCE} AS uvsource

FROM ${PYTHON_BASE} AS runtime

# uv for fast, reproducible dependency installs (same pattern as the backend
# Dockerfile). Doing the sync in the final image (not a separate build stage)
# keeps the venv's interpreter and the runtime interpreter identical.
COPY --from=uvsource /uv /uvx /bin/

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
