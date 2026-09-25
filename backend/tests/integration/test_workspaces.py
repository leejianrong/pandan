"""Workspace CRUD integration tests (M9 V65-V66, KAN-1054/1055; ADR 0021).

V65 coverage: the create-bootstraps-owner demo ("create a workspace via the API, see
yourself listed as its owner"), list scoping to membership (a workspace has no owner
analogue — membership *is* visibility, unlike a board's owner+member union), the
403/404/401 shape of ``GET /{id}``, and that ``board.workspace_id`` defaults to NULL
and is unaffected by the migration (R5).

V66 coverage: rename (owner-role gated, doesn't touch a linked board's
``workspace_id``) and delete (owner-role gated; boards pointing at it are unclaimed via
``ON DELETE SET NULL``, not deleted). Workspace-*member* management (add/remove/
re-role) is covered separately in ``test_workspace_members.py``.

Per the suite convention, app imports live inside the test bodies.
"""
from __future__ import annotations

WORKSPACES = "/api/v1/workspaces"
BOARDS = "/api/v1/boards"

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")


def test_create_workspace_lists_creator_as_owner(login_as):
    alice = login_as(*ALICE)

    r = alice.post(WORKSPACES, json={"name": "Platform"})
    assert r.status_code == 201
    workspace = r.json()
    assert workspace["name"] == "Platform"
    assert workspace["role"] == "owner"

    # And it shows up, still role=owner, on both list and get.
    listed = alice.get(WORKSPACES).json()
    assert len(listed) == 1
    assert listed[0]["id"] == workspace["id"]
    assert listed[0]["role"] == "owner"

    got = alice.get(f"{WORKSPACES}/{workspace['id']}").json()
    assert got["role"] == "owner"


def test_create_workspace_name_non_empty_422(login_as):
    alice = login_as(*ALICE)
    assert alice.post(WORKSPACES, json={"name": "  "}).status_code == 422
    assert alice.post(WORKSPACES, json={"name": ""}).status_code == 422


def test_list_workspaces_scoped_to_membership(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)

    alice.post(WORKSPACES, json={"name": "Platform"})
    bob.post(WORKSPACES, json={"name": "Growth"})

    alice_workspaces = alice.get(WORKSPACES).json()
    bob_workspaces = bob.get(WORKSPACES).json()
    assert {t["name"] for t in alice_workspaces} == {"Platform"}
    assert {t["name"] for t in bob_workspaces} == {"Growth"}


def test_get_workspace_non_member_403(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]

    assert bob.get(f"{WORKSPACES}/{workspace_id}").status_code == 403


def test_get_unknown_workspace_404(login_as):
    alice = login_as(*ALICE)
    assert alice.get(f"{WORKSPACES}/9999").status_code == 404


def test_unauthenticated_is_401(client, login_as):
    alice = login_as(*ALICE)
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]

    assert client.get(WORKSPACES).status_code == 401
    assert client.post(WORKSPACES, json={"name": "x"}).status_code == 401
    assert client.get(f"{WORKSPACES}/{workspace_id}").status_code == 401


def test_board_workspace_id_column_defaults_to_null(login_as):
    """R5 / SHAPING: the additive ``board.workspace_id`` column is NULL for every board
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
        workspace_id = conn.execute(
            select(Board.workspace_id).where(Board.id == board_id)
        ).scalar_one()
    assert workspace_id is None


# --- V66: rename ---------------------------------------------------------------


def test_owner_renames_workspace(login_as):
    alice = login_as(*ALICE)
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]

    r = alice.patch(f"{WORKSPACES}/{workspace_id}", json={"name": "Core Platform"})
    assert r.status_code == 200
    assert r.json()["name"] == "Core Platform"
    assert alice.get(f"{WORKSPACES}/{workspace_id}").json()["name"] == "Core Platform"


def test_rename_empty_name_422(login_as):
    alice = login_as(*ALICE)
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]
    assert alice.patch(f"{WORKSPACES}/{workspace_id}", json={"name": "  "}).status_code == 422


def test_rename_does_not_touch_a_linked_board(login_as):
    """The demo line from SLICES.md: "renaming a workspace doesn't touch its boards."
    Board<->workspace linking is V67 (KAN-1056); until it lands the only way to produce
    a board with a non-null workspace_id is a direct write, exactly like the V65
    NULL-default test does — this asserts a rename leaves that value alone."""
    alice = login_as(*ALICE)
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]
    board_id = alice.get(BOARDS).json()[0]["id"]

    from sqlalchemy import select, update

    from app.db import engine
    from app.models import Board

    with engine.begin() as conn:
        conn.execute(update(Board).where(Board.id == board_id).values(workspace_id=workspace_id))

    r = alice.patch(f"{WORKSPACES}/{workspace_id}", json={"name": "Core Platform"})
    assert r.status_code == 200

    with engine.begin() as conn:
        linked = conn.execute(
            select(Board.workspace_id).where(Board.id == board_id)
        ).scalar_one()
    assert linked == workspace_id


def test_rename_non_owner_403(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    bob_id = bob.get("/users/me").json()["id"]
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]
    alice.post(f"{WORKSPACES}/{workspace_id}/members", json={"user_id": bob_id, "role": "editor"})

    assert bob.patch(f"{WORKSPACES}/{workspace_id}", json={"name": "Nope"}).status_code == 403


def test_rename_non_member_403(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]

    assert bob.patch(f"{WORKSPACES}/{workspace_id}", json={"name": "Nope"}).status_code == 403


def test_rename_unknown_workspace_404(login_as):
    alice = login_as(*ALICE)
    assert alice.patch(f"{WORKSPACES}/9999", json={"name": "Nope"}).status_code == 404


# --- V66: delete -----------------------------------------------------------


def test_owner_deletes_workspace(login_as):
    alice = login_as(*ALICE)
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]

    assert alice.delete(f"{WORKSPACES}/{workspace_id}").status_code == 204
    assert alice.get(f"{WORKSPACES}/{workspace_id}").status_code == 404
    assert alice.get(WORKSPACES).json() == []


def test_delete_unclaims_linked_boards_via_set_null(login_as):
    """ADR 0021 §Shape: deleting a workspace unclaims its boards (SET NULL), never
    destroys them."""
    alice = login_as(*ALICE)
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]
    board_id = alice.get(BOARDS).json()[0]["id"]

    from sqlalchemy import select, update

    from app.db import engine
    from app.models import Board

    with engine.begin() as conn:
        conn.execute(update(Board).where(Board.id == board_id).values(workspace_id=workspace_id))

    assert alice.delete(f"{WORKSPACES}/{workspace_id}").status_code == 204

    # The board still exists...
    assert alice.get(f"{BOARDS}/{board_id}").status_code == 200
    # ...but is unclaimed from the now-deleted workspace.
    with engine.begin() as conn:
        linked = conn.execute(
            select(Board.workspace_id).where(Board.id == board_id)
        ).scalar_one()
    assert linked is None


def test_delete_non_owner_403(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    bob_id = bob.get("/users/me").json()["id"]
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]
    alice.post(f"{WORKSPACES}/{workspace_id}/members", json={"user_id": bob_id, "role": "editor"})

    assert bob.delete(f"{WORKSPACES}/{workspace_id}").status_code == 403


def test_delete_unknown_workspace_404(login_as):
    alice = login_as(*ALICE)
    assert alice.delete(f"{WORKSPACES}/9999").status_code == 404
