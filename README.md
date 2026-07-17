# balo-salesforce-export

Balo Bubble.io data export and Salesforce sync tool. Fetches data from Bubble's Data API,
transforms it into Salesforce-compatible payloads, and either generates Excel spreadsheets
for review or syncs live to Salesforce through the sf-middleware-api.

**This tool also serves as a foundation for future data migration** from Bubble to the
new Balo platform (Next.js + Postgres). The fetcher enumerates every Bubble table with
full FK resolution, and the transformer maps all field names — swap the SF output for
SQL inserts when the time comes.

---

## Two entry points

### 1. `export.py` — Excel export (for review)

Generates a multi-sheet XLSX workbook with all SF payloads laid out for developer review.
Used during initial Salesforce integration setup to validate field mappings.

```bash
python export.py                              # auto-select top companies
python export.py --companies ID1,ID2,ID3      # specific companies
python export.py --output ~/Desktop/test.xlsx  # custom output path
python export.py --dry-run --verbose           # fetch + transform, no file
```

Output: `output/Balo_SF_Test_Data.xlsx`

### 2. `sync.py` — Live Salesforce sync

Syncs Bubble data to Salesforce through the sf-middleware-api. Supports incremental
syncs (cursor-based) and full backfills.

```bash
python sync.py --list                # show all targets
python sync.py prospects --full      # initial backfill
python sync.py accounts --full       # initial backfill
python sync.py contacts --full       # initial backfill
python sync.py cases --full
python sync.py projects --full
python sync.py project-experts --full
python sync.py consultations --full
```

**Flags:**
- `--full` — ignore cursor, fetch everything (use for initial backfill)
- `--limit N` — stop after N successful sends
- `--dry-run` — fetch + transform + log, but don't POST to middleware
- `--since <iso>` — override the auto-derived cursor
- `-v, --verbose` — print every API call

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in values (see Environment Variables below)
```

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `BALO_API_TOKEN` | Yes | — | Bubble.io Data API token |
| `MIDDLEWARE_URL` | For sync | `https://sf-middleware-api-production.up.railway.app` | sf-middleware-api base URL |
| `MIDDLEWARE_API_SECRET` | For sync | — | Bearer token for middleware auth |
| `BALO_COMPANY_IDS` | No | — | Comma-separated company IDs (export.py only) |
| `BALO_AGENCY_IDS` | No | — | Comma-separated agency IDs (export.py only) |

---

## Sync targets and execution order

Run in this order — each step depends on the previous (foreign keys must exist in SF).

| # | Command | SF Object | What it does |
|---|---------|-----------|-------------|
| 1 | `python sync.py prospects --full` | Prospect + Account + Contact | Creates client users + their company Accounts via Apex |
| 2 | `python sync.py accounts --full` | Account | Updates Accounts with Stripe IDs, flags. Creates agency + freelance Accounts |
| 3 | `python sync.py contacts --full` | Contact | Updates expert Contacts with certifications, ratings, LinkedIn, etc. |
| 4 | `python sync.py cases --full` | Opportunity (Case) | Case opportunities linked to Accounts + Contacts |
| 5 | `python sync.py projects --full` | Opportunity (Project) | Project opportunities with conditional stage logic |
| 6 | `python sync.py project-experts --full` | Project__c | Expert-to-Opportunity links (EOI status) |
| 7 | `python sync.py consultations --full` | Consultation__c | Meetings with billing, duration, cancellation data |

---

## Filtering decisions

Each target filters rows before sending. Reasons are captured in the audit report.

### Prospects (client signups)
- **Not a CLIENT row** — experts are synced separately via contacts
- **Has expert/admin role** — user has `agency-expert`, `freelance-expert`, `agency-admin`,
  or `admin` in their Roles. Their associated company is a dummy Bubble record
- **Blocked test email** — matches `@revido.io`, `ylinkz`, or `yomi@getbalo.com`

### Accounts (companies + agencies + freelance)
- **Blocked admin email** — same email patterns as above
- **No real client users** — CLIENT company where ALL users have expert/admin roles.
  These are dummy companies auto-created by Bubble for experts. A company passes if at
  least one user has pure client roles. Agencies and freelance synthetic accounts always pass.

### Contacts (expert profiles)
- **Not an EXPERT row** — client users already created by prospect Apex endpoint
- **No expert role in user Roles** — has an expert profile in Bubble but no expert role
  (data integrity issue in Bubble)
- **Profile not approved** — `Application_Status__c` must be `approved`. Excludes
  `started`, `submitted`, `waitlisted`, `rejected`
- **Blocked test email** — same patterns

### Cases / Projects
- **Empty Name** (projects only) — incomplete draft requests with no title

### Project Experts
- **Missing composite Balo_Id__c** — can't construct the `{request_id}-{expert_user_id}` key

### Consultations
- No additional filters (all meetings synced)

---

## Audit reports

Every sync run generates a Markdown report at `output/reports/<target>_<date>_<time>.md`.

Each report contains:
- **Summary** — counts for sent, filtered, skipped, errors
- **Filtered** — every dropped row with full Balo ID, name, and the specific reason
- **Sent** — every sent row with Balo ID, name, middleware job ID, HTTP status
- **Skipped** — rows already sent in a previous run (dedup)
- **Errors** — middleware failures with status and response
- **Warnings** — missing FK parents from the fetcher

Use these to cross-validate against Bubble after each step.

