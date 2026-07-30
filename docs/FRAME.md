# FRAME — Pandan (MVP)

Succinct product definition captured at the start of shaping (Shape Up). Sources: REQS.md (raw),
docs/PRD.md + CONTEXT.md (scaffolding).

---

## Source (verbatim, from REQS.md)

> I want to make a simple kanban app. For now, it should just be an MVP (prioritize shipping
> something deployable).
>
> What it is - a simple Kanban app that software engineers and other teams can use. It should be a
> CRUD app with frontend, backend, and persistent database.
>
> Why - I want a simple kanban app that can be extensible and include future integration with an
> MCP server and CLI so that LLM agents can execute actions on the kanban app.
>
> Rough features: todo/in-progress/done columns; move cards between columns in the frontend; cards
> have title, description, story points, assigned-to; each card has a Jira-like number; an API so
> external parties (users, LLMs, MCP, CLI) can perform actions.
>
> Constraints: demoable UI; Svelte 5 + Vite 8; FastAPI; SQLite→(now PostgreSQL); no auth/billing;
> GitHub Actions CI/CD deployed somewhere free/low-cost.

## Problem (what's broken / the pain)

The team has no lightweight, self-owned board to track work across Todo → In Progress → Done.
Off-the-shelf tools are heavy, paid, or awkward to automate. Critically, they want a board that
**agents and scripts can drive**, not just humans — but there is nothing today that is both simple
enough to ship immediately and structured so that MCP/CLI/LLM automation can be bolted on later
without rework.

## Outcome (what success looks like)

A publicly deployed, demoable Kanban board where a team member can create, edit, assign, estimate,
move, and reorder cards across three fixed columns — and where **every one of those actions is
already available over a documented REST API**. Success = the full vertical slice works in
production (Svelte UI + FastAPI + PostgreSQL, shipped via GitHub Actions to Fly.io/Neon), and the
API is clean enough that a future MCP server or CLI is a thin adapter, not a rebuild.

## Appetite & boundaries

- **Appetite:** small — an MVP meant to ship fast and demo, not a polished product.
- **In:** three fixed columns, card CRUD, move/reorder, ticket numbers, full REST API + OpenAPI,
  single deployed artifact, CI/CD, seed data.
- **Out (explicit):** auth, billing, multi-board, custom columns, WIP limits, comments, labels,
  attachments, due dates, history, real-time sync, and the MCP/CLI/agent clients themselves.
- **Fixed rabbit holes avoided:** no real-time collaboration, no optimistic locking, no user
  accounts — last-write-wins is accepted (ADR 0007).
