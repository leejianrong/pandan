"""Ambient board context for an agent session (V48, KAN-431 — AXI 7).

The idea: an agent shouldn't have to *ask* what's on the board before it can act.
`pandan context install` wires a **Claude Code `SessionStart` hook** into a
`settings.json`, so every new session starts with the default board's open cards
and per-column counts already in the model's context. `pandan context show
--hook` is what that hook runs.

Verified hook contract (docs + the shipped schema, not inferred)
---------------------------------------------------------------
* Event name is **``SessionStart``**. It is in the ``hooks`` propertyNames enum of
  ``claude-code-settings.schema.json`` (shipped with the Claude Code VS Code
  extension), and https://code.claude.com/docs/en/hooks lists it as "When a
  session begins or resumes".
* Config shape is ``{"hooks": {"SessionStart": [{"hooks": [{"type": "command",
  "command": …, "timeout": …}]}]}}``. Per the schema, only ``type`` + ``command``
  are required on a hook and ``timeout`` is a **number of seconds**
  (``exclusiveMinimum: 0``). ``matcher`` is **optional**, and the docs' own
  ``SessionStart`` example omits it — an omitted matcher fires for every source
  (``startup`` / ``resume`` / ``clear`` / ``compact`` / ``fork``). We omit it: a
  freshly compacted session needs the board state at least as much as a new one.
* **stdout on exit 0 reaches the model.** The docs are explicit: "For
  ``UserPromptSubmit``, ``UserPromptExpansion``, and ``SessionStart``, … stdout is
  added as context that Claude can see and act on", and JSON output is parsed on
  exit 0. We emit the structured form,
  ``{"hookSpecificOutput": {"hookEventName": "SessionStart",
  "additionalContext": …}}``.
* A ``SessionStart`` hook **cannot block** the session (the docs' can-block column
  reads "No"; exit 2 only renders stderr in the transcript). But it *is* awaited —
  its output has to land before the first prompt — so it can absolutely **delay**
  one, and the default command-hook timeout is **600 seconds**.

Which is why the soft-fail path is the design, not an edge case
--------------------------------------------------------------
This project's backend is on a free tier that scales to zero (KAN-25/KAN-45): the
first request after ~5 minutes idle can read-timeout or die with a TLS
``UNEXPECTED_EOF``, indistinguishable from the host being down, and the shared
``PandanClient`` deliberately rides that out with a **35 s** read timeout plus an
automatic retry (``pandan_client/client.py:34-39``) — a ~76-second worst case.
Inherit those defaults in a session hook and every agent session on a cold board
hangs. So:

* ``show --hook`` builds its own client with a **tight, halved** per-request
  timeout and **no retry backoff**, so the total stays inside ``--timeout``
  (default ``5.0`` s).
* ``show --hook`` **never** exits non-zero and **never** writes anything to stdout
  but a valid envelope. A failure is one line on stderr, which exit 0 discards.
  (An error row on stdout would otherwise be *injected into the model's context*
  as fake board state — worse than no context at all.)
* ``install`` additionally writes an explicit ``timeout`` into the hook entry, a
  small margin above the CLI's own budget, so even a wedged process is capped by
  the harness at seconds instead of ten minutes.

Everything here is a ``local_func`` handler (see ``cli.run``): the four verbs own
their own printing and their own client, precisely so ``show --hook`` can opt out
of the CLI's normal "structured error on stdout" contract (V43, KAN-426) that the
shared ``_emit`` path would impose.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any

from pandan_client import PandanClient

from . import __version__
from .build_info import BUILD_SHA
from .config import resolve_values

# The hook event we install into. Verified against the shipped settings schema's
# `hooks` propertyNames enum — a typo here would silently never fire.
HOOK_EVENT = "SessionStart"

# Total wall-clock budget for the hook's API work, in seconds. Deliberately far
# below the shared client's cold-start-friendly 35 s: a session hook trades
# completeness for never making a human wait. A cold board simply yields no
# ambient block that session.
DEFAULT_HOOK_TIMEOUT = 5.0

# Extra seconds handed to the harness-level `timeout` on top of our own budget,
# so the two caps can't race: ours should always fire first.
HOOK_TIMEOUT_MARGIN = 2.0

# Max open cards listed in the ambient block. Bounded on purpose — this text is
# prepended to every session, so it must not scale with the backlog.
DEFAULT_CARD_LIMIT = 20

# Cards fetched in the single request the block costs. Counts are computed from
# this page; a board bigger than this is reported as truncated rather than
# paginated (another round trip would double the timeout budget).
_FETCH_LIMIT = 200

# The open columns, in the order they're listed.
_OPEN_COLUMNS = ("in_progress", "todo")

# The substring that identifies a hook entry as **ours**, in any settings file.
# It is guaranteed to appear in every command we generate (``_hook_command``
# always appends these three tokens, and ``shlex.quote`` leaves bare tokens
# alone), which is what makes install idempotent and uninstall exact. Matching on
# a fragment of our own command line beats a magic comment key: the schema
# requires only ``type``/``command``, so a custom marker key isn't guaranteed to
# survive a settings round-trip.
HOOK_SENTINEL = "context show --hook"

# Where the packaged skill is laid down, relative to the Claude config dir.
_SKILL_RELPATH = Path("skills") / "pandan" / "SKILL.md"


# --- paths ------------------------------------------------------------------


def claude_config_dir() -> Path:
    """The Claude Code config directory: ``$CLAUDE_CONFIG_DIR`` if set, else
    ``~/.claude``. Honouring the env var matters for tests as much as for users —
    it is how the suite points every write at a tmp dir instead of the developer's
    real config."""
    base = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return Path(base) if base else Path.home() / ".claude"


def settings_path() -> Path:
    """The user-level settings file the hook is installed into by default."""
    return claude_config_dir() / "settings.json"


def skill_target_path() -> Path:
    """Where ``install`` lays the packaged skill down."""
    return claude_config_dir() / _SKILL_RELPATH


def packaged_skill_path() -> Path | None:
    """The in-repo copy of the ``pandan`` skill that ``install`` distributes, or
    ``None`` when this build doesn't carry one.

    The skill lives *inside* the package (``pandan_cli/skills/pandan/SKILL.md``)
    so a wheel picks it up as package data, and the release workflow adds
    ``--add-data`` so the PyInstaller onefile does too — where it unpacks under
    ``sys._MEIPASS``. Returning ``None`` rather than raising is deliberate: an
    older binary built before the ``--add-data`` line still installs the hook, and
    just says the skill wasn't bundled.
    """
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass) / "pandan_cli" / "skills")
    roots.append(Path(__file__).resolve().parent / "skills")
    for root in roots:
        candidate = root / "pandan" / "SKILL.md"
        if candidate.is_file():
            return candidate
    return None


# --- skill provenance (KAN-505) ---------------------------------------------
#
# The bug this exists to kill: comparing the installed skill against *this
# build's* packaged copy and calling any difference "locally modified". The
# baseline is the wrong reference — the same untouched file reported
# `locally modified` under a released v0.12.0 binary and `matches this build`
# under v0.15.0 source, because the packaged copy legitimately changed between
# them. Worse, "locally modified" is the state that makes `install` refuse
# without `--force-skill`, so a user whose binary was merely a release behind was
# told they had edits *and* pointed at the one action that silently downgrades
# their skill. Same class as KAN-484: a check whose baseline is wrong produces
# confident, wrong output, and the obvious response to it makes things worse.
#
# Fixing it needs a *direction*, and content comparison alone cannot supply one:
# "differs" is symmetric. So `install` writes a build stamp into the copy it lays
# down, and the comparison becomes version-aware. What a stamp cannot do is
# retrofit provenance onto a copy already on disk — every pre-KAN-505 install is
# unstamped forever — so `UNKNOWN` is a real, permanent outcome and must degrade
# honestly rather than guess a direction. That hedge matches the tone
# `_uninstall_skill` already had ("locally modified or unknown build").

# The stamp `install` appends to the copy it writes.
#
# An HTML comment, deliberately **not** a YAML frontmatter key. The frontmatter
# is the harness's own skill-metadata contract (`name`/`description` drive
# discovery), so an unrecognised key there is a schema risk in a file Claude Code
# actually parses; an HTML comment is inert in Markdown and, as agent
# instructions, carries no imperative — it names a build, it does not tell the
# model to do anything. It goes on the **last** line so it can never displace the
# skill's opening framing.
SKILL_STAMP_PREFIX = "<!-- pandan-cli: skill installed by pandan "
SKILL_STAMP_SUFFIX = " -->"

# What a source checkout writes where a release writes its commit — the same
# wording `--version` uses, so the two can never be confused (build_info.py).
SKILL_STAMP_SOURCE = "source checkout"

# Comparison outcomes for an installed copy vs. this build's packaged copy.
SKILL_ABSENT = "absent"  # nothing installed
SKILL_NO_PACKAGED = "no_packaged"  # this build carries no copy to compare against
SKILL_MATCH = "match"  # byte-identical body — no question to answer
SKILL_NEWER = "newer"  # stamped by a NEWER build: the *binary* is stale
SKILL_OLDER = "older"  # stamped by an OLDER build: the *skill* is stale
SKILL_MODIFIED = "modified"  # stamped by THIS build, body differs → hand-edited
SKILL_UNKNOWN = "unknown"  # differs, direction genuinely not decidable


def stamp_line(version: str = __version__, build_sha: str | None = BUILD_SHA) -> str:
    """The one-line build stamp, e.g.
    ``<!-- pandan-cli: skill installed by pandan 0.17.0 (2f03276) -->``.

    Both args are injectable so tests can render any build's stamp without
    freezing a binary — the same seam ``build_info.version_string`` uses."""
    sha = (build_sha or "").strip()
    return f"{SKILL_STAMP_PREFIX}{version} ({sha or SKILL_STAMP_SOURCE}){SKILL_STAMP_SUFFIX}"


def parse_stamp(text: str) -> tuple[str, str] | None:
    """``(version, build_sha)`` from a skill body's stamp, or ``None`` when it has
    none. ``build_sha`` is ``""`` for a source-checkout stamp.

    Only the **last** non-empty line is considered: the stamp is something we
    appended, and scanning the whole file would let prose inside the skill (which
    documents `--version` output, so it genuinely contains version-shaped text)
    masquerade as provenance."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    line = lines[-1].strip()
    if not line.startswith(SKILL_STAMP_PREFIX) or not line.endswith(SKILL_STAMP_SUFFIX):
        return None
    inner = line[len(SKILL_STAMP_PREFIX) : -len(SKILL_STAMP_SUFFIX)].strip()
    version, _, rest = inner.partition(" ")
    sha = rest.strip().lstrip("(").rstrip(")").strip()
    if sha == SKILL_STAMP_SOURCE:
        sha = ""
    return (version, sha) if version else None


