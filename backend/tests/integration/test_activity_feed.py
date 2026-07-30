"""API tests for the activity-feed READ side — KAN-18 (M4 audit trail, R5.1).

KAN-17 shipped the ``activity`` model + write path (see test_activity_log.py);
this slice adds ``GET /api/v1/boards/{id}/activity`` — a paginated, newest-first,
member-scoped feed. These tests drive real mutations over the HTTP client (which
record activity) and then read them back through the new endpoint, asserting the
entries, newest-first ordering, keyset pagination, and the authz gates (member
READ / non-member 403 / no-or-bad-token 401).

Per the suite convention, all app-module imports live inside the test bodies, not
at module top (the PR #17 collection-time trap).
"""
from __future__ import annotations

import pytest

CARDS = "/api/v1/cards"
BOARDS = "/api/v1/boards"

ACTOR_EMAIL = "octocat@example.com"

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")
CAROL = ("carol@example.com", "gh-carol")


@pytest.fixture
def client(logged_in_client):
    """/api/v1 is owner-gated (V8); run as the board-owning session user, who owns
    the reset fixture's default board via claim-on-login."""
    return logged_in_client


def _activity_url(board_id: int) -> str:
    return f"{BOARDS}/{board_id}/activity"


# --- feed contents + ordering ------------------------------------------------


def test_feed_returns_recorded_activity_newest_first(client):
    board_id = client.get(BOARDS).json()[0]["id"]
    # Three ordered mutations: create → update → move (three activity rows).
    card = client.post(CARDS, json={"title": "Fix login"}).json()
    client.patch(f"{CARDS}/{card['id']}", json={"title": "Fix login flow"})
    client.post(f"{CARDS}/{card['id']}/move", json={"column": "in_progress"})

    r = client.get(_activity_url(board_id))
    assert r.status_code == 200, r.text
    feed = r.json()
    # Newest-first: the most recent action (move) leads.
    actions = [a["action"] for a in feed]
    assert actions == ["moved", "updated", "created"]

    # Entries carry the model's real fields.
    top = feed[0]
    assert top["board_id"] == board_id
    assert top["entity_type"] == "card"
    assert top["entity_id"] == card["id"]
    assert top["actor_label"] == ACTOR_EMAIL
    assert top["actor_user_id"] is not None
    assert "in_progress" in top["summary"]
    assert top["ts"] is not None
    # ts is monotonically non-increasing (newest-first).
    timestamps = [a["ts"] for a in feed]
    assert timestamps == sorted(timestamps, reverse=True)


def test_feed_is_scoped_to_its_board(client):
    """A board's feed shows only its own activity, not another board's."""
    other = client.post(BOARDS, json={"name": "Other"}).json()
    default_id = client.get(BOARDS).json()[0]["id"]
    # A card on `other` records activity on `other`, not the default board.
    client.post(CARDS, json={"title": "elsewhere", "board_id": other["id"]})

    default_feed = client.get(_activity_url(default_id)).json()
    assert all(a["board_id"] == default_id for a in default_feed)
    other_feed = client.get(_activity_url(other["id"])).json()
    assert all(a["board_id"] == other["id"] for a in other_feed)
    # `other` has at least its own board-created + card-created rows.
    assert {a["action"] for a in other_feed} >= {"created"}


# --- keyset pagination (mirrors GET /cards) ----------------------------------


def test_pagination_pages_through_newest_first_without_gaps(client):
    board_id = client.get(BOARDS).json()[0]["id"]
    # Six creates → six activity rows (plus the board-claim rows already present).
    for i in range(6):
        client.post(CARDS, json={"title": f"card-{i}"})

    seen: list[int] = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        r = client.get(_activity_url(board_id), params=params)
        assert r.status_code == 200, r.text
        page = r.json()
        seen.extend(a["id"] for a in page)
        cursor = r.headers.get("X-Next-Cursor")
        pages += 1
        # A short page is the last one — no next cursor.
        if len(page) < 2:
            assert cursor is None
            break
        if cursor is None:
            break
        assert pages < 50  # guard against a runaway loop

    # Every id seen exactly once (disjoint, gap-free) and strictly newest-first.
    assert len(seen) == len(set(seen))
    assert seen == sorted(seen, reverse=True)


def test_invalid_cursor_is_422(client):
    board_id = client.get(BOARDS).json()[0]["id"]
    r = client.get(_activity_url(board_id), params={"cursor": "not-a-cursor"})
    assert r.status_code == 422, r.text


# --- authorization: member READ / non-member 403 / no-or-bad token 401 -------


def test_member_can_read_feed(login_as):
    """A viewer member (not just the owner) may read the board's activity feed."""
    alice = login_as(*ALICE)  # owns the default board
    bob = login_as(*BOB)
    bob_id = bob.get("/users/me").json()["id"]
    board_id = alice.get(BOARDS).json()[0]["id"]
    alice.post(CARDS, json={"title": "seed activity", "board_id": board_id})

    alice.post(f"{BOARDS}/{board_id}/members", json={"user_id": bob_id, "role": "viewer"})

    r = bob.get(_activity_url(board_id))
    assert r.status_code == 200, r.text
    assert len(r.json()) >= 1


def test_non_member_gets_403(login_as):
    """A user who is neither owner nor member is forbidden (not a silent empty)."""
    alice = login_as(*ALICE)  # owns the default board
    carol = login_as(*CAROL)  # member of nothing
    board_id = alice.get(BOARDS).json()[0]["id"]

    r = carol.get(_activity_url(board_id))
    assert r.status_code == 403, r.text


def test_no_token_gets_401(client):
    """An unauthenticated caller (no cookie session, no bearer) is rejected."""
    board_id = client.get(BOARDS).json()[0]["id"]
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anon:
        r = anon.get(_activity_url(board_id))
    assert r.status_code == 401, r.text


def test_bad_token_gets_401(client):
    """A garbage bearer token resolves to no principal → 401."""
    board_id = client.get(BOARDS).json()[0]["id"]
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anon:
        r = anon.get(
            _activity_url(board_id),
            headers={"Authorization": "Bearer pandan_pat_totally-bogus"},
        )
    assert r.status_code == 401, r.text
