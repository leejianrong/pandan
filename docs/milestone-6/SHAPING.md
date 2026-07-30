---
shaping: true
---

# Milestone 6 — Shaping ("Harden & Sharpen")

M6 has one blunt reason to exist and one ambition. The **reason**: the app is live to the public on
Fly.io with **zero abuse controls** — no rate limiting, no security headers, no payload caps, on a
256 MB shared-CPU box that scales to zero. That is the responsible thing to fix first. The
**ambition**: pull selectively toward Linear/Jira on the axes that fit a *simple, API-first,
agent-native, no-real-time* board — without importing their complexity.

So M6 is two movements: **harden** (defend the deploy) then **sharpen** (a curated set of
tracker-parity features). A third strand — the **simple-markdown** sister app — is *recorded here as
intent* but built as a separate project (see [kaya-vision](../kaya-vision.md)).

This records a single **shape-of-record** — the maintainer settled scope directly (hardening-first;
four named parity features; sister-app recorded-not-built) — with the fit check confirming coverage.

## Why these requirements

### Hardening — the honest split
"Defend against DDoS" is mostly **not** an app-code problem. Volumetric floods are absorbed at the
**network edge**; app code stops **abuse** (brute force, scraping, expensive-query hammering, payload
bombs) and **sheds load** gracefully. M6 does both layers, and is explicit about which is which.

What the code has today (audited during M6 shaping):

| Concern | State before M6 |
|---|---|
| Rate limiting | ❌ none (no `slowapi`/`limits`, no middleware) |
| Security headers (HSTS/CSP/nosniff/frame) | ❌ none — no middleware layer in `main.py` |
| Request body-size cap | ❌ none |
| String/array payload caps | ❌ text fields are `min_length=1` only (no `max_length`); `batch`/`template` arrays are unbounded |
| List pagination cap | ✅ `limit` `le=200` on the card list |
| Edge / WAF / origin hiding | ❌ Fly origin directly reachable |
| Load-shedding | ❌ no Fly concurrency `hard_limit`; a burst OOMs the 256 MB box |
| Client-IP trust | ⚠️ uvicorn runs `--forwarded-allow-ips=*` → raw `X-Forwarded-For` is spoofable; must use `Fly-Client-IP` for IP keys |
| DB statement timeout | ❌ none — a slow cold-Neon query can pile up connections |

### Parity — the curated Linear/Jira delta
Building on M5's competitive-delta table. We **already** have labels, priority, due dates,
dependencies, comments, PR auto-sync, activity, roles/membership, saved views, full-text search,
metrics, templates, batch, scoped tokens. Adopted in M6 (fit "simple"); declined stays declined.

| Capability | Who leans on it | Have it? | In M6? |
|---|---|---|---|
| **Projects** (target date, lead, progress %) | Linear Projects, Jira versions | partial (epics are name+desc) | ✅ (R2) |
| **Cycles / iterations** (sprints + burndown) | Linear Cycles, Jira sprints | ❌ | ✅ (R3) |
| **Command palette (⌘K) + keyboard UX** | Linear (signature) | ❌ | ✅ tail (R4) |
| **Notifications / inbox + outbound webhooks** | Linear Inbox, both (webhooks) | ❌ (inbound only) | ✅ tail (R5) |
| Sub-issue *hierarchy*, workflow engine, custom fields, time tracking, permission schemes | Jira | ❌ | ❌ (off-ethos) |
| File attachments / rich docs | Jira↔Confluence, Linear Docs | ❌ | ❌ → **simple-markdown** (separate app) |
| Real-time collaboration | all | ❌ by design | ❌ (ADR 0007 reaffirmed) |

**Best ideas adopted:** Linear → projects with health, cycles, the ⌘K palette, an inbox. Both →
outbound webhooks as the universal integration primitive. **Deliberately not adopted:** Jira's
workflow/permission engine, custom-field explosion, time tracking; sub-issue *trees* (a lightweight
checklist would be the in-ethos version if ever wanted). File/rich-content is answered by a *sibling*
app, not by growing kanban.

---

## Requirements (R)

