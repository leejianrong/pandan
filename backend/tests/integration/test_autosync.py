"""API tests for GitHub → board auto-sync mapping (KAN-43, app.autosync).

The webhook receiver is authenticated by its HMAC signature, not the board
principal resolver, so these tests drive signed webhook POSTs (no cookie) and
verify the resulting card side effects through the owner-authenticated API.

Covered: ticket parsing from the PR branch, the per-board opt-out gate
(``autosync_enabled`` false → no writes), PR link attach + idempotency, a CI
comment on check_suite / status, and the merge→done move ONLY when the separate
``autosync_advance_to_done`` flag is on.

Per the suite convention, every ``import app...`` lives inside a test/fixture body.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest

CARDS = "/api/v1/cards"
BOARDS = "/api/v1/boards"
WEBHOOK = "/api/v1/webhooks/github"
SECRET = "shhh-autosync-secret"


@pytest.fixture(autouse=True)
def _webhook_secret(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)


@pytest.fixture
def owner(logged_in_client):
    """Board-owning session client — it claimed the default board (id=1) on login."""
    return logged_in_client


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _send(client, event: str, payload: dict):
    body = json.dumps(payload).encode()
    return client.post(
        WEBHOOK,
        content=body,
        headers={"X-GitHub-Event": event, "X-Hub-Signature-256": _sign(body)},
    )


def _default_board_id(owner) -> int:
    return owner.get(BOARDS).json()[0]["id"]


def _enable_autosync(owner, board_id, *, advance=False):
    r = owner.patch(
        f"{BOARDS}/{board_id}",
        json={"autosync_enabled": True, "autosync_advance_to_done": advance},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _make_card(owner, **fields):
    r = owner.post(CARDS, json={"title": "auto", **fields})
    assert r.status_code == 201, r.text
    return r.json()


def _pr_opened(ticket: str, url: str, action: str = "opened") -> dict:
    return {
        "action": action,
        "pull_request": {
            "head": {"ref": f"feat/{ticket.lower()}-work"},
            "title": f"{ticket}: do the thing",
            "html_url": url,
            "merged": False,
        },
    }


# --- schema / defaults -------------------------------------------------------


def test_board_autosync_flags_default_off(owner):
    board = owner.get(BOARDS).json()[0]
    assert board["autosync_enabled"] is False
    assert board["autosync_advance_to_done"] is False


# --- PR opened → work-link ---------------------------------------------------


def test_pr_opened_attaches_pr_link(owner):
    board_id = _default_board_id(owner)
    _enable_autosync(owner, board_id)
    card = _make_card(owner)
    url = "https://github.com/acme/repo/pull/1"

    resp = _send(owner, "pull_request", _pr_opened(card["ticket_number"], url))
    assert resp.status_code == 200

    detail = owner.get(f"{CARDS}/{card['id']}").json()
    assert [(link["label"], link["url"]) for link in detail["links"]] == [("PR", url)]


def test_pr_link_attach_is_idempotent(owner):
    board_id = _default_board_id(owner)
    _enable_autosync(owner, board_id)
    card = _make_card(owner)
    url = "https://github.com/acme/repo/pull/2"
    payload = _pr_opened(card["ticket_number"], url)

    _send(owner, "pull_request", payload)
    _send(owner, "pull_request", payload)  # same URL again

    detail = owner.get(f"{CARDS}/{card['id']}").json()
    assert len(detail["links"]) == 1  # not duplicated


def test_pr_reopened_also_attaches(owner):
    board_id = _default_board_id(owner)
    _enable_autosync(owner, board_id)
    card = _make_card(owner)
    url = "https://github.com/acme/repo/pull/3"

    _send(owner, "pull_request", _pr_opened(card["ticket_number"], url, action="reopened"))
    detail = owner.get(f"{CARDS}/{card['id']}").json()
    assert len(detail["links"]) == 1


# --- the opt-out gate --------------------------------------------------------


def test_autosync_disabled_is_a_noop(owner):
    # Board left with autosync OFF (the default): the webhook must not write.
    card = _make_card(owner)
    url = "https://github.com/acme/repo/pull/4"

    resp = _send(owner, "pull_request", _pr_opened(card["ticket_number"], url))
    assert resp.status_code == 200  # still acked

    detail = owner.get(f"{CARDS}/{card['id']}").json()
    assert detail["links"] == []  # nothing attached


def test_unknown_ticket_is_a_noop(owner):
    board_id = _default_board_id(owner)
    _enable_autosync(owner, board_id)
    resp = _send(
        owner,
        "pull_request",
        _pr_opened("KAN-999999", "https://github.com/acme/repo/pull/5"),
    )
    assert resp.status_code == 200  # no such card → acked, nothing written


# --- check_suite / status → comment ------------------------------------------


def test_check_suite_posts_comment(owner):
    board_id = _default_board_id(owner)
    _enable_autosync(owner, board_id)
    card = _make_card(owner)

    resp = _send(
        owner,
        "check_suite",
        {
            "action": "completed",
            "check_suite": {
                "status": "completed",
                "conclusion": "success",
                "head_branch": f"feat/{card['ticket_number'].lower()}-work",
            },
        },
    )
    assert resp.status_code == 200

    comments = owner.get(f"{CARDS}/{card['id']}/comments").json()
    assert len(comments) == 1
    assert "success" in comments[0]["body"]
    assert comments[0]["author_id"] is None  # system-authored


def test_status_posts_comment(owner):
    board_id = _default_board_id(owner)
    _enable_autosync(owner, board_id)
    card = _make_card(owner)

    resp = _send(
        owner,
        "status",
        {
            "state": "failure",
            "context": "ci/build",
            "branches": [{"name": f"feat/{card['ticket_number'].lower()}-work"}],
        },
    )
    assert resp.status_code == 200

    comments = owner.get(f"{CARDS}/{card['id']}/comments").json()
    assert len(comments) == 1
    assert "failure" in comments[0]["body"]


def test_check_suite_noop_when_disabled(owner):
    card = _make_card(owner)  # board autosync OFF
    _send(
        owner,
        "check_suite",
        {
            "check_suite": {
                "conclusion": "success",
                "head_branch": f"feat/{card['ticket_number'].lower()}",
            }
        },
    )
    assert owner.get(f"{CARDS}/{card['id']}/comments").json() == []


# --- PR merged → move to done (only when advance flag on) --------------------


def _pr_merged(ticket: str) -> dict:
    return {
        "action": "closed",
        "pull_request": {
            "head": {"ref": f"feat/{ticket.lower()}"},
            "title": f"{ticket}: done",
            "merged": True,
        },
    }


def test_merge_does_not_advance_without_flag(owner):
    board_id = _default_board_id(owner)
    _enable_autosync(owner, board_id, advance=False)  # enabled, but advance OFF
    card = _make_card(owner, column="todo")

    _send(owner, "pull_request", _pr_merged(card["ticket_number"]))

    detail = owner.get(f"{CARDS}/{card['id']}").json()
    assert detail["column"] == "todo"  # left where the human put it


def test_merge_advances_to_done_with_flag(owner):
    board_id = _default_board_id(owner)
    _enable_autosync(owner, board_id, advance=True)
    card = _make_card(owner, column="in_progress")

    _send(owner, "pull_request", _pr_merged(card["ticket_number"]))

    detail = owner.get(f"{CARDS}/{card['id']}").json()
    assert detail["column"] == "done"


def test_merge_noop_when_autosync_disabled(owner):
    # advance_to_done is irrelevant while the master switch is off.
    card = _make_card(owner, column="todo")
    _send(owner, "pull_request", _pr_merged(card["ticket_number"]))
    assert owner.get(f"{CARDS}/{card['id']}").json()["column"] == "todo"


# --- board-local refs in a branch name (M8 V53, KAN-974) ---------------------
# The two forms resolve in OPPOSITE directions, and that is the whole of SHAPING D3
# in one code path: a canonical ``KAN-123`` is globally unique, so the card is found
# first and the board follows; a board-local ``ENG-42`` means nothing without a board,
# and a webhook has none of its own — so the *board* is found first, from the set the
# webhook is willing to touch at all (those that opted into auto-sync), and the card
# follows. That opt-in flag is not a convenience filter here; it is what supplies the
# missing board context.


def test_a_board_local_branch_name_attaches_the_pr_link(owner):
    """The card's requirement, verbatim: a branch named ``eng-42-fix-the-thing`` must
    match."""
    board = owner.post(BOARDS, json={"name": "Engine Room", "key": "ENG"}).json()
    _enable_autosync(owner, board["id"])
    card = _make_card(owner, board_id=board["id"])
    assert card["ref"] == "ENG-1"

    url = "https://github.com/acme/repo/pull/42"
    payload = {
        "action": "opened",
        "pull_request": {
            "head": {"ref": "eng-1-fix-the-thing"},
            "title": "no ticket in here",
            "html_url": url,
            "merged": False,
        },
    }
    assert _send(owner, "pull_request", payload).status_code == 200
    links = owner.get(f"{CARDS}/{card['id']}").json()["links"]
    assert [link["url"] for link in links] == [url]


def test_a_board_local_branch_is_ignored_when_the_board_has_not_opted_in(owner):
    """The opt-in is the board context, so without it there is no board to resolve
    against and the webhook is a no-op — the same outcome as the canonical form on a
    board that never opted in."""
    board = owner.post(BOARDS, json={"name": "Engine Room", "key": "ENG"}).json()
    card = _make_card(owner, board_id=board["id"])  # autosync NOT enabled

    payload = {
        "action": "opened",
        "pull_request": {
            "head": {"ref": "eng-1-fix"},
            "title": "x",
            "html_url": "https://github.com/acme/repo/pull/9",
            "merged": False,
        },
    }
    assert _send(owner, "pull_request", payload).status_code == 200
    assert owner.get(f"{CARDS}/{card['id']}").json()["links"] == []


def test_two_opted_in_boards_sharing_a_key_are_skipped_not_guessed(owner, login_as):
    """SHAPING D3's "never a silent pick", in the one place that cannot ask. A webhook
    has no user to prompt, so the only honest answers are one board or none."""
    mine = owner.post(BOARDS, json={"name": "Engine Room", "key": "ENG"}).json()
    _enable_autosync(owner, mine["id"])
    my_card = _make_card(owner, board_id=mine["id"])

    other = login_as("other-eng@example.com", "gh-other-eng")
    theirs = other.post(BOARDS, json={"name": "Engineering", "key": "ENG"}).json()
    _enable_autosync(other, theirs["id"])
    other.post(CARDS, json={"title": "theirs", "board_id": theirs["id"]})

    payload = {
        "action": "opened",
        "pull_request": {
            "head": {"ref": "eng-1-ambiguous"},
            "title": "x",
            "html_url": "https://github.com/acme/repo/pull/7",
            "merged": False,
        },
    }
    assert _send(owner, "pull_request", payload).status_code == 200
    # Neither card touched.
    assert owner.get(f"{CARDS}/{my_card['id']}").json()["links"] == []


def test_the_canonical_form_still_wins_over_a_board_local_one(owner):
    """Canonical is searched across every candidate before board-local is searched
    across any: it is the form that cannot be wrong, since it needs no board context.
    Here the branch carries a board-local ref for a DIFFERENT card and the title
    carries the canonical one — the canonical must win."""
    board = owner.post(BOARDS, json={"name": "Engine Room", "key": "ENG"}).json()
    _enable_autosync(owner, board["id"])
    first = _make_card(owner, board_id=board["id"])
    second = _make_card(owner, board_id=board["id"])

    url = "https://github.com/acme/repo/pull/11"
    payload = {
        "action": "opened",
        "pull_request": {
            "head": {"ref": "eng-1-branch"},
            "title": f"{second['ticket_number']}: the real one",
            "html_url": url,
            "merged": False,
        },
    }
    assert _send(owner, "pull_request", payload).status_code == 200
    assert owner.get(f"{CARDS}/{second['id']}").json()["links"][0]["url"] == url
    assert owner.get(f"{CARDS}/{first['id']}").json()["links"] == []
