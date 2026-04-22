# Refactor Plan: Bubble → Middleware Historic Sync

**Status:** Phases 1–5 landed (2026-04-22). Tool can now enumerate, transform, log, and POST historic Bubble data through sf-middleware-api, and inspect per-balo_id send history. Outstanding: initial full backfill run, `src/manifest.py` retirement (still used by the XLSX path), and any reconciler work. See the phase headings below for what's done.

## Goal

Refactor this tool from "sample + emit XLSX" into "enumerate all historic Bubble data and POST through the `sf-middleware-api` to land it in Salesforce." Keep the XLSX exporter as a secondary debugging view.

All sent objects are logged to a local SQLite database with the full payload and the Bubble `_id`s of every source record that was read to construct it, so a Salesforce-side failure can be traced back to the component rows.

## Resolved decisions

1. **Repeatable.** Fetcher takes a `modified_since` cursor; each run pulls only Bubble rows modified since the last completed run. Historic backfill is just the first run with cursor = null.
2. **Middleware queue topology.** Single FIFO BullMQ queue (`sf-forward`) shared across all 9 routes, concurrency 5. Technically concurrency > 1 means strict landing order is not guaranteed between parent/child jobs enqueued back-to-back, but this is resolved by (3) below so it doesn't matter in practice.
3. **Manual phased sends.** `sync.py` does not run all phases in one shot. Operator runs it one phase at a time, waiting for each phase to drain in middleware logs before starting the next. This makes the concurrency-5 concern moot (phase boundaries are minutes/hours apart, not seconds).
4. **Keep XLSX exporter.** Retained as a read-only debugging view of current Bubble state. Transformer is shared, cost is near-zero.
5. **No payload scrubbing in sync.db.** Single-user local tool; `sync.db` inherits `.env` sensitivity.

## Phased send plan

The sender routes each transformer's rows to middleware routes based on row type:

- **Phase 1 — Client signups.** Client rows from `transform_prospects_contacts` → `POST /crm/prospect`. Apex atomically creates client Account + Contact + Prospect__c with basic fields.
- **Phase 2 — Accounts and Expert Contacts.**
  - All Account rows from `transform_accounts` (both client and agency) → `PATCH /crm/account/:id`. This patches extra Account fields (`Stripe_Customer_Id__c`, `Has_Booked_Consultation__c`, `Has_Redeemed_Credits__c`, etc.) that the Apex prospect call does not set, and creates agency Accounts.
  - Expert rows from `transform_prospects_contacts` → `PATCH /crm/contact/:id`. Sent **after** agency Accounts so agency references resolve.
- **Phase 3 — Child records.**
  - `transform_opportunities_cases` → `PATCH /crm/opportunity/case/:id`
  - `transform_opportunities_projects` → `PATCH /crm/opportunity/project/:id`
  - `transform_project_experts` → `PATCH /crm/project-expert/:id`
  - `transform_consultations` → `PATCH /crm/consultation/:id`

The sender uses each transformer's `_contact_type` / `_group` helper columns to decide routing. These columns stay out of the outgoing payload.

## Target architecture

```
sync.py (new entry)
  └── Fetcher.fetch_all_historic()      # full enumeration, no scoring
         → DataStore (in memory)
  └── transform_all()                   # now returns (cols, rows, provenance)
  └── Sender.send_in_order()            # dependency order per MIDDLEWARE_ENDPOINTS.md
         ├── log_send() before POST     → sync.db row, status=pending
         └── log_result() after 202     → fill job_id, http_status

inspect.py <balo_id>                    # query sync.db, pretty-print payload + sources
export.py (kept)                        # XLSX mode, unchanged UX
```

## SQLite schema (`output/sync.db`)

