"""Auto-sync: map GitHub webhook events onto board card updates (KAN-43).

The webhook receiver (:mod:`app.routers.webhooks`, KAN-42) verifies GitHub's HMAC
signature and dispatches per event; this module turns those events into board
side effects so the board reflects real git/CI state automatically:

- ``pull_request`` ``opened`` / ``reopened`` → attach the PR URL as a card
  work-link (``CardLink``), idempotent by URL.
- ``check_suite`` / ``status`` → post a card comment (``CardComment``) summarising
  the CI result (state / status / conclusion).
- ``pull_request`` ``closed`` with ``merged == true`` → move the card to ``done``
  — but **only** if the board additionally opted into ``autosync_advance_to_done``.

**Opt-out is the gate (per-board, default OFF).** Every action first resolves the
target card's :class:`~app.models.Board` and does nothing unless
``board.autosync_enabled`` is true — a board owner who prefers to move cards by
hand simply leaves the toggle off. Moving to ``done`` on merge is doubly gated by
``autosync_advance_to_done`` so 'done' stays a human-in-the-loop decision.

These writes act as **the system**, not a logged-in user: the webhook is
authenticated by the HMAC signature, so — unlike the rest of ``/api/v1`` — this
path deliberately does NOT go through ``get_principal`` / ``authorize_board``
(ADR 0013). The per-board opt-in flag is the authorization. We open our own sync
session (:data:`app.db.SessionLocal`) rather than depending on ``get_db`` for the
same reason. To keep the DB-free unit tests DB-free, each entry point parses the
card ticket **before** touching the database and no-ops (no session opened) when a
payload carries no ``KAN-<n>``.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .board_seq import ParsedRef, find_ref
from .db import SessionLocal
from .models import Board, Card, CardComment, CardLink
from .notifications import record_notification
from .ordering import next_position, renumber_column

logger = logging.getLogger("app.autosync")

# check_suite ``conclusion`` / status ``state`` values that mean CI **failed** — the
# ones that warrant a notification (V37, KAN-301). A passing / neutral / in-progress
# result posts the usual CI comment but raises no notification.
_CI_FAILURE_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})
_CI_FAILURE_STATES = frozenset({"failure", "error"})

# A reference is found in free text (a branch name, a PR title) by
# :func:`app.board_seq.find_ref`, which knows both forms — the canonical ``KAN-123``
# and the board-local ``ENG-42`` (V53, KAN-974). Matched case-insensitively, since
# branch names are usually lowercased.

DONE_COLUMN = "done"
PR_LINK_LABEL = "PR"


def parse_ticket(*candidates: str | None) -> ParsedRef | None:
    """The first reference found across ``candidates`` (e.g. a branch name then a PR
    title), in either form; ``None`` if none match or the match is not a *card*.

    An epic reference is discarded here rather than downstream: auto-sync attaches PR
    links and moves columns, and an epic has neither. Before V53 this could not arise
    — the pattern only matched ``KAN-`` — so it is a new case, not a latent one.
    """
    ref = find_ref(*candidates)
    if ref is None or ref.entity != "card":
        return None
    return ref


def _describe(ref: ParsedRef) -> str:
    """A reference as it appeared, for log lines."""
    if ref.canonical:
        return f"KAN-{ref.number}"
    return f"{ref.board_key}-{ref.number}"


def _resolve_synced_board(db: Session, ref: ParsedRef) -> tuple[Card, Board] | None:
    """Resolve the ``(card, board)`` for ``ref``, or ``None`` when there is no such
    card, its board is missing, or the board has **not** opted into auto-sync (the
    per-board opt-out gate).

    **The two forms resolve in opposite directions**, and that asymmetry is the whole
    of SHAPING D3 in one function:

    * A **canonical** ``KAN-123`` is globally unique, so the card is found first and
      the board follows from it. Unchanged from before V53.
    * A **board-local** ``ENG-42`` means nothing without a board, and a webhook has no
      board context of its own. So the *board* is found first, from the set the
      webhook is willing to act on at all — boards that opted into auto-sync — and the
      card follows from ``(board_id, board_seq)``. That opt-in flag is not a
      convenience filter here; it is what supplies the missing board context, which is
      why board-local refs are safe in a global endpoint.

    If two opted-in boards share the key, this **skips and logs** rather than guessing.
    Never a silent pick (D3): a webhook cannot ask, so the only honest answers are one
    board or none.
    """
    if ref.canonical:
        # A soft-deleted card (KAN-19) is invisible, so the webhook never resurrects it.
        card = db.scalars(
            select(Card).where(
                Card.ticket_number == f"KAN-{ref.number}", Card.deleted_at.is_(None)
            )
        ).first()
        if card is None:
            logger.info("autosync no card for ref=%s", _describe(ref))
            return None
        board = db.get(Board, card.board_id)
        if board is None or not board.autosync_enabled:
            logger.info(
                "autosync skipped ref=%s board=%s (autosync disabled)",
                _describe(ref),
                card.board_id,
            )
            return None
        return card, board

    boards = list(
        db.scalars(
            select(Board).where(
                Board.key == ref.board_key, Board.autosync_enabled.is_(True)
            )
        ).all()
    )
    if not boards:
        logger.info(
            "autosync no autosync-enabled board with key=%s (ref=%s)",
            ref.board_key,
            _describe(ref),
        )
        return None
    if len(boards) > 1:
        logger.warning(
            "autosync ambiguous ref=%s: %d autosync-enabled boards share key=%s "
            "(%s) — skipping rather than guessing",
            _describe(ref),
            len(boards),
            ref.board_key,
            ",".join(str(b.id) for b in boards),
        )
        return None
    board = boards[0]
    card = db.scalars(
        select(Card).where(
            Card.board_id == board.id,
            Card.board_seq == ref.number,
            Card.deleted_at.is_(None),
        )
    ).first()
    if card is None:
        logger.info(
            "autosync no card for ref=%s on board=%s", _describe(ref), board.id
        )
        return None
    return card, board


def _attach_pr_link(db: Session, card: Card, url: str) -> None:
    """Attach ``url`` as a ``PR`` work-link on ``card``, idempotently — a link with
    the same URL already on the card is left untouched (mirrors the field semantics
    of ``routers/cards.py``'s ``add_link``)."""
    existing = db.scalars(
        select(CardLink).where(CardLink.card_id == card.id, CardLink.url == url)
    ).first()
    if existing is not None:
        logger.info("autosync PR link already present card=%s url=%s", card.id, url)
        return
    db.add(CardLink(card_id=card.id, label=PR_LINK_LABEL, url=url))
    logger.info("autosync attached PR link card=%s url=%s", card.id, url)


def _post_comment(db: Session, card: Card, body: str) -> None:
    """Post a system comment on ``card``. ``author_id`` is left NULL — this is the
    system acting, not a user (``CardComment.author_id`` is nullable)."""
    db.add(CardComment(card_id=card.id, author_id=None, body=body))
    logger.info("autosync comment card=%s body=%r", card.id, body)


def _advance_to_done(db: Session, card: Card) -> None:
    """Move ``card`` to the ``done`` column (append to its end) and re-sequence the
    source column, mirroring ``routers/cards.py``'s move semantics."""
    if card.column == DONE_COLUMN:
        return
    source_column = card.column
    card.column = DONE_COLUMN
    # next_position counts the target column's current rows; the pending column
    # change isn't flushed yet (autoflush is off), so this is the correct end index.
    card.position = next_position(db, card.board_id, DONE_COLUMN)
    db.flush()
    renumber_column(db, card.board_id, source_column)
    logger.info("autosync advanced card=%s to done", card.id)


# --- event entry points (called by app.routers.webhooks handlers) ------------


def on_pull_request(payload: dict) -> None:
    """Map a ``pull_request`` event. ``opened`` / ``reopened`` attach the PR URL as
    a work-link; ``closed`` + ``merged`` advances the card to ``done`` **iff** the
    board also set ``autosync_advance_to_done``. Any other action is a no-op."""
    pr = payload.get("pull_request") or {}
    head_ref = (pr.get("head") or {}).get("ref")
    ticket = parse_ticket(head_ref, pr.get("title"))
    if ticket is None:
        return
    action = payload.get("action")
    with SessionLocal() as db:
        resolved = _resolve_synced_board(db, ticket)
        if resolved is None:
            return
        card, board = resolved
        if action in ("opened", "reopened"):
            url = pr.get("html_url") or pr.get("url")
            if url:
                _attach_pr_link(db, card, url)
        elif action == "closed" and pr.get("merged"):
            if board.autosync_advance_to_done:
                _advance_to_done(db, card)
            else:
                logger.info(
                    "autosync merge not advanced card=%s (advance_to_done off)",
                    card.id,
                )
        db.commit()


def on_check_suite(payload: dict) -> None:
    """Map a ``check_suite`` event to a CI comment. The ticket is parsed from the
    suite's head branch or any associated PR's head ref."""
    suite = payload.get("check_suite") or {}
    candidates: list[str | None] = [suite.get("head_branch")]
    for pr in suite.get("pull_requests") or []:
        candidates.append((pr.get("head") or {}).get("ref"))
    ticket = parse_ticket(*candidates)
    if ticket is None:
        return
    body = (
        f"CI check_suite: status={suite.get('status')} "
        f"conclusion={suite.get('conclusion')}"
    )
    with SessionLocal() as db:
        resolved = _resolve_synced_board(db, ticket)
        if resolved is None:
            return
        card, board = resolved
        _post_comment(db, card, body)
        # Notify the board owner when the suite's CI failed (V37, KAN-301) — a linked
        # PR's checks going red is something a human shouldn't miss.
        conclusion = (suite.get("conclusion") or "").lower()
        if conclusion in _CI_FAILURE_CONCLUSIONS:
            record_notification(
                db,
                board_id=board.id,
                card_id=card.id,
                kind="ci_failed",
                body=f"CI failed on {card.ticket_number} (check_suite: {conclusion})",
            )
        db.commit()


def on_status(payload: dict) -> None:
    """Map a ``status`` event to a CI comment. The ticket is parsed from the
    branch names carried in the payload."""
    branches = payload.get("branches") or []
    candidates = [b.get("name") for b in branches]
    ticket = parse_ticket(*candidates)
    if ticket is None:
        return
    body = f"CI status: {payload.get('context')} → {payload.get('state')}"
    with SessionLocal() as db:
        resolved = _resolve_synced_board(db, ticket)
        if resolved is None:
            return
        card, board = resolved
        _post_comment(db, card, body)
        # Notify the board owner when the status is a CI failure (V37, KAN-301).
        state = (payload.get("state") or "").lower()
        if state in _CI_FAILURE_STATES:
            record_notification(
                db,
                board_id=board.id,
                card_id=card.id,
                kind="ci_failed",
                body=(
                    f"CI failed on {card.ticket_number} "
                    f"({payload.get('context')} → {state})"
                ),
            )
        db.commit()