---

## Deduplication and cursors

- **sync.db** (SQLite) tracks every send attempt with HTTP status and job ID
- Rows that got `202 Accepted` are skipped on subsequent runs (idempotent)
- Each target's cursor is the `started_at` of its most recent completed run
- `--full` ignores the cursor (full backfill)
- If a run fails mid-way, the cursor doesn't advance — safe to re-run

To start completely fresh:
```bash
rm output/sync.db
```

---

## How the data flows

```
Bubble.io Data API
       |
       v
  src/fetcher.py          Fetches all tables, resolves FK parents (BFS)
       |
       v
  src/transformer.py      Maps Bubble fields → SF payload format
       |
       +---> export.py     Writes Excel (openpyxl) for review
       |
       +---> sync.py       Filters → builds payload → sends to middleware
                |
                v
           src/sender.py   POST/PATCH to sf-middleware-api (with retries)
                |
                v
         sf-middleware-api  Queues in BullMQ → forwards to Salesforce
                |
                v
           Salesforce
```

---

## Key technical decisions

### Why a middleware, not direct SF calls?
Bubble's backend workflows are unreliable for direct API calls. The middleware provides
queuing (BullMQ), retries with exponential backoff, structured logging (Axiom), and
Slack notifications. Bubble fires and forgets; the middleware handles reliability.

### Empty strings vs null vs omit
- **PATCH routes:** empty strings `""` are sent as-is (SF interprets as "clear this field")
- **`omit_if_empty`:** specific fields are dropped when empty — used for foreign key
  references that SF would try to resolve (e.g. `Account.Balo_Id__c` for freelancers)
- **`nullify_empty_strings`:** converts `""` to `null` in JSON — used only for the
  `/crm/prospect` Apex endpoint, which 500s on empty strings but accepts null
- **`defaults`:** fallback values for required fields (e.g. `CloseDate` defaults to
  today + 365 days on Opportunity)

### Dot-notation to nested objects
SF REST API requires relationship fields as nested objects. The transformer produces
flat keys like `Account.Balo_Id__c`. The `_build_payload` function automatically converts
these to `{"Account": {"Balo_Id__c": "..."}}`.

### Unicode sanitization
The middleware strips invisible Unicode characters (U+200E, U+FEFF, etc.) from all
payload strings before forwarding to SF. Bubble text fields sometimes embed these,
which break SF Apex date parsers.

### Concurrency
The middleware processes one job at a time (BullMQ concurrency = 1) to prevent SF upsert
race conditions. Two concurrent upserts on the same Account by external ID can cause
duplicate value errors even with proper UPSERT logic.

### baloRoles as JSON array
The SF Apex `/crm/prospect` endpoint expects `baloRoles` as a JSON array, not a
semicolon-delimited string. The transformer uses `list_array_slugs()` for API payloads
and `join_array_slugs()` for Excel output.

---

## Future: Bubble → Postgres migration

This tool is a strong starting point for migrating Balo data from Bubble to the new
Next.js + Postgres stack. What's reusable:

- **`src/fetcher.py`** — enumerates every Bubble table with full FK resolution. The
  `fetch_all_historic()` method pulls all records with a BFS pass to resolve missing
  parents. Swap the SF transformer for Prisma creates / SQL inserts.
- **`src/api_client.py`** — Bubble Data API client with rate limiting, retries, and
  pagination. Works for any Bubble table.
- **`src/config.py`** — all 13 Bubble table paths (emoji-encoded), field name helpers,
  option set slug/display extractors.
- **`FIELD_MAPPING.md`** — complete field-by-field mapping reference.
- **`balo-bubble-data-api-swagger.json`** — full OpenAPI spec for Bubble's Data API.

The migration would:
1. Keep the fetcher and API client as-is
2. Replace `src/transformer.py` with a Postgres schema mapper
3. Replace `src/sender.py` with direct database writes (Prisma or psycopg2)
4. Keep the audit report system for migration validation

---

## Project structure

```
balo-salesforce-export/
  export.py                  # Excel export entry point
  sync.py                    # Salesforce sync entry point (7 targets)
  requirements.txt           # Python dependencies
  .env.example               # Environment variable template
  src/
    config.py                # Env vars, Bubble table paths, SF constants
    api_client.py            # Bubble Data API HTTP client
    fetcher.py               # DataStore + Fetcher (5-round + historic fetch)
    transformer.py           # 6 transform functions (Bubble → SF payloads)
    sender.py                # Middleware HTTP client (POST/PATCH with retries)
    sync_log.py              # SQLite sync.db (dedup + cursor tracking)
    excel_writer.py          # XLSX generation (openpyxl)
    manifest.py              # Export manifest tracking (export.py only)
  output/
    sync.db                  # SQLite dedup database (auto-created)
    reports/                 # Per-run Markdown audit reports (auto-created)
  docs/
    MIDDLEWARE_ENDPOINTS.md   # Middleware route → SF target mapping
    FIELD_MAPPING.md          # Bubble field → SF field reference
    EXPORT_FORMAT.md          # Excel output format spec
    REFACTOR_PLAN.md          # Sync refactor design notes
```

---

## Related repos

- **[sf-middleware](https://github.com/yomi-balo/balo-sf-middleware)** — Fastify service
  that sits between this tool (and Bubble) and Salesforce. Handles auth, queuing, retries,
  and Slack notifications.
