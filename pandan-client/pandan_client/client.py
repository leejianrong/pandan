"""Thin synchronous httpx client over the Pandan REST API (`/api/v1`).

Shared single source of truth for talking to the API: the MCP server and the
CLI both import ``PandanClient`` from here so the two thin adapters never drift
(DRY; API-first, ADR 0005). One method per API endpoint. The transport is
injectable so unit tests can drive every method against an ``httpx.MockTransport``
with no real server. Non-2xx responses become a ``PandanApiError`` carrying the
API's own ``detail`` string, so the caller sees a useful message (e.g. a 401 when
a token is required).

Config (base_url / token / timeout / connect_timeout / retry_backoff) is passed
in by the caller — this module reads no environment, so each adapter (MCP, CLI)
owns its own env parsing.

Cold-start resilience (KAN-25): the Fly free tier scales to zero, so the first
request after idle fails while the machine wakes. The request path uses a
generous read timeout plus a single automatic retry to ride that out; see
``PandanClient._send_with_retry`` for the exact policy.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

# The Fly free tier scales the app to zero, so the FIRST request after idle does
# not just come back slow — the machine takes ~30-40s to wake and the request
# fails mid-flight (connect/handshake error or a read timeout) before it serves
# 200s normally. So we ride it out with a generous READ timeout and a short
# CONNECT timeout (a dead host should fail fast; a waking one just reads slowly),
# plus a single automatic retry (see ``_request``). Read timeout is deliberately
# > the observed ~30s cold-start window. ``timeout`` is caller-configurable.
DEFAULT_TIMEOUT = 35.0
DEFAULT_CONNECT_TIMEOUT = 5.0

# Fixed backoff before the single cold-start retry, giving the machine a moment
# to finish waking. One retry, not a loop — caller-configurable (tests set 0).
DEFAULT_RETRY_BACKOFF = 1.0

# Transport failures where the request provably never reached the server (no
# connection / broken handshake). Safe to retry for ANY method — nothing was
# applied server-side. ``RemoteProtocolError`` is the raw symptom of Fly's
# TLS "UNEXPECTED_EOF" mid-handshake while the machine wakes.
_RETRY_ALWAYS_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError)

# Agent-facing hints for the auth failures V10 cares about (ADR 0015): a bad/
# expired token vs. a board the caller's user doesn't own. The raw server detail
# is preserved on ``.detail``; the hint just frames it usefully for the agent.
_FRIENDLY_HINTS = {
    401: "bad or expired token — set PANDAN_TOKEN to a valid PAT (create one in the Tokens UI)",
    403: "that board isn't yours — call list_boards to see the boards you can use",
}


class PandanApiError(RuntimeError):
    """A non-2xx response from the Pandan API (status + server-provided detail)."""

    def __init__(self, status_code: int, detail: str) -> None:
        hint = _FRIENDLY_HINTS.get(status_code)
        message = f"{status_code}: {hint} ({detail})" if hint else f"{status_code}: {detail}"
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


def _detail(response: httpx.Response) -> str:
    """Best-effort extraction of the API's ``{"detail": ...}`` error message."""
    try:
        body = response.json()
    except ValueError:
        return response.text or f"request failed ({response.status_code})"
    if isinstance(body, dict) and body.get("detail") is not None:
        detail = body["detail"]
        return detail if isinstance(detail, str) else str(detail)
    return f"request failed ({response.status_code})"


def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    """Drop unset (None) fields so we send only what the caller provided."""
    return {key: value for key, value in fields.items() if value is not None}


def split_card_selectors(raw: str) -> tuple[str | None, str | None]:
    """Split one mixed selector list into the API's ``(ids, refs)`` pair.

    The REST endpoint keeps ``ids=`` and ``refs=`` separate, which is right for a
    machine caller that already knows which it holds. A human or an agent usually
    does not — a note's wikilinks are ``KAN-12``, a script's are numeric, and a list
    pasted from somewhere is both. So the CLI and the MCP server take one mixed list
    and this puts each token in the right bucket, exactly as every other
    id-or-ticket argument in the CLI already behaves.

    Tokens are not validated here beyond "is it all digits" — a malformed selector is
    the API's ``422`` to raise, and duplicating that rule client-side is how the two
    drift. Returns ``(None, None)`` for an all-empty input so the caller sends
    neither param.
    """
    ids = [t.strip() for t in raw.split(",") if t.strip().isdigit()]
    refs = [t.strip() for t in raw.split(",") if t.strip() and not t.strip().isdigit()]
    return (",".join(ids) or None, ",".join(refs) or None)


class PandanClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        retry_backoff: float = DEFAULT_RETRY_BACKOFF,
    ) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._retry_backoff = retry_backoff
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/v1",
            headers=headers,
            # Generous read/write/pool timeout to ride out a cold start, but a
            # short connect timeout so a genuinely-down host fails fast.
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PandanClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._send_with_retry(method, path, **kwargs)
        if not response.is_success:
            # An HTTP error *response* (4xx/5xx) is not a cold start — never
            # retried; the existing error mapping is unchanged.
            raise PandanApiError(response.status_code, _detail(response))
        return response

    def _send_with_retry(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send once, with a single cold-start retry on transient transport errors.

        A scale-to-zero cold start surfaces as a transport-level exception, not an
        error response, so the retry lives here and never fires on 4xx/5xx:

        - connection/handshake errors (``_RETRY_ALWAYS_ERRORS``) mean the request
          never reached the server, so retry is safe for **any** method;
        - a ``ReadTimeout`` means the request *may* have been applied server-side,
          so we only retry **idempotent** ``GET``s. This app is last-write-wins
          with no idempotency keys (ADR 0007), so we never risk a double
          POST/PATCH/DELETE.

        Exactly one retry — if the retry also fails, the exception propagates.
        """
        try:
            return self._client.request(method, path, **kwargs)
        except _RETRY_ALWAYS_ERRORS:
            return self._retry(method, path, **kwargs)
        except httpx.ReadTimeout:
            if method.upper() != "GET":
                raise
            return self._retry(method, path, **kwargs)

    def _retry(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._retry_backoff > 0:
            time.sleep(self._retry_backoff)
        return self._client.request(method, path, **kwargs)

    # --- boards (discovery — V10) -------------------------------------------

    def list_boards(self) -> dict[str, Any]:
        """List the boards the caller's user owns (owner-scoped by the API)."""
        return {"boards": self._request("GET", "/boards").json()}

    def create_board(self, name: str) -> dict[str, Any]:
        """Create a board owned by the caller's user."""
        return self._request("POST", "/boards", json={"name": name}).json()

    def update_board(
        self,
        board_id: int,
        *,
        name: str | None = None,
        autosync_enabled: bool | None = None,
        autosync_advance_to_done: bool | None = None,
        outbound_webhook_url: str | None = None,
        outbound_webhook_secret: str | None = None,
        outbound_webhook_enabled: bool | None = None,
    ) -> dict[str, Any]:
        """PATCH a board's settings — only the arguments you pass are sent.

        ``name`` renames it; the ``autosync_*`` pair is the EPIC-10 / ADR 0016 GitHub
        PR→board opt-in (``autosync_enabled`` is the master switch, and
        ``autosync_advance_to_done`` separately gates merge→Done, which only has effect
        while the master switch is on); the ``outbound_webhook_*`` trio configures the
        V38 signed outbound webhook (``_url`` target, ``_secret`` write-only HMAC key,
        ``_enabled`` on/off).

        These are the six fields of the API's ``BoardUpdate``. ``_clean`` drops unset
        (None) args — and only ``None``, so an explicit ``False`` *is* sent — meaning an
        omitted field is left untouched (clearing a string value needs the raw API,
        which accepts explicit null)."""
        payload = _clean(
            {
                "name": name,
                "autosync_enabled": autosync_enabled,
                "autosync_advance_to_done": autosync_advance_to_done,
                "outbound_webhook_url": outbound_webhook_url,
                "outbound_webhook_secret": outbound_webhook_secret,
                "outbound_webhook_enabled": outbound_webhook_enabled,
            }
        )
        return self._request("PATCH", f"/boards/{board_id}", json=payload).json()

    def get_board(self, board_id: int) -> dict[str, Any]:
        return self._request("GET", f"/boards/{board_id}").json()

    def delete_board(self, board_id: int) -> dict[str, Any]:
        # 204 No Content — no body to parse.
        self._request("DELETE", f"/boards/{board_id}")
        return {"deleted": board_id}

    # --- health / warmup ----------------------------------------------------

    def health(self) -> dict[str, Any]:
        """GET the **unversioned** ``/api/health`` (it lives at the origin, not
        under ``/api/v1``). Rides a cold start via the shared retry/timeout and
        raises ``PandanApiError`` on a non-2xx response; returns the parsed body
        (``{"status": "ok"}``)."""
        # base_url is ``<origin>/api/v1/``; joining an absolute path swaps the
        # whole path (RFC 3986) so we reach ``<origin>/api/health`` without the
        # ``/api/v1`` prefix and without hard-coding the origin. The result is a
        # fully-qualified URL, so httpx sends it as-is (no base_url merge).
        url = self._client.base_url.join("/api/health")
        return self._request("GET", str(url)).json()

    def warmup(self) -> dict[str, Any]:
        """Wake a scaled-to-zero server by pinging ``/api/health``.

        Rides the cold start via the shared retry/timeout (an idempotent GET is
        retried once), but **does not throw** on a slow wake: a still-waking
        server (transport error/timeout) returns ``{"status": "waking", ...}`` and
        any other API error returns ``{"status": "error", ...}``, so an agent gets
        a clear result to act on rather than an exception. A healthy server returns
        ``{"status": "ok", "health": {...}}``.
        """
        try:
            body = self.health()
        except httpx.TransportError as exc:
            return {
                "status": "waking",
                "detail": f"server not ready yet ({exc.__class__.__name__}); retry shortly",
            }
        except PandanApiError as exc:
            return {"status": "error", "detail": str(exc)}
        return {"status": "ok", "health": body}

    # --- reads --------------------------------------------------------------

    def list_cards(
        self,
        *,
        board_id: int | None = None,
        ids: str | None = None,
        refs: str | None = None,
        column: str | None = None,
        epic_id: int | None = None,
        cycle_id: int | None = None,
        updated_since: str | None = None,
        priority: str | None = None,
        label: int | None = None,
        due_before: str | None = None,
        overdue: bool | None = None,
        needs_human: bool | None = None,
        assignee: str | None = None,
        q: str | None = None,
        sort: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params = _clean(
            {
                "board_id": board_id,
                # Batch read by numeric id / ticket ref (issue #254).
                "ids": ids,
                "refs": refs,
                "column": column,
                "epic_id": epic_id,
                "cycle_id": cycle_id,
                "updated_since": updated_since,
                "priority": priority,
                "label": label,
                "due_before": due_before,
                "overdue": overdue,
                "needs_human": needs_human,
                "assignee": assignee,
                # Free-text full-text search over title+description (M5 V15).
                "q": q,
                "sort": sort,
                "limit": limit,
                "cursor": cursor,
            }
        )
        response = self._request("GET", "/cards", params=params)
        result: dict[str, Any] = {"cards": response.json()}
        # The keyset pagination cursor for the next page rides a header (V3).
        next_cursor = response.headers.get("X-Next-Cursor")
        if next_cursor:
            result["next_cursor"] = next_cursor
        # Selectors from an ids=/refs= batch read that matched nothing (issue #254).
        # Lifted out of its header into the envelope, and only when non-empty, so a
        # caller sees the miss without having to know the endpoint reports in headers.
        unresolved = response.headers.get("X-Unresolved-Selectors")
        if unresolved:
            result["unresolved"] = unresolved.split(",")
        return result

    def list_epics(self, *, board_id: int | None = None) -> dict[str, Any]:
        params = _clean({"board_id": board_id})
        return {"epics": self._request("GET", "/epics", params=params).json()}

    def get_card(self, card_id: int) -> dict[str, Any]:
        return self._request("GET", f"/cards/{card_id}").json()

    def get_epic(self, epic_id: int) -> dict[str, Any]:
        return self._request("GET", f"/epics/{epic_id}").json()

    # --- writes -------------------------------------------------------------

    def create_card(
        self,
        title: str,
        *,
        board_id: int | None = None,
        description: str | None = None,
        column: str | None = None,
        story_points: int | None = None,
        assignee: str | None = None,
        epic_id: int | None = None,
        cycle_id: int | None = None,
        priority: str | None = None,
        due_date: str | None = None,
        label_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        payload = _clean(
            {
                "board_id": board_id,
                "title": title,
                "description": description,
                "column": column,
                "story_points": story_points,
                "assignee": assignee,
                "epic_id": epic_id,
                "cycle_id": cycle_id,
                "priority": priority,
                "due_date": due_date,
                "label_ids": label_ids,
            }
        )
        return self._request("POST", "/cards", json=payload).json()

    def create_cards(self, cards: list[dict[str, Any]]) -> dict[str, Any]:
        """Batch-create stories: loop ``create_card`` for each dict in ``cards``
        (a warm-connection convenience for filing a whole epic's worth of stories
        in one call — the shared client's cold-start retry only bites the first
        request). Each dict takes the same fields as ``create_card`` (``title``
        required; optional ``board_id``/``description``/``column``/``story_points``/
        ``assignee``/``epic_id``). Returns ``{"created": [<card>, ...]}``.

        **Fail-fast, not atomic:** on the first error the exception propagates and
        cards created before it **stay created** (no rollback — there is no batch
        endpoint; ADR 0007 last-write-wins). Order is preserved.
        """
        created = [self.create_card(**card) for card in cards]
        return {"created": created}

    def create_epic(
        self,
        name: str,
        *,
        board_id: int | None = None,
        description: str | None = None,
        target_date: str | None = None,
        lead: str | None = None,
    ) -> dict[str, Any]:
        payload = _clean(
            {
                "board_id": board_id,
                "name": name,
                "description": description,
                # Project fields (V31, KAN-295): target_date (ISO-8601) + lead.
                "target_date": target_date,
                "lead": lead,
            }
        )
        return self._request("POST", "/epics", json=payload).json()

    def update_epic(
        self,
        epic_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        target_date: str | None = None,
        lead: str | None = None,
    ) -> dict[str, Any]:
        payload = _clean(
            {
                "name": name,
                "description": description,
                "target_date": target_date,
                "lead": lead,
            }
        )
        return self._request("PATCH", f"/epics/{epic_id}", json=payload).json()

    def delete_epic(self, epic_id: int) -> dict[str, Any]:
        # 204 No Content — no body to parse.
        self._request("DELETE", f"/epics/{epic_id}")
        return {"deleted": epic_id}

    def update_card(
        self,
        card_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
        story_points: int | None = None,
        assignee: str | None = None,
        epic_id: int | None = None,
        cycle_id: int | None = None,
        priority: str | None = None,
        due_date: str | None = None,
        label_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        payload = _clean(
            {
                "title": title,
                "description": description,
                "story_points": story_points,
                "assignee": assignee,
                "epic_id": epic_id,
                "cycle_id": cycle_id,
                "priority": priority,
                "due_date": due_date,
                "label_ids": label_ids,
            }
        )
        return self._request("PATCH", f"/cards/{card_id}", json=payload).json()

    def move_card(
        self, card_id: int, column: str, *, position: int | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"column": column}
        if position is not None:
            payload["position"] = position
        return self._request("POST", f"/cards/{card_id}/move", json=payload).json()

    def claim_card(self, card_id: int, assignee: str) -> dict[str, Any]:
        """Atomically 'pull' a card: move it to ``in_progress`` **and** set its
        ``assignee`` in one call. Composes the two existing endpoints — first
        ``move_card`` (column change), then ``update_card`` (field edit), since the
        move/edit split is deliberate (ADR 0005). Returns the resulting card (the
        PATCH response, reflecting both changes). Not transactional: if the PATCH
        fails after the move, the card stays moved but unassigned.
        """
        self.move_card(card_id, "in_progress")
        return self.update_card(card_id, assignee=assignee)

    def delete_card(self, card_id: int) -> dict[str, Any]:
        # 204 No Content — no body to parse.
        self._request("DELETE", f"/cards/{card_id}")
        return {"deleted": card_id}

    # --- card-to-card dependencies (KAN-28 API / KAN-31 adapter) ------------

    def add_dependency(self, card_id: int, blocker_id: int) -> dict[str, Any]:
        """Record that card ``card_id`` is **blocked-by** ``blocker_id`` (insert the
        edge ``blocker_id → card_id``). Returns the now-blocked card with its
        refreshed ``blocked_by`` / ``blocks`` arrays."""
        return self._request(
            "POST", f"/cards/{card_id}/dependencies", json={"blocker_id": blocker_id}
        ).json()

    def remove_dependency(self, card_id: int, blocker_id: int) -> dict[str, Any]:
        """Remove the ``blocker_id → card_id`` edge (card ``card_id`` is no longer
        blocked-by ``blocker_id``). Returns the card with refreshed dependency
        arrays (the DELETE responds with the card body, not 204)."""
        return self._request(
            "DELETE", f"/cards/{card_id}/dependencies/{blocker_id}"
        ).json()

    def list_dependencies(self, card_id: int) -> dict[str, Any]:
        """List a card's dependency edges. There is no dedicated endpoint — the
        API surfaces ``blocked_by`` / ``blocks`` on the card itself — so this reads
        the card (``GET /cards/{id}``) and shapes just its dependency arrays:
        ``{"card_id": id, "blocked_by": [...], "blocks": [...]}``.
        ``blocked_by`` = ids that block this card; ``blocks`` = ids it blocks."""
        card = self.get_card(card_id)
        return {
            "card_id": card_id,
            "blocked_by": card.get("blocked_by", []),
            "blocks": card.get("blocks", []),
        }

    # --- card work-links (KAN-32 API / KAN-34 adapter) ----------------------

    def add_link(self, card_id: int, label: str, url: str) -> dict[str, Any]:
        """Attach a work-link (``label`` + ``url`` — e.g. a PR URL, branch, or CI
        run) to card ``card_id``. Returns the card with its refreshed ``links``
        array (the POST responds with the card body, not 204)."""
        return self._request(
            "POST", f"/cards/{card_id}/links", json={"label": label, "url": url}
        ).json()

    def remove_link(self, card_id: int, link_id: int) -> dict[str, Any]:
        """Detach work-link ``link_id`` from card ``card_id``. Returns the card with
        its refreshed ``links`` array (the DELETE responds with the card body, not
        204)."""
        return self._request("DELETE", f"/cards/{card_id}/links/{link_id}").json()

    # --- card notes / comments (KAN-33 API / KAN-34 adapter) ----------------

    def add_comment(self, card_id: int, body: str) -> dict[str, Any]:
        """Post a note to card ``card_id``. Returns the created comment (id, body,
        author_id, created_at). The author is the acting principal, never the
        body."""
        return self._request(
            "POST", f"/cards/{card_id}/comments", json={"body": body}
        ).json()

    def list_comments(self, card_id: int) -> dict[str, Any]:
        """List a card's notes, oldest-first (creation order). Returns
        ``{"comments": [<comment>, ...]}``."""
        return {"comments": self._request("GET", f"/cards/{card_id}/comments").json()}

    # --- board labels (M5 V11 API / KAN-244 adapter) ------------------------

    def list_labels(self, board_id: int) -> dict[str, Any]:
        """List a board's labels (id, name, color), oldest-first. Returns
        ``{"labels": [<label>, ...]}``."""
        return {
            "labels": self._request("GET", f"/boards/{board_id}/labels").json()
        }

    def create_label(self, board_id: int, name: str, color: str) -> dict[str, Any]:
        """Create a board-scoped label (``name`` + ``color`` — e.g. a hex string).
        Returns the created label. The label can then be attached to cards on that
        board via ``label_ids`` on create/update."""
        return self._request(
            "POST", f"/boards/{board_id}/labels", json={"name": name, "color": color}
        ).json()

    def delete_label(self, label_id: int) -> dict[str, Any]:
        """Delete a label by id; it detaches from every card that carried it (ON
        DELETE CASCADE). 204 No Content — no body to parse."""
        self._request("DELETE", f"/labels/{label_id}")
        return {"deleted": label_id}

    # --- dispatch + fleet-safe claim (M5 V12 API / KAN-245 adapter) ---------

    def dispatch(
        self,
        board_id: int,
        *,
        assignee: str | None = None,
        label: int | None = None,
        priority: str | None = None,
    ) -> dict[str, Any]:
        """Atomically claim the next ready-to-work card on ``board_id`` (M5 V12):
        the API selects the next unblocked ``todo`` card (``priority`` DESC then
        position), assigns it (``assignee``, else the caller), and moves it to
        ``in_progress`` in one ``FOR UPDATE SKIP LOCKED`` transaction — so a whole
        fleet can dispatch at once and never collide. ``label``/``priority`` narrow
        the selection (``priority`` is a *minimum*). Returns ``{"card": <card>}``,
        or ``{"card": None}`` when nothing is ready (the API's 204)."""
        payload = _clean({"assignee": assignee, "label": label, "priority": priority})
        response = self._request("POST", f"/boards/{board_id}/dispatch", json=payload)
        # 204 No Content = nothing ready; it has no body to parse.
        if response.status_code == 204:
            return {"card": None}
        return {"card": response.json()}

    def next_ready(
        self,
        board_id: int,
        *,
        label: int | None = None,
        priority: str | None = None,
    ) -> dict[str, Any]:
        """Peek at the next ready-to-work card on ``board_id`` **without** claiming
        it (M5 V12) — the same selection as ``dispatch`` but read-only. Returns
        ``{"card": <card>}``, or ``{"card": None}`` when nothing is ready (204)."""
        params = _clean({"label": label, "priority": priority})
        response = self._request("GET", f"/boards/{board_id}/next", params=params)
        if response.status_code == 204:
            return {"card": None}
        return {"card": response.json()}

    # --- needs-human handoff (M5 V13 API / KAN-246 adapter) -----------------

    def flag_needs_human(
        self, card_id: int, *, attention_note: str | None = None
    ) -> dict[str, Any]:
        """Flag card ``card_id`` as needing a human, with an optional
        ``attention_note`` describing the ask. Returns the updated card
        (``needs_human=true``). Records an ``attention`` activity event."""
        payload = _clean({"attention_note": attention_note})
        return self._request(
            "POST", f"/cards/{card_id}/needs-human", json=payload
        ).json()

    def resolve_card(self, card_id: int) -> dict[str, Any]:
        """Clear the needs-human flag on card ``card_id`` (``needs_human=false``,
        note cleared). Returns the updated card. Records a ``resolved`` activity
        event. The resolution channel for the agent is the card's comments."""
        return self._request("POST", f"/cards/{card_id}/resolve").json()

    # --- fleet reporting / metrics (M5 V17 API / KAN-250 adapter) -----------

    def board_metrics(
        self,
        board_id: int,
        *,
        since: str | None = None,
        window: str | None = None,
    ) -> dict[str, Any]:
        """Fetch derived flow metrics for ``board_id`` (M5 V17): throughput, cycle
        time, aging WIP, and a per-assignee breakdown — all computed from the
        activity feed + card timestamps (no stored metric). ``since`` (an ISO-8601
        timestamp) or ``window`` (``7d``/``24h``/``30m``) bound the period; omit
        both for all time. Returns the metrics object as-is."""
        params = _clean({"since": since, "window": window})
        return self._request("GET", f"/boards/{board_id}/metrics", params=params).json()

    def list_activity(
        self,
        board_id: int,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        actor: str | None = None,
        action: str | None = None,
    ) -> dict[str, Any]:
        """Fetch ``board_id``'s activity feed (KAN-18), newest-first — one row per
        successful create / update / delete / move of a card, epic or board.
        Optional filters (M5 V16, KAN-249, AND-ed): ``actor`` (exact match on an
        actor's email / agent handle) and ``action`` (the action verb, e.g.
        created/updated/deleted/moved/restored). Paginate with ``limit``; when a
        full page is returned the next page's cursor rides the ``X-Next-Cursor``
        header, surfaced as ``next_cursor`` and echoed back as ``cursor``. Returns
        ``{"activity": [...], "next_cursor"?: str}``."""
        params = _clean(
            {
                "limit": limit,
                "cursor": cursor,
                "actor": actor,
                "action": action,
            }
        )
        response = self._request(
            "GET", f"/boards/{board_id}/activity", params=params
        )
        result: dict[str, Any] = {"activity": response.json()}
        next_cursor = response.headers.get("X-Next-Cursor")
        if next_cursor:
            result["next_cursor"] = next_cursor
        return result

    # --- notification inbox (V37 API / KAN-301 adapter) ---------------------

    def list_notifications(self, *, unread: bool | None = None) -> dict[str, Any]:
        """List the caller's own notifications (V37, KAN-301), newest-first — inbox
        items for events a human shouldn't miss (``needs_human`` / ``blocked`` /
        ``ci_failed`` / ``assigned``). ``unread=True`` returns only the unread ones;
        omit (or ``None``) for all. Owner-scoped by the API (you only see your own).
        Poll/pull only (ADR 0007). Returns ``{"notifications": [<notification>, ...]}``."""
        params = _clean({"unread": unread})
        return {
            "notifications": self._request(
                "GET", "/notifications", params=params
            ).json()
        }

    def mark_notification_read(self, notification_id: int) -> dict[str, Any]:
        """Mark one of your notifications read (stamp ``read_at``); idempotent —
        re-marking leaves the timestamp untouched. 404 if it doesn't exist or isn't
        yours. Returns the updated notification."""
        return self._request(
            "PATCH", f"/notifications/{notification_id}"
        ).json()

    # --- saved views (M5 V14 API / KAN-247 adapter) -------------------------

    def list_views(self, board_id: int) -> dict[str, Any]:
        """List a board's saved views (id, name, query), oldest-first. Returns
        ``{"views": [<view>, ...]}``. Each view's ``query`` is the filter+sort
        grammar; pass it (spread) as ``list_cards`` kwargs to reproduce its set."""
        return {
            "views": self._request("GET", f"/boards/{board_id}/views").json()
        }

    def create_view(
        self, board_id: int, name: str, query: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Create a saved view on ``board_id`` — a ``name`` and a ``query`` (the
        structured filter+sort grammar, e.g. ``{"priority": "high", "sort":
        "-priority"}``; omit/``{}`` for an unfiltered view). Returns the created
        view (with its stored ``query``)."""
        payload = {"name": name, "query": query or {}}
        return self._request(
            "POST", f"/boards/{board_id}/views", json=payload
        ).json()

    def get_view(self, board_id: int, view_id: int) -> dict[str, Any]:
        """Fetch one saved view on ``board_id`` by id. 404 if it doesn't exist or
        isn't on that board."""
        return self._request("GET", f"/boards/{board_id}/views/{view_id}").json()

    def delete_view(self, board_id: int, view_id: int) -> dict[str, Any]:
        """Delete a saved view on ``board_id``. 204 No Content — no body to parse."""
        self._request("DELETE", f"/boards/{board_id}/views/{view_id}")
        return {"deleted": view_id}

    # --- batch update + card templates (M5 V19 API / KAN-252 adapter) -------

    def update_cards(self, updates: list[dict[str, Any]]) -> dict[str, Any]:
        """Batch-update several cards **atomically** in one server call — hand it a
        list of ``{"id": <id>, ...fields}`` dicts, each taking the same field edits
        as ``update_card`` (title/description/story_points/assignee/epic_id/priority/
        due_date/label_ids; **not** column/position — those stay on ``move_card``).
        Unlike ``create_cards`` (a client-side loop), this hits ``PATCH /cards/batch``,
        so it is **all-or-nothing**: any missing id 404s and no card changes. Returns
        ``{"updated": [<card>, ...]}`` in request order."""
        updated = self._request("PATCH", "/cards/batch", json=updates).json()
        return {"updated": updated}

    def list_templates(self, board_id: int) -> dict[str, Any]:
        """List a board's card templates (id, name, cards), oldest-first. Returns
        ``{"templates": [<template>, ...]}``."""
        return {
            "templates": self._request(
                "GET", f"/boards/{board_id}/templates"
            ).json()
        }

    def create_template(
        self, board_id: int, name: str, cards: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Create a card template on ``board_id`` — a ``name`` and a non-empty
        ``cards`` list (each a card payload: ``title`` required; optional
        description/column/story_points/assignee/epic_id/priority/due_date/label_ids).
        Returns the created template."""
        payload = {"name": name, "cards": cards}
        return self._request(
            "POST", f"/boards/{board_id}/templates", json=payload
        ).json()

    def get_template(self, board_id: int, template_id: int) -> dict[str, Any]:
        """Fetch one card template on ``board_id`` by id. 404 if it doesn't exist or
        isn't on that board."""
        return self._request(
            "GET", f"/boards/{board_id}/templates/{template_id}"
        ).json()

    def delete_template(self, board_id: int, template_id: int) -> dict[str, Any]:
        """Delete a card template on ``board_id``. 204 No Content — no body."""
        self._request("DELETE", f"/boards/{board_id}/templates/{template_id}")
        return {"deleted": template_id}

    def apply_template(self, board_id: int, template_id: int) -> dict[str, Any]:
        """Seed a plan in one call: instantiate a template's cards on ``board_id``
        (atomic, one transaction server-side). Returns ``{"created": [<card>, ...]}``
        in template order."""
        created = self._request(
            "POST", f"/boards/{board_id}/templates/{template_id}/apply"
        ).json()
        return {"created": created}

    # --- cycles / iterations (V33 API / KAN-297 adapter) --------------------

    def list_cycles(self, board_id: int) -> dict[str, Any]:
        """List a board's cycles (id, name, starts_on, ends_on), oldest-first.
        Returns ``{"cycles": [<cycle>, ...]}``. Use a cycle's id as the ``cycle_id``
        filter on ``list_cards`` or when assigning a card via ``update_card``."""
        return {
            "cycles": self._request("GET", f"/boards/{board_id}/cycles").json()
        }

    def create_cycle(
        self,
        board_id: int,
        name: str,
        *,
        starts_on: str | None = None,
        ends_on: str | None = None,
    ) -> dict[str, Any]:
        """Create a cycle (a time-boxed iteration) on ``board_id`` — a ``name`` and
        optional ISO-8601 ``starts_on`` / ``ends_on`` bounds. Returns the created
        cycle; assign cards to it via ``update_card(card_id, cycle_id=...)``."""
        payload = _clean({"name": name, "starts_on": starts_on, "ends_on": ends_on})
        return self._request(
            "POST", f"/boards/{board_id}/cycles", json=payload
        ).json()

    def get_cycle(self, board_id: int, cycle_id: int) -> dict[str, Any]:
        """Fetch one cycle on ``board_id`` by id. 404 if it doesn't exist or isn't
        on that board."""
        return self._request(
            "GET", f"/boards/{board_id}/cycles/{cycle_id}"
        ).json()

    def delete_cycle(self, board_id: int, cycle_id: int) -> dict[str, Any]:
        """Delete a cycle on ``board_id`` (its cards are detached, not deleted).
        204 No Content — no body to parse."""
        self._request("DELETE", f"/boards/{board_id}/cycles/{cycle_id}")
        return {"deleted": cycle_id}

    def cycle_metrics(self, board_id: int, cycle_id: int) -> dict[str, Any]:
        """Fetch derived burndown / velocity metrics for a cycle (V34): committed
        vs completed (stories + points), velocity (completed points), and a per-day
        burndown over the cycle's ``starts_on``..``ends_on`` window — all computed
        from the cycle's card state + activity feed (no stored metric). 404 if the
        cycle doesn't exist or isn't on ``board_id``. Returns the metrics as-is."""
        return self._request(
            "GET", f"/boards/{board_id}/cycles/{cycle_id}/metrics"
        ).json()
