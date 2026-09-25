"""Board<->workspace linking integration tests (M9 V67, KAN-1056; ADR 0021).

Covers the SLICES.md demo ("create a board under a workspace; GET shows its workspace_id"),
the create/update membership-gate (403 for a non-member, uniformly for an unknown
workspace too), that omitting ``workspace_id`` keeps today's behavior byte-for-byte (NULL),
and that a PATCH can both set and explicitly clear the link.

Per the suite convention, app imports live inside the test bodies.
"""
from __future__ import annotations

BOARDS = "/api/v1/boards"
WORKSPACES = "/api/v1/workspaces"

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")


def test_create_board_under_a_workspace(login_as):
    alice = login_as(*ALICE)
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]

    r = alice.post(BOARDS, json={"name": "Roadmap", "workspace_id": workspace_id})
    assert r.status_code == 201
    board = r.json()
    assert board["workspace_id"] == workspace_id

    got = alice.get(f"{BOARDS}/{board['id']}").json()
    assert got["workspace_id"] == workspace_id


def test_create_board_omitting_workspace_id_is_null(login_as):
    alice = login_as(*ALICE)
    board = alice.post(BOARDS, json={"name": "Solo"}).json()
    assert board["workspace_id"] is None


def test_create_board_non_member_workspace_403(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]

    r = bob.post(BOARDS, json={"name": "Not mine", "workspace_id": workspace_id})
    assert r.status_code == 403


def test_create_board_unknown_workspace_403(login_as):
    """Uniform with the non-member case — a create can't be used to probe which
    workspace ids exist (ADR 0021 §New surface)."""
    alice = login_as(*ALICE)
    assert alice.post(BOARDS, json={"name": "x", "workspace_id": 999999}).status_code == 403


def test_patch_sets_workspace_id(login_as):
    alice = login_as(*ALICE)
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]
    board_id = alice.post(BOARDS, json={"name": "Solo"}).json()["id"]

    r = alice.patch(f"{BOARDS}/{board_id}", json={"workspace_id": workspace_id})
    assert r.status_code == 200
    assert r.json()["workspace_id"] == workspace_id


def test_patch_clears_workspace_id(login_as):
    alice = login_as(*ALICE)
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]
    board_id = alice.post(
        BOARDS, json={"name": "Roadmap", "workspace_id": workspace_id}
    ).json()["id"]

    r = alice.patch(f"{BOARDS}/{board_id}", json={"workspace_id": None})
    assert r.status_code == 200
    assert r.json()["workspace_id"] is None


def test_patch_non_member_workspace_403(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]
    # Bob owns his own board and tries to link it to a workspace he's not on.
    board_id = bob.post(BOARDS, json={"name": "Bob's board"}).json()["id"]

    r = bob.patch(f"{BOARDS}/{board_id}", json={"workspace_id": workspace_id})
    assert r.status_code == 403
    # Unaffected — the rejected PATCH must not have partially applied.
    assert bob.get(f"{BOARDS}/{board_id}").json()["workspace_id"] is None


def test_patch_unrelated_field_leaves_workspace_id_untouched(login_as):
    alice = login_as(*ALICE)
    workspace_id = alice.post(WORKSPACES, json={"name": "Platform"}).json()["id"]
    board_id = alice.post(
        BOARDS, json={"name": "Roadmap", "workspace_id": workspace_id}
    ).json()["id"]

    r = alice.patch(f"{BOARDS}/{board_id}", json={"name": "Roadmap v2"})
    assert r.status_code == 200
    assert r.json()["workspace_id"] == workspace_id
