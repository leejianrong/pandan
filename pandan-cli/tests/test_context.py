"""Unit tests for ``pandan context …`` (V48, KAN-431 — AXI 7).

Three promises the slice makes, and what proves each here:

* **install is idempotent / uninstall is clean.** Byte-level, not "looks right": a
  second install must leave the file *identical*, and an install→uninstall round
  trip must return a settings file to exactly its previous bytes, with every
  unrelated setting (and every unrelated ``SessionStart`` hook) untouched.
* **unconfigured is a no-op with a message.** Proven by asserting the settings file
  was never even created.
* **a slow or failing API soft-fails, fast.** The one most likely to bite a real
  user: this backend scales to zero, a ``SessionStart`` hook is awaited before the
  first prompt, and the harness's own default cap is 600 s. So there is a test that
  points the CLI at a socket which accepts and never answers, and asserts it comes
  back — exit 0, nothing on stdout — inside a few seconds.

Every test runs against a ``CLAUDE_CONFIG_DIR`` inside ``tmp_path``. An autouse
fixture enforces that, so no test can reach the developer's real
``~/.claude/settings.json``.
"""
from __future__ import annotations

import json
import socket
import threading
import time

import httpx
import pytest
from pandan_client import PandanApiError

from pandan_cli import cli, config, context

CARDS = [
    {"id": 1, "ticket_number": "KAN-1", "column": "todo", "title": "A", "story_points": 3,
     "position": 1},
    {"id": 2, "ticket_number": "KAN-2", "column": "in_progress", "title": "B",
     "story_points": None, "position": 1, "assignee": "agent:x"},
    {"id": 3, "ticket_number": "KAN-3", "column": "done", "title": "C", "story_points": 1,
     "position": 1},
]