```sql
CREATE TABLE sync_events (
  id            INTEGER PRIMARY KEY,
  ts            TEXT NOT NULL,
  sf_object     TEXT NOT NULL,          -- 'Account', 'Consultation__c', ...
  route         TEXT NOT NULL,          -- '/crm/consultation/1749...'
  balo_id       TEXT NOT NULL,          -- external id used by SF
  payload       TEXT NOT NULL,          -- full JSON sent to middleware
  sources       TEXT NOT NULL,          -- JSON: [{table, _id, label}, ...]
  http_status   INTEGER,
  job_id        TEXT,                   -- from middleware 202 response
  response_body TEXT,
  duration_ms   INTEGER,
  sf_status     TEXT DEFAULT 'pending', -- pending | landed | failed (updated manually or by reconciler)
  sf_error      TEXT
);
CREATE INDEX idx_balo_id ON sync_events(balo_id);
CREATE INDEX idx_job_id  ON sync_events(job_id);
CREATE INDEX idx_status  ON sync_events(sf_status);

CREATE TABLE sync_runs (
  id                  INTEGER PRIMARY KEY,
  route               TEXT NOT NULL,      -- '/crm/prospect', '/crm/account/:id', ...
  started_at          TEXT NOT NULL,
  completed_at        TEXT,               -- null if crashed / in-progress
  modified_since      TEXT,               -- cursor value used for this run (null for full backfill)
  records_sent        INTEGER DEFAULT 0,
  records_skipped     INTEGER DEFAULT 0,  -- already in sync_events
  notes               TEXT
);
CREATE INDEX idx_sync_runs_route ON sync_runs(route, completed_at);
```

`sync_runs` gives the next repeatable run a `modified_since` cursor: `SELECT max(completed_at) FROM sync_runs WHERE route = ? AND completed_at IS NOT NULL`.

Treat `sync.db` as sensitive — payloads contain real customer data and Cronofy tokens. Local only, already covered by `.gitignore`'s `output/` rule. No scrub pass.

## Phased plan

### Phase 1 — Infrastructure (no behavior change)

**Done (2026-04-22).** `src/config.py` additions, `src/sync_log.py`, `src/sender.py` all landed.

- Add `MIDDLEWARE_URL`, `MIDDLEWARE_API_SECRET` to `src/config.py` and `.env.example`.
- New `src/sync_log.py` with the schema above plus `log_send()`, `update_status()`, `lookup(balo_id)`, `already_sent(balo_id, route)`.
- New `src/sender.py` with a `Sender` class: one method per middleware route, Bearer auth, 202 parsing, retry with exponential backoff on 5xx / network errors, configurable QPS throttle. `dry_run` flag logs without posting.

### Phase 2 — Transformer provenance

**Done (2026-04-22).** All six `transform_*` return `(columns, rows, provenance)`; `excel_writer.write_workbook` and `export.py` tolerant-unpack the 3-tuple.

