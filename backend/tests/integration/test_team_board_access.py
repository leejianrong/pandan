"""Team-default board access integration tests (M9 V68, KAN-1057; ADR 0021).

The full 401/403/200 matrix the SLICES.md testing notes call for: owner /
explicit-``BoardMember``-override / team-default / neither, crossed with
viewer/editor/owner at each layer, plus the "removed from team loses the default
but keeps an explicit share" case named directly in ADR 0021. Written as its own
suite (not folded into ``test_role_enforcement.py``) so a future change to
``_effective_access`` can't silently drop a case.

A team-default grant behaves exactly like a ``board_member`` row of the same role
(``test_role_enforcement.py`` covers that read/write/manage shape in full) — the
new thing this suite proves is the *precedence*: an explicit ``board_member`` row
always wins over the team default, in **both** directions (a lower explicit role
does not get boosted by a higher team default, and vice versa), and the default
disappears the moment team membership does while an explicit share does not.

Two+ distinct human sessions come from the ``login_as`` factory (see conftest).
Per the suite convention, app imports live inside the test bodies (none needed
here — everything is HTTP).
"""
from __future__ import annotations

BOARDS = "/api/v1/boards"
CARDS = "/api/v1/cards"
EPICS = "/api/v1/epics"
TEAMS = "/api/v1/teams"

ALICE = ("alice@example.com", "gh-alice")
BOB = ("bob@example.com", "gh-bob")
CAROL = ("carol@example.com", "gh-carol")


def _members_url(board_id: int) -> str:
    return f"{BOARDS}/{board_id}/members"


def _team_members_url(team_id: int) -> str:
    return f"{TEAMS}/{team_id}/members"


def _setup_team_default(login_as, role: str):
    """Alice owns the default board and links it to a team; Bob joins the team
    with ``role`` and gets **no explicit** ``board_member`` row — his access flows
    purely through the V68 team-default rung.

    Returns ``(alice, bob, board_id, a_card, a_epic, team_id)``.
    """
    alice = login_as(*ALICE)  # first login claims the default board
    board_id = alice.get(BOARDS).json()[0]["id"]
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    assert alice.patch(f"{BOARDS}/{board_id}", json={"team_id": team_id}).status_code == 200
    a_card = alice.post(CARDS, json={"title": "seed", "board_id": board_id}).json()
    a_epic = alice.post(EPICS, json={"name": "seed-epic", "board_id": board_id}).json()

    bob = login_as(*BOB)
    bob_id = bob.get("/users/me").json()["id"]
    added = alice.post(_team_members_url(team_id), json={"user_id": bob_id, "role": role})
    assert added.status_code == 201
    return alice, bob, board_id, a_card, a_epic, team_id


# --- team-default viewer: read yes, write no ----------------------------------


def test_team_viewer_can_read(login_as):
    _alice, bob, board_id, a_card, a_epic, _team_id = _setup_team_default(login_as, "viewer")

    assert bob.get(f"{BOARDS}/{board_id}").status_code == 200
    assert bob.get(f"{CARDS}/{a_card['id']}").status_code == 200
    assert bob.get(f"{EPICS}/{a_epic['id']}").status_code == 200
    assert bob.get(CARDS, params={"board_id": board_id}).status_code == 200
    assert bob.get(EPICS, params={"board_id": board_id}).status_code == 200


def test_team_viewer_cannot_write(login_as):
    _alice, bob, board_id, a_card, _a_epic, _team_id = _setup_team_default(login_as, "viewer")

    assert bob.post(CARDS, json={"title": "x", "board_id": board_id}).status_code == 403
    assert bob.patch(f"{CARDS}/{a_card['id']}", json={"title": "x"}).status_code == 403
    assert bob.delete(f"{CARDS}/{a_card['id']}").status_code == 403


def test_team_viewer_cannot_manage(login_as):
    _alice, bob, board_id, _a_card, _a_epic, _team_id = _setup_team_default(login_as, "viewer")

    assert bob.patch(f"{BOARDS}/{board_id}", json={"name": "x"}).status_code == 403
    assert bob.delete(f"{BOARDS}/{board_id}").status_code == 403


# --- team-default editor: read + write yes, manage no -------------------------


def test_team_editor_can_read_and_write(login_as):
    _alice, bob, board_id, a_card, a_epic, _team_id = _setup_team_default(login_as, "editor")

    made = bob.post(CARDS, json={"title": "by-editor", "board_id": board_id})
    assert made.status_code == 201
    assert bob.patch(f"{CARDS}/{a_card['id']}", json={"title": "edited"}).status_code == 200
    assert bob.post(f"{CARDS}/{a_card['id']}/move", json={"column": "done"}).status_code == 200
    assert bob.delete(f"{CARDS}/{made.json()['id']}").status_code == 204
    epic = bob.post(EPICS, json={"name": "by-editor", "board_id": board_id})
    assert epic.status_code == 201
    assert bob.patch(f"{EPICS}/{a_epic['id']}", json={"name": "e2"}).status_code == 200


def test_team_editor_cannot_manage(login_as):
    _alice, bob, board_id, _a_card, _a_epic, _team_id = _setup_team_default(login_as, "editor")

    assert bob.patch(f"{BOARDS}/{board_id}", json={"name": "x"}).status_code == 403
    assert bob.delete(f"{BOARDS}/{board_id}").status_code == 403
    assert bob.post(_members_url(board_id), json={"email": CAROL[0]}).status_code == 403


# --- team-default owner: full access, like a board_member owner row -----------