@pytest.fixture(autouse=True)
def sandbox(monkeypatch, tmp_path):
    """Confine every write to ``tmp_path`` and give a configured board by default.

    ``CLAUDE_CONFIG_DIR`` is the seam that makes this possible — without it these
    tests would write to the developer's real Claude config, which is exactly the
    kind of side effect a test must never have."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("pandan_cli.config.find_mcp_json", lambda *a, **k: None)
    for names in config._ENV_NAMES.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
    config._warned.clear()
    monkeypatch.setenv("PANDAN_TOKEN", "pandan_pat_test")
    monkeypatch.setenv("PANDAN_BOARD_ID", "7")
    monkeypatch.setenv("PANDAN_API_URL", "http://api.test")


class FakeClient:
    """Records the constructor kwargs (the cold-start guard lives there) and returns
    a canned page, or raises."""

    last_kwargs: dict = {}

    def __init__(self, base_url, token, **kwargs):
        FakeClient.last_kwargs = dict(kwargs)
        self.base_url = base_url
        self.token = token
        self.calls: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def list_cards(self, **kw):
        self.calls.append(kw)
        return {"cards": CARDS}


def _install_fake(monkeypatch, factory=None):
    made: list = []

    def build(base_url, token, **kwargs):
        client = (factory or FakeClient)(base_url, token, **kwargs)
        made.append(client)
        return client

    monkeypatch.setattr(context, "PandanClient", build)
    return made


def settings_file(tmp_path):
    return tmp_path / "claude" / "settings.json"


# --- install: idempotent, and never clobbers ------------------------------


def test_install_writes_a_valid_session_start_hook(tmp_path, capsys):
    assert cli.run(["context", "install"]) == 0
    data = json.loads(settings_file(tmp_path).read_text())

    # The exact shape verified against the shipped claude-code-settings.schema.json:
    # `hooks` is an object keyed by event name; each value is an array of groups;
    # each group has a `hooks` array; each hook requires `type` + `command`, and
    # `timeout` is a number of SECONDS with exclusiveMinimum 0.
    groups = data["hooks"]["SessionStart"]
    assert isinstance(groups, list) and len(groups) == 1
    hooks = groups[0]["hooks"]
    assert len(hooks) == 1
    hook = hooks[0]
    assert hook["type"] == "command"
    assert isinstance(hook["command"], str)
    assert isinstance(hook["timeout"], (int, float)) and hook["timeout"] > 0
    # `matcher` is deliberately absent so the hook fires for every session source
    # (startup / resume / clear / compact / fork) — a compacted session needs the
    # board state as much as a fresh one. Both key sets are pinned exactly, because
    # `matcher` belongs on the GROUP and a copy misplaced onto the hook object would
    # be silently ignored by the harness while looking correct in review. (A
    # group-level `"matcher": "startup"` mutation passed an earlier draft of this
    # test that only checked `"matcher" not in groups[0]` for the hook dict.)
    assert set(groups[0]) == {"hooks"}
    assert set(hook) == {"type", "command", "timeout"}
    assert context.HOOK_SENTINEL in hook["command"]

    out = capsys.readouterr().out
    assert out.startswith("installed\t")
    assert "SessionStart" in out


def test_install_bounds_the_hook_timeout_well_under_the_600s_default(tmp_path):
    # The harness default for a command hook is 600 seconds. An unbounded hook on a
    # cold-started board would delay session start by minutes, so install MUST
    # write an explicit timeout, and it must stay in single-digit seconds.
    assert cli.run(["context", "install"]) == 0
    hook = json.loads(settings_file(tmp_path).read_text())["hooks"]["SessionStart"][0]["hooks"][0]
    assert hook["timeout"] < 60
    assert hook["timeout"] == pytest.approx(
        context.DEFAULT_HOOK_TIMEOUT + context.HOOK_TIMEOUT_MARGIN
    )


def test_install_is_idempotent_byte_for_byte(tmp_path, capsys):
    assert cli.run(["context", "install"]) == 0
    first = settings_file(tmp_path).read_bytes()
    capsys.readouterr()

    assert cli.run(["context", "install"]) == 0
    assert settings_file(tmp_path).read_bytes() == first
    assert capsys.readouterr().out.startswith("already installed\t")


def test_install_preserves_unrelated_settings_and_unrelated_hooks(tmp_path):
    path = settings_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "model": "opus",
                "hooks": {
                    "SessionStart": [
                        {"matcher": "compact", "hooks": [{"type": "command", "command": "echo hi"}]}
                    ],
                    "Stop": [{"hooks": [{"type": "command", "command": "echo bye"}]}],
                },
            }
        )
    )
    assert cli.run(["context", "install"]) == 0

    data = json.loads(path.read_text())
    assert data["model"] == "opus"
    assert data["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": "echo bye"}]}]
    groups = data["hooks"]["SessionStart"]
    assert groups[0] == {
        "matcher": "compact",
        "hooks": [{"type": "command", "command": "echo hi"}],
    }
    assert len(groups) == 2
    assert context.HOOK_SENTINEL in groups[1]["hooks"][0]["command"]


def test_install_updates_in_place_rather_than_appending_a_second_entry(tmp_path):
    assert cli.run(["context", "install"]) == 0
    assert cli.run(["context", "install", "--limit", "5"]) == 0
    groups = json.loads(settings_file(tmp_path).read_text())["hooks"]["SessionStart"]
    assert len(groups) == 1
    command = groups[0]["hooks"][0]["command"]
    assert "--limit 5" in command


def test_install_collapses_duplicates_left_by_a_hand_edit(tmp_path):
    path = settings_file(tmp_path)
    path.parent.mkdir(parents=True)
    stale = {"type": "command", "command": "pandan context show --hook --timeout 99 --limit 1"}
    path.write_text(
        json.dumps({"hooks": {"SessionStart": [{"hooks": [stale]}, {"hooks": [dict(stale)]}]}})
    )
    assert cli.run(["context", "install"]) == 0
    groups = json.loads(path.read_text())["hooks"]["SessionStart"]
    assert len(groups) == 1
    assert "--timeout 99" not in groups[0]["hooks"][0]["command"]


def test_install_refuses_to_overwrite_an_unparseable_settings_file(tmp_path, capsys):
    # The one irreversible thing an installer can do is replace a settings file it
    # failed to understand. It must abort with the bytes intact.
    path = settings_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{ this is not json")
    assert cli.run(["context", "install"]) == 1
    assert path.read_text() == "{ this is not json"
    assert "not valid JSON" in capsys.readouterr().out


def test_install_honours_an_explicit_settings_path(tmp_path):
    target = tmp_path / "project" / ".claude" / "settings.json"
    assert cli.run(["context", "install", "--settings", str(target)]) == 0
    assert target.is_file()
    assert not settings_file(tmp_path).exists()


def test_install_hook_command_runs_this_pandan_not_one_found_on_path(tmp_path):
    # A stale `pandan` binary on $PATH has caused two false bug reports on this
    # project, so the installed hook re-invokes the interpreter that installed it
    # (`sys.executable -m pandan_cli`, or the frozen binary itself) and never
    # shutil.which()es for a name.
    assert cli.run(["context", "install"]) == 0
    command = json.loads(settings_file(tmp_path).read_text())["hooks"]["SessionStart"][0][
        "hooks"
    ][0]["command"]
    assert command.split()[0] == context._self_argv()[0]
    assert "-m pandan_cli" in command


def test_install_exec_override_is_used_verbatim(tmp_path):
    assert cli.run(["context", "install", "--exec", "/opt/bin/pandan"]) == 0
    command = json.loads(settings_file(tmp_path).read_text())["hooks"]["SessionStart"][0][
        "hooks"
    ][0]["command"]
    assert command == "/opt/bin/pandan context show --hook --timeout 5 --limit 20"


# --- unconfigured: a no-op with a clear message ---------------------------


@pytest.mark.parametrize("unset", ["PANDAN_BOARD_ID", "PANDAN_TOKEN"])
def test_install_without_a_configured_board_is_a_no_op_with_a_message(
    tmp_path, monkeypatch, capsys, unset
):
    monkeypatch.delenv(unset)
    assert cli.run(["context", "install"]) == 1
    # Proof it was a no-op: the file was not merely left unchanged, it was never
    # created — config is resolved before the settings path is even opened.
    assert not settings_file(tmp_path).exists()
    out = capsys.readouterr().out
    assert out.startswith("error\tconfig\t")
    assert "no board configured" in out
    assert unset in out
    assert "nothing was changed" in out


def test_uninstall_works_without_any_config(tmp_path, monkeypatch, capsys):
    # You must always be able to undo this, even from an environment that could no
    # longer install it.
    assert cli.run(["context", "install"]) == 0
    capsys.readouterr()
    monkeypatch.delenv("PANDAN_TOKEN")
    monkeypatch.delenv("PANDAN_BOARD_ID")
    assert cli.run(["context", "uninstall"]) == 0
    assert "SessionStart" not in settings_file(tmp_path).read_text()


# --- uninstall: clean and idempotent -------------------------------------


def test_install_then_uninstall_is_a_byte_exact_round_trip(tmp_path):
    path = settings_file(tmp_path)
    path.parent.mkdir(parents=True)
    original = json.dumps({"model": "opus", "hooks": {"Stop": []}}, indent=2) + "\n"
    path.write_text(original)

    assert cli.run(["context", "install"]) == 0
    assert path.read_text() != original
    assert cli.run(["context", "uninstall"]) == 0
    # `hooks.SessionStart` and the group that held only our hook are both pruned, so
    # the file comes back exactly as it was — including formatting.
    assert path.read_text() == original


def test_uninstall_of_the_only_hook_removes_the_empty_hooks_key(tmp_path):
    assert cli.run(["context", "install"]) == 0
    assert cli.run(["context", "uninstall"]) == 0
    assert json.loads(settings_file(tmp_path).read_text()) == {}


def test_uninstall_is_idempotent_and_creates_nothing(tmp_path, capsys):
    assert cli.run(["context", "uninstall"]) == 0
    assert not settings_file(tmp_path).exists()
    assert capsys.readouterr().out.startswith("nothing to remove\t")

    assert cli.run(["context", "install"]) == 0
    assert cli.run(["context", "uninstall"]) == 0
    after = settings_file(tmp_path).read_bytes()
    capsys.readouterr()
    assert cli.run(["context", "uninstall"]) == 0
    assert settings_file(tmp_path).read_bytes() == after
    assert capsys.readouterr().out.startswith("nothing to remove\t")


def test_uninstall_leaves_someone_elses_session_start_hook_alone(tmp_path):
    path = settings_file(tmp_path)
    path.parent.mkdir(parents=True)
    mine = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}
    path.write_text(json.dumps(mine))
    assert cli.run(["context", "install"]) == 0
    assert cli.run(["context", "uninstall"]) == 0
    assert json.loads(path.read_text()) == mine


# --- the ambient block + the hook envelope -------------------------------


def test_show_renders_counts_and_open_cards(monkeypatch, capsys):
    _install_fake(monkeypatch)
    assert cli.run(["context", "show"]) == 0
    out = capsys.readouterr().out
    assert "counts: todo=1, in_progress=1, done=1, total=3" in out
    # Only the open columns are listed, in_progress first.
    assert "KAN-2\tin_progress" in out
    assert "KAN-1\ttodo" in out
    assert "KAN-3" not in out
    assert out.index("KAN-2") < out.index("KAN-1")


def test_show_hook_emits_exactly_the_verified_envelope(monkeypatch, capsys):
    _install_fake(monkeypatch)
    assert cli.run(["context", "show", "--hook"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # These three key names are the contract from
    # https://code.claude.com/docs/en/hooks — `additionalContext` inside
    # `hookSpecificOutput`, tagged with `hookEventName`. A typo in any of them means
    # the block is silently never injected.
    assert set(payload) == {"hookSpecificOutput"}
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "counts:" in payload["hookSpecificOutput"]["additionalContext"]


def test_show_respects_the_card_limit(monkeypatch, capsys):
    _install_fake(monkeypatch)
    assert cli.run(["context", "show", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "open cards (1 of 2)" in out
    assert "KAN-1\ttodo" not in out


def test_show_defaults_to_the_configured_board_and_can_be_overridden(monkeypatch):
    made = _install_fake(monkeypatch)
    assert cli.run(["context", "show"]) == 0
    assert made[0].calls[0]["board_id"] == 7
    assert cli.run(["context", "show", "--board", "9"]) == 0
    assert made[1].calls[0]["board_id"] == 9


# --- the cold-start guard: bounded, no retry, soft-fail ------------------


def test_the_hook_client_is_built_with_a_bounded_no_retry_budget(monkeypatch):
    # THE load-bearing assertion of this slice. The shared PandanClient defaults are
    # 35 s read + 5 s connect + a 1 s-backoff retry (client.py:34-39) — a ~76 s worst
    # case, chosen for batch CLI work on a scaled-to-zero backend. Inherit those in
    # an awaited SessionStart hook and every agent session hangs on a cold board.
    _install_fake(monkeypatch)
    assert cli.run(["context", "show", "--hook", "--timeout", "4"]) == 0
    kwargs = FakeClient.last_kwargs
    # Halved, because the client still retries a failed GET exactly once: two
    # attempts at budget/2 keeps the total inside the budget.
    assert kwargs["timeout"] == pytest.approx(2.0)
    assert kwargs["connect_timeout"] <= 2.0
    assert kwargs["retry_backoff"] == 0


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("too slow"),
        httpx.ConnectError("refused"),
        httpx.RemoteProtocolError("UNEXPECTED_EOF"),  # Fly's cold-start TLS symptom
        PandanApiError(401, "bad token"),
        PandanApiError(500, "boom"),
        RuntimeError("something unforeseen"),
    ],
)
def test_show_hook_soft_fails_silently_on_any_error(monkeypatch, capsys, error):
    class Boom(FakeClient):
        def list_cards(self, **kw):
            raise error

    _install_fake(monkeypatch, Boom)
    # Exit 0 and an EMPTY stdout are both required. Exit non-zero puts a hook-error
    # notice in the transcript for something the user can't act on; anything on
    # stdout is parsed as hook output and INJECTED INTO THE MODEL'S CONTEXT — an
    # `error<TAB>config<TAB>…` row posing as board state is worse than no block.
    assert cli.run(["context", "show", "--hook"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no ambient board context" in captured.err


def test_show_hook_soft_fails_even_when_nothing_is_configured(monkeypatch, capsys):
    monkeypatch.delenv("PANDAN_BOARD_ID")
    assert cli.run(["context", "show", "--hook"]) == 0
    assert capsys.readouterr().out == ""


def test_show_without_hook_does_not_swallow_errors(monkeypatch, capsys):
    class Boom(FakeClient):
        def list_cards(self, **kw):
            raise PandanApiError(403, "not yours")

    _install_fake(monkeypatch, Boom)
    # The soft-fail is scoped to --hook. A human running `context show` must still
    # get the CLI's normal error contract, or a broken hook is undiagnosable.
    assert cli.run(["context", "show"]) == 4
    assert capsys.readouterr().out.startswith("error\tforbidden\t")


def test_show_hook_returns_fast_against_a_server_that_never_answers(monkeypatch, capsys):
    """End-to-end wall-clock proof, over a real socket.

    The mocked tests above check that the right timeouts are *passed*; this one
    checks the process actually comes back. The listener accepts the connection and
    then says nothing — which is precisely how a scaled-to-zero Fly machine behaves
    while it wakes, and the case that would otherwise hang every session for up to
    the harness's 600 s default."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    port = listener.getsockname()[1]
    held: list = []
    stop = threading.Event()

    def accept_and_stall():
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                held.append(listener.accept()[0])
            except OSError:
                continue

    thread = threading.Thread(target=accept_and_stall, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("PANDAN_API_URL", f"http://127.0.0.1:{port}")
        started = time.monotonic()
        code = cli.run(["context", "show", "--hook", "--timeout", "1"])
        elapsed = time.monotonic() - started
    finally:
        stop.set()
        thread.join(timeout=2)
        for conn in held:
            conn.close()
        listener.close()

    assert code == 0
    assert capsys.readouterr().out == ""
    # Budget is 1 s (two 0.5 s attempts). 4 s leaves generous CI slack while still
    # being nowhere near the 35 s a default client, or the 600 s a default hook,
    # would have taken.
    assert elapsed < 4.0, f"soft-fail took {elapsed:.1f}s — a session hook must not hang"


# --- status ---------------------------------------------------------------


def test_status_reports_before_and_after_install(tmp_path, capsys):
    assert cli.run(["context", "status"]) == 0
    assert "hook\tnot installed" in capsys.readouterr().out

    assert cli.run(["context", "install"]) == 0
    capsys.readouterr()
    assert cli.run(["context", "status"]) == 0
    out = capsys.readouterr().out
    assert "hook\tinstalled" in out
    assert "board_id\t7" in out
    # Never print the token itself.
    assert "token\tset" in out
    assert "pandan_pat_test" not in out


# --- the packaged skill --------------------------------------------------


def test_the_skill_is_packaged_in_the_repo():
    # KAN-434's trap: a card looks done in-repo while its out-of-repo half is
    # unshipped. The repo now carries the skill, so the installer has something to
    # distribute and the two copies can be diffed.
    packaged = context.packaged_skill_path()
    assert packaged is not None and packaged.is_file()
    text = packaged.read_text(encoding="utf-8")
    assert text.startswith("---\nname: pandan\n")
    assert "pandan" in text


def test_install_lays_down_the_skill_and_uninstall_removes_it(tmp_path, capsys):
    target = context.skill_target_path()
    assert cli.run(["context", "install"]) == 0
    assert target.read_bytes() == context.packaged_skill_path().read_bytes()
    assert "skill\tinstalled" in capsys.readouterr().out

    assert cli.run(["context", "uninstall"]) == 0
    assert not target.exists()
    assert "skill\tremoved" in capsys.readouterr().out


def test_install_does_not_clobber_a_locally_edited_skill(tmp_path, capsys):
    target = context.skill_target_path()
    target.parent.mkdir(parents=True)
    target.write_text("my own notes")
    assert cli.run(["context", "install"]) == 0
    assert target.read_text() == "my own notes"
    assert "left alone (locally modified)" in capsys.readouterr().out

    assert cli.run(["context", "install", "--force-skill"]) == 0
    assert target.read_bytes() == context.packaged_skill_path().read_bytes()


def test_uninstall_never_deletes_a_locally_edited_skill(tmp_path, capsys):
    target = context.skill_target_path()
    target.parent.mkdir(parents=True)
    target.write_text("my own notes")
    assert cli.run(["context", "uninstall"]) == 0
    assert target.read_text() == "my own notes"
    assert "kept (locally modified" in capsys.readouterr().out


def test_no_skill_and_keep_skill_opt_out(tmp_path, capsys):
    assert cli.run(["context", "install", "--no-skill"]) == 0
    assert not context.skill_target_path().exists()
    assert "skill\tskipped (--no-skill)" in capsys.readouterr().out

    assert cli.run(["context", "install"]) == 0
    capsys.readouterr()
    assert cli.run(["context", "uninstall", "--keep-skill"]) == 0
    assert context.skill_target_path().is_file()
    assert "skill\tkept (--keep-skill)" in capsys.readouterr().out


# --- argument validation -------------------------------------------------


@pytest.mark.parametrize("flag,value", [("--timeout", "0"), ("--timeout", "600"),
                                        ("--timeout", "abc"), ("--limit", "0"),
                                        ("--limit", "9999")])
def test_out_of_range_bounds_are_a_usage_error(flag, value, capsys):
    # A `--timeout 600` hook is the very thing this slice exists to prevent, so the
    # flag refuses to express it.
    with pytest.raises(SystemExit) as exc:
        cli.run(["context", "install", flag, value])
    assert exc.value.code == 2
    assert capsys.readouterr().out.startswith("error\tusage\t")


def test_context_is_registered_on_the_top_level_parser():
    parser = cli.build_parser()
    actions = [a for a in parser._actions if getattr(a, "choices", None)]
    names = set()
    for action in actions:
        names.update(action.choices or {})
    assert {"context"} <= names
