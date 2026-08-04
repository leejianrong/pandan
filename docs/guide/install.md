<!--
title: "Installation"
description: Install the pandan CLI from a prebuilt binary, with uv, or run the MCP server from a container image.
-->

# Installation

You do not have to install anything to use Pandan. The board runs in a browser, and if that is all
you need, go straight to the [user guide](tutorial/index.md).

Install the CLI when you want to drive the board from a terminal, a script, or a CI job. Install the
MCP server when you want an agent to drive it.

## Install the CLI

=== "Prebuilt binary"

    The release ships a single self-contained executable. No Python, no virtualenv.

    ```bash
    cd ~/Downloads    # anywhere outside a git checkout
    curl -L -o pandan https://github.com/leejianrong/pandan/releases/latest/download/pandan-linux-x86_64
    chmod +x pandan
    mv pandan ~/.local/bin/
    ```

    On an Apple Silicon Mac, swap the asset name:

    ```bash
    curl -L -o pandan https://github.com/leejianrong/pandan/releases/latest/download/pandan-macos-arm64
    ```

    The `releases/latest/download/…` URL always resolves to the newest release, so you can pin it in
    a Dockerfile without editing a version.

    !!! warning "Download outside your repository"

        The binary is about 15 MB. Run `curl` from a checkout and you drop 15 MB of untracked
        artifact into your working tree. Download it somewhere else, or delete it after the `mv`.

=== "uv"

    Needs Python and [uv](https://docs.astral.sh/uv/). `uv` clones the repository and resolves the
    sibling `pandan-client` dependency from the same checkout, so there is nothing to clone by hand.

    ```bash
    uv tool install "git+https://github.com/leejianrong/pandan.git#subdirectory=pandan-cli"
    ```

    This is the install path to pick on a platform with no prebuilt asset, including Intel Macs.

=== "Container"

    There is no CLI container image. The published image runs the *MCP server*, covered in
    [agents and MCP](agents/mcp-setup.md).

    If you want the CLI in a container, install the binary in your own Dockerfile:

    ```dockerfile
    RUN curl -L -o /usr/local/bin/pandan \
          https://github.com/leejianrong/pandan/releases/latest/download/pandan-linux-x86_64 \
     && chmod +x /usr/local/bin/pandan
    ```

### Check it worked

```console
$ pandan --version
pandan 0.22.0 (09882f5)
```

The parenthesised value is the git commit the binary was built from. A source checkout prints
`(source checkout, not a released build)` instead, which is how you tell a real release from a
development build.

!!! tip "`pandan` not found?"

    `~/.local/bin` has to be on your `PATH`. Check with `echo $PATH | tr ':' '\n' | grep local/bin`.
    If it is missing, add it to your shell profile:

    ```bash
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && exec bash
    ```

### Platform requirements

The Linux binary is built against glibc and needs **2.28 or newer**, which covers Ubuntu 20.04+,
Debian 11+, and RHEL / Rocky / Alma 8+. Check yours with `ldd --version`. On an older distribution,
or on Alpine (musl), install with `uv` instead.

Only `pandan-linux-x86_64` and `pandan-macos-arm64` are published. Intel Macs can run the arm64
binary under Rosetta 2, or install with `uv`.

!!! note "macOS Gatekeeper"

    The binary is not notarised, so the first run is blocked. Clear the quarantine flag once:

    ```bash
    xattr -d com.apple.quarantine ~/.local/bin/pandan
    ```

### Want a shorter command?

Symlink it to whatever you like:

```bash
ln -sf ~/.local/bin/pandan ~/.local/bin/pdn
```

A built-in `pdn` alias was tried and dropped. A console-script alias only works for installers that
generate one, and the release is a single executable, so it never existed on the install path these
docs lead with. A symlink works on both.

## Install the MCP server

Two options, neither of which needs the CLI. Both are covered properly in
[set up the MCP server](agents/mcp-setup.md), so this is just the summary:

- **Container.** Run `ghcr.io/leejianrong/pandan-mcp:latest`. No Python, no `uv`, no checkout.
- **From source.** `uv run --directory ./mcp python -m pandan_mcp` from a repository checkout.

## Recap

Install the binary, put it on your `PATH`, and confirm the version:

```bash
curl -L -o pandan https://github.com/leejianrong/pandan/releases/latest/download/pandan-linux-x86_64
chmod +x pandan && mv pandan ~/.local/bin/
pandan --version
```

Nothing is configured yet, so the CLI is still pointing at `http://localhost:8000`. Next,
[first steps](first-steps.md) points it at a real board and gets you authenticated.
