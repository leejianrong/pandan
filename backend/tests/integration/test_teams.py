"""Team CRUD integration tests (M9 V65-V66, KAN-1054/1055; ADR 0021).

V65 coverage: the create-bootstraps-owner demo ("create a team via the API, see
yourself listed as its owner"), list scoping to membership (a team has no owner
analogue — membership *is* visibility, unlike a board's owner+member union), the
403/404/401 shape of ``GET /{id}``, and that ``board.team_id`` defaults to NULL
and is unaffected by the migration (R5).

V66 coverage: rename (owner-role gated, doesn't touch a linked board's
``team_id``) and delete (owner-role gated; boards pointing at it are unclaimed via
``ON DELETE SET NULL``, not deleted). Team-*member* management (add/remove/
re-role) is covered separately in ``test_team_members.py``.

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


# --- V66: rename ---------------------------------------------------------------


def test_owner_renames_team(login_as):
    alice = login_as(*ALICE)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]

    r = alice.patch(f"{TEAMS}/{team_id}", json={"name": "Core Platform"})
    assert r.status_code == 200
    assert r.json()["name"] == "Core Platform"
    assert alice.get(f"{TEAMS}/{team_id}").json()["name"] == "Core Platform"


def test_rename_empty_name_422(login_as):
    alice = login_as(*ALICE)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    assert alice.patch(f"{TEAMS}/{team_id}", json={"name": "  "}).status_code == 422


def test_rename_does_not_touch_a_linked_board(login_as):
    """The demo line from SLICES.md: "renaming a team doesn't touch its boards."
    Board<->team linking is V67 (KAN-1056); until it lands the only way to produce
    a board with a non-null team_id is a direct write, exactly like the V65
    NULL-default test does — this asserts a rename leaves that value alone."""
    alice = login_as(*ALICE)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    board_id = alice.get(BOARDS).json()[0]["id"]

    from sqlalchemy import select, update

    from app.db import engine
    from app.models import Board

    with engine.begin() as conn:
        conn.execute(update(Board).where(Board.id == board_id).values(team_id=team_id))

    assert alice.patch(f"{TEAMS}/{team_id}", json={"name": "Core Platform"}).status_code == 200

    with engine.begin() as conn:
        linked = conn.execute(
            select(Board.team_id).where(Board.id == board_id)
        ).scalar_one()
    assert linked == team_id


def test_rename_non_owner_403(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    bob_id = bob.get("/users/me").json()["id"]
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    alice.post(f"{TEAMS}/{team_id}/members", json={"user_id": bob_id, "role": "editor"})

    assert bob.patch(f"{TEAMS}/{team_id}", json={"name": "Nope"}).status_code == 403


def test_rename_non_member_403(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]

    assert bob.patch(f"{TEAMS}/{team_id}", json={"name": "Nope"}).status_code == 403


def test_rename_unknown_team_404(login_as):
    alice = login_as(*ALICE)
    assert alice.patch(f"{TEAMS}/9999", json={"name": "Nope"}).status_code == 404


# --- V66: delete -----------------------------------------------------------


def test_owner_deletes_team(login_as):
    alice = login_as(*ALICE)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]

    assert alice.delete(f"{TEAMS}/{team_id}").status_code == 204
    assert alice.get(f"{TEAMS}/{team_id}").status_code == 404
    assert alice.get(TEAMS).json() == []


def test_delete_unclaims_linked_boards_via_set_null(login_as):
    """ADR 0021 §Shape: deleting a team unclaims its boards (SET NULL), never
    destroys them."""
    alice = login_as(*ALICE)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    board_id = alice.get(BOARDS).json()[0]["id"]

    from sqlalchemy import select, update

    from app.db import engine
    from app.models import Board

    with engine.begin() as conn:
        conn.execute(update(Board).where(Board.id == board_id).values(team_id=team_id))

    assert alice.delete(f"{TEAMS}/{team_id}").status_code == 204

    # The board still exists...
    assert alice.get(f"{BOARDS}/{board_id}").status_code == 200
    # ...but is unclaimed from the now-deleted team.
    with engine.begin() as conn:
        linked = conn.execute(
            select(Board.team_id).where(Board.id == board_id)
        ).scalar_one()
    assert linked is None


def test_delete_non_owner_403(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    bob_id = bob.get("/users/me").json()["id"]
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    alice.post(f"{TEAMS}/{team_id}/members", json={"user_id": bob_id, "role": "editor"})

    assert bob.delete(f"{TEAMS}/{team_id}").status_code == 403


def test_delete_unknown_team_404(login_as):
    alice = login_as(*ALICE)
    assert alice.delete(f"{TEAMS}/9999").status_code == 404
