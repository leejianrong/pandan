"""Team-membership CRUD integration tests (M9 V66, KAN-1055; ADR 0021).

Mirrors ``test_board_members.py``'s coverage (owner adds/lists/re-roles/removes a
member by email or user_id, duplicate/unknown-user error cases, non-owner ``403``,
unauthenticated ``401``) plus the two things unique to a team: **any owner-role
member** (not just one distinguished owner) may manage membership, and a
**last-owner guard** — a team has no ``owner_id`` fallback the way a board does, so
demoting or removing the team's sole owner is rejected with ``409`` rather than
silently orphaning it.

Per the suite convention, app imports live inside the test bodies.
"""
from __future__ import annotations

TEAMS = "/api/v1/teams"

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")
CAROL = ("carol@example.com", "gh-carol")


def _members_url(team_id: int) -> str:
    return f"{TEAMS}/{team_id}/members"


# --- an owner can manage members ---------------------------------------------


def test_owner_adds_member_by_email(login_as):
    alice = login_as(*ALICE)  # auto-owner of the team it creates
    bob = login_as(*BOB)
    bob_id = bob.get("/users/me").json()["id"]
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]

    r = alice.post(_members_url(team_id), json={"email": BOB[0], "role": "editor"})
    assert r.status_code == 201
    member = r.json()
    assert member["user_id"] == bob_id
    assert member["email"] == BOB[0]
    assert member["role"] == "editor"
    assert member["team_id"] == team_id


def test_owner_adds_member_by_user_id_default_role_viewer(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    bob_id = bob.get("/users/me").json()["id"]
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]

    r = alice.post(_members_url(team_id), json={"user_id": bob_id})
    assert r.status_code == 201
    assert r.json()["role"] == "viewer"  # default


def test_email_lookup_is_case_insensitive(login_as):
    alice = login_as(*ALICE)
    login_as(*BOB)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]

    r = alice.post(_members_url(team_id), json={"email": BOB[0].upper()})
    assert r.status_code == 201
    assert r.json()["email"] == BOB[0]


def test_list_members_includes_creator_and_added(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    carol = login_as(*CAROL)
    bob_id = bob.get("/users/me").json()["id"]
    carol_id = carol.get("/users/me").json()["id"]
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]

    alice.post(_members_url(team_id), json={"user_id": bob_id, "role": "viewer"})
    alice.post(_members_url(team_id), json={"user_id": carol_id, "role": "editor"})

    listed = alice.get(_members_url(team_id)).json()
    assert {m["email"] for m in listed} == {ALICE[0], BOB[0], CAROL[0]}
    assert {m["email"]: m["role"] for m in listed} == {
        ALICE[0]: "owner",
        BOB[0]: "viewer",
        CAROL[0]: "editor",
    }


def test_change_member_role(login_as):
    alice = login_as(*ALICE)
    login_as(*BOB)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    member_id = alice.post(
        _members_url(team_id), json={"email": BOB[0], "role": "viewer"}
    ).json()["id"]

    r = alice.patch(f"{_members_url(team_id)}/{member_id}", json={"role": "editor"})
    assert r.status_code == 200
    assert r.json()["role"] == "editor"


def test_remove_member(login_as):
    alice = login_as(*ALICE)
    login_as(*BOB)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    member_id = alice.post(_members_url(team_id), json={"email": BOB[0]}).json()["id"]

    assert alice.delete(f"{_members_url(team_id)}/{member_id}").status_code == 204
    remaining = {m["email"] for m in alice.get(_members_url(team_id)).json()}
    assert remaining == {ALICE[0]}


def test_any_owner_role_member_can_manage(login_as):
    """Unlike a board (one owner_id), a team may have several owner-role members —
    any of them can manage membership (ADR 0021 §New surface)."""
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    carol = login_as(*CAROL)
    bob_id = bob.get("/users/me").json()["id"]
    carol_id = carol.get("/users/me").json()["id"]
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    alice.post(_members_url(team_id), json={"user_id": bob_id, "role": "owner"})

    # Bob, a co-owner (not the creator), can add Carol.
    r = bob.post(_members_url(team_id), json={"user_id": carol_id, "role": "viewer"})
    assert r.status_code == 201


# --- error cases ---------------------------------------------------------------


def test_add_unknown_user_404(login_as):
    alice = login_as(*ALICE)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    assert (
        alice.post(
            _members_url(team_id), json={"email": "nobody@example.com"}
        ).status_code
        == 404
    )


def test_add_duplicate_member_409(login_as):
    alice = login_as(*ALICE)
    login_as(*BOB)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    assert alice.post(_members_url(team_id), json={"email": BOB[0]}).status_code == 201
    assert alice.post(_members_url(team_id), json={"email": BOB[0]}).status_code == 409


