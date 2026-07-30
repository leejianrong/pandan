"""Unit tests for observability wiring (KAN-172): the JSON log formatter, log
configuration, and the Sentry opt-in. All DB-free, so they run in the fast unit
suite. ``app.observability`` imports only FastAPI (never ``app.db``), so importing
it at module top is safe here."""
from __future__ import annotations

import json
import logging

from app.observability import (
    ACCESS_LOGGER,
    JsonLogFormatter,
    configure_logging,
    init_error_tracking,
)


def _record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="kanban.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formatter_emits_json_with_request_fields():
    line = JsonLogFormatter().format(
        _record(
            method="GET",
            path="/api/v1/cards",
            status_code=200,
            latency_ms=1.5,
            principal_id="abc-123",
        )
    )
    payload = json.loads(line)
    assert payload["method"] == "GET"
    assert payload["path"] == "/api/v1/cards"
    assert payload["status_code"] == 200
    assert payload["latency_ms"] == 1.5
    assert payload["principal_id"] == "abc-123"
    assert payload["level"] == "INFO"
    assert payload["msg"] == "request"
    assert "ts" in payload


def test_formatter_allowlists_fields_so_stray_attrs_never_leak():
    """Only the known request fields are serialised — an attribute that isn't on
    the allow-list (e.g. a stray token) never reaches the log line."""
    line = JsonLogFormatter().format(
        _record(path="/api/v1/cards", authorization="Bearer pandan_pat_secret")
    )
    payload = json.loads(line)
    assert "authorization" not in payload
    assert "pandan_pat_secret" not in line


def test_formatter_omits_absent_optional_fields():
    payload = json.loads(JsonLogFormatter().format(_record()))
    for field in ("method", "path", "status_code", "latency_ms", "principal_id"):
        assert field not in payload


def test_configure_logging_respects_level_env(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "warning")
    configure_logging()
    logger = logging.getLogger(ACCESS_LOGGER)
    assert logger.level == logging.WARNING
    assert len(logger.handlers) == 1  # idempotent: no duplicate handlers
    configure_logging()
    assert len(logger.handlers) == 1


def test_error_tracking_is_noop_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_error_tracking() is False


def test_error_tracking_inits_when_dsn_set(monkeypatch):
    import sentry_sdk

    calls = {}

    def fake_init(**kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(sentry_sdk, "init", fake_init)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.ingest.sentry.io/1")
    assert init_error_tracking() is True
    # PII off so cookies/headers/tokens are never transmitted.
    assert calls["send_default_pii"] is False
