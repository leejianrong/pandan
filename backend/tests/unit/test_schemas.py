"""Unit tests for the Pydantic request schemas (app.schemas).

Pure validation logic — no database, no HTTP, no Docker. These exercise the
CardCreate/CardUpdate validators (title non-empty, story_points in the allowed
set, column enum) directly, so they run in milliseconds in the `unit` CI job.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import (
    CardCreate,
    CardRead,
    CardUpdate,
    ColumnEnum,
    CommentCreate,
    CycleCreate,
    DependencyCreate,
    EpicCreate,
    EpicUpdate,
    LabelCreate,
    LinkCreate,
    NeedsHumanRequest,
    PriorityEnum,
    TokenCreate,
    TokenScope,
)


def test_create_minimal_defaults_to_todo():
    card = CardCreate(title="Write docs")
    assert card.column is ColumnEnum.todo
    assert card.description is None
    assert card.story_points is None
    # No epic link by default (that the id references an existing epic is checked
    # in the router, not here).
    assert card.epic_id is None


def test_create_accepts_epic_id():
    assert CardCreate(title="ok", epic_id=7).epic_id == 7


def test_create_and_update_accept_cycle_id():
    # V33 (KAN-297): cycle_id defaults to None and is accepted on create + update.
    assert CardCreate(title="ok").cycle_id is None
    assert CardCreate(title="ok", cycle_id=4).cycle_id == 4
    assert CardUpdate(cycle_id=4).cycle_id == 4
    assert CardUpdate(cycle_id=None).cycle_id is None


def test_cycle_create_requires_non_empty_name():
    # V33 (KAN-297): name required non-empty; bounds optional (default None).
    cycle = CycleCreate(name="Sprint 1")
    assert cycle.starts_on is None and cycle.ends_on is None
    for bad_name in ("", "   ", "\t\n"):
        with pytest.raises(ValidationError):
            CycleCreate(name=bad_name)


def test_cycle_create_accepts_bounds():
    cycle = CycleCreate(
        name="Sprint 1",
        starts_on="2026-01-01T00:00:00Z",
        ends_on="2026-01-14T00:00:00Z",
    )
    assert cycle.starts_on is not None and cycle.ends_on is not None


def test_epic_create_requires_non_empty_name():
    assert EpicCreate(name="Mobile Checkout").description is None
    for bad_name in ("", "   ", "\t\n"):
        with pytest.raises(ValidationError):
            EpicCreate(name=bad_name)


def test_epic_project_fields_default_to_none():
    # V31 (KAN-295): target_date + lead are optional and default to None.
    epic = EpicCreate(name="Q3 Launch")
    assert epic.target_date is None
    assert epic.lead is None
    upd = EpicUpdate()
    assert upd.target_date is None
    assert upd.lead is None


def test_epic_create_accepts_project_fields():
    epic = EpicCreate(name="Q3 Launch", target_date="2026-09-01T00:00:00Z", lead="ada")
    assert epic.target_date is not None
    assert epic.lead == "ada"


def test_epic_update_accepts_project_fields_and_clears():
    upd = EpicUpdate(target_date="2026-09-01T00:00:00Z", lead="ada")
    assert upd.target_date is not None
    assert upd.lead == "ada"
    # Explicit null clears (only sent fields are applied by the router).
    cleared = EpicUpdate(target_date=None, lead=None)
    assert cleared.model_dump(exclude_unset=True) == {"target_date": None, "lead": None}


def test_epic_lead_rejects_over_length():
    # lead is varchar(255); an over-long value is a clean 422, not a 500 at INSERT.
    with pytest.raises(ValidationError):
        EpicCreate(name="ok", lead="x" * 256)
    with pytest.raises(ValidationError):
        EpicUpdate(lead="x" * 256)


def test_epic_create_rejects_bad_target_date():
    with pytest.raises(ValidationError):
        EpicCreate(name="ok", target_date="not-a-date")


@pytest.mark.parametrize("bad_title", ["", "   ", "\t\n"])
def test_create_rejects_empty_or_whitespace_title(bad_title):
    with pytest.raises(ValidationError):
        CardCreate(title=bad_title)


@pytest.mark.parametrize("points", [1, 2, 3, 5, 8, 13, None])
def test_create_accepts_valid_story_points(points):
    assert CardCreate(title="ok", story_points=points).story_points == points


@pytest.mark.parametrize("points", [0, 4, 6, 7, 100, -1])
def test_create_rejects_story_points_outside_set(points):
    with pytest.raises(ValidationError):
        CardCreate(title="ok", story_points=points)


def test_create_rejects_unknown_column():
    with pytest.raises(ValidationError):
        CardCreate(title="ok", column="archived")


def test_update_allows_none_title_but_not_empty():
    # None means "field not being edited" and is allowed.
    assert CardUpdate(title=None).title is None
    # An explicit empty/whitespace title is a validation error.
    with pytest.raises(ValidationError):
        CardUpdate(title="   ")


# --- card dependencies (KAN-28) --------------------------------------------


def test_card_read_dependency_arrays_default_empty():
    # The router populates these from the card_dependency table; when it can't
    # (or there are none) they default to empty rather than error out.
    card = CardRead(
        id=1,
        ticket_number="KAN-1",
        board_id=1,
        title="t",
        description=None,
        column=ColumnEnum.todo,
        position=0,
        story_points=None,
        assignee=None,
        epic_id=None,
        cycle_id=None,
        priority="none",
        due_date=None,
        needs_human=False,
        attention_note=None,
        created_at="2026-07-09T00:00:00Z",
        updated_at="2026-07-09T00:00:00Z",
    )
    assert card.blocked_by == []
    assert card.blocks == []


def test_dependency_create_requires_blocker_id():
    assert DependencyCreate(blocker_id=5).blocker_id == 5
    with pytest.raises(ValidationError):
        DependencyCreate()


# --- card work-links (KAN-32) ----------------------------------------------


def test_card_read_links_default_empty():
    # The router populates ``links`` from the card_link table; when there are none
    # it defaults to empty rather than error out.
    card = CardRead(
        id=1,
        ticket_number="KAN-1",
        board_id=1,
        title="t",
        description=None,
        column=ColumnEnum.todo,
        position=0,
        story_points=None,
        assignee=None,
        epic_id=None,
        cycle_id=None,
        priority="none",
        due_date=None,
        needs_human=False,
        attention_note=None,
        created_at="2026-07-10T00:00:00Z",
        updated_at="2026-07-10T00:00:00Z",
    )
    assert card.links == []


def test_link_create_requires_non_empty_label_and_url():
    link = LinkCreate(label="PR", url="https://github.com/x/y/pull/1")
    assert link.label == "PR"
    assert link.url == "https://github.com/x/y/pull/1"
    for bad in ("", "   ", "\t\n"):
        with pytest.raises(ValidationError):
            LinkCreate(label=bad, url="https://example.com")
        with pytest.raises(ValidationError):
            LinkCreate(label="PR", url=bad)
    # Both fields are required.
    with pytest.raises(ValidationError):
        LinkCreate(label="PR")


# --- card notes / comments (KAN-33) ----------------------------------------


def test_comment_create_requires_non_empty_body():
    comment = CommentCreate(body="why this is blocked: waiting on infra")
    assert comment.body == "why this is blocked: waiting on infra"
    for bad in ("", "   ", "\t\n"):
        with pytest.raises(ValidationError):
            CommentCreate(body=bad)
    # body is required.
    with pytest.raises(ValidationError):
        CommentCreate()


# --- card fields: priority / due_date / labels (M5 V11, KAN-244) ------------


def test_priority_defaults_to_none():
    assert CardCreate(title="t").priority is PriorityEnum.none


def test_priority_accepts_valid_values():
    for value in ("none", "low", "medium", "high", "urgent"):
        assert CardCreate(title="t", priority=value).priority.value == value


def test_priority_rejects_unknown_value():
    with pytest.raises(ValidationError):
        CardCreate(title="t", priority="critical")
    with pytest.raises(ValidationError):
        CardUpdate(priority="whenever")


def test_label_ids_default_none_and_accept_list():
    assert CardCreate(title="t").label_ids is None
    assert CardCreate(title="t", label_ids=[1, 2]).label_ids == [1, 2]
    # Update accepts an empty list (a deliberate "clear all labels").
    assert CardUpdate(label_ids=[]).label_ids == []


def test_due_date_optional_and_parsed():
    assert CardCreate(title="t").due_date is None
    card = CardCreate(title="t", due_date="2026-08-01T00:00:00Z")
    assert card.due_date is not None


def test_label_create_requires_non_empty_name_and_color():
    assert LabelCreate(name="bug", color="#ef4444").color == "#ef4444"
    for bad in ("", "   ", "\t"):
        with pytest.raises(ValidationError):
            LabelCreate(name=bad, color="#000")
        with pytest.raises(ValidationError):
            LabelCreate(name="ok", color=bad)


# --- needs-human handoff (M5 V13, KAN-246) ---------------------------------


def test_needs_human_request_note_optional():
    # The note is optional — an empty request flags the card without a note.
    assert NeedsHumanRequest().attention_note is None
    assert NeedsHumanRequest(attention_note=None).attention_note is None
    assert (
        NeedsHumanRequest(attention_note="need a prod db password").attention_note
        == "need a prod db password"
    )


def test_needs_human_request_rejects_blank_note():
    # A present-but-blank note is a mistake — reject it (mirrors CommentCreate).
    for bad in ("", "   ", "\t\n"):
        with pytest.raises(ValidationError):
            NeedsHumanRequest(attention_note=bad)


def test_card_read_exposes_needs_human_fields():
    # CardRead carries the flag + note (from_attributes reads the real columns).
    fields = CardRead.model_fields
    assert "needs_human" in fields
    assert "attention_note" in fields


# --- scoped tokens (M5 V18, KAN-251) -----------------------------------------


def test_token_create_defaults_to_write_scope():
    # Back-compat: a token without an explicit scope is a writer (R5.3).
    assert TokenCreate(name="ci-bot").scope is TokenScope.write


def test_token_create_accepts_read_scope():
    assert TokenCreate(name="observer", scope="read").scope is TokenScope.read


def test_token_create_rejects_unknown_scope():
    with pytest.raises(ValidationError):
        TokenCreate(name="bad", scope="admin")
