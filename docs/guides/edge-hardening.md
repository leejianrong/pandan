# Edge hardening: Cloudflare in front of Fly + load-shedding

This guide covers putting **Cloudflare (free tier)** in front of the Fly.io deploy and the Fly-side
concurrency limit that makes the 256MB box **shed load (`503`) instead of OOM-ing** under a burst.
Together they are the layer that actually addresses volumetric / DDoS traffic — **app code cannot**.
The in-app rate limiter (V27, `RATE_LIMIT_*`) is per-tier fairness once a request reaches uvicorn; it
does nothing for a flood large enough to saturate the single machine or the origin bandwidth. That
job belongs to the edge.

Two parts:

1. **The Fly `fly.toml` concurrency limit** — already wired in the repo, applied on the next deploy.
   Documented in [§Fly concurrency limit](#fly-concurrency-limit-already-in-flytoml) below.
2. **The Cloudflare setup** — a **human/ops task** performed in the Cloudflare and GitHub consoles.
   Nothing here is automated and no secrets are added to the repo or to Fly. Follow the numbered steps
   below once you own a domain.

> **Prerequisite: you need a custom domain.** Cloudflare **cannot** proxy a `*.fly.dev` hostname — it
> only proxies DNS records inside a zone you control. So `simple-kanban-jian.fly.dev` can never sit
> behind Cloudflare directly; you must point a domain you own (e.g. `kanban.example.com`) at the Fly
> app and proxy *that*. If you don't have a domain, only the Fly concurrency limit applies and the
> rest of this guide is a no-op.

## Fly concurrency limit (already in `fly.toml`)

[`fly.toml`](../../fly.toml) declares a per-machine request-concurrency cap under `[http_service]`:

```toml
[http_service.concurrency]
  type = "requests"
  soft_limit = 20
  hard_limit = 40
```

- **`type = "requests"`** counts concurrent in-flight HTTP requests (not raw TCP connections).
- **`hard_limit = 40`** — Fly's proxy refuses further requests to the machine past this with a `503`
  **before** they reach uvicorn, so a burst is shed at the proxy instead of piling up connections and
  memory until the kernel OOM-kills the 256MB `shared-cpu-1x` process.
- **`soft_limit = 20`** — the point past which Fly's load balancer prefers another machine (or wakes
  a stopped one). With `min_machines_running = 0` and a single machine there's usually nowhere else to
  send it, so `soft_limit` is mostly advisory here; `hard_limit` is the real backstop.

