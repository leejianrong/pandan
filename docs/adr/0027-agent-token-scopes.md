# ADR 0027 — Labelled agent tokens and scoped permissions

- **Status:** Accepted (2026-09-30)
- **Deciders:** Jian
- **Context source:** [competitive research and vision](../competitive-research-and-vision-2026-09.md).
  Amends ADR 0014 (agent PATs) and builds on ADR 0024 (OAuth device flow and scoped tokens). Companion
  to ADR 0028 (approval policy), which depends on this one.

## Context

Every principal in pandan is a real user (ADR 0014, ADR 0015). That was the right call for the first
agent story, but it means an agent acting through a PAT is indistinguishable from its owner. The
activity feed records `actor_label = principal.email`, comments store only `author_id`, and the only
agent marker is the free-text `assignee` convention `agent:<slug>`, which the limits page admits makes
`claude`, `Claude` and `agent:claude` three different assignees. Nothing records which token acted.

Tokens already carry a `read`/`write` scope and an optional board allow-list (ADR 0024). That is too
coarse for the next step: the maintainer wants some humans and agents allowed to move cards and others
not, and wants critical cards gated (ADR 0028). Competitors that do this well (Linear, ClickUp) give the
agent its own labelled identity and keep the human accountable. Trello, which has agents act as the
user, loses attribution.

## Decision (proposed)

1. **A token has a kind and a label.** Add `kind` (`personal` | `agent`) and `label` (a short slug such
   as `alex`) to `personal_access_token`. Existing tokens migrate to `kind = personal`. An `agent` token
   still resolves to its owning user, so ADR 0014's "every principal is a real user" holds. What changes
   is that the credential and its label become visible.
2. **Attribution is recorded.** Activity rows gain `actor_token_id`, `actor_kind` and a structured label
   (rendered as "alex, for you@example.com"). Comments gain `author_token_id`. The SPA and CLI show an
   agent marker. `actor_label` stays denormalised so a revoked token still reads correctly in history.
3. **Scopes become a small set, not a free-form list.** Presets: `read`, `write`, `write-no-delete`.
   Fine-grained scopes on top: `cards:move` (optionally limited to target columns, for example
   `move_into=todo,in_progress`), `cards:delete`, `approve`.
4. **`approve` is never grantable to an `agent` token.** Approval must come from a human session or a
   `personal` token. This is a hard rule, not a default, because an agent that can approve its own
   request defeats ADR 0028.
5. **`agent` tokens default to a 90-day lifetime** (decided 2026-09-30), overridable at creation.
6. **The board allow-list stays.** A token's effective rights are the intersection of the owner's board
   role, the token's scopes and its board allow-list.
7. **A separate `delegate` field on cards is a follow-up**, not part of this ADR. It replaces the
   `agent:` assignee string and is shaped once tokens are labelled.
8. **An OAuth-connected app always counts as `agent`.** The app's registered name is the label, the
   `approve` scope can never be granted to it, and the consent screen says so. A person driving a tool
   through Claude.ai or Cursor is still an agent acting through a tool, and can approve in the UI.
9. **Rate limits are keyed by token.** A per-token write bucket (starting proposal: 120 a minute) sits
   under the existing per-IP ceiling, so one runaway agent cannot starve others sharing an IP. Responses
   carry standard rate-limit headers and `Retry-After` on 429. Counters stay in memory on the single
   machine; running more than one machine needs a shared store, the same trigger as the live
   collaboration pub/sub.

## Consequences

- Attribution answers "which human, which agent, which token" with one migration and no new principal.
- ADR 0014 needs a short amendment noting the new columns. ADR 0015's "no separate agent identity"
  stays accurate.
- MCP and CLI tool schemas do not change shape, but responses to a forbidden action must be structured
  so an agent can tell "not allowed" from "needs approval" (see ADR 0028).
- Kaya needs the mirror of this (its own token kinds and presets). That is tracked in kaya ADR 0015.

## Open questions

- None blocking. Answered 2026-09-30: see decisions 8 and 9. The 120 a minute figure is a starting
  proposal and should be tuned against real traffic.

## Alternatives considered

- **A new principal type for agents.** Reverses ADRs 0014 and 0015 and touches every auth path. Deferred
  until agents need standing of their own (owning boards, their own permissions).
- **Keep the `agent:<slug>` assignee convention.** No validation, no attribution, no revocation.
