"""Board<->team linking integration tests (M9 V67, KAN-1056; ADR 0021).

Covers the SLICES.md demo ("create a board under a team; GET shows its team_id"),
the create/update membership-gate (403 for a non-member, uniformly for an unknown
team too), that omitting ``team_id`` keeps today's behavior byte-for-byte (NULL),
and that a PATCH can both set and explicitly clear the link.

Per the suite convention, app imports live inside the test bodies.
"""
from __future__ import annotations

BOARDS = "/api/v1/boards"
TEAMS = "/api/v1/teams"

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")


def test_create_board_under_a_team(login_as):
    alice = login_as(*ALICE)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]

    r = alice.post(BOARDS, json={"name": "Roadmap", "team_id": team_id})
    assert r.status_code == 201
    board = r.json()
    assert board["team_id"] == team_id

    got = alice.get(f"{BOARDS}/{board['id']}").json()
    assert got["team_id"] == team_id


def test_create_board_omitting_team_id_is_null(login_as):
    alice = login_as(*ALICE)
    board = alice.post(BOARDS, json={"name": "Solo"}).json()
    assert board["team_id"] is None


def test_create_board_non_member_team_403(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]

    r = bob.post(BOARDS, json={"name": "Not mine", "team_id": team_id})
    assert r.status_code == 403


def test_create_board_unknown_team_403(login_as):
    """Uniform with the non-member case — a create can't be used to probe which
    team ids exist (ADR 0021 §New surface)."""
    alice = login_as(*ALICE)
    assert alice.post(BOARDS, json={"name": "x", "team_id": 999999}).status_code == 403


def test_patch_sets_team_id(login_as):
    alice = login_as(*ALICE)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    board_id = alice.post(BOARDS, json={"name": "Solo"}).json()["id"]

    r = alice.patch(f"{BOARDS}/{board_id}", json={"team_id": team_id})
    assert r.status_code == 200
    assert r.json()["team_id"] == team_id


def test_patch_clears_team_id(login_as):
    alice = login_as(*ALICE)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    board_id = alice.post(BOARDS, json={"name": "Roadmap", "team_id": team_id}).json()["id"]

    r = alice.patch(f"{BOARDS}/{board_id}", json={"team_id": None})
    assert r.status_code == 200
    assert r.json()["team_id"] is None


def test_patch_non_member_team_403(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    # Bob owns his own board and tries to link it to a team he's not on.
    board_id = bob.post(BOARDS, json={"name": "Bob's board"}).json()["id"]

    r = bob.patch(f"{BOARDS}/{board_id}", json={"team_id": team_id})
    assert r.status_code == 403
    # Unaffected — the rejected PATCH must not have partially applied.
    assert bob.get(f"{BOARDS}/{board_id}").json()["team_id"] is None


def test_patch_unrelated_field_leaves_team_id_untouched(login_as):
    alice = login_as(*ALICE)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    board_id = alice.post(BOARDS, json={"name": "Roadmap", "team_id": team_id}).json()["id"]

    r = alice.patch(f"{BOARDS}/{board_id}", json={"name": "Roadmap v2"})
    assert r.status_code == 200
    assert r.json()["team_id"] == team_id