def strip_stamp(payload: bytes) -> bytes:
    """``payload`` without its trailing stamp line — the form that is compared.

    Comparison has to happen on the *body*: once ``install`` stamps what it
    writes, an unmodified installed copy is no longer byte-identical to the
    packaged one, and a naive compare would report every install as modified.
    Non-UTF-8 bytes are returned untouched (and will simply compare unequal)
    rather than raising: a status command must never crash on a mangled file."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload
    if parse_stamp(text) is None:
        return payload
    kept: list[str] = []
    lines = text.split("\n")
    dropped = False
    for line in reversed(lines):
        if not dropped and line.strip().startswith(SKILL_STAMP_PREFIX):
            dropped = True
            continue
        kept.append(line)
    return "\n".join(reversed(kept)).encode("utf-8")


def _version_tuple(raw: str) -> tuple[int, ...] | None:
    """``"0.17.0"`` → ``(0, 17, 0)``; anything not purely numeric → ``None``.

    ``None`` deliberately propagates to ``SKILL_UNKNOWN``. An unparseable version
    is exactly the case where inventing an ordering would re-create this bug one
    level up."""
    parts = raw.strip().split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def compare_skill(
    installed: bytes | None,
    packaged: bytes | None,
    *,
    version: str = __version__,
    build_sha: str | None = BUILD_SHA,
) -> tuple[str, str]:
    """``(state, detail)`` for an installed skill copy against this build's.

    Pure and fully injectable — no filesystem, no globals — because this is the
    decision the whole card turns on, and it has to be testable at every build
    skew without producing real binaries. ``detail`` is the stamped build's
    version when one was read, else ``""``.

    The ordering of the branches is the honesty contract:

    * identical bodies short-circuit, so a stale stamp on an unmodified copy is
      harmless and ``install`` needn't rewrite the file just to refresh it;
    * a **newer** stamp is the KAN-505 case — the binary is behind, and
      ``--force-skill`` would *downgrade* the skill, so callers must not offer it;
    * an **older** stamp means the skill is behind, where ``--force-skill`` is the
      correct upgrade;
    * equal version **and** equal commit is the only situation in which a
      differing body proves a hand edit;
    * everything else — no stamp at all, an unparseable version, or the V50
      pathology of one version number covering two different builds — is
      ``UNKNOWN``, and says so instead of picking a direction.
    """
    if installed is None:
        return SKILL_ABSENT, ""
    if packaged is None:
        return SKILL_NO_PACKAGED, ""
    if strip_stamp(installed) == strip_stamp(packaged):
        return SKILL_MATCH, ""

    try:
        stamp = parse_stamp(installed.decode("utf-8"))
    except UnicodeDecodeError:
        stamp = None
    if stamp is None:
        return SKILL_UNKNOWN, ""

    stamped_version, stamped_sha = stamp
    theirs = _version_tuple(stamped_version)
    ours = _version_tuple(version)
    if theirs is None or ours is None:
        return SKILL_UNKNOWN, stamped_version
    if theirs > ours:
        return SKILL_NEWER, stamped_version
    if theirs < ours:
        return SKILL_OLDER, stamped_version
    if stamped_sha == (build_sha or "").strip():
        return SKILL_MODIFIED, stamped_version
    # One version number, two different builds — the exact ambiguity V50's commit
    # stamp exists to expose. Refuse to guess.
    return SKILL_UNKNOWN, stamped_version


# --- the hook entry ---------------------------------------------------------


def _self_argv() -> list[str]:
    """How to re-invoke *this* pandan, as an argv prefix.

    A frozen onefile is its own executable; a source/venv/pipx run is
    ``<python> -m pandan_cli``. Note what this deliberately does **not** do: it
    never reaches for a ``pandan`` on ``$PATH``. A stale binary there has already
    caused two false bug reports on this project, and "the hook runs the same
    pandan you installed it with" is both the honest promise and the debuggable
    one. ``--exec`` overrides it for anyone who wants otherwise.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "pandan_cli"]


