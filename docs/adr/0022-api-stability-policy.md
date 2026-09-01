# ADR 0022 — `/api/v1` stability and versioning policy

- **Status:** Accepted (2026-09-01, on merge) — a policy statement, not a code change. Nothing here
  retroactively flags an existing endpoint; it governs what happens the next time a breaking change is
  on the table.
- **Date:** 2026-09-01
- **Context source:** [issue #324](https://github.com/leejianrong/pandan/issues/324), third of three
  cross-repo issues from kaya's 2026-09-01 roadmap session, explicitly filed as depending on
  [#322](https://github.com/leejianrong/pandan/issues/322) (ADR 0021, org/team tier — Proposed) and
  [#323](https://github.com/leejianrong/pandan/issues/323) (self-hosting audit — PR #326) landing
  first, since both grow the surface a versioning policy would need to cover. This ADR does not
  actually need either merged first: it commits to a *process*, not to naming today's exact endpoint
  list, and it is written so that whatever #322 eventually adds (a plain new `/api/v1/teams` resource)
  needs no exception — a new resource is the least controversial case in the table below. Builds on
  ADR 0005 (API-first: "endpoint naming and payloads should stay explicit and stable-feeling, since
  future agent tools will bind to them" — the promise this ADR makes concrete) and ADR 0013 (which
  declared, in Milestone 3, "\[no] `/api/v2`… we own every client \[SPA, e2e, MCP] and move them
  together" — true then, no longer true now that **kaya is a separate repository with its own release
  cadence**, which is exactly the gap this ADR closes). Formalizes a one-line assertion already sitting
  in the published guide (`docs/guide/about/releases.md`: "a breaking change would go to a new prefix
  rather than altering `v1` underneath existing clients") — this ADR is that line's reasoning, written
  down for the first time rather than asserted without one.

## Context

`/api/v1` has taken real growth without a single removal or rename: `board_seq`/`ref` added to card and
epic reads (M8 V52–53), `fields`/`full` shaping added to the read-heavy endpoints (KAN-501), `GET
/api/v1/me` added from nothing (KAN-530, issue #253), the batch card read added to `GET /api/v1/cards`
(issue #254). Every one of those is a strict superset of what came before — old callers see nothing
different unless they opt in. That track record is genuinely good, but it has never been tested by an
actual removal, and there is nothing written down about what happens the day one is needed — only the
one-liner in `releases.md`.

**One precedent complicates a simple "breaking always needs v2" reading of history**: ADR 0013 made the
*entire* `/api/v1` surface auth-required in place — turning previously-`200` anonymous reads into `401` —
without a new prefix, and said so explicitly: it was safe because "we own every client… and move them
together." That was true in Milestone 3. **It is the condition that has since stopped holding** — kaya
now calls this API from a separate repository, on its own deploy schedule, maintained by the same person
but not built and shipped in the same PR. A self-hosted third-party integration (issue #323's audience)
never held that condition to begin with. This ADR is what replaces "we own every client" now that it
isn't true.

## Decision

### 1. `/api/v1` stays `/api/v1`. A breaking change ships as `/api/v2`, mounted alongside it.

Not a replacement — `v1` keeps running, unmodified, for whoever hasn't moved. This is the one-liner
already in `releases.md`, now load-bearing rather than aspirational, and it evolves ADR 0013's
"no v2" stance for exactly the reason above: that stance was correct when the only clients were code in
this repository, moved in the same PR as the API change. It stops being correct the moment a consumer
outside this repository exists — which, as of kaya, it does.

### 2. What counts as breaking, stated as a table rather than a feeling

| Not breaking — ships in `v1`, no notice needed | Breaking — needs the process in §3, or `v2` |
|---|---|
| A new endpoint | Removing an endpoint |
| A new optional request field | Removing or renaming a response field |
| A new response field | Renaming a request field, or making an optional one required |
| A new enum value that doesn't change existing values' meaning | Changing a field's type or the meaning of an existing value |
| Widening a limit (e.g. raising `MAX_BATCH_ITEMS`) | Tightening validation so previously-valid input is rejected |
| Relaxing validation so previously-invalid input is accepted | Changing what a status code means for an existing situation |
| A new query parameter | Changing a default that existing callers rely on |

The left column is every change `/api/v1` has actually made since M3 — the table describes existing
practice, it doesn't invent a stricter one.

### 3. Two deprecation tiers, because "give notice" means something different for each

`/api/v1` has exactly two kinds of consumer, and they get different treatment because the maintainer's
actual knowledge of each is different:

- **Tracked consumers — kaya, the CLI, the MCP server, the SPA.** For these, *confirm the migration
  actually happened* rather than wait out a calendar. Introduce the replacement additively, mark the old
  shape deprecated (below), and don't remove it in the same PR that adds the replacement — but the gate
  on removal is "kaya's client and this repo's own CLI/MCP/SPA have been checked to call the new shape,"
  not a fixed number of days. This is stronger than a calendar for a same-maintainer sibling repo, and
  it's the same "verify, don't assume" discipline this repo already applies everywhere else.
- **Untrackable consumers — a self-hosted instance's own scripts or integrations.** The maintainer
  cannot know these exist, so there is nothing to confirm. For these, a **fixed floor of 90 days** from
  when a shape is first marked deprecated to when it may be removed, full stop. This is the only lever
  available for a consumer you cannot see, and it is what makes §4 below a real guarantee rather than a
  hope.

A deprecated shape is marked with the `Deprecation` and `Sunset` response headers (RFC 8594) on any
response that includes it — new, additive, and ignorable by a caller that doesn't look for them. This is
the same notice-on-the-wire instinct as ADR 0018's stderr deprecation line for `KANBAN_*` env vars, moved
from a client-side CLI print to a server-side header so a programmatic consumer (kaya, a self-hosted
script) can detect it without reading a changelog.

### 4. The policy is per-release, not per-deployment — so it applies identically to a self-hoster

There is one `/api/v1` codebase. A hosted instance runs whatever's on `main`; a self-hosted instance runs
whatever commit its operator chose to deploy and hasn't yet upgraded past. **The guarantee this ADR makes
is about what a given release promises, not about who's running it** — a self-hoster who never upgrades
never experiences a removal, because removal is a property of a future commit they haven't taken. This
directly answers issue #324's third question: the same policy, the same two tiers, the same headers,
apply whether the caller is kaya calling the hosted board or a self-hoster's cron job calling their own
instance. The 90-day floor for untrackable consumers exists *specifically* to protect that self-hoster's
integration, since the maintainer has no other way to know it's there.

### 5. Scope: the REST surface only

This ADR governs `/api/v1` request/response shapes. It does not touch two things that already have their
own rule: the MCP tool surface is frozen at 49 tools by ADR 0019 (arguments may grow; tool count may not,
without an ADR amendment), and the CLI's own version number is a separate, already-enforced discipline
(a behavior change bumps `pandan --version`, guarded by the pre-push hook and CI — `releases.md`
§Versioning). Both are consistent with this ADR's spirit; neither needed to change to make this ADR true.

## Consequences

- **A `v2` fork, if it ever happens, is a large and rare event — not a per-endpoint escape hatch.** The
  whole surface moves together, the same way ADR 0013's "move together" worked when everything was one
  repo, except "together" now means every known consumer confirmed migrated rather than assumed.
- **Two small, additive server mechanisms are new**: the `Deprecation`/`Sunset` response headers. Nothing
  existing changes shape; a caller that never checks for them sees nothing different.
- **`docs/guide/reference/api.md` and `about/releases.md` should cross-reference this ADR** once accepted,
  since the latter already states the one-line conclusion this ADR justifies.
- **Nothing is currently deprecated.** This ADR creates the process; it does not start a clock on
  anything that exists today.

## Alternatives rejected

- **Header or media-type versioning** (`Accept: application/vnd.pandan.v2+json`) instead of a URL prefix.
  Rejected: more machinery than today's consumer count (one sibling repo, plus this repo's own CLI/MCP/
  SPA) justifies, and the URL-prefix approach is already precedented in `releases.md` and simpler to
  route, test, and explain.
- **One fixed calendar SLA for every breaking change, regardless of consumer.** Rejected as the *only*
  rule: for kaya, confirming actual migration is both stronger and often faster than waiting out a
  calendar, since the maintainer can just go check. The fixed 90-day floor is reserved for the case that
  actually needs a calendar — a consumer nobody can ping.
- **Never breaking, ever — additive forever**, the `KANBAN_*`-fallback pattern (ADR 0018) taken as an
  absolute rule. Rejected: some changes genuinely cannot be done additively (a field with the wrong
  type, say), and pretending otherwise would eventually leave `v1` a pile of deprecated-but-immortal
  fields with no release valve. `v2` is that valve, used rarely.

## Open

- **No automated schema-diff gate yet.** Nothing in CI currently compares `openapi.json` across a PR to
  catch an accidental breaking change before merge — today this policy is enforced by review discipline,
  not machinery. Worth adding once a real deprecation happens once and the shape of "what actually needs
  catching" is concrete, rather than guessing at the check now.
- **Whether kaya adopts a mirror policy for its own API is kaya's decision**, not this repo's — noted
  only because the two guides will read oddly if they diverge without either acknowledging the other.
