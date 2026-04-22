# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

One-off Python CLI that pulls a coherent slice of Balo's Bubble.io Data API, maps Bubble fields to the Salesforce API payload shapes used by the `sf-middleware-api`, and writes a single annotated XLSX so devs can hand-craft Salesforce API / middleware test calls. `FIELD_MAPPING.md` and `MIDDLEWARE_ENDPOINTS.md` are the authoritative mapping specs — the transformer exists to implement them, so when mapping questions come up, read those first rather than inferring from code.

## Commands

```bash
# First-time setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit to add BALO_API_TOKEN

# Default run — auto-scouts 3 data-rich companies + 3 agencies, writes output/Balo_SF_Test_Data.xlsx
python export.py

# Targeted run — export specific records by Bubble _id
python export.py --companies ID1,ID2 --agencies ID3

# Fast iteration while debugging transformers — fetches + transforms but skips the XLSX write
python export.py --dry-run --verbose

# Custom output path
python export.py --output path/to/file.xlsx
```

No test suite, no linter, no build. Running `python export.py --dry-run -v` against the live API is the only smoke test.

## Architecture

The pipeline is four sequential phases driven by `export.py`:

1. **Fetch** (`src/fetcher.py`) — `Fetcher.fetch_all()` executes five rounds in a fixed order that encodes the FK graph: `_round1_anchors` (companies, agencies, countries) → `_round2_users_experts` → `_round3_cases_projects` (requests + finalized projects + EOIs) → `_round4_meetings` (plus linked consultations / project-meetings) → `_round5_packages`. Each round's output is what the next round needs — don't reorder.
2. **Transform** (`src/transformer.py`) — `transform_all()` calls one `transform_*` per output sheet. Each returns `(columns, rows)` where `columns` is the ordered header list and `rows` is a list of dicts. Rows may be "separator" markers (`{"_is_separator": True, "_label": ...}`) that the writer styles as section headers.
3. **Write** (`src/excel_writer.py`) — `write_workbook()` emits a README sheet plus one sheet per transformer. Columns starting with `_` (e.g. `_group`, `_source_stage`, `_meeting_type`) are dev-only helpers styled with a grey fill; they are documented as "don't send to SF" in the README sheet.
4. **Manifest** (`src/manifest.py`) — `save_manifest()` appends this run to `output/export_manifest.json`. On the next run, `get_exported_ids()` reads the manifest so auto-scouting skips companies/agencies already exported, keeping successive runs diverse.

### DataStore — the shape the transformer expects

`Fetcher` populates a single `DataStore` (see `src/fetcher.py:7`). The split between list and dict fields is load-bearing:

- **Lists** (order preserved, iteration is the output order): `clientcompanies`, `agencies`, `cases`, `project_requests`, `project_eois`, `meetings`.
- **Dicts keyed by `_id`** (random-access lookups from FKs): `users`, `experts`, `countries`, `projects`, `consultations`, `projectmeetings`, `packages`.

Transformers assume this layout — if you add a new entity, match the pattern of its siblings rather than inventing a new one.

### Bubble API quirks baked into the client

`src/api_client.py` hides several Bubble-specific behaviors that matter when extending fetch logic:

- Table paths in `src/config.py` `TABLE_PATHS` are URL-encoded emoji names (e.g. `👥profile:clientcompany`). Always route through `TABLE_PATHS[key]`, never hardcode a path.
- Global 1s delay between requests plus exponential backoff on `429`; `400` and `404` return `None` rather than raising, so callers must tolerate missing records.
- `fetch_all_pages` uses Bubble's `cursor`/`remaining` paging convention — don't substitute offset arithmetic.
- Auth is `?api_token=<token>` as a query param, not a header.

### Transformer conventions

- Option-set values arrive as `{"slug": ..., "display": ...}` dicts or bare strings. Use `get_slug` / `get_display` / `join_array_slugs` (`src/config.py`) — don't access `.slug` directly.
- Option fields whose value depends on the request's `Mode` (AI / Manual / Final) are resolved with `_smart_field` in `src/transformer.py:43`. When adding mode-dependent fields, go through this helper.
- `SENSITIVE_FIELDS` in `src/config.py` lists Cronofy tokens and similar that must never hit output; use `_redact` if you pass a raw record through.
- Salesforce `RecordTypeId` constants live in `src/config.py`. `RECORD_TYPE_PROJECT_OPPORTUNITY` is explicitly flagged `# FLAG FOR NICK` pending confirmation — surface any further flags the same way so the README sheet can highlight them.
- The output sheet order in `src/excel_writer.py` `sheet_order` must match the keys returned by `transform_all` in `src/transformer.py` — if you add a sheet, update both.

## Reference docs in this repo

- `REFACTOR_PLAN.md` — in-progress plan to extend this tool from XLSX-export into a full historic Bubble→middleware→Salesforce sync with SQLite sync log and `inspect.py` CLI. Read this first if the task involves sync, sender, sync.db, or provenance logging.
- `FIELD_MAPPING.md` — canonical Bubble-field → Salesforce-field mapping per endpoint. Source of truth for transformer logic.
- `MIDDLEWARE_ENDPOINTS.md` — maps each `transform_*` function to the `sf-middleware-api` route it feeds. Consult when the tool is extended to POST through the middleware instead of emitting XLSX.
- `EXPORT_FORMAT.md` — describes the legacy 6-CSV layout; the current tool emits one XLSX with equivalent sheets.
- `Balo - Salesforce Integration.postman_collection (3).json` and `balo-bubble-data-api-swagger.json` — external API specs (SF target and Bubble source respectively).
