# ADR 0028 — Approval policy for protected card moves

- **Status:** Accepted (2026-09-30)
- **Deciders:** Jian
- **Context source:** [competitive research and vision](../competitive-research-and-vision-2026-09.md).
  Depends on ADR 0027 (labelled agent tokens and scopes). Related to ADR 0007 (last-write-wins) and
  ADR 0019 (MCP surface frozen against growth).

## Context

Review is where agent work stalls in every product surveyed, and every serious tool ends up with a
draft-then-accept step or a review lane (TOW, Linear coding sessions, Asana teammates). The maintainer
wants this flexible: low-risk cards move freely, critical ones move only after human approval, and it
should work through an extra flag and/or scoped permissions.

Today a move is a plain permission check. There is no way to say "this actor may ask, but a human must
confirm", and a refused move returns `403`, which an agent may simply retry.

## Decision (proposed)

1. **Two inputs decide whether a move needs approval.**
   - A **board rule**: a list of transitions, each a target column and an optional source column
     (for example `in_progress` to `done` only, or anything into `done`). Decided 2026-09-30.
   - A **card flag**: `requires_approval` (boolean, default false) for individual critical cards.
   A move needs approval when either applies and the actor lacks the `approve` capability.
2. **Who can approve.** Board owners and members with the editor role, acting through a human session or
   a `personal` token. Never an `agent` token (ADR 0027). Agents cannot approve in v1. Kept deliberately
   simple: no named approver list per board (decided 2026-09-30); revisit if a team needs one.
3. **A protected move creates a pending request, not an error.** New `approval_request` table:
   `card_id`, requester (user, token, label), `from_column`, `to_column`, `status`
   (`pending` | `approved` | `rejected` | `expired` | `stale`), `decided_by`, `decided_at`, `note`.
   The API returns `202` with a structured body `{"status": "pending_approval", "request_id": …}`. The
   CLI exits with a distinct code (proposal: `8`) so an agent stops instead of retrying. MCP returns the
   same body from `move_card`.
4. **Approval applies the move.** The move is recorded in the activity feed with both actors ("moved by
   alex, approved by jian"). Rejection posts a comment and notifies the requester.
5. **A request goes stale** if the card's column changed or the card was edited materially since the
   request; the approver sees why. Requests expire after a configurable window (proposal: 7 days).
6. **The card shows a sub-state**, "waiting for approval", inside its current column. The board keeps
   its three columns.
7. **Notifications.** A new kind `approval_requested`, delivered to approvers rather than the board owner
   alone, which also starts to lift the owner-only limit on notifications.
8. **No MCP tool to decide in v1.** Deciding is UI and CLI only (`pandan approval list|approve|reject`),
   consistent with how workspace membership is kept CLI-only under ADR 0019. `move_card` changes its
   response shape, which is an argument-level change, not a new tool.
9. **What an agent sees while a request is pending.** Repeating the same move returns the same
   `request_id` instead of creating a duplicate. `get_card` includes a `pending_approval` object (target
   column, requester, requested time). The decision reaches the requester as a notification and an
   activity row. `next` and `dispatch` skip any card with a pending request, so a gated move cannot leave
   the card available to a second agent.
10. **Metrics.** Rejected requests never count towards throughput. An approved request counts when the
    move is applied, so cycle time stays truthful. Approval wait may become its own metric later.

## Consequences

- Flexibility without a fourth column: the maintainer can protect one card, one board transition, or
  both, and can scope which actors may move at all through ADR 0027.
- Adds one table and one migration, and lands alone per this repo's rule for migrations.
- Response shape of `move` gains a `202` case. Under ADR 0022 that is additive, but clients that assume
  `200` on success need a note in the changelog.
- The same mechanism is the natural home for proposed agent edits to critical kaya notes later.

## Open questions

- None blocking. Answered 2026-09-30: see decisions 9 and 10.

## Alternatives considered

- **Return `403` for a protected move.** Loses the intent and invites retry loops.
- **A fourth "review" column.** Changes the column `CHECK`, three type definitions and every metric, and
  implies every card has a human reviewer, which is not true.
- **Per-card flag only.** Cannot express "everything into `done` needs approval" without touching each
  card.