- Change every `transform_*` in `src/transformer.py` to return `(columns, rows, provenance)` where `provenance[i]` is `[{table, _id, label}, ...]` for `rows[i]`.
- Update `transform_all()` to propagate the new tuple.
- Update `excel_writer.write_workbook()` to ignore the provenance element (XLSX doesn't need it).
- No new joins — the source `_id`s are already being read; just capture them explicitly as each row is built.

### Phase 3 — Fetcher rewrite

**Done (2026-04-22)** — except the `src/manifest.py` retirement, which is deferred because `export.py` still uses it for the XLSX scouting path.

- Add `Fetcher.fetch_all_historic(modified_since=None)` that enumerates every table via `fetch_all_pages` with no `max_pages` cap, optionally filtered by Bubble's `Modified Date > modified_since` constraint.
- Replace per-anchor FK queries with "fetch all rows of each table, resolve FKs locally from the loaded store." Faster, simpler, deterministic.
- Caveat for repeatable runs: a child record (e.g. a consultation) can be `modified_since` the cursor while its parent (e.g. client company) is not. The fetcher must still resolve parent FKs — do a second pass that pulls any referenced `_id` not already in the store via `fetch_record`, regardless of modified date.
- Keep existing `fetch_all()` sampling mode for the XLSX path.
- Retire `src/manifest.py` after Phase 4 lands — superseded by `sync.db`.

### Phase 4 — Sync orchestration

**Done (2026-04-22).** `sync.py` with seven subcommands + `--list`, shared `--limit` / `--dry-run` / `--since` / `--full` / `-v`. Cursor derives from `sync_runs.completed_at`; on `SenderError` the run aborts without marking `completed_at` so the cursor doesn't advance. Payload scrub is per-target allowlists built from `MIDDLEWARE_ENDPOINTS.md`. First-run backfill has not yet been executed against production.

- New `sync.py` entry: fetch → transform → send. Invoked **once per sync target**, not all at once.
- Seven subcommands, one per logical sync target:

  ```
  sync.py prospects           # POST  /crm/prospect                  (client users only)
  sync.py accounts            # PATCH /crm/account/:id               (client companies + agencies)
  sync.py contacts            # PATCH /crm/contact/:id               (expert users only)
  sync.py cases               # PATCH /crm/opportunity/case/:id
  sync.py projects            # PATCH /crm/opportunity/project/:id
  sync.py project-experts     # PATCH /crm/project-expert/:id
  sync.py consultations       # PATCH /crm/consultation/:id
  sync.py --list              # print subcommand → route mapping
  ```

- For transformers that fan out (`transform_prospects_contacts` serves both `prospects` and `contacts`), the subcommand selects the row subset using the `_contact_type` helper column. `accounts` sends both `CLIENT` and `AGENCY` rows without a filter — they share the route and queue order is handled by FIFO.
- Before each send, check `already_sent(balo_id, route)` in `sync.db` and skip. Free resume-on-crash and free "don't resend" on repeat runs.
- On each invocation, insert a `sync_runs` row at start and update `completed_at` at end. Next invocation of the **same subcommand** derives `modified_since` from the prior row's `completed_at`.
- Common flags (apply to every subcommand):
  - `--limit N` — stop after N records. Use for smoke-testing a phase before the full run.
  - `--dry-run` — fetch + transform + log to `sync.db` with `http_status=null`, but do not POST.
  - `--since <iso-datetime>` — override the auto-derived `modified_since` cursor.
  - `--full` — ignore the cursor, fetch everything (first run / re-backfill).

- Operator rollout for the initial historic backfill:

  ```
  # Phase 1 — Client signups
  sync.py prospects --limit 1 --full   # smoke
  sync.py prospects --full

  # Phase 2 — Accounts then Expert Contacts
  sync.py accounts --full              # client companies + agencies, FIFO within the wave
  sync.py contacts --full              # kick off after Accounts drain in middleware logs

  # Phase 3 — Child records
  sync.py cases --full
  sync.py projects --full
  sync.py project-experts --full
  sync.py consultations --full
  ```

  Subsequent repeatable runs drop `--full` and use the auto-derived `modified_since` cursor.

### Phase 5 — Inspection CLI

**Done (2026-04-22).** `inspect.py` supports `<balo_id>`, `--status pending|landed|failed`, and `<balo_id> --refetch` (Bubble refetch + drift flag against event `ts`).

- `inspect.py <balo_id>` → show sync.db row: route, ts, http_status, job_id, full payload (pretty), source table list.
- `inspect.py --status failed` / `--status pending` → list.
- `inspect.py <balo_id> --refetch` → pull current state of each source record from Bubble and diff against the logged payload (answers "has the data drifted since we sent?").

## Explicitly out of scope

- Polling middleware for terminal SF status. `sf_status` stays `pending`; update manually when a failure is reported, or build a reconciler later if it hurts.
- Parallel sends. Single-threaded is fine at this scale; revisit only if total runtime becomes painful.
- Automated multi-phase execution. Operator runs `sync.py` one phase at a time; no orchestrator that runs all three in sequence with inter-phase waits.
- Scrubbing sensitive fields from logged payloads (decided against — single-user local tool).

## Suggested order of work

Phases 1 → 2 → 3 can land as three independent commits with no user-visible change. Phase 4 is where `sync.py` first runs end-to-end — test against a single record (`--limit 1 --only /crm/account/:id`) before unleashing it on the full DB.

## What survives unchanged

- Bubble API client (`src/api_client.py`) — paging, rate-limit backoff, auth.
- Field-mapping constants and option-set helpers in `src/config.py`.
- Transformer logic bodies — only the return shape changes.
- XLSX writer (`src/excel_writer.py`) — adjusted to ignore provenance, otherwise untouched.