def test_team_owner_role_member_can_manage(login_as):
    alice, bob, board_id, _a_card, _a_epic, _team_id = _setup_team_default(login_as, "owner")

    assert bob.patch(f"{BOARDS}/{board_id}", json={"name": "renamed"}).status_code == 200
    carol = login_as(*CAROL)
    carol_id = carol.get("/users/me").json()["id"]
    added = bob.post(_members_url(board_id), json={"user_id": carol_id, "role": "viewer"})
    assert added.status_code == 201
    # And the real board owner still manages, of course.
    assert alice.delete(f"{BOARDS}/{board_id}").status_code == 204


# --- precedence: an explicit board_member row always wins ---------------------


def test_explicit_share_overrides_a_lower_team_default(login_as):
    """Bob's team role is editor, but an explicit *viewer* board_member row on this
    board caps him at READ — an explicit share wins on presence, not on being the
    higher grant (ADR 0021 §Interaction, SHAPING D2)."""
    alice, bob, board_id, a_card, _a_epic, _team_id = _setup_team_default(login_as, "editor")
    alice.post(_members_url(board_id), json={"email": BOB[0], "role": "viewer"})

    assert bob.get(f"{BOARDS}/{board_id}").status_code == 200
    assert bob.post(CARDS, json={"title": "x", "board_id": board_id}).status_code == 403
    assert bob.patch(f"{CARDS}/{a_card['id']}", json={"title": "x"}).status_code == 403


def test_explicit_share_overrides_a_higher_team_default(login_as):
    """The flip side: Bob's team role is viewer, but an explicit *editor*
    board_member row grants him WRITE — the override cuts both directions."""
    alice, bob, board_id, a_card, _a_epic, _team_id = _setup_team_default(login_as, "viewer")
    alice.post(_members_url(board_id), json={"email": BOB[0], "role": "editor"})

    assert bob.patch(f"{CARDS}/{a_card['id']}", json={"title": "edited"}).status_code == 200


# --- removal semantics ----------------------------------------------------


def test_removing_from_team_removes_the_default(login_as):
    alice, bob, board_id, _a_card, _a_epic, team_id = _setup_team_default(login_as, "editor")
    bob_member_id = next(
        m["id"]
        for m in alice.get(_team_members_url(team_id)).json()
        if m["email"] == BOB[0]
    )

    assert alice.delete(f"{_team_members_url(team_id)}/{bob_member_id}").status_code == 204

    assert bob.get(f"{BOARDS}/{board_id}").status_code == 403


def test_removing_from_team_leaves_an_explicit_share_untouched(login_as):
    """The case named directly in ADR 0021: removing team membership removes only
    the *default*; a separately-granted explicit share survives, at its own
    (possibly lower) level."""
    alice, bob, board_id, a_card, _a_epic, team_id = _setup_team_default(login_as, "editor")
    alice.post(_members_url(board_id), json={"email": BOB[0], "role": "viewer"})
    bob_team_member_id = next(
        m["id"]
        for m in alice.get(_team_members_url(team_id)).json()
        if m["email"] == BOB[0]
    )

    assert alice.delete(f"{_team_members_url(team_id)}/{bob_team_member_id}").status_code == 204

    # The explicit viewer share still stands...
    assert bob.get(f"{BOARDS}/{board_id}").status_code == 200
    # ...but Bob never had WRITE from the explicit row alone (only from the now-gone
    # default), so he's capped at READ.
    assert bob.patch(f"{CARDS}/{a_card['id']}", json={"title": "x"}).status_code == 403


# --- the default doesn't leak beyond its own team/board ------------------------


def test_team_default_does_not_leak_to_an_unrelated_board(login_as):
    """Bob is on Team A, which owns no board; Board X belongs to Team B instead.
    Bob's Team-A membership must not grant him anything on Board X."""
    alice = login_as(*ALICE)
    board_id = alice.get(BOARDS).json()[0]["id"]
    team_b = alice.post(TEAMS, json={"name": "Team B"}).json()["id"]
    alice.patch(f"{BOARDS}/{board_id}", json={"team_id": team_b})

    bob = login_as(*BOB)
    bob_id = bob.get("/users/me").json()["id"]
    team_a = alice.post(TEAMS, json={"name": "Team A"}).json()["id"]
    alice.post(_team_members_url(team_a), json={"user_id": bob_id, "role": "owner"})

    assert bob.get(f"{BOARDS}/{board_id}").status_code == 403


def test_team_membership_grants_nothing_on_a_teamless_board(login_as):
    alice = login_as(*ALICE)
    board_id = alice.get(BOARDS).json()[0]["id"]  # team_id stays NULL
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]

    bob = login_as(*BOB)
    bob_id = bob.get("/users/me").json()["id"]
    alice.post(_team_members_url(team_id), json={"user_id": bob_id, "role": "owner"})

    assert bob.get(f"{BOARDS}/{board_id}").status_code == 403


# --- list visibility (KAN-15's OR, extended) -----------------------------------


def test_team_default_board_appears_in_list(login_as):
    _alice, bob, board_id, _a_card, _a_epic, _team_id = _setup_team_default(login_as, "viewer")

    listed_ids = {b["id"] for b in bob.get(BOARDS).json()}
    assert board_id in listed_ids


def test_non_member_board_absent_from_list(login_as):
    alice = login_as(*ALICE)
    board_id = alice.get(BOARDS).json()[0]["id"]
    team_id = alice.post(TEAMS, json={"name": "Platform"}).json()["id"]
    alice.patch(f"{BOARDS}/{board_id}", json={"team_id": team_id})

    bob = login_as(*BOB)  # never joins the team
    assert bob.get(BOARDS).json() == []


# --- unauthenticated is rejected outright --------------------------------------


def test_unauthenticated_is_401(client, login_as):
    _alice, _bob, board_id, _a_card, _a_epic, _team_id = _setup_team_default(login_as, "viewer")
    assert client.get(f"{BOARDS}/{board_id}").status_code == 401