| ID | Requirement | Status |
|----|-------------|--------|
| **R0** | **A public, agent-driven board that stays available and abuse-resistant, and pulls toward Linear/Jira only where it stays simple** | Core goal |
| **R1** | **Abuse hardening & resilience** | |
| R1.1 | **Edge protection** in front of Fly (hide origin, cache SPA, bot/WAF rules) — the layer that addresses volumetric DDoS | Must-have |
| R1.2 | **Load-shedding**: a Fly concurrency cap so the box returns 503, never OOMs | Must-have |
| R1.3 | **App rate limiting** on auth, writes/dispatch, token-create, search/metrics, webhook — `429` + `Retry-After`, keyed on the trusted client IP + principal | Must-have |
| R1.4 | **Payload caps**: body size, string `max_length`, `batch`/`template` array length | Must-have |
| R1.5 | **Security headers**: HSTS, CSP (single-origin), nosniff, frame-ancestors, Referrer-Policy | Must-have |
| R1.6 | **DB resilience**: statement timeout + pool/connect timeouts against cold-start pile-ups | Must-have |
| **R2** | **Projects (epics upgraded)** | |
| R2.1 | An epic carries a **target date** and a **lead** | Must-have |
| R2.2 | A **derived progress rollup** (% done) + health (on-track / at-risk / overdue), no new write path | Must-have |
| **R3** | **Cycles / iterations** | |
| R3.1 | A **cycle** (name, start, end) groups cards; a card links to zero-or-one cycle | Must-have |
| R3.2 | **Cycle-scoped metrics** — burndown, committed-vs-completed, velocity — derived from the activity feed | Must-have |
| **R4** | **Command palette & keyboard UX** *(tail)* | |
| R4.1 | A **⌘K command palette** over existing API actions (navigate, create/move, filter, switch) | Nice-to-have |
| R4.2 | **Keyboard shortcuts** + a `?` help overlay | Nice-to-have |
| **R5** | **Notifications & outbound webhooks** *(tail)* | |
| R5.1 | A **notification store + inbox** emitting on must-not-miss events; poll/pull, owner-scoped | Nice-to-have |
| R5.2 | A **signed outbound webhook** (per-board opt-in, HMAC — mirrors inbound `WEBHOOK_SECRET`) | Nice-to-have |
| **R6** | **Constraints (non-functional)** | |
| R6.1 | Preserve **no-real-time / LWW** (ADR 0007) — awareness via poll/refresh | Must-have |
| R6.2 | **Single-origin** serving preserved; CSP relies on it | Must-have |
| R6.3 | **Additive & back-compat** — nullable columns / new tables only | Must-have |
| R6.4 | **API + MCP + CLI parity** per slice for any new surface (ADR 0005) | Must-have |
| R6.5 | Ships as **demo-able vertical slices behind CI** (M2–M5 cadence) | Must-have |
| **R7** | **Sister app recorded, not built** — simple-markdown is a separate repo/project; M6 only records the vision + a human kickoff card | Must-have |

---

## Decisions log

- **Hardening ships first (Wave 1), as its own epic.** The board is live and unguarded; feature work
  waits behind it. The other four epics are the "sharpen" waves, with the palette and notifications
  epics explicitly marked **tail** (demo-complete without them, as M5 did with V18/V19).
- **Edge ≠ app, and we say so.** Cloudflare (free tier) is the DDoS answer; `slowapi` is the abuse
  answer. The card copy and docs never claim rate limiting "stops DDoS."
- **Rate-limit store is in-memory** for the single Fly machine (resets on cold-start — acceptable
  MVP). If the deploy ever runs >1 machine, swap in a shared store (Redis/Upstash) — noted, not built.
- **IP keys use `Fly-Client-IP`,** not raw `X-Forwarded-For` (which `--forwarded-allow-ips=*` makes
  spoofable). A real correctness point, not cosmetic.
- **CSP is tractable only because we're single-origin** (ADR 0003) — `self` + inline SPA, no CDN.
- **Projects & cycle metrics are derived** (no new write path), consistent with M5's reporting stance.
- **`cycle` is a first-class table** with a nullable `card.cycle_id` FK (`ON DELETE SET NULL`,
  mirroring `card.epic_id`) — a cycle is board-scoped and time-boxed; deleting it detaches cards.
- **Epics gain fields, not a new entity.** `target_date`/`lead` are additive columns on `epic`; the
  "project" is the epic, richer — no `project` table (avoids a second grouping hierarchy).
- **The palette adds no backend.** It composes existing `/api/v1` calls + the usual `refetch()`
  (server-authoritative, no optimistic UI — BREADBOARD §7 preserved).
- **Outbound webhook mirrors the inbound one** (HMAC-SHA256, per-board opt-in) — symmetry with
  EPIC-10's `WEBHOOK_SECRET`, so ops and code reuse the same mental model.
- **simple-markdown is a sibling, not a feature.** It answers the file/rich-content gap without
  bolting storage onto kanban, and keeps each app simple. Recorded; the human owns kickoff.

## Open questions (resolve during slicing)

- Rate-limit granularity: per-route decorators (`slowapi` default) vs one tiered middleware. Leaning
  decorators for the sensitive routes + a coarse global middleware ceiling.
- Notification emit: inline at the write path vs a lightweight post-commit hook. Leaning a small
  helper called from the same transaction's routers (like the activity log).
