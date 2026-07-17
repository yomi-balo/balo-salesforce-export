# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

This repo is the **Python historic sync engine** for Balo's Bubble.io → Salesforce migration. It runs on the operator's laptop, pulls records from Bubble's Data API, transforms them into the shapes SF expects, and POSTs them to the `sf-middleware-api` (a separate Node.js service). Every send is logged to `output/sync.db`; every run also emits a Markdown audit report to `output/reports/`.

Real-time Bubble→SF traffic (webhooks fired when users edit records in Bubble) goes **directly to the middleware, bypassing this repo entirely**. This tool is only for historic backfill + operator-driven catch-up syncs. That distinction matters: any transformation this repo does (field renames, picklist normalisation, date-format fixes) must be mirrored in Bubble's webhook payloads OR in the middleware's route transforms — otherwise real-time and historic sync produce different SF records.

## Two-repo world

- **This repo** (`~/Desktop/balo/atlas/balo-salesforce-export/`, branch `feat/historic-sync-pipeline`) — Python sync tool
- **Middleware** (`~/Desktop/balo/Salesforce/`, branch `main`) — Fastify + BullMQ + ioredis, deployed to Railway. Receives POSTs from this tool AND from Bubble webhooks, queues jobs, talks to Salesforce Apex + REST, posts success/failure to `#sf-sync-activity` / `#sf-sync-errors` Slack channels.

When investigating an error, the flow is: `sync.py` → HTTP 202 from middleware → BullMQ worker → SF Apex or REST → Slack notification. HTTP 202 only means "middleware accepted the job", not "SF accepted the record". SF outcomes must be checked in Slack.

## Team

- **Yomi** (`yomi@getbalo.com`) — product owner + operator running this tool. Uses the sync interactively.
- **Yash** — Bubble dev. Owns Bubble data model + the real-time webhook flows.
- **Nick** — Salesforce dev. Owns SF schema, Apex classes (especially `ProspectAPI.upsertProspect`), SF Flows, picklist values, and Connected App auth.

Error triage follows those boundaries: picklist / Apex / Flow / soft-deleted-Account issues → Nick. Missing Bubble fields / wrong slug values / Bubble-side data quality → Yash. Sync logic, transformer, middleware routing → this repo.

## Commands

```bash
# First-time setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit to add BALO_API_TOKEN + MIDDLEWARE_API_SECRET

# List all sync targets
python sync.py --list

# Full backfill of one target (ignore cursor, fetch everything from Bubble)
python sync.py prospects --full
python sync.py accounts --full
# ... etc.

# Cursor-based incremental (default) — only fetches Bubble records modified
# since the last completed run's started_at
python sync.py projects

# Common flags
python sync.py cases --limit 5 --dry-run    # transform + log to sync.db but do NOT POST
python sync.py accounts --since 2026-06-01T00:00:00Z
python sync.py contacts -v                  # print every middleware request
```

**There is no test suite and no linter.** The only smoke test is `--dry-run -v` against the live Bubble API. When making non-trivial changes, dry-run first, inspect the report, then run live against a small `--limit`.

## Sync target dependency order

The 7 targets have real FK dependencies in SF — running them out of order causes cascading FK-not-found errors. Correct order for a full resync from empty:

1. **prospects** (`POST /crm/prospect`) — creates Client Account + Client Contact atomically via Nick's Apex. Foundation for everything else.
2. **accounts** (`PATCH /crm/account/:id`) — fills in Account extras (Stripe, Has_Booked_*, etc.) on top of what prospects created; also creates FREELANCE + AGENCY synthetic Accounts.
3. **contacts** (`PATCH /crm/contact/:id`) — Expert Contacts only. Depends on their FREELANCE/AGENCY Accounts.
4. **projects** (`PATCH /crm/opportunity/project/:id`) — needs client Account + Primary_Contact from prospects.
5. **cases** (`PATCH /crm/opportunity/case/:id`) — same parents as projects.
6. **project-experts** (`PATCH /crm/project-expert/:id`) — needs project Opportunity + Expert Contact.
7. **consultations** (`PATCH /crm/consultation/:id`) — needs Opportunity (project or case) + Project__c (project-expert).

