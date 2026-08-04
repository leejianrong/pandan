<!--
title: "Releases"
description: Where to find Pandan releases, how CLI versioning works, and how to tell which build you are running.
-->

# Releases

## Where they are

**[github.com/leejianrong/pandan/releases](https://github.com/leejianrong/pandan/releases)**

Each release publishes two CLI binaries:

| Asset | Platform |
| --- | --- |
| `pandan-linux-x86_64` | Linux, glibc 2.28 or newer |
| `pandan-macos-arm64` | macOS on Apple Silicon |

There is no Intel Mac binary. Run the arm64 one under Rosetta 2, or install with `uv`. See
[installation](../install.md).

The `releases/latest/download/<asset>` URL always resolves to the newest release, which is convenient in a
Dockerfile and worth pinning in a pipeline you want to be reproducible.

## Which build am I running

```console
$ pandan --version
pandan 0.22.0 (09882f5)
```

The value in brackets is the git commit the binary was built from, so you can check exactly what is in it.
A build from a source checkout says so explicitly instead:

```
pandan 0.22.0 (source checkout, not a released build)
```

That distinction exists so a stale binary is detectable. If someone reports behaviour that does not match
these docs, `pandan --version` is the first thing to ask for.

!!! tip "Verify the download actually worked"

    A `curl` without `-f` writes an error page to the output file, and `chmod +x` makes it executable, so
    the failure surfaces later as a confusing execution error. Run `pandan --version` straight after
    installing.

## The MCP image

The MCP server ships as a container image:

```
ghcr.io/leejianrong/pandan-mcp:latest
```

It is public, so `docker pull` needs no login. Tags track the release, so pin a version for a stable
setup rather than tracking `latest`.

!!! note "An older image path still exists"

    Images published before the rename live at `ghcr.io/leejianrong/simple-kanban-mcp`. That path still
    works, but new releases go to `pandan-mcp`. Use the new one.

## Versioning

The CLI carries its own version, separate from the application. A change to CLI behaviour must bump it,
enforced by both a local pre-push hook and a CI check, with no override flag.

That strictness is on purpose. The whole value of printing a build commit is that a stale binary is
detectable, and an unbumped version silently breaks that.

The API is versioned by its path prefix, `/api/v1`. A breaking change would go to a new prefix rather than
altering `v1` underneath existing clients.

## What is not in a release

**The application itself is not released as a versioned artifact.** It is deployed continuously from the
default branch, so the hosted board runs whatever last passed CI. To self-host a specific state, build the
image from a commit you choose.

**Database migrations are not versioned separately.** They are applied in order with Alembic, and the schema
is whatever `alembic upgrade head` produces for the code you deployed.

## Upgrading the CLI

Same command as installing. It overwrites in place:

```bash
curl -L -o pandan https://github.com/leejianrong/pandan/releases/latest/download/pandan-linux-x86_64
chmod +x pandan && mv pandan ~/.local/bin/
pandan --version
```

With `uv`:

```bash
uv tool upgrade pandan-cli
```

Your configuration is untouched by an upgrade. `~/.config/pandan/config.toml` is written by the CLI but
never replaced by installing a new one.
