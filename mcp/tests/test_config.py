"""Config resolution for the MCP server (V40, KAN-423, ADR 0018).

The rebrand introduced ``PANDAN_API_URL`` / ``PANDAN_TOKEN`` / ``PANDAN_BOARD_ID``
and kept the pre-rebrand ``KANBAN_*`` names as a **deprecated fallback**, read
second, so a live ``.mcp.json`` can't be bricked mid-cutover. These tests pin that
precedence, the one-line stderr notice, and that the notice never reaches stdout —
an MCP stdio server's stdout is the JSON-RPC channel, so a stray print there would
corrupt the protocol, which is the failure mode most worth a regression test.
"""
from __future__ import annotations

import pytest

from pandan_mcp import config as config_mod
from pandan_mcp.config import DEFAULT_API_URL, load_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """No config from the developer's shell or their real config file, and a
    fresh notice memo per test.

    ``XDG_CONFIG_HOME`` is redirected to an empty ``tmp_path`` — without this,
    a machine that has ever run ``pandan login``/``pandan auth login`` has a
    real ``~/.config/pandan/config.toml`` carrying a real token, and KAN-1731's
    file fallback would read it straight into these tests (this bit exactly
    that way in development: the fallback's own tests passed by accident
    against a *legacy*-format file that used the ``[kan]`` table instead of
    ``[pandan]``, and would have started leaking a real secret the moment that
    file was migrated to the current format)."""
    for names in config_mod._ENV_NAMES.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config_mod._warned.clear()


def test_defaults_when_nothing_is_set():
    cfg = load_config()
    assert cfg.api_url == DEFAULT_API_URL
    assert cfg.token is None
    assert cfg.board_id is None


def test_pandan_env_wins_over_kanban_env(monkeypatch, capsys):
    monkeypatch.setenv("PANDAN_API_URL", "https://new.example")
    monkeypatch.setenv("KANBAN_API_URL", "https://old.example")
    monkeypatch.setenv("PANDAN_TOKEN", "pandan_pat_new")
    monkeypatch.setenv("KANBAN_TOKEN", "kanban_pat_old")
    monkeypatch.setenv("PANDAN_BOARD_ID", "5")
    monkeypatch.setenv("KANBAN_BOARD_ID", "9")

    cfg = load_config()

    assert cfg.api_url == "https://new.example"
    assert cfg.token == "pandan_pat_new"
    assert cfg.board_id == 5
    assert capsys.readouterr().err == ""  # nothing deprecated was used


def test_kanban_env_alone_still_resolves_and_warns_on_stderr(monkeypatch, capsys):
    monkeypatch.setenv("KANBAN_API_URL", "https://old.example")
    monkeypatch.setenv("KANBAN_TOKEN", "kanban_pat_old")
    monkeypatch.setenv("KANBAN_BOARD_ID", "9")

    cfg = load_config()

    assert cfg.api_url == "https://old.example"
    assert cfg.token == "kanban_pat_old"
    assert cfg.board_id == 9
    captured = capsys.readouterr()
    # stdout is the JSON-RPC channel — it MUST stay empty.
    assert captured.out == ""
    for name in ("KANBAN_API_URL", "KANBAN_TOKEN", "KANBAN_BOARD_ID"):
        assert name in captured.err
        assert name.replace("KANBAN_", "PANDAN_") in captured.err
    assert "deprecated" in captured.err


def test_notice_is_emitted_once_per_process(monkeypatch, capsys):
    monkeypatch.setenv("KANBAN_TOKEN", "kanban_pat_old")
    load_config()
    assert capsys.readouterr().err.count("KANBAN_TOKEN") == 1
    load_config()
    assert capsys.readouterr().err == ""


def test_mixed_env_resolves_per_value(monkeypatch):
    monkeypatch.setenv("PANDAN_TOKEN", "pandan_pat_new")
    monkeypatch.setenv("KANBAN_BOARD_ID", "9")
    cfg = load_config()
    assert cfg.token == "pandan_pat_new"
    assert cfg.board_id == 9


