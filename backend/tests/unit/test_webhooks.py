"""Unit tests for the GitHub webhook receiver (KAN-42, app.routers.webhooks).

No database, no Postgres, no Docker — the endpoint is standalone (its auth is the
HMAC signature, not the board principal resolver), so we mount just its router on
a bare FastAPI app and drive it with TestClient. Covers signature verification
(valid → 200, bad → 401, missing header → 401, secret unset → 503) and event
dispatch (pull_request / check_suite / status routed, unknown ignored but 200).
"""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import webhooks

SECRET = "shhh-test-secret"


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    app = FastAPI()
    app.include_router(webhooks.router, prefix="/api/v1")
    return TestClient(app)


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post(client: TestClient, event: str, payload: dict, *, secret: str = SECRET):
    body = json.dumps(payload).encode()
    headers = {
        "X-GitHub-Event": event,
        "X-Hub-Signature-256": _sign(body, secret),
        "Content-Type": "application/json",
    }
    return client.post("/api/v1/webhooks/github", content=body, headers=headers)


# --- signature verification --------------------------------------------------


def test_valid_signature_is_accepted(client):
    resp = _post(client, "pull_request", {"action": "opened", "number": 1})
    assert resp.status_code == 200
    assert resp.json()["handled"] is True


def test_bad_signature_is_rejected(client):
    body = json.dumps({"action": "opened"}).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": "sha256=" + "0" * 64,
    }
    resp = client.post("/api/v1/webhooks/github", content=body, headers=headers)
    assert resp.status_code == 401


def test_missing_signature_header_is_rejected(client):
    body = json.dumps({"action": "opened"}).encode()
    resp = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "pull_request"},
    )
    assert resp.status_code == 401


def test_wrong_secret_signature_is_rejected(client):
    resp = _post(client, "pull_request", {"action": "opened"}, secret="wrong-secret")
    assert resp.status_code == 401


def test_unconfigured_secret_returns_503(monkeypatch):
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    app = FastAPI()
    app.include_router(webhooks.router, prefix="/api/v1")
    unconfigured = TestClient(app)
    body = json.dumps({"action": "opened"}).encode()
    resp = unconfigured.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": _sign(body)},
    )
    assert resp.status_code == 503


# --- event dispatch ----------------------------------------------------------


@pytest.mark.parametrize(
    "event,payload",
    [
        ("pull_request", {"action": "closed", "number": 7, "pull_request": {"merged": True}}),
        ("check_suite", {"action": "completed", "check_suite": {"conclusion": "success"}}),
        ("status", {"state": "success", "sha": "abc123", "context": "ci/test"}),
    ],
)
def test_handled_events_are_routed(client, event, payload):
    resp = _post(client, event, payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["event"] == event
    assert body["handled"] is True


def test_unknown_event_is_acknowledged_but_ignored(client):
    resp = _post(client, "ping", {"zen": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["event"] == "ping"
    assert body["handled"] is False


def test_dispatch_invokes_the_matching_handler(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setitem(webhooks._DISPATCH, "pull_request", lambda p: calls.append(p))
    _post(client, "pull_request", {"action": "opened", "number": 42})
    assert calls == [{"action": "opened", "number": 42}]


# --- ticket parsing (KAN-43, app.autosync; both forms since V53, KAN-974) ------
# Pure-function, DB-free: the mapping layer parses the reference before it touches
# the database, so these payloads (no ticket) never open a session. Since V53 it
# returns a parsed reference rather than a string, because a board-local ``ENG-42``
# cannot be flattened to one — resolving it needs the key and the number apart.


def test_parse_ticket_from_branch():
    from app.autosync import parse_ticket

    ref = parse_ticket("feat/kan-12-add-widget", None)
    assert (ref.canonical, ref.entity, ref.number) == (True, "card", 12)


def test_parse_ticket_is_case_insensitive():
    from app.autosync import parse_ticket

    for spelling in ("KAN-7", "kan-7", "Kan-7"):
        ref = parse_ticket(spelling)
        assert (ref.canonical, ref.number) == (True, 7), spelling


def test_parse_ticket_prefers_first_candidate():
    from app.autosync import parse_ticket

    # Branch first, then title — the branch's ticket wins.
    assert parse_ticket("feature/KAN-3", "KAN-99: something").number == 3


def test_parse_ticket_falls_back_to_later_candidate():
    from app.autosync import parse_ticket

    assert parse_ticket(None, "fix KAN-5 in the parser").number == 5


def test_parse_ticket_none_when_absent():
    from app.autosync import parse_ticket

    assert parse_ticket("main", "no ticket here", None) is None


def test_parse_ticket_reads_a_board_local_branch():
    """V53's requirement, verbatim from the card: a branch named
    ``eng-42-fix-the-thing`` must match."""
    from app.autosync import parse_ticket

    ref = parse_ticket("eng-42-fix-the-thing")
    assert (ref.canonical, ref.entity, ref.board_key, ref.number) == (
        False,
        "card",
        "ENG",
        42,
    )


def test_the_canonical_form_wins_over_a_board_local_one_anywhere_in_the_text():
    """Canonical is searched across every candidate before board-local is searched
    across any. It is the form that cannot be wrong — it needs no board context — so
    letting a coincidental board-local match outrank it would be strictly worse."""
    from app.autosync import parse_ticket

    ref = parse_ticket("eng-9-branch", "fixes KAN-12")
    assert (ref.canonical, ref.number) == (True, 12)


def test_a_board_local_scan_is_loose_and_that_is_deliberate():
    """``release-2024`` really does parse as key ``RELEASE``, number 2024. Pinned
    rather than papered over: nothing is decided by parsing. Resolution then looks
    for an **auto-sync-enabled** board with that key, and a key nobody owns finds
    nothing — which is why a loose scanner is safe here."""
    from app.autosync import parse_ticket

    ref = parse_ticket("release-2024")
    assert (ref.board_key, ref.number) == ("RELEASE", 2024)


def test_an_epic_reference_is_not_a_card_and_is_discarded():
    """Auto-sync attaches PR links and moves columns; an epic has neither. Before V53
    this could not arise, because the pattern only matched ``KAN-``."""
    from app.autosync import parse_ticket

    assert parse_ticket("EPIC-3") is None
    assert parse_ticket("eng-e7-branch") is None


def test_a_longer_number_is_not_truncated():
    """Without the trailing boundary, ``eng-4200`` would read as ``ENG-42`` and the
    webhook would attach to the wrong card."""
    from app.autosync import parse_ticket

    assert parse_ticket("eng-4200").number == 4200
    assert parse_ticket("kan-4200").number == 4200


def test_pull_request_without_ticket_is_a_noop(client):
    # A handled event whose payload carries no KAN-<n> is acked but touches no DB
    # (proves the mapping short-circuits before opening a session).
    resp = _post(
        client,
        "pull_request",
        {"action": "opened", "pull_request": {"head": {"ref": "main"}, "title": "x"}},
    )
    assert resp.status_code == 200
    assert resp.json()["handled"] is True
