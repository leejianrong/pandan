# ADR 0021 — Team: the tenant tier above a user, and where "organization" would go later

- **Status:** Proposed — an ADR-level design, no code yet, exactly as the issue asked for. Pending
  maintainer sign-off before any slice is shaped or scheduled.
- **Date:** 2026-09-01
- **Context source:** cross-repo planning from kaya's 2026-09-01 roadmap session, filed as three
  issues in priority order because the first blocks the other two:
  [#322](https://github.com/leejianrong/pandan/issues/322) (this ADR),
  [#323](https://github.com/leejianrong/pandan/issues/323) (self-hosting audit),
  [#324](https://github.com/leejianrong/pandan/issues/324) (API stability policy — explicitly named as
  depending on this one and #323 landing first, since both grow the surface a policy would need to
  cover). kaya is blocked because its own KAN-1048 spike (kaya board 18) can't conclude without an
  answer here — kaya has no identity of its own and forwards to `GET /api/v1/me` for everything
  (kaya ADR 0002), so whatever shape this ADR settles on is what kaya consumes. Builds on ADR 0012
  (multi-board with ownership), ADR 0013 (the `Access` levels + `BoardMember` role model this reuses
  rather than replaces), ADR 0014/0015 (a PAT always resolves to one real `User`), and ADR 0020 (board
  keys, whose Alternatives-rejected section already named "a workspace/organisation tier above the
  user" as a deliberately deferred, deliberately compatible later step — this is that step).
  **Scope, pinned by the issue's own non-goals**: a company self-hosting *one* pandan+kaya instance
  with several internal teams — not a hosted multi-tenant SaaS serving many separate companies.
  Billing, seat limits, and SSO/SAML are explicitly out of scope for this pass.

## Context

Today there is nothing above a `User`. A board has exactly one `owner_id` (ADR 0012) and is shared to
other individuals one at a time via `BoardMember` rows carrying a `viewer`/`editor`/`owner` role (ADR
0013, KAN-12/13). That is fine for "a person shares a board with a few collaborators" but has no
concept of "a company has three teams, each with its own set of boards, and someone should be able to
add a new hire to Platform and have them see every Platform board at once" — today that's N individual
shares, with no single place to grant or revoke all of them together, and no default: a person removed
from the team keeps whatever board shares they were given individually, and a person added to the team
gets nothing until someone remembers to share each board with them by hand.

The issue frames the open question as a fork: is there one tier above `User` (call it "team"), or two
(an "organization" owning "teams" which group members)? Answering that fork is the actual ADR-level
work, because it decides how much schema this pass commits to.

## Decision

**Add one tier — `team` — and treat it as the tenant boundary. Do not add `organization` yet.**

The scope note is the reason, not a simplification for its own sake: the target deployment shape is one
company per self-hosted instance. An `organization` row in that shape has exactly one live row, forever
— the same over-modeling ADR 0006 deliberately avoided for "board" back when there was only one board
per instance, and evolved (ADR 0012) only once multi-board was a real need. `team` is the boundary the
issue's actual scenario needs today; `organization` is a real future need (a hosted product serving
several separate companies from shared infrastructure) but not this one, and forcing it in now buys
nothing a self-hoster will ever exercise.

### Shape

- **`team`** — `id`, `name`, `created_at`, `updated_at`. Deliberately **no `owner_id`**: unlike a
  board, a team isn't administered by one person by default — it's administered by whichever of its
  members hold the `owner` role (below). No `key` either — a team has no ticket-ref namespace of its
  own; that stays exactly where ADR 0020 put it (see Consequences).
- **`team_member`** — `team_id`, `user_id`, `role`, `UNIQUE(team_id, user_id)`, both FKs
  `ON DELETE CASCADE` — the same shape as `board_member` (KAN-12), on purpose.
- **Team roles reuse `VALID_ROLES`** (`viewer`/`editor`/`owner`) rather than inventing a second
  vocabulary. One `_ROLE_ACCESS` mapping already turns a role into an `Access` level
  (`app/authz.py`); a team role maps through the *same* table when it becomes a board's **default**
  access (below). One vocabulary, two places it can be granted — not two vocabularies.
- **`board.team_id`** — new nullable FK → `team`, `ON DELETE SET NULL`. This mirrors `board.owner_id`'s
  own pattern exactly (ADR 0012): deleting a team unclaims its boards rather than destroying them.
  **`board.owner_id` is untouched and still required** — a board keeps exactly one human owner exactly
  as today; `team_id` is an additional *grouping/sharing* pointer layered on top, not a replacement for
  ownership. A board belongs to **at most one** team in this pass (see Alternatives rejected).

### Interaction with the existing board-role model (the issue's second question)

Team membership grants a **default** board access; an explicit `BoardMember` row is still checked first
and still wins — that *is* the per-board override the issue asks for, and it falls out for free because
`_effective_access` already checks the most-specific thing first:

| Check, in order | Source | Result |
|---|---|---|
| 1. `board.owner_id == principal.id` | unchanged | `MANAGE` |
| 2. an explicit `BoardMember` row for this board | unchanged | that row's mapped `Access` — **the override** |
| 3. `board.team_id` is set and the principal is a `team_member` of it | **new** | that membership's role, mapped through the same `_ROLE_ACCESS` — **the default** |
| 4. none of the above | unchanged | `None` → 403 |

Concretely: adding someone to the Platform team as an `editor` gives them `WRITE` on every Platform
board they don't already have an explicit, different role on. Removing them from the team removes that
default; any explicit per-board shares they were separately given are untouched, because those are a
different row entirely. `visible_board_ids` gains the matching `OR` clause so team-visible boards
appear in list endpoints with no per-board lookup needed.

### PAT scope (the issue's third question) — no change

**A PAT still resolves to exactly one `User`, unchanged (ADR 0014/0015).** A user's reachable boards
already flow entirely through `_effective_access`/`visible_board_ids`; adding a rung to those functions
means a PAT automatically inherits whatever its owning user's team memberships grant, with **zero**
change to `app/tokens.py`, `_resolve_pat`, or the `read`/`write` PAT scope axis (V18, KAN-251) — that
axis is orthogonal (it caps *what kind of call* a token may make, not *which boards*) and composes with
this unchanged. This is also the answer kaya needs: kaya delegates identity to `GET /api/v1/me`
(kaya ADR 0002) and that route **stays exactly `{id, email}`** — nothing about team membership belongs
in an identity-resolution endpoint that was deliberately kept minimal (KAN-530, "the minimum, on
purpose"). A `GET /api/v1/teams` (new, below) is where team-shaped questions get answered, not `/me`.

### New surface

- **`/api/v1/teams`**, mirroring `/api/v1/boards`'s existing shape: `GET` (list, scoped to teams the
  principal is a member of — a `visible_team_ids` subquery alongside `visible_board_ids`), `GET /{id}`,
  `POST` (create; the creator is auto-added as an `owner`-role `team_member`, the same bootstrap
  `authorize_board` already gives a board's creator), `PATCH` (rename; `owner`-role members only),
  `DELETE` (`owner`-role members only; boards with that `team_id` are unclaimed via `SET NULL`, not
  deleted). Team-member management (`POST`/`DELETE`/`PATCH` on `team_member`) mirrors the existing
  `board_member` endpoints, gated on the acting principal holding `owner` on the team.
- **`POST /api/v1/boards` gains an optional `team_id`.** Validated that the creating principal is a
  member of that team (any role) — `403` otherwise, matching the existing "you don't get to point a
  create at something you can't touch" pattern used for `epic_id` (`_validate_epic`, `routers/cards.py`).
  Omitted → `team_id = NULL`, i.e. today's behavior, byte-for-byte.

## Consequences

- **Purely additive migration**: two new tables, one nullable FK column on `board`. Every existing
  board gets `team_id = NULL` with no backfill logic needed — `NULL` *is* "personal board," which is
  exactly every board's current, unchanged meaning.
- **`app/authz.py` grows one rung, not a rewrite.** `_effective_access` gains step 3 above;
  `visible_board_ids` gains one `OR`. Every existing 403/200 test keeps passing unmodified because the
  new clause is a no-op for any board with `team_id IS NULL` — which is every board that exists today.
- **Board keys (ADR 0020) are untouched — deliberately not addressed here.** Keys stay unique **per
  owner** (a `User`), not per team. Two members of the same team can each own a board keyed `ENG`;
  a third team-mate who can see both still gets `ambiguous_ref`, exactly as they would today for any
  two boards they can see with the same key. This ADR neither creates nor fixes that — it's ADR 0020's
  D2/D3 territory, and nothing in kaya's stated blocker needs it solved now. Listed under Open below.
- **Notifications (V37) keep their MVP rule unchanged**: the recipient of a board event is always
  `board.owner_id`, never a team. A team member other than the owner gets no notification for a team
  board. Naming a fan-out policy for team-owned boards is a separable design question this ADR
  deliberately does not answer — the issue didn't ask for it, and it deserves its own shape.
- **MCP/CLI surface is out of scope for this ADR.** ADR 0019's freeze governs the 49-tool *count*; a
  `list_teams`/`create_team` pair (and CLI equivalents) would need the same sizing discussion the board
  tools already went through, once this ADR is accepted and a slice actually adds them.
- **No milestone/slice numbers are claimed here.** M8 is still mid-flight (V54, V56–V60, V63–V64
  remain per `docs/milestone-8/SLICES.md`); whenever this is picked up for real it gets its own
  shaping pass and its own `SLICES.md`, not V-numbers squatted on by an ADR.
- **Unblocks #323 lightly, in one place**: a self-hosting first-admin bootstrap (#323's "migration/
  bootstrap steps" ask) may want to offer "create a default team" alongside "claim the default board" —
  worth a one-line cross-reference when #323 is written, not a decision this ADR makes.

## Alternatives rejected

- **`organization` above `team`, built now.** Rejected on scope: the target deployment shape (one
  company, one self-hosted instance) never has more than one, so the row would exist purely as
  ceremony. The seam is named instead of built: a future `organization` table would sit above `team`
  (`team.org_id`, nullable → NOT NULL, exactly the `board.owner_id` migration shape from ADR 0012)
  the day a genuinely multi-company hosted use case exists. Nothing in this design forecloses it.
- **Polymorphic board ownership** (`board.owner_id` pointing at a `User` *or* a `Team`). Rejected: it
  ripples into notifications (whose whole MVP model is "the recipient is always a real `User`," V37),
  into `board_keys`' per-owner uniqueness, and into the `authz` owner check — for no benefit the
  additive `team_id` grouping FK doesn't already deliver, at a fraction of the blast radius.
- **A separate team-role vocabulary.** Rejected: reusing `VALID_ROLES` keeps exactly one authorization
  vocabulary and one mapping table (`_ROLE_ACCESS`), regardless of whether the role came from a
  `board_member` row or a `team_member` row. Two vocabularies would need two things kept in sync for
  no expressive gain.
- **Many-to-many board↔team.** Rejected for this pass: the issue's own scenario reads singular ("each
  [team] with its own set of boards"), and a single nullable `team_id` upgrades to a join table later
  without touching anything this ADR's Decision section commits to (the `BoardMember`-wins-over-team-
  default precedence, the `_ROLE_ACCESS` mapping) — it would only add another `OR` clause to
  `visible_board_ids`.
- **Growing `GET /api/v1/me` to carry team memberships.** Rejected for this pass: nothing downstream
  (kaya's stated blocker) needs it, and V50/KAN-530 deliberately kept that route to the minimum. Add it
  as its own slice — or better, a dedicated `GET /api/v1/teams` call, which already exists in this
  design — if and when a real consumer needs team data alongside identity.

## Open

- **Team-scoped key uniqueness.** Does a team eventually want its own `ENG`-style namespace the way a
  user does (ADR 0020)? Deferred until a real `ambiguous_ref` collision inside a team is reported —
  today's per-owner scoping is a strict superset of correctness, just not maximally convenient.
- **Notification fan-out to team members.** Left to whoever eventually asks for "notify the whole team,
  not just the board owner" — a genuinely separate design question (who, on what events, with what
  opt-out) rather than a corollary of this ADR.
- **A second tenant tier for a hosted multi-company future.** Explicitly out of scope per the issue's
  own scope note. If it ever becomes real, it is the `organization`-above-`team` seam named above, not
  a redesign of `team` itself.