def test_empty_string_is_treated_as_unset(monkeypatch):
    """``.mcp.json`` commonly ships ``"PANDAN_TOKEN": ""`` as a placeholder."""
    monkeypatch.setenv("PANDAN_TOKEN", "  ")
    monkeypatch.setenv("KANBAN_TOKEN", "kanban_pat_old")
    assert load_config().token == "kanban_pat_old"


def test_non_integer_board_id_names_the_current_env_var(monkeypatch):
    monkeypatch.setenv("KANBAN_BOARD_ID", "not-a-number")
    with pytest.raises(ValueError) as excinfo:
        load_config()
    assert "PANDAN_BOARD_ID" in str(excinfo.value)


# --- the config-file fallback (ADR 0024, KAN-1731) ---------------------------


def _write_config_file(tmp_path, body: str) -> None:
    config_dir = tmp_path / "pandan"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(body, encoding="utf-8")


def test_falls_back_to_the_cli_config_file_when_no_env_is_set(tmp_path):
    """``XDG_CONFIG_HOME`` is already redirected to ``tmp_path`` by the
    autouse ``clean_env`` fixture."""
    _write_config_file(
        tmp_path,
        '[pandan]\napi_url = "https://file.example"\ntoken = "pandan_pat_fromfile"\nboard_id = 7\n',
    )
    cfg = load_config()
    assert cfg.api_url == "https://file.example"
    assert cfg.token == "pandan_pat_fromfile"
    assert cfg.board_id == 7


def test_env_wins_over_the_config_file_per_value(tmp_path, monkeypatch):
    """Precedence is per value, mirroring the CLI's own ``KANBAN_*``/``PANDAN_*``
    resolution: an env var set for *one* key must not make the file's other
    values disappear."""
    _write_config_file(
        tmp_path,
        '[pandan]\napi_url = "https://file.example"\ntoken = "pandan_pat_fromfile"\nboard_id = 7\n',
    )
    monkeypatch.setenv("PANDAN_TOKEN", "pandan_pat_fromenv")

    cfg = load_config()
    assert cfg.token == "pandan_pat_fromenv"  # env wins
    assert cfg.api_url == "https://file.example"  # file still supplies the rest
    assert cfg.board_id == 7


def test_a_deprecated_env_spelling_still_beats_the_config_file(tmp_path, monkeypatch):
    """The file fallback sits *behind* the whole PANDAN_*/KANBAN_* chain, not
    just PANDAN_* — an already-configured .mcp.json (even on the old spelling)
    must not be silently overridden by a file most .mcp.json users never
    wrote."""
    _write_config_file(tmp_path, '[pandan]\ntoken = "pandan_pat_fromfile"\n')
    monkeypatch.setenv("KANBAN_TOKEN", "kanban_pat_fromenv")

    assert load_config().token == "kanban_pat_fromenv"


def test_no_config_file_at_all_is_not_an_error(tmp_path):
    """``tmp_path`` exists but has no ``pandan/config.toml`` in it — the common
    case for anyone who has never run ``pandan login``."""
    cfg = load_config()
    assert cfg.token is None


def test_a_malformed_config_file_is_not_fatal(tmp_path):
    _write_config_file(tmp_path, "this is not [valid toml")
    cfg = load_config()
    assert cfg.token is None


def test_a_legacy_kan_table_is_not_read_by_this_fallback(tmp_path):
    """Deliberately narrower than the CLI's own file handling (see the module
    docstring): only the current ``[pandan]`` table is read here, not the
    legacy ``[kan]`` one a not-yet-migrated CLI config file might still use."""
    _write_config_file(tmp_path, '[kan]\ntoken = "kanban_pat_legacy"\n')
    assert load_config().token is None


def test_a_bare_top_level_table_is_still_tolerated(tmp_path):
    """Mirrors ``pandan_cli.config``'s own tolerance for a config file with no
    table header at all — keys directly at the document root."""
    _write_config_file(tmp_path, 'token = "pandan_pat_bare"\n')
    assert load_config().token == "pandan_pat_bare"