def _hook_command(argv_prefix: list[str], *, timeout: float, limit: int) -> str:
    """The shell command string the hook entry runs.

    A plain ``command`` string, not the schema's newer ``args`` exec-form: the
    string form is what every Claude Code version understands, and
    ``shlex.quote`` already makes a path with spaces safe. The three sentinel
    tokens land verbatim (quoting a bare token is a no-op), which is what
    ``_is_ours`` relies on."""
    parts = [
        *argv_prefix,
        "context",
        "show",
        "--hook",
        "--timeout",
        _fmt_seconds(timeout),
        "--limit",
        str(limit),
    ]
    return " ".join(shlex.quote(part) for part in parts)


def _fmt_seconds(value: float) -> str:
    """``5.0`` → ``"5"``, ``2.5`` → ``"2.5"`` — so the generated command line reads
    like something a human would have typed."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def hook_entry(*, command: str, timeout: float) -> dict[str, Any]:
    """One ``SessionStart`` hook object.

    ``matcher`` is omitted (fires for every session source) and the harness
    ``timeout`` is our budget plus a margin, so our own bound trips first and the
    600-second default never applies."""
    return {
        "type": "command",
        "command": command,
        "timeout": round(timeout + HOOK_TIMEOUT_MARGIN, 3),
    }


def _is_ours(hook: Any) -> bool:
    """Whether a hook object in a settings file was installed by us."""
    return (
        isinstance(hook, dict)
        and isinstance(hook.get("command"), str)
        and HOOK_SENTINEL in hook["command"]
    )


# --- settings file I/O ------------------------------------------------------


class ContextError(Exception):
    """A context-command failure. ``cli`` maps this onto its own error contract, so
    this module needn't import ``CliError`` (and can't circularly import ``cli``).

    ``code`` is a machine code from ``cli.ERROR_CODES``; ``arg`` is the offending
    flag when one is at fault."""

    def __init__(self, message: str, *, code: str, arg: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.arg = arg


def read_settings(path: Path) -> dict[str, Any]:
    """Parse a settings file, or ``{}`` when it doesn't exist.

    A file that exists but doesn't parse is a hard error, **never** an implicit
    ``{}``: writing over it would silently destroy every unrelated setting the
    user has. That is the one irreversible thing an installer can do."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContextError(f"cannot read {path}: {exc}", code="invalid_input") from exc
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContextError(
            f"{path} is not valid JSON ({exc}) — fix or move it first; "
            "refusing to overwrite a settings file we can't parse",
            code="invalid_input",
        ) from exc
    if not isinstance(data, dict):
        raise ContextError(
            f"{path} does not contain a JSON object — refusing to overwrite it",
            code="invalid_input",
        )
    return data


