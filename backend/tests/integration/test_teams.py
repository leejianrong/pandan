"""Team CRUD integration tests (M9 V65, KAN-1054; ADR 0021).

Minimal-CRUD slice: create/list/get only. Covers the create-bootstraps-owner demo
("create a team via the API, see yourself listed as its owner"), list scoping to
membership (a team has no owner analogue — membership *is* visibility, unlike a
board's owner+member union), the 403/404/401 shape of ``GET /{id}``, and that
``board.team_id`` defaults to NULL and is unaffected by the migration (R5).

Per the suite convention, app imports live inside the test bodies.
"""
from __future__ import annotations

TEAMS = "/api/v1/teams"
BOARDS = "/api/v1/boards"

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")


def test_create_team_lists_creator_as_owner(login_as):
    alice = login_as(*ALICE)

    r = alice.post(TEAMS, json={"name": "Platform"})
    assert r.status_code == 201
    team = r.json()
    assert team["name"] == "Platform"
    assert team["role"] == "owner"

    # And it shows up, still role=owner, on both list and get.
    listed = alice.get(TEAMS).json()
    assert len(listed) == 1
    assert listed[0]["id"] == team["id"]
    assert listed[0]["role"] == "owner"

    got = alice.get(f"{TEAMS}/{team['id']}").json()
    assert got["role"] == "owner"


def test_create_team_name_non_empty_422(login_as):
    alice = login_as(*ALICE)
    assert alice.post(TEAMS, json={"name": "  "}).status_code == 422
    assert alice.post(TEAMS, json={"name": ""}).status_code == 422


def test_list_teams_scoped_to_membership(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)

    alice.post(TEAMS, json={"name": "Platform"})
    bob.post(TEAMS, json={"name": "Growth"})

    alice_teams = alice.get(TEAMS).json()
    bob_teams = bob.get(TEAMS).json()
    assert {t["name"] for t in alice_teams} == {"Platform"}
    assert {t["name"] for t in bob_teams} == {"Growth"}


def test_get_team_non_member_403(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]

    assert bob.get(f"{TEAMS}/{team_id}").status_code == 403


def test_get_unknown_team_404(login_as):
    alice = login_as(*ALICE)
    assert alice.get(f"{TEAMS}/9999").status_code == 404


def test_unauthenticated_is_401(client, login_as):
    alice = login_as(*ALICE)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]

    assert client.get(TEAMS).status_code == 401
    assert client.post(TEAMS, json={"name": "x"}).status_code == 401
    assert client.get(f"{TEAMS}/{team_id}").status_code == 401


def test_board_team_id_column_defaults_to_null(login_as):
    """R5 / SHAPING: the additive ``board.team_id`` column is NULL for every board
    with no backfill logic needed. V67 (KAN-1056) is what lets a create actually
    set it (and surfaces it on ``BoardRead``) — this slice only adds the column, so
    it's asserted at the DB layer rather than through a board schema this slice
    deliberately doesn't touch."""
    alice = login_as(*ALICE)  # claims the seeded default board
    board_id = alice.get(BOARDS).json()[0]["id"]

    from sqlalchemy import select

    from app.db import engine
    from app.models import Board

    with engine.begin() as conn:
        team_id = conn.execute(
            select(Board.team_id).where(Board.id == board_id)
        ).scalar_one()
    assert team_id is None
