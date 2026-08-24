"""API tests for the batch card read — ``GET /api/v1/cards?ids=``/``refs=`` (issue #254).

The endpoint exists to collapse an N-round-trip fan-out into one request; the
motivating case is kaya rendering ``[[KAN-12]]`` wikilinks, where a spec note with
forty refs was forty reads on every render.

The design decision worth testing hardest is what happens to a selector that
resolves to nothing. Both answers are defensible — a renderer must not have one bad
ref blank the whole note, a script wants a hard guarantee — and the issue names the
one option to avoid: omitting silently. So the contract is **omit from the body, name
in the ``X-Unresolved-Selectors`` header**, and most of this file pins that:

* unknown / soft-deleted / another user's card all report identically, because
  distinguishing them would leak whether a row exists on a board you cannot see;
* malformed input is a *different* thing and 422s, so a broken caller cannot be
  mistaken for one asking about a deleted card;
* the cap is a documented 422, never a silent truncation;
* ``limit``/``cursor`` are refused, because a truncated page would report real,
  visible cards as misses.

Per the suite convention, app-module imports go inside test bodies, not at module top.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def client(logged_in_client):
    """V8 (ADR 0013): /api/v1 is owner-gated, so these run as the board-owning
    session user (claim-on-login gives them the reset fixture's default board)."""
    return logged_in_client


CARDS = "/api/v1/cards"
UNRESOLVED = "X-Unresolved-Selectors"


def _create(client, **fields):
    return client.post(CARDS, json={"title": "T", **fields}).json()


# --- the happy path --------------------------------------------------------


def test_read_many_by_id_in_one_request(client):
    a = _create(client, title="A")
    b = _create(client, title="B")
    _create(client, title="C")  # not asked for

    r = client.get(CARDS, params={"ids": f"{a['id']},{b['id']}"})
    assert r.status_code == 200
    assert {c["title"] for c in r.json()} == {"A", "B"}
    # Nothing missed → no header at all, so its absence means a complete answer.
    assert UNRESOLVED not in r.headers


def test_read_many_by_ticket_ref(client):
    a = _create(client, title="A")
    b = _create(client, title="B")

    r = client.get(CARDS, params={"refs": f"{a['ticket_number']},{b['ticket_number']}"})
    assert r.status_code == 200
    assert {c["title"] for c in r.json()} == {"A", "B"}
    assert UNRESOLVED not in r.headers


def test_refs_are_case_insensitive(client):
    a = _create(client, title="A")
    r = client.get(CARDS, params={"refs": a["ticket_number"].lower()})
    assert r.status_code == 200
    assert [c["title"] for c in r.json()] == ["A"]
    assert UNRESOLVED not in r.headers


def test_ids_and_refs_combine_as_a_union(client):
    a = _create(client, title="A")
    b = _create(client, title="B")
    r = client.get(CARDS, params={"ids": str(a["id"]), "refs": b["ticket_number"]})
    assert r.status_code == 200
    assert {c["title"] for c in r.json()} == {"A", "B"}


def test_a_card_named_both_ways_is_returned_once(client):
    """``ids`` and ``refs`` OR together, so naming one card twice must not duplicate
    it — nor report the second naming as a miss."""
    a = _create(client, title="A")
    r = client.get(CARDS, params={"ids": str(a["id"]), "refs": a["ticket_number"]})
    assert r.status_code == 200
    assert [c["title"] for c in r.json()] == ["A"]
    assert UNRESOLVED not in r.headers


def test_duplicate_selectors_are_not_reported_as_misses(client):
    """``ids=7,7`` must not come back as one hit and one miss."""
    a = _create(client, title="A")
    r = client.get(CARDS, params={"ids": f"{a['id']},{a['id']}"})
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert UNRESOLVED not in r.headers


def test_selectors_and_the_filters_compose(client):
    """The selector set ANDs with the ordinary filters, so "which of these are done"
    is one request."""
    a = _create(client, title="A", column="done")
    b = _create(client, title="B", column="todo")
    r = client.get(CARDS, params={"ids": f"{a['id']},{b['id']}", "column": "done"})
    assert r.status_code == 200
    assert [c["title"] for c in r.json()] == ["A"]
    # B was filtered out, not missing — but the report is computed from what came
    # back, so it is named. Documented: selectors report against the final result.
    assert r.headers.get(UNRESOLVED) == str(b["id"])


# --- the unresolved contract ----------------------------------------------


def test_unknown_id_is_omitted_and_named(client):
    a = _create(client, title="A")
    r = client.get(CARDS, params={"ids": f"{a['id']},99999999"})
    assert r.status_code == 200
    assert [c["title"] for c in r.json()] == ["A"]
    assert r.headers[UNRESOLVED] == "99999999"


def test_unresolved_preserves_the_callers_order_and_spelling(client):
    """The header reads back in the caller's own terms so a renderer can map it
    straight onto the wikilinks it failed to resolve."""
    r = client.get(CARDS, params={"refs": "KAN-9999999,kan-9999998"})
    assert r.status_code == 200
    assert r.json() == []
    assert r.headers[UNRESOLVED] == "KAN-9999999,kan-9999998"


def test_a_soft_deleted_card_reports_as_unresolved(client):
    """Soft-deleted rows are invisible to every default read (KAN-19); a batch read
    must not become the exception that resurrects them."""
    a = _create(client, title="A")
    assert client.delete(f"{CARDS}/{a['id']}").status_code in (200, 204)
    r = client.get(CARDS, params={"ids": str(a["id"])})
    assert r.status_code == 200
    assert r.json() == []
    assert r.headers[UNRESOLVED] == str(a["id"])


def test_an_epic_ticket_parses_but_resolves_to_nothing(client):
    """``EPIC-3`` is a well-formed ticket that simply is not a card. That is an
    unresolved selector, not malformed input — a note containing ``[[EPIC-3]]``
    should not 422 the whole batch."""
    a = _create(client, title="A")
    r = client.get(CARDS, params={"refs": f"{a['ticket_number']},EPIC-1"})
    assert r.status_code == 200
    assert [c["title"] for c in r.json()] == ["A"]
    assert r.headers[UNRESOLVED] == "EPIC-1"


def test_another_users_card_is_unresolved_not_forbidden(login_as):
    """**The security-relevant case.** Naming a board directly is a 403, but a batch
    read must not become an existence oracle: an id on someone else's board has to be
    indistinguishable from an id that never existed."""
    owner = login_as("owner@example.com", "gh-owner")
    other = login_as("other@example.com", "gh-other")

    theirs = owner.post(CARDS, json={"title": "secret"}).json()

    r = other.get(CARDS, params={"ids": str(theirs["id"])})
    assert r.status_code == 200  # not 403 — that would confirm the row exists
    assert r.json() == []
    assert r.headers[UNRESOLVED] == str(theirs["id"])

    # And the report is byte-identical to a plainly non-existent id.
    r_missing = other.get(CARDS, params={"ids": "99999999"})
    assert r_missing.json() == []
    assert r_missing.headers[UNRESOLVED] == "99999999"


# --- malformed input is a different thing ----------------------------------


def test_non_numeric_id_is_422_not_unresolved(client):
    """A broken caller must not be able to look like one asking about a deleted
    card."""
    r = client.get(CARDS, params={"ids": "abc"})
    assert r.status_code == 422
    assert "numeric" in r.json()["detail"]


def test_a_ref_that_is_not_a_ticket_is_422(client):
    r = client.get(CARDS, params={"refs": "not-a-ticket"})
    assert r.status_code == 422
    assert "KAN-12" in r.json()["detail"]


def test_an_empty_selector_list_is_422(client):
    """``ids=`` is a caller bug — almost certainly an unpopulated variable. Returning
    the whole board for it is exactly the accidental full-table read the cap exists
    to prevent."""
    r = client.get(CARDS, params={"ids": ""})
    assert r.status_code == 422
    r = client.get(CARDS, params={"refs": " , "})
    assert r.status_code == 422


# --- the cap ---------------------------------------------------------------


def test_too_many_selectors_is_422_not_a_silent_truncation(client):
    from app.schemas import MAX_CARD_SELECTORS

    too_many = ",".join(str(i) for i in range(1, MAX_CARD_SELECTORS + 2))
    r = client.get(CARDS, params={"ids": too_many})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert str(MAX_CARD_SELECTORS) in detail


def test_exactly_the_cap_is_allowed(client):
    from app.schemas import MAX_CARD_SELECTORS

    at_cap = ",".join(str(i) for i in range(1, MAX_CARD_SELECTORS + 1))
    assert client.get(CARDS, params={"ids": at_cap}).status_code == 200


def test_the_cap_counts_ids_and_refs_together(client):
    """Otherwise the two params are a trivial way to double it."""
    from app.schemas import MAX_CARD_SELECTORS

    half = MAX_CARD_SELECTORS // 2 + 1
    r = client.get(
        CARDS,
        params={
            "ids": ",".join(str(i) for i in range(1, half + 1)),
            "refs": ",".join(f"KAN-{i}" for i in range(1000, 1000 + half)),
        },
    )
    assert r.status_code == 422


# --- pagination is refused, not silently wrong -----------------------------


@pytest.mark.parametrize("extra", [{"limit": 1}, {"cursor": "x"}])
def test_selectors_cannot_be_paginated(client, extra):
    """A page cut short would leave real, visible cards looking like misses, and the
    caller could not tell the difference."""
    a = _create(client, title="A")
    b = _create(client, title="B")
    r = client.get(CARDS, params={"ids": f"{a['id']},{b['id']}", **extra})
    assert r.status_code == 422
    assert "limit or cursor" in r.json()["detail"]


# --- back-compat -----------------------------------------------------------


def test_absent_selectors_change_nothing(client):
    """The whole feature is additive: no ids/refs → the endpoint behaves exactly as
    before, header included."""
    _create(client, title="A")
    _create(client, title="B")
    r = client.get(CARDS)
    assert r.status_code == 200
    assert len(r.json()) == 2
    assert UNRESOLVED not in r.headers


# --- board-local refs (M8 V53, KAN-974) ------------------------------------
# ``ENG-14`` resolves only inside a known board, so this endpoint requires
# ``board_id`` for it. That is not a limitation of the batch read, it is what
# "board-local" means: keys are unique per OWNER (ADR 0020), so one ref can name a
# different card for two people.

BOARDS = "/api/v1/boards"


def _keyed_board(client, name: str, key: str) -> dict:
    return client.post(BOARDS, json={"name": name, "key": key}).json()


def test_a_board_local_ref_resolves_within_its_board(client):
    board = _keyed_board(client, "Engine Room", "ENG")
    first = _create(client, title="one", board_id=board["id"])
    second = _create(client, title="two", board_id=board["id"])

    r = client.get(CARDS, params={"board_id": board["id"], "refs": "ENG-2"})
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == [second["id"]]
    assert UNRESOLVED not in r.headers
    assert first["id"] not in [c["id"] for c in r.json()]


def test_board_local_and_canonical_refs_name_the_same_card(client):
    """The equivalence the whole slice exists for."""
    board = _keyed_board(client, "Engine Room", "ENG")
    card = _create(client, title="one", board_id=board["id"])

    by_local = client.get(CARDS, params={"board_id": board["id"], "refs": "ENG-1"}).json()
    by_canonical = client.get(
        CARDS, params={"board_id": board["id"], "refs": card["ticket_number"]}
    ).json()
    assert [c["id"] for c in by_local] == [c["id"] for c in by_canonical] == [card["id"]]


def test_a_board_local_ref_is_case_insensitive(client):
    board = _keyed_board(client, "Engine Room", "ENG")
    card = _create(client, title="one", board_id=board["id"])
    r = client.get(CARDS, params={"board_id": board["id"], "refs": "eng-1"})
    assert [c["id"] for c in r.json()] == [card["id"]]


def test_a_board_local_ref_without_a_board_is_422(client):
    """The alternatives were both worse. Resolving across every visible board would
    silently return two cards for one selector; failing the whole request on one
    ambiguous selector would contradict this endpoint's own design, where a miss is
    *reported* rather than fatal. Requiring the board is neither."""
    _keyed_board(client, "Engine Room", "ENG")
    r = client.get(CARDS, params={"refs": "ENG-1"})
    assert r.status_code == 422
    assert "board-local" in r.json()["detail"]
    assert "board_id" in r.json()["detail"]


def test_an_owner_qualified_ref_is_422_here(client):
    """With ``board_id`` given the owner is already determined, so the qualifier can
    only agree redundantly or contradict. The CLI resolves that form; this endpoint
    does not need to."""
    board = _keyed_board(client, "Engine Room", "ENG")
    r = client.get(
        CARDS, params={"board_id": board["id"], "refs": "someone/ENG-1"}
    )
    assert r.status_code == 422
    assert "owner-qualified" in r.json()["detail"]


def test_a_board_local_ref_for_another_board_is_unresolved_not_wrong(client):
    """Naming board 1's key while asking board 2 must report a miss, never reach across
    — the board filter and the selector filter are AND-ed, not OR-ed."""
    one = _keyed_board(client, "Engine Room", "ENG")
    two = _keyed_board(client, "Platform", "PLT")
    _create(client, title="on one", board_id=one["id"])
    r = client.get(CARDS, params={"board_id": two["id"], "refs": "ENG-1"})
    assert r.status_code == 200
    assert r.json() == []
    assert r.headers[UNRESOLVED] == "ENG-1"


def test_a_board_local_epic_ref_parses_and_resolves_to_nothing(client):
    """``ENG-E7`` is a well-formed reference to something that is not a card — the same
    disposition as ``EPIC-3``: reported, not rejected."""
    board = _keyed_board(client, "Engine Room", "ENG")
    _create(client, title="one", board_id=board["id"])
    r = client.get(CARDS, params={"board_id": board["id"], "refs": "ENG-1,ENG-E7"})
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.headers[UNRESOLVED] == "ENG-E7"


def test_the_two_forms_mix_in_one_request(client):
    board = _keyed_board(client, "Engine Room", "ENG")
    a = _create(client, title="A", board_id=board["id"])
    b = _create(client, title="B", board_id=board["id"])
    r = client.get(
        CARDS,
        params={"board_id": board["id"], "refs": f"ENG-1,{b['ticket_number']},ENG-9"},
    )
    assert sorted(c["id"] for c in r.json()) == sorted([a["id"], b["id"]])
    assert r.headers[UNRESOLVED] == "ENG-9"


def test_a_board_local_ref_cannot_read_across_an_authorization_boundary(client, login_as):
    """The selector filter is AND-ed with the owner-scoping, so a stranger naming a
    board they cannot see gets a miss — never a 403, which would confirm the row."""
    board = _keyed_board(client, "Engine Room", "ENG")
    _create(client, title="private", board_id=board["id"])
    stranger = login_as("refs-stranger@example.com", "gh-refs-stranger")
    r = stranger.get(CARDS, params={"board_id": board["id"], "refs": "ENG-1"})
    # Naming a board you cannot read is still a 403 — that predates this slice and is
    # about the *board* parameter, not the ref.
    assert r.status_code == 403