def write_settings(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` as pretty JSON, atomically, preserving the file's mode.

    Atomic because a half-written ``settings.json`` is a broken Claude Code: the
    temp file is created in the *same* directory (so ``os.replace`` is a rename
    within one filesystem) and swapped in one step."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else None
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".settings-", suffix=".json")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        if mode is not None:
            tmp.chmod(mode)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _session_start_groups(settings: dict[str, Any]) -> list[Any]:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return []
    groups = hooks.get(HOOK_EVENT)
    return groups if isinstance(groups, list) else []


def find_installed(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Every hook object in ``settings`` that we installed (usually 0 or 1; more if
    a hand edit duplicated it, which install then collapses)."""
    found: list[dict[str, Any]] = []
    for group in _session_start_groups(settings):
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks") or []:
            if _is_ours(hook):
                found.append(hook)
    return found


def _strip_ours(settings: dict[str, Any]) -> int:
    """Remove our hook objects in place, pruning containers that we emptied but
    **only** those we emptied. Returns how many were removed.

    The pruning is what makes uninstall *clean*: a settings file that had nothing
    but our hook comes back byte-identical to one that never had it, so
    install→uninstall is a true round trip."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    groups = hooks.get(HOOK_EVENT)
    if not isinstance(groups, list):
        return 0

    removed = 0
    surviving_groups: list[Any] = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            surviving_groups.append(group)
            continue
        kept = [hook for hook in group["hooks"] if not _is_ours(hook)]
        removed += len(group["hooks"]) - len(kept)
        if not kept:
            # The group existed only to hold our hook — drop it. A group that had
            # other hooks keeps them (and its matcher).
            continue
        group["hooks"] = kept
        surviving_groups.append(group)

    if surviving_groups:
        hooks[HOOK_EVENT] = surviving_groups
    else:
        hooks.pop(HOOK_EVENT, None)
    if not hooks:
        settings.pop("hooks", None)
    return removed


# --- config resolution -----------------------------------------------------


def _resolved_board() -> tuple[str, str, str]:
    """``(api_url, token, board_id)`` from the normal config chain, or a
    ``ContextError`` naming exactly what's missing.

    Both a token and a **default board** are required: a hook with no board would
    span every board the user owns, which is a lot of context and, per ADR 0015,
    an easy way to look at the wrong board."""
    resolved = resolve_values()
    token = resolved.get("token", "")
    board_id = resolved.get("board_id", "")
    missing = []
    if not board_id:
        missing.append("PANDAN_BOARD_ID")
    if not token:
        missing.append("PANDAN_TOKEN")
    if missing:
        raise ContextError(
            f"no board configured ({' and '.join(missing)} unset) — nothing was changed. "
            "Set a default board first: `pandan login --board-id <id>`, "
            "`pandan config set --board-id <id>`, or .mcpServers.pandan.env in .mcp.json. "
            "`pandan config show` prints what resolved.",
            code="config",
        )
    from .config import DEFAULT_API_URL

    return resolved.get("api_url") or DEFAULT_API_URL, token, board_id


# --- the ambient block -----------------------------------------------------


def _card_row(card: dict[str, Any]) -> str:
    points = card.get("story_points")
    # The board-local ref (M8 V54, KAN-975) when the API attached one, else the
    # canonical ticket_number, else the raw id. Mirrors cli.py's ``_display_ref`` —
    # duplicated rather than imported, since this module can't circularly import
    # ``cli`` (see the ``ContextError`` docstring above).
    ticket = card.get("ref") or card.get("ticket_number") or f"#{card.get('id')}"
    title = str(card.get("title") or "").replace("\n", " ").strip()
    assignee = card.get("assignee")
    row = f"{ticket}\t{card.get('column')}\t{title}\tpts={points if points else '-'}"
    if assignee:
        row += f"\tassignee={assignee}"
    if card.get("needs_human"):
        row += "\tneeds_human"
    return row


def render_block(board_id: str, page: dict[str, Any], *, limit: int) -> str:
    """The ambient text itself: one header, per-column counts, then the open cards.

    Plain text rather than JSON — it is read by a model, and the CLI's own
    tab-separated human rows are already the cheapest shape the repo has (V47,
    KAN-430). Bounded by ``limit`` so a big backlog can't dominate a session."""
    cards = page.get("cards") or []
    counts: dict[str, int] = {}
    for card in cards:
        column = str(card.get("column") or "?")
        counts[column] = counts.get(column, 0) + 1
    truncated = bool(page.get("next_cursor"))

    lines = [f"Pandan board {board_id} — ambient state (from `pandan context show`):"]
    known = ("todo", "in_progress", "done")
    summary = ", ".join(f"{column}={counts.get(column, 0)}" for column in known)
    extra = {k: v for k, v in counts.items() if k not in known}
    if extra:
        summary += ", " + ", ".join(f"{k}={v}" for k, v in sorted(extra.items()))
    lines.append(f"counts: {summary}, total={len(cards)}" + (" (truncated)" if truncated else ""))

    open_cards = [c for c in cards if c.get("column") in _OPEN_COLUMNS]
    open_cards.sort(
        key=lambda c: (_OPEN_COLUMNS.index(str(c.get("column"))), c.get("position") or 0)
    )
    if not open_cards:
        lines.append("open cards: none")
    else:
        shown = open_cards[:limit]
        lines.append(f"open cards ({len(shown)} of {len(open_cards)}), ticket/column/title/points:")
        lines.extend(_card_row(card) for card in shown)
    lines.append(
        "This is a point-in-time snapshot, not a live view — re-read with the pandan "
        "CLI before acting on it."
    )
    return "\n".join(lines)


def fetch_block(*, board_arg: int | None, limit: int, timeout: float) -> str:
    """Resolve config, make **one** bounded API call, and render the block.

    One call, not two: each round trip costs against the same budget, and a board
    *name* isn't worth doubling the time a session can be delayed. The per-request
    timeout is half the budget because ``PandanClient`` retries a failed GET
    exactly once (``client.py:123-150``) — halving it keeps the worst case inside
    ``timeout``, and ``retry_backoff=0`` removes the extra second the retry would
    otherwise sleep."""
    api_url, token, configured_board = _resolved_board()
    board_id = str(board_arg) if board_arg is not None else configured_board
    per_request = max(0.5, timeout / 2)
    with PandanClient(
        api_url,
        token,
        timeout=per_request,
        connect_timeout=min(2.0, per_request),
        retry_backoff=0.0,
    ) as client:
        page = client.list_cards(board_id=int(board_id), limit=_FETCH_LIMIT)
    return render_block(board_id, page, limit=limit)


def hook_envelope(text: str) -> dict[str, Any]:
    """The verified ``SessionStart`` JSON output form. ``additionalContext`` is the
    field the docs name for adding context on this event."""
    return {
        "hookSpecificOutput": {
            "hookEventName": HOOK_EVENT,
            "additionalContext": text,
        }
    }


# --- command handlers ------------------------------------------------------


def cmd_show(args: argparse.Namespace) -> int:
    """``pandan context show [--hook]`` — print the ambient block.

    Two modes with deliberately different failure behaviour:

    * plain — a human (or a test) inspecting the block. Failures propagate and get
      the CLI's normal structured error + non-zero exit.
    * ``--hook`` — what the installed ``SessionStart`` hook runs. **Always exits 0
      and prints nothing but a valid envelope on stdout.** Anything else on stdout
      would be parsed as hook output and injected into the model's context; an
      ``error<TAB>config<TAB>…`` row masquerading as board state is strictly worse
      than no ambient block. The reason goes to stderr, which exit 0 discards
      (harmless, and visible with ``--debug``).
    """
    hook_mode = bool(getattr(args, "hook", False))
    try:
        text = fetch_block(
            board_arg=getattr(args, "board", None),
            limit=args.limit,
            timeout=args.timeout,
        )
    except BaseException as exc:  # noqa: BLE001 - the whole point is to never escape
        if not hook_mode:
            raise
        # KeyboardInterrupt/SystemExit included on purpose: a hook that dies noisily
        # mid-session-start is exactly what must not happen.
        print(
            f"pandan: no ambient board context this session ({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )
        return 0
    print(json.dumps(hook_envelope(text)) if hook_mode else text)
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    """``pandan context install`` — add (or update) the ``SessionStart`` hook.

    Idempotent by construction: the entry is built deterministically from the
    flags, so a second run with the same flags finds a byte-identical entry and
    writes nothing at all. Changed flags rewrite the single entry (and collapse
    any duplicates a hand edit left behind) rather than appending another.

    Unrelated settings are never touched: read → merge → atomic write, and an
    unparseable file aborts instead of being replaced.
    """
    # Resolve config FIRST, so the unconfigured case is provably a no-op: the
    # settings file is not opened, let alone written.
    _resolved_board()

    path = _settings_arg(args)
    argv_prefix = [args.exec] if getattr(args, "exec", None) else _self_argv()
    command = _hook_command(argv_prefix, timeout=args.timeout, limit=args.limit)
    desired = hook_entry(command=command, timeout=args.timeout)

    settings = read_settings(path)
    existing = find_installed(settings)
    already = len(existing) == 1 and existing[0] == desired

    if already:
        print(f"already installed\t{path}")
    else:
        _strip_ours(settings)
        hooks = settings.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise ContextError(
                f'{path} has a non-object "hooks" key — refusing to overwrite it',
                code="invalid_input",
            )
        groups = hooks.setdefault(HOOK_EVENT, [])
        if not isinstance(groups, list):
            raise ContextError(
                f'{path} has a non-array "hooks.{HOOK_EVENT}" key — refusing to overwrite it',
                code="invalid_input",
            )
        groups.append({"hooks": [desired]})
        write_settings(path, settings)
        verb = "updated" if existing else "installed"
        print(f"{verb}\t{path}")

    print(f"event\t{HOOK_EVENT} (all sources)")
    print(f"command\t{command}")
    print(f"budget\t{_fmt_seconds(args.timeout)}s (hook timeout {desired['timeout']}s)")
    for line in _install_skill(args):
        print(line)
    print("note\tstart a new session (or /clear) to see the ambient block")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    """``pandan context uninstall`` — remove the hook, and the skill if unmodified.

    Idempotent: with nothing of ours present the settings file is not written at
    all (so it isn't even created, and its mtime doesn't move). Needs no board
    configured — you must always be able to undo this."""
    path = _settings_arg(args)
    settings = read_settings(path)
    removed = _strip_ours(settings)
    if removed:
        write_settings(path, settings)
        print(f"removed\t{removed} {HOOK_EVENT} hook(s)\t{path}")
    else:
        print(f"nothing to remove\t{path}")
    for line in _uninstall_skill(args):
        print(line)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """``pandan context status`` — read-only: is the hook installed, and would it
    have anything to say? The affordance that makes an idempotent installer
    checkable without running it."""
    path = _settings_arg(args)
    installed = find_installed(read_settings(path))
    print(f"settings\t{path}")
    print(f"hook\t{'installed' if installed else 'not installed'}")
    for hook in installed:
        print(f"command\t{hook.get('command')}")
        print(f"timeout\t{hook.get('timeout')}")
    resolved = resolve_values()
    print(f"board_id\t{resolved.get('board_id') or '(unset)'}")
    print(f"token\t{'set' if resolved.get('token') else '(unset)'}")
    skill = skill_target_path()
    for line in _skill_status_lines(skill):
        print(line)
    return 0


def _skill_status_lines(skill: Path) -> list[str]:
    """The ``skill`` rows of ``context status`` — one state row, plus an advice row
    where there is something safe to advise.

    The point of the split (KAN-505): the advice is *state-dependent*, and the one
    state that must never carry "pass --force-skill" is the one where the installed
    copy is newer than this build, because there the flag downgrades it. Collapsing
    the states would put the destructive suggestion under the false alarm."""
    packaged = packaged_skill_path()
    state, detail = compare_skill(
        skill.read_bytes() if skill.is_file() else None,
        packaged.read_bytes() if packaged is not None else None,
    )
    if state == SKILL_ABSENT:
        return [f"skill\tnot installed\t{skill}"]
    if state == SKILL_NO_PACKAGED:
        return [f"skill\tinstalled (this build carries no copy to compare against)\t{skill}"]
    if state == SKILL_MATCH:
        return [f"skill\tinstalled (matches this build)\t{skill}"]
    if state == SKILL_NEWER:
        return [
            f"skill\tinstalled copy is NEWER than this build "
            f"(laid down by {detail}, this is {__version__})\t{skill}",
            "skill\tyour binary is stale — re-download the release. Do NOT pass "
            "--force-skill: it would downgrade the skill to this older build's copy",
        ]
    if state == SKILL_OLDER:
        return [
            f"skill\tinstalled (from an older build {detail}, or locally modified)\t{skill}",
            "skill\tre-run `pandan context install --force-skill` to update it to "
            "this build's copy",
        ]
    if state == SKILL_MODIFIED:
        return [
            f"skill\tinstalled (locally modified)\t{skill}",
            "skill\tpass --force-skill to overwrite it with this build's copy",
        ]
    return [
        f"skill\tinstalled (differs from this build; no build stamp, so local edits "
        f"and a different build are indistinguishable)\t{skill}",
        "skill\tcheck `pandan --version` against the build you installed it with "
        "before passing --force-skill, which overwrites it with this build's copy",
    ]


# --- skill distribution ----------------------------------------------------


def _install_skill(args: argparse.Namespace) -> list[str]:
    """Lay the packaged ``pandan`` skill down beside the hook.

    Never clobbers a locally edited skill without ``--force-skill``: the file is
    the user's, and silently reverting their edits is the kind of surprise that
    stops people trusting an installer. Writing identical bytes over identical
    bytes is a no-op, which is what keeps ``install`` idempotent here too."""
    if getattr(args, "no_skill", False):
        return ["skill\tskipped (--no-skill)"]
    source = packaged_skill_path()
    if source is None:
        return [
            "skill\tnot bundled in this build — install it by hand from "
            "pandan-cli/pandan_cli/skills/pandan/SKILL.md"
        ]
    target = skill_target_path()
    payload = source.read_bytes()
    forced = bool(getattr(args, "force_skill", False))
    notes: list[str] = []
    if target.is_file():
        state, detail = compare_skill(target.read_bytes(), payload)
        if state == SKILL_MATCH:
            return [f"skill\tup to date\t{target}"]
        if not forced:
            # KAN-505: the refusal message is per-state, and only the states where
            # overwriting is an *upgrade* (or is at worst same-version) may point at
            # --force-skill. Offering it under SKILL_NEWER is what made the false
            # alarm dangerous rather than merely wrong.
            if state == SKILL_NEWER:
                return [
                    f"skill\tleft alone — installed copy is NEWER than this build "
                    f"(laid down by {detail}, this is {__version__})\t{target}",
                    "skill\tyour binary is stale — re-download the release rather than "
                    "forcing this older copy over it",
                ]
            if state == SKILL_OLDER:
                return [
                    f"skill\tleft alone (from an older build {detail}, or locally "
                    f"modified)\t{target}",
                    "skill\tpass --force-skill to overwrite it with this build's copy",
                ]
            if state == SKILL_UNKNOWN:
                return [
                    f"skill\tleft alone (differs from this build; no build stamp, so "
                    f"local edits and a different build are indistinguishable)\t{target}",
                    "skill\tpass --force-skill to overwrite it with this build's copy",
                ]
            return [
                f"skill\tleft alone (locally modified)\t{target}",
                "skill\tpass --force-skill to overwrite it with this build's copy",
            ]
        verb = "overwrote"
        if state == SKILL_NEWER:
            # --force-skill stays an escape hatch: an explicit flag is intent, and
            # refusing it outright would leave no way back to an older skill. But it
            # is labelled, so a downgrade is never silent.
            notes.append(
                f"skill\tWARNING: this DOWNGRADED the skill — the copy you replaced was "
                f"laid down by {detail}, newer than this build ({__version__})"
            )
    else:
        verb = "installed"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_stamped(payload))
    return [f"skill\t{verb}\t{target}", *notes]


def _stamped(payload: bytes) -> bytes:
    """``payload`` with this build's stamp as its last line.

    This is the half of KAN-505 that makes provenance *decidable* going forward: a
    copy on disk can now name the build that wrote it, so "differs" acquires a
    direction. It does nothing for a copy already installed — those stay
    ``SKILL_UNKNOWN`` forever, which is why that state had to be honest."""
    body = strip_stamp(payload)
    text = body.decode("utf-8", errors="strict")
    if not text.endswith("\n"):
        text += "\n"
    return (text + stamp_line() + "\n").encode("utf-8")


def _uninstall_skill(args: argparse.Namespace) -> list[str]:
    """Remove the skill only when it is byte-identical to what we shipped, so a
    user's own edits are never deleted by an uninstall."""
    if getattr(args, "keep_skill", False):
        return ["skill\tkept (--keep-skill)"]
    target = skill_target_path()
    if not target.is_file():
        return ["skill\tnot installed"]
    source = packaged_skill_path()
    state, _detail = compare_skill(
        target.read_bytes(), source.read_bytes() if source is not None else None
    )
    if state != SKILL_MATCH:
        # Compared on the **body**, so our own stamp doesn't make an otherwise
        # untouched copy look edited and thus undeletable (KAN-505). The hedged
        # wording is unchanged — it was right all along, and is the tone the rest of
        # this module now matches.
        return [
            f"skill\tkept (locally modified or unknown build)\t{target}",
            "skill\tdelete it by hand if you meant to remove it",
        ]
    target.unlink()
    for directory in (target.parent,):
        try:
            directory.rmdir()  # only succeeds when we left it empty
        except OSError:
            pass
    return [f"skill\tremoved\t{target}"]


# --- argument wiring -------------------------------------------------------


def _settings_arg(args: argparse.Namespace) -> Path:
    raw = getattr(args, "settings", None)
    return Path(raw).expanduser() if raw else settings_path()


def _positive_seconds(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a number of seconds, got {raw!r}") from exc
    if not 0 < value <= 60:
        raise argparse.ArgumentTypeError(
            f"--timeout must be > 0 and <= 60 seconds (a session hook is awaited), got {raw!r}"
        )
    return value


def _positive_limit(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected an integer, got {raw!r}") from exc
    if not 0 < value <= 200:
        raise argparse.ArgumentTypeError(f"--limit must be between 1 and 200, got {raw!r}")
    return value


def add_parser(sub: Any, common: argparse.ArgumentParser) -> None:
    """Register the ``context`` group on ``sub`` (called from ``cli.build_parser``).

    A nested group, matching every other multi-verb area of this CLI (``board``,
    ``epic``, ``config``, ``template``…) rather than a flat ``install-context`` /
    ``uninstall-context`` pair: the four verbs share one noun, and one of them
    (``show``) is *also* the hook's own entry point, which only reads sensibly
    under that noun."""
    parser = sub.add_parser(
        "context",
        help="ambient board context for an agent session (install / uninstall / show / status)",
        description=(
            "Wire the default board's state into an agent session before it acts, as a "
            f"Claude Code {HOOK_EVENT} hook. `install` is idempotent, `uninstall` is clean, "
            "and the hook soft-fails inside a few seconds so a cold-started API can never "
            "delay a session."
        ),
    )
    group = parser.add_subparsers(dest="context_command", metavar="<subcommand>", required=True)

    p_install = group.add_parser(
        "install",
        parents=[common],
        help=f"add the {HOOK_EVENT} hook to settings.json (idempotent)",
    )
    _add_settings_arg(p_install)
    p_install.add_argument(
        "--exec",
        metavar="PATH",
        help=(
            "the pandan executable the hook should run (default: the one running this "
            "command — never a `pandan` found on $PATH, which may be stale)"
        ),
    )
    p_install.add_argument(
        "--timeout",
        type=_positive_seconds,
        default=DEFAULT_HOOK_TIMEOUT,
        metavar="SECONDS",
        help=(
            "wall-clock budget for the hook's API call (default "
            f"{_fmt_seconds(DEFAULT_HOOK_TIMEOUT)}). Kept small on purpose: a session "
            "hook is awaited, and this API scales to zero"
        ),
    )
    p_install.add_argument(
        "--limit",
        type=_positive_limit,
        default=DEFAULT_CARD_LIMIT,
        metavar="N",
        help=f"max open cards in the ambient block (default {DEFAULT_CARD_LIMIT})",
    )
    p_install.add_argument(
        "--no-skill", action="store_true", help="install the hook only; don't lay down the skill"
    )
    p_install.add_argument(
        "--force-skill",
        action="store_true",
        help="overwrite a locally modified ~/.claude/skills/pandan/SKILL.md",
    )
    p_install.set_defaults(local_func=cmd_install)

    p_uninstall = group.add_parser(
        "uninstall",
        parents=[common],
        help="remove the hook (and the skill, if unmodified) — idempotent",
    )
    _add_settings_arg(p_uninstall)
    p_uninstall.add_argument(
        "--keep-skill", action="store_true", help="leave the installed skill in place"
    )
    p_uninstall.set_defaults(local_func=cmd_uninstall)

    p_show = group.add_parser(
        "show",
        parents=[common],
        help="print the ambient block (what the hook runs)",
    )
    p_show.add_argument("--board", type=int, help="board id (default: PANDAN_BOARD_ID)")
    p_show.add_argument(
        "--hook",
        action="store_true",
        help=(
            f"emit the {HOOK_EVENT} JSON envelope and soft-fail: always exit 0, never "
            "print anything but a valid envelope on stdout"
        ),
    )
    p_show.add_argument(
        "--timeout", type=_positive_seconds, default=DEFAULT_HOOK_TIMEOUT, metavar="SECONDS"
    )
    p_show.add_argument(
        "--limit", type=_positive_limit, default=DEFAULT_CARD_LIMIT, metavar="N"
    )
    p_show.set_defaults(local_func=cmd_show)

    p_status = group.add_parser(
        "status", parents=[common], help="report whether the hook + skill are installed"
    )
    _add_settings_arg(p_status)
    p_status.set_defaults(local_func=cmd_status)


def _add_settings_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--settings",
        metavar="PATH",
        help=(
            "settings.json to operate on (default: ~/.claude/settings.json, or "
            "$CLAUDE_CONFIG_DIR/settings.json). Use .claude/settings.json for a "
            "project-scoped install"
        ),
    )