def test_add_member_requires_exactly_one_identity(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    bob_id = bob.get("/users/me").json()["id"]
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    assert alice.post(_members_url(team_id), json={"role": "viewer"}).status_code == 422
    assert (
        alice.post(
            _members_url(team_id), json={"email": BOB[0], "user_id": bob_id}
        ).status_code
        == 422
    )


def test_invalid_role_422(login_as):
    alice = login_as(*ALICE)
    login_as(*BOB)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    assert (
        alice.post(
            _members_url(team_id), json={"email": BOB[0], "role": "admin"}
        ).status_code
        == 422
    )


def test_patch_or_delete_unknown_member_404(login_as):
    alice = login_as(*ALICE)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    assert (
        alice.patch(f"{_members_url(team_id)}/9999", json={"role": "editor"}).status_code
        == 404
    )
    assert alice.delete(f"{_members_url(team_id)}/9999").status_code == 404


def test_member_of_another_team_is_404_here(login_as):
    alice = login_as(*ALICE)
    login_as(*BOB)
    t1 = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    t2 = alice.post(TEAMS, json={"name": "Growth"}).json()["id"]
    member_id = alice.post(_members_url(t1), json={"email": BOB[0]}).json()["id"]

    patch = alice.patch(f"{_members_url(t2)}/{member_id}", json={"role": "editor"})
    assert patch.status_code == 404
    assert alice.delete(f"{_members_url(t2)}/{member_id}").status_code == 404


# --- last-owner guard (the team-specific edge case) --------------------------


def test_cannot_remove_last_owner(login_as):
    alice = login_as(*ALICE)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    member_id = alice.get(_members_url(team_id)).json()[0]["id"]  # alice, the creator

    r = alice.delete(f"{_members_url(team_id)}/{member_id}")
    assert r.status_code == 409


def test_cannot_demote_last_owner(login_as):
    alice = login_as(*ALICE)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    member_id = alice.get(_members_url(team_id)).json()[0]["id"]

    r = alice.patch(f"{_members_url(team_id)}/{member_id}", json={"role": "editor"})
    assert r.status_code == 409


def test_can_remove_an_owner_when_another_owner_remains(login_as):
    alice = login_as(*ALICE)
    bob = login_as(*BOB)
    bob_id = bob.get("/users/me").json()["id"]
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    bob_member_id = alice.post(
        _members_url(team_id), json={"user_id": bob_id, "role": "owner"}
    ).json()["id"]
    alice_member_id = next(
        m["id"]
        for m in alice.get(_members_url(team_id)).json()
        if m["email"] == ALICE[0]
    )

    # Two owners now — removing one is fine, leaving the other as the sole owner.
    assert alice.delete(f"{_members_url(team_id)}/{bob_member_id}").status_code == 204
    # ...but now alice (the last owner) can't be removed.
    assert alice.delete(f"{_members_url(team_id)}/{alice_member_id}").status_code == 409


# --- non-owner is forbidden ----------------------------------------------------


def test_non_owner_gets_403_on_management_routes_but_can_list(login_as):
    alice = login_as(*ALICE)  # owner
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    carol = login_as(*CAROL)
    carol_id = carol.get("/users/me").json()["id"]
    member_id = alice.post(
        _members_url(team_id), json={"user_id": carol_id, "role": "viewer"}
    ).json()["id"]

    # Carol, a viewer, can list (member-gated) but not manage (owner-role gated).
    assert carol.get(_members_url(team_id)).status_code == 200
    assert carol.post(_members_url(team_id), json={"email": BOB[0]}).status_code == 403
    assert (
        carol.patch(
            f"{_members_url(team_id)}/{member_id}", json={"role": "editor"}
        ).status_code
        == 403
    )
    assert carol.delete(f"{_members_url(team_id)}/{member_id}").status_code == 403


def test_non_member_gets_403_on_every_member_route(login_as):
    alice = login_as(*ALICE)  # owns the team
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]

    bob = login_as(*BOB)  # not a member at all
    assert bob.get(_members_url(team_id)).status_code == 403
    assert bob.post(_members_url(team_id), json={"email": BOB[0]}).status_code == 403


# --- unauthenticated is rejected outright --------------------------------------


def test_unauthenticated_is_401(client, login_as):
    alice = login_as(*ALICE)
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    assert client.get(_members_url(team_id)).status_code == 401
    assert client.post(_members_url(team_id), json={"email": BOB[0]}).status_code == 401
    assert (
        client.patch(f"{_members_url(team_id)}/1", json={"role": "editor"}).status_code
        == 401
    )
    assert client.delete(f"{_members_url(team_id)}/1").status_code == 401
