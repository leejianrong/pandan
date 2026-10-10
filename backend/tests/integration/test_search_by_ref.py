"""Searching ``q=`` by ticket reference (canonical, board-local, owner-qualified).

App imports live inside test bodies per the suite convention (there are none).
"""
from __future__ import annotations

BOARDS = "/api/v1/boards"
CARDS = "/api/v1/cards"


def _board(client, name, key):
    return client.post(BOARDS, json={"name": name, "key": key}).json()


def _card(client, board_id, title="story", **f):
    return client.post(CARDS, json={"title": title, "board_id": board_id, **f}).json()


def test_canonical_ticket_finds_the_card(logged_in_client):
    b = _board(logged_in_client, "Engine", "ENG")
    c = _card(logged_in_client, b["id"], "alpha")
    _card(logged_in_client, b["id"], "beta")
    r = logged_in_client.get(CARDS, params={"q": c["ticket_number"].lower()})
    assert [x["id"] for x in r.json()] == [c["id"]]


def test_board_local_ref_with_board_id(logged_in_client):
    b = _board(logged_in_client, "Engine", "ENG")
    _card(logged_in_client, b["id"], "one")
    two = _card(logged_in_client, b["id"], "two")
    r = logged_in_client.get(CARDS, params={"q": "ENG-2", "board_id": b["id"]})
    assert [x["id"] for x in r.json()] == [two["id"]]


def test_board_local_ref_without_board_id_spans_visible_boards(logged_in_client):
    b = _board(logged_in_client, "Engine", "ENG")
    p = _board(logged_in_client, "Plat", "PLT")
    _card(logged_in_client, b["id"], "e1")
    p1 = _card(logged_in_client, p["id"], "p1")
    r = logged_in_client.get(CARDS, params={"q": "plt-1"})
    assert [x["id"] for x in r.json()] == [p1["id"]]


def test_board_local_ref_is_scoped_to_the_named_board(logged_in_client):
    b = _board(logged_in_client, "Engine", "ENG")
    p = _board(logged_in_client, "Plat", "PLT")
    _card(logged_in_client, p["id"], "p1")
    r = logged_in_client.get(CARDS, params={"q": "PLT-1", "board_id": b["id"]})
    assert r.json() == []


def test_owner_qualified_ref(logged_in_client):
    b = _board(logged_in_client, "Engine", "ENG")
    c = _card(logged_in_client, b["id"], "one")
    me = logged_in_client.get("/api/v1/me").json()["email"]
    ok = logged_in_client.get(CARDS, params={"q": f"{me}/ENG-1"})
    assert [x["id"] for x in ok.json()] == [c["id"]]
    local = logged_in_client.get(CARDS, params={"q": f"{me.split('@')[0]}/ENG-1"})
    assert [x["id"] for x in local.json()] == [c["id"]]
    other = logged_in_client.get(CARDS, params={"q": "nobody/ENG-1"})
    assert other.json() == []


def test_exact_ref_ranks_above_a_text_mention(logged_in_client):
    b = _board(logged_in_client, "Engine", "ENG")
    target = _card(logged_in_client, b["id"], "plain")
    t = target["ticket_number"]
    _card(logged_in_client, b["id"], f"mentions {t} {t}")
    r = logged_in_client.get(CARDS, params={"q": t})
    assert r.json()[0]["id"] == target["id"]


def test_partial_ref_does_not_match_exactly(logged_in_client):
    b = _board(logged_in_client, "Engine", "ENG")
    for n in range(12):
        _card(logged_in_client, b["id"], f"c{n}")
    r = logged_in_client.get(CARDS, params={"q": "ENG-1", "board_id": b["id"]})
    assert [x["ref"] for x in r.json()] == ["ENG-1"]
