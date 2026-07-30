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
def clean_env(monkeypatch):
    """No config from the developer's shell, and a fresh notice memo per test."""
    for names in config_mod._ENV_NAMES.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
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