- Outbound-webhook delivery: synchronous best-effort vs a tiny retry queue. Leaning best-effort +
  short backoff in-request for MVP (no worker infra); log failures.
- CSP strictness: report-only first (measure) then enforce, to avoid breaking `/docs` or the SPA.

---

## Shape — "Harden & Sharpen"

Parts are vertical slices (mechanism + its data), traced to the R's they satisfy. Grouped by the two
movements + the recorded sister strand.

| Part | Mechanism | Wave |
|------|-----------|:----:|
| **H1** | **Edge + load-shedding.** Cloudflare in front (origin hidden, SPA cached, bot/WAF); Fly `hard_limit` concurrency. (R1.1, R1.2) | 1 |
| **H2** | **App rate limiting.** `slowapi` on auth/OAuth, writes+dispatch, token-create, search/metrics, webhook; `Fly-Client-IP` + principal keys; `429`+`Retry-After`. (R1.3) | 1 |
| **H3** | **Payload hardening.** Body-size middleware; `max_length` on text; array caps on batch/template. (R1.4) | 1 |
| **H4** | **Security headers.** HSTS/CSP/nosniff/frame/Referrer middleware. (R1.5) | 1 |
| **H5** | **DB resilience.** `statement_timeout` + pool/connect timeouts, both engines. (R1.6) | 1 |
| **P1** | **Project fields.** Additive `epic.target_date` + `epic.lead`; schemas + parity. (R2.1) | 2 |
| **P2** | **Progress rollup + health.** Derived % + on-track/at-risk/overdue; epic read/list + UI. (R2.2) | 2 |
| **C1** | **Cycle model + API.** `cycle` table + `card.cycle_id`; CRUD + assign + filter; parity. (R3.1) | 2 |
| **C2** | **Cycle burndown/velocity.** Cycle-scoped derived metrics + chart. (R3.2) | 2 |
| **K1** | **Command palette (⌘K).** Fuzzy menu over existing API actions; frontend-only. (R4.1) | 3 (tail) |
| **K2** | **Keyboard shortcuts + help overlay.** (R4.2) | 3 (tail) |
| **N1** | **Notification store + inbox API.** Emit-on-event + `GET/PATCH` + `kan notify`. (R5.1) | 3 (tail) |
| **N2** | **Signed outbound webhook.** Per-board, HMAC, rate-limited. (R5.2) | 3 (tail) |
| **N3** | **Inbox UI + unread badge.** Read-first panel, poll/refresh. (R5.1) | 3 (tail) |

## Fit Check — R × Part

| Req | Requirement | Status | Part |
|-----|-------------|--------|------|
| R1.1 | Edge protection | Must | ✅ H1 |
| R1.2 | Load-shedding | Must | ✅ H1 |
| R1.3 | App rate limiting | Must | ✅ H2 |
| R1.4 | Payload caps | Must | ✅ H3 |
| R1.5 | Security headers | Must | ✅ H4 |
| R1.6 | DB resilience | Must | ✅ H5 |
| R2.1 | Epic target date + lead | Must | ✅ P1 |
| R2.2 | Progress rollup + health | Must | ✅ P2 |
| R3.1 | Cycle groups cards | Must | ✅ C1 |
| R3.2 | Cycle-scoped metrics | Must | ✅ C2 |
| R4.1 | ⌘K palette | Nice | ✅ K1 |
| R4.2 | Keyboard shortcuts | Nice | ✅ K2 |
| R5.1 | Notification store + inbox | Nice | ✅ N1, N3 |
| R5.2 | Signed outbound webhook | Nice | ✅ N2 |
| R6.1 | No-real-time / LWW | Must | ✅ (all poll/pull) |
| R6.2 | Single-origin | Must | ✅ (CSP depends on it) |
| R6.3 | Additive & back-compat | Must | ✅ P1, C1, N1 |
| R6.4 | API/MCP/CLI parity | Must | ✅ P1, C1, C2, N1, N2 |
| R6.5 | Demo-able slices behind CI | Must | ✅ |
| R7 | Sister app recorded, not built | Must | ✅ (vision doc + KAN-304) |

**Notes:** No ❌. The two tail epics (K, N) are real but *Nice-to-have*; M6 is demo-complete after
Waves 1–2 (hardening + projects + cycles). Slicing follows in [SLICES.md](SLICES.md).

---

## Detail — affordances

Most of M6 extends existing surfaces rather than inventing places:
- **Hardening** is middleware + config + ops — no new UI. Documented in a `docs/guides/` ops page.
- **Projects** enrich the existing Epics page; **cycles** add a switcher + a Dashboard chart.
- **Palette/keyboard** overlay the existing board.
- **Notifications** add one nav entry (Inbox) + a badge; the webhook is board-settings + ops.

Slicing + per-slice acceptance in [SLICES.md](SLICES.md).