**Why these numbers.** The box is one 256MB `shared-cpu-1x` instance. The sync board path holds a
bounded DB connection pool of 10 (`DB_POOL_SIZE` 5 + `DB_MAX_OVERFLOW` 5, V30), so ~20 concurrent
requests is already past steady-state throughput and 40 is a hard ceiling that still leaves memory
headroom. They're deliberately conservative — better to shed a few requests with a clean `503` than
to let the process get OOM-killed and drop **every** in-flight request. If you later scale the box up
or add machines, raise these (or they'll cause spurious `503`s under legitimate concurrency).

This is the one part of edge hardening that lands via the repo: **merging a change to `fly.toml`
deploys and applies the limit**. Everything below is manual Cloudflare/GitHub console work.

## 1. Add a custom domain to the Fly app

Point a hostname you own at the app and let Fly issue its certificate. From the repo root:

```bash
fly certs add kanban.example.com   # your domain, not *.fly.dev
```

`fly certs show kanban.example.com` (or `fly certs list`) prints the DNS records Fly needs you to
create — typically:

- An **`A`/`AAAA`** (or `CNAME`) record for the hostname pointing at the Fly app's IPs.
- An **`_acme-challenge.kanban.example.com` `CNAME`** used for the ACME/Let's Encrypt validation that
  issues the cert.

Keep this tab open — you'll create these records in Cloudflare in the next step.

## 2. Create the DNS records in Cloudflare (proxied app, DNS-only ACME)

In the Cloudflare dashboard for your zone, go to **DNS → Records** and add exactly what `fly certs
show` listed, with the right proxy status on each:

- **The app record** (`A`/`AAAA`/`CNAME` for `kanban.example.com`): set the proxy toggle to
  **Proxied** (orange cloud). This is what hides the Fly origin behind Cloudflare's IPs and routes
  traffic through the WAF / cache / rate limiting.
- **The `_acme-challenge` record**: set it to **DNS only** (grey cloud). ACME validation must resolve
  to the real target, not Cloudflare's proxy — if you proxy it, Fly's certificate issuance/renewal
  fails. This one stays grey **permanently**, not just during setup.

Wait for `fly certs show kanban.example.com` to report the cert as **issued/valid** before moving on.

> **Origin still exposed after this step.** Proxying the record hides the origin's *IP* from casual
> lookups, but `simple-kanban-jian.fly.dev` itself stays publicly reachable and bypasses Cloudflare
> entirely. See [§Honest caveat](#honest-caveat-flydev-stays-reachable) — closing that gap is a
> follow-up, not part of this guide.

## 3. SSL/TLS mode: Full (strict)

In Cloudflare **SSL/TLS → Overview**, set the encryption mode to **Full (strict)**.

- Fly terminates TLS at its proxy with a real, valid certificate for your custom domain (issued in
  step 1), so **Full (strict)** — which requires a trusted cert on the origin — is correct and safest.
- **Do not** use **Flexible** (it makes Cloudflare→origin plaintext, breaks `force_https`, and can
  cause redirect loops) and you don't need **Full** (non-strict) since the origin cert is genuine.

The app already sets `force_https = true` and runs uvicorn with `--proxy-headers
--forwarded-allow-ips=*`, so it correctly sees the client-facing HTTPS scheme through Cloudflare +
Fly. No app change is needed for TLS.

## 4. Turn on Bot Fight Mode + WAF managed rules

In **Security**:

- **Bot Fight Mode** (Security → Bots): turn it **on**. On the free tier this challenges obviously
  automated traffic and is the cheapest first line against low-effort bots and scrapers.
- **WAF Managed Rules** (Security → WAF → Managed rules): enable the **Cloudflare Free Managed
  Ruleset**. It blocks common exploit patterns (injection probes, known-bad payloads) at the edge.
- **Security level**: leave at **Medium** (or raise to **High** during an active attack).

## 5. Add a rate-limiting rule

Cloudflare's edge rate limiting sheds a flood **before** it reaches Fly or the app limiter. The free
tier includes one rate-limiting rule. Under **Security → WAF → Rate limiting rules → Create rule**:

- **Match:** the API surface is the expensive part — scope the rule to `/api/*` (or all traffic if
  you prefer a blanket cap).
- **Counting:** requests **per client IP**.
- **Threshold:** a conservative value that's well above a real human/agent but below a flood — e.g.
  **100 requests per minute per IP**. Tune from real traffic.
- **Action:** **Block** (or **Managed Challenge**) for a period (e.g. 1 minute).

This complements — does not replace — the app rate limiter (V27): Cloudflare stops volumetric abuse
at the edge; the app limiter enforces per-tier fairness (auth / write / expensive / webhook) for
traffic that gets through. Keep both.

## 6. Cache the static SPA, bypass the API

The SPA's hashed static assets are safe to cache hard at the edge; the API and docs must never be
cached. Under **Caching → Cache Rules → Create rule** (create the bypass rule *first* / order it
above the cache rule so it wins):

- **Bypass cache** when the URI path **starts with `/api/`** — every API response is
  per-user/owner-gated and must always hit the origin. Also bypass **`/docs`** and **`/openapi.json`**
  (the live OpenAPI surface).
- **Cache** (eligible for cache, edge TTL e.g. a few hours to a day) when the URI path **starts with
  `/assets/`** — Vite emits content-hashed filenames under `/assets/`, so they're immutable and a
  long TTL is safe (a new build produces new filenames). This offloads the SPA bundle from the origin
  and is what lets Cloudflare absorb a traffic spike on the static shell without waking/loading Fly.
- Leave the SPA entry (`/` and the `index.html` catch-all) **uncached or short-TTL**, so a new deploy
  is picked up promptly.

> Do **not** enable a blanket "Cache Everything" without the `/api/*` + `/docs` bypass — you would
> serve one user's owner-gated board data to another, and cache stale mutations. The bypass is
> load-bearing.

## 7. Update the GitHub OAuth callback for the new origin

Human login is a GitHub OAuth App whose callback URL must match the origin the browser is on. Once
users reach the app at `https://kanban.example.com`, the prod OAuth App's callback must be updated —
a GitHub OAuth App allows only **one** callback URL (which is why dev and prod already use separate
Apps; see CLAUDE.md §Configuration).

- In the prod GitHub **OAuth App** settings, set **Authorization callback URL** to
  `https://kanban.example.com/auth/github/callback`.
- The Fly app derives `redirect_uri` from the incoming request; behind Cloudflare + Fly with
  `--proxy-headers --forwarded-allow-ips=*` it already generates an `https://<host>/…` URL, so no
  `fly secrets` or code change is needed — only the GitHub App's callback string.
- If you keep the old `*.fly.dev` origin reachable and want login to work there too, that's a
  *second* origin and would need its own OAuth App (GitHub's one-callback-URL limit). Simpler: send
  all human traffic to the custom domain.

Log in once end-to-end after the change to confirm the round-trip.

## Honest caveat: `*.fly.dev` stays reachable

**Putting Cloudflare in front of a custom domain does not take the Fly origin offline.**
`simple-kanban-jian.fly.dev` remains publicly reachable and bypasses Cloudflare's WAF, rate limiting,
and cache entirely — an attacker who knows (or guesses) the `*.fly.dev` hostname can hit the origin
directly and skip every protection in this guide. Proxying the DNS record hides the origin *IP* from
a casual `dig`, not the well-known `*.fly.dev` name.

Closing this gap is a **follow-up**, not covered here, and needs one of:

- **A Cloudflare Tunnel (`cloudflared`)** so the origin has no public inbound listener at all and only
  Cloudflare can reach it — the most complete fix, but it's a running sidecar/process the 256MB box
  has to host, so weigh the memory cost.
- **An origin IP allowlist**: restrict the Fly app to accept traffic only from Cloudflare's published
  IP ranges (e.g. at the Fly proxy / a firewall layer), rejecting anything that didn't come through
  Cloudflare. Cloudflare's ranges change, so this needs periodic updating.

Until one of those is in place, treat the edge protections as raising the cost of an attack, not as a
hard perimeter. The Fly `hard_limit` (above) is the last-resort backstop that keeps a direct-to-origin
flood from OOM-ing the box — it applies **regardless** of Cloudflare, which is why it ships in
`fly.toml` rather than living only in the edge config. File the tunnel/allowlist work as a tracked
follow-up card.

## Summary checklist

- [ ] `fly.toml` concurrency limit merged + deployed (soft 20 / hard 40) — **in-repo, automatic on deploy**.
- [ ] Custom domain added: `fly certs add`, cert issued.
- [ ] Cloudflare DNS: app record **Proxied**, `_acme-challenge` **DNS only**.
- [ ] SSL/TLS mode **Full (strict)**.
- [ ] Bot Fight Mode on + Free Managed WAF ruleset enabled.
- [ ] Rate-limiting rule on `/api/*` (per-IP, conservative threshold).
- [ ] Cache rule: cache `/assets/*`, **bypass** `/api/*` + `/docs`.
- [ ] GitHub OAuth callback updated to the new origin.
- [ ] Follow-up filed: Cloudflare Tunnel **or** origin IP allowlist to close the `*.fly.dev` bypass.