## Payload diffing (2026-07-17)

`sync.py` compares each row's current Bubble payload against the last successful send stored in `sync.db`:

- **Identical** → skip entirely (nothing sent to middleware). Reported under `Unchanged`.
- **Some fields changed, PATCH route** → send only the changed fields. SF PATCH leaves untouched fields alone, so sales-team edits stick.
- **Some fields changed, `/crm/prospect`** → send full payload (Nick's Apex expects it complete; the Apex has its own dedupe).
- **First-ever send** (no baseline in sync.db) → send full payload.

Diffing is field-level. Nested reference objects (`{"Account": {"Balo_Id__c": "..."}}`) recurse to the leaf, but always ship the full nested object when any inner field changes — SF PATCH needs the FK identifier inside the reference to match. Fields present in the last payload but absent in the current one are NOT sent (no null-wipes) — matches the transformer's `omit_if_empty` behaviour and prevents Bubble-clears from wiping SF fields.

Implementation lives in `sync.py::_diff_payload` and `src/sync_log.py::last_successful_payload`. The sender stores the **full current payload** in `sync.db` even when only a diff went over HTTP, so next run's diff has the correct baseline.

## Architecture — pipeline phases

Each `python sync.py <target>` runs four phases:

1. **Fetch** (`src/fetcher.py`) — `Fetcher.fetch_all()` pulls in a fixed FK-graph order: `_round1_anchors` (companies, agencies, countries) → `_round2_users_experts` → `_round3_cases_projects` (requests + finalized projects + EOIs) → `_round4_meetings` (+ linked consultations / project-meetings) → `_round5_packages`. Each round's output is what the next needs — don't reorder.
2. **Transform** (`src/transformer.py`) — one `transform_*` per target. Each returns `(columns, rows, provenance)`. Rows are dicts of Bubble→SF-shaped payloads. Filters live here (e.g. dual-role-only company filter for accounts, blocked-email filter for contacts).
3. **Send** (`src/sender.py`) — POSTs each row to the middleware. Retries on 5xx/network with exponential backoff. Logs every attempt to sync.db BEFORE the HTTP call so a crash leaves a pending row.
4. **Report** (`sync.py::_write_report`) — Markdown audit at `output/reports/<target>_<ts>.md` listing Sent / Filtered / Unchanged / Errors per row.

### `DataStore` — shape the transformer expects

`Fetcher` populates a single `DataStore` (see `src/fetcher.py`). Load-bearing split:

- **Lists** (order preserved, iteration is output order): `clientcompanies`, `agencies`, `cases`, `project_requests`, `project_eois`, `meetings`.
- **Dicts keyed by `_id`** (random-access FK lookups): `users`, `experts`, `countries`, `projects`, `consultations`, `projectmeetings`, `packages`.

New entities should match the pattern of siblings.

### Bubble API quirks

`src/api_client.py` hides Bubble-specific behaviours:

- Table paths in `src/config.py::TABLE_PATHS` are URL-encoded emoji names (e.g. `👥profile:clientcompany`). Always route through `TABLE_PATHS[key]`, never hardcode.
- Global 1s delay between requests + exponential backoff on 429. Returns `None` on 400/404 rather than raising — callers must tolerate missing records.
- `fetch_all_pages` uses Bubble's `cursor`/`remaining` paging. Don't substitute offset arithmetic.
- Auth is `?api_token=<token>` as a query param, not a header.
- `modified_since` cursor filters at the API level using Bubble's `Modified Date`.

### Transformer conventions

- Option-set values arrive as `{"slug": ..., "display": ...}` dicts OR bare strings. Use `get_slug` / `get_display` / `join_array_slugs` / `list_array_slugs` in `src/config.py` — never `.slug` directly.
- Mode-dependent option fields (AI / Manual / Final) go through `_smart_field` (in `src/transformer.py`).
- `SENSITIVE_FIELDS` in `src/config.py` lists Cronofy tokens etc. that must never hit output. Use `_redact` if you pass a raw record through.
- SF `RecordTypeId` constants and `PROSPECT_STATUS` / `ACCOUNT_SOURCE` live in `src/config.py`.
- Empty-string handling is nuanced. Per-target config in `sync.py`: `omit_if_empty` drops the field from the payload; `nullify_empty_strings` sends `null`. Don't invert the wrong one — see the `_build_payload` helper for the exact precedence.

## Row filters (why records don't sync)

Each target has `row_checks` in `sync.py` — a list of `(reason, lambda)` filters. Common ones:

- **`no pure-client users (expert-only or dual-role-only dummy company)`** — client Accounts require at least one user with a `client-*` role AND no expert role. Dual-role users (freelance-expert + client-admin, common for experts who signed up their own company) DON'T count. See `EXPERT_OR_ADMIN_ROLES` and `CLIENT_ROLES` in `src/config.py`.
- **`not a real client (no client role)`** — prospects target only pushes users with a client role.
- **`profile not approved`** — contacts target only pushes Experts with `Application_Status__c == "approved"`.
- **`blocked test email`** — hard-drops emails matching `BLOCKED_EMAIL_PATTERNS` (revido.io, ylinkz, yomi@getbalo.com). Prevents test users from creating SF pollution. Downstream cost: any project/case owned by a blocked user orphans in SF; see `YASH_TODO.md` "Decisions pending".
- **`not an EXPERT row`** — contacts target only creates Expert Contacts; Client Contacts are created via `/crm/prospect`.

Filters are per-target — a row can pass one target's filter and fail another's.

## `sync.db` schema

Single SQLite file at `output/sync.db`. Two tables:

**`sync_events`** — one row per attempted send:
```
id, ts, sf_object, route, balo_id, payload (JSON), sources (JSON),
http_status, job_id, response_body, duration_ms, sf_status, sf_error
```
- `payload` is the **full** current Bubble payload at send time (baseline for next run's diff), even if only a partial diff was sent over HTTP.
- `http_status = 202` means middleware accepted; `sf_status` and `sf_error` are currently always `'pending'` and empty because the middleware doesn't propagate final SF outcomes back (see `YASH_TODO.md` — Nick-side follow-up).

**`sync_runs`** — one row per `python sync.py <target>` invocation, used for cursor tracking:
```
id, route, started_at, completed_at, modified_since, records_sent, records_skipped, notes
```

Common queries live inline in `src/sync_log.py`: `already_sent`, `last_successful_payload`, `latest_cursor`, `lookup`.

**Manual sync.db manipulation is common and expected.** To retry specific records:

```bash
sqlite3 output/sync.db "DELETE FROM sync_events WHERE balo_id IN ('...','...') AND route = '/crm/prospect';"
```

Always `cp output/sync.db output/sync.db.bak.YYYY-MM-DD` before destructive changes. Backups already exist in the same folder.

## OAuth flow (middleware ↔ SF)

Nick switched the SF Connected App from **Resource Owner Password Grant → Client Credentials** on 2026-06-18. The middleware sends only `client_id + client_secret` — no username/password. If auth breaks, the middleware Slacks `SF token fetch failed: 400 {invalid_grant}`. Fix: check `SF_CLIENT_ID` / `SF_CLIENT_SECRET` in Railway env vars against what Nick provided.

## Slack channels (via Slack MCP when available)

- `#sf-sync-activity` — green success ticks. Every 202+SF-accepted upsert.
- `#sf-sync-errors` — 4xx from SF, 5xx from SF, token-refresh failures, permanently-failed jobs (BullMQ gave up after 3 attempts).

Sample the errors channel with `slack_read_channel`. Response payloads can be huge — for ≥100-message reads the tool may exceed the token budget and save to a temp file; parse with `grep`/`python3` slicing.

## YASH_TODO.md — the running punchlist

`YASH_TODO.md` at the repo root is the shared TODO tracker for anything the sync can't fix locally:

- **Outstanding for Nick** — SF-side issues (Apex bugs, missing picklist values, SF Flow failures, `ENTITY_IS_DELETED` on soft-deleted Accounts, etc.).
- **Real-time payload normalization (for Yash)** — transformations this repo applies that Yash's Bubble webhooks should also apply, so real-time and historic sync produce identical SF records.
- **Bubble data quality (for Yash)** — missing fields, `Title (Manual)` empties, EOI `Modified Date` used as `Finalized_Date__c` proxy, etc.
- **Decisions pending (Yomi)** — open policy questions (e.g. `yomi@getbalo.com` blocked-email Primary_Contact orphans).

When a new error class appears in Slack, log it here with an example payload + example failing IDs + date. When a fix lands, note the fix date; delete or move to a "Resolved" section only when confirmed working end-to-end.

Every recent commit involving `YASH_TODO.md` is a good example of the format.

## Common workflows

### "The sync is failing with error X"
1. Read the error class in `#sf-sync-errors`. Is it FK / picklist / Apex-500 / SF-Flow / auth?
2. Check `YASH_TODO.md` — is it already logged? Nick may already be working on it.
3. Trace the parent: if FK-not-found for entity Y, grep the latest report to see if Y was Sent, Filtered, or Errored.
4. If cascade from a failed parent: fix the parent, clear sync.db entries for both parent + child, re-run in dependency order.

### "I need to retry a specific set of records"
1. `sqlite3 output/sync.db "SELECT id, ts, http_status, sf_status FROM sync_events WHERE balo_id IN (...) AND route = '...';"` to see current state.
2. `cp output/sync.db output/sync.db.bak.YYYY-MM-DD`
3. `sqlite3 output/sync.db "DELETE FROM sync_events WHERE ..."`
4. `python sync.py <target> --full` — will only re-send the deleted ones since everything else is unchanged.

### "I want to know if this project failed"
1. Grep the latest per-target report at `output/reports/<target>_*.md`.
2. Cross-reference the `Job ID` column against `#sf-sync-errors` in Slack.
3. If report shows HTTP 202 but `#sf-sync-errors` has a permanent-failure entry, it's a silent middleware→SF failure (documented in `YASH_TODO.md` — Nick to add SF-side status callback).

## Reference docs in this repo

- `FIELD_MAPPING.md` — canonical Bubble→SF field mapping per endpoint. Source of truth for transformer logic; keep in sync when field renames happen.
- `MIDDLEWARE_ENDPOINTS.md` — describes each middleware route the transformer feeds.
- `REFACTOR_PLAN.md` — historical design doc for the sync engine. Read for context on why sync.py/sync.db exist. Current state has largely landed.
- `YASH_TODO.md` — running punchlist (described above).
- `EXPORT_FORMAT.md` — legacy 6-CSV layout. The XLSX export path (`export.py`) is deprecated in favour of `sync.py`; keep for reference until removed.
- `Balo - Salesforce Integration.postman_collection (3).json` and `balo-bubble-data-api-swagger.json` — external API specs.

## Related Middleware repo (`~/Desktop/balo/Salesforce/`)

Not covered here in detail, but the middleware handles:
- Token management (Client Credentials OAuth, cached in Redis)
- Route-scoped payload normalisation (e.g. `Type_of_Support__c` rename, `StageName` capitalisation, Bubble rich-text tag stripping) — see `src/queue/processor.ts`
- BullMQ job queue with retry + exponential backoff
- Slack webhook posts (activity / errors channels)
- Bull Board admin UI at `/admin/queues` (basic auth)

If a transformation logically belongs in the middleware (so real-time Bubble webhooks get it too), edit the middleware repo, not this one. If it's a historic-only concern (e.g. computing derived fields from multiple Bubble records), edit here.
