# Bubble-side changes for Yash

Notes for Yash on what needs to change in the Bubble app + real-time webhook
flows that POST to the `sf-middleware-api`. The Python historic sync handles
these transformations server-side, but real-time Bubble payloads bypass the
transformer and hit the middleware directly — so Bubble flows need their own
fixes for parity.

> Maintained by Yomi/Claude as new issues come up. Last updated: 2026-05-27.

---

## Outstanding for Nick (Salesforce side)

### `Prospect upsert failed: bad value for restricted picklist field: Bad Data`

The `/crm/prospect` Apex endpoint started rejecting some new client-admin
prospects (2026-05-26 onwards) with the above error. Example users affected:
- Lewin Ellis (lewin@accessaccom.com.au, Bubble user
  `1779770026822x368870255722896200`)
- Daniel Witherington (daniel.witherington@thetransformationgroup.com.au)

Payloads look identical in shape to earlier successful prospects (same roles,
same `accountType: Prospect`). The literal `"Bad Data"` in the error message
suggests either an actual picklist value of "Bad Data" being sent somewhere,
or a generic error string in the Apex. Needs Nick to debug.

### Silent SF failures with HTTP 202 ack from middleware

Throughout the backfill we've found records where the middleware returned
HTTP 202 (job queued) but the actual SF upsert silently failed without ever
making it to sync.db's `sf_status`. Currently we only catch these when a
downstream FK lookup fails. **Improve middleware/worker so the final SF
status (success/failure) is propagated back to sync.db** so we can detect
orphans proactively instead of via cascade.

---

## 1. Real-time payload normalization

### 1.1 Cases — `PATCH /crm/opportunity/case/:id`

The middleware now applies safety-net transforms (route-scoped) so Bubble
payloads can leak slightly without breaking SF. But ideally Bubble sends the
canonical values directly.

- **Field name:** rename `Type_Of_Support__c` → `Type_of_Support__c`
  (lowercase `of`). SF schema is case-sensitive on field rename.
- **StageName casing:** send Title-case picklist value (`"Ongoing"`,
  `"Closed Won"`, etc.) — not the Bubble slug (`"ongoing"`).
- **`Amount` field:** should be the **gross** total (Total credits used /
  what the client paid). Not `Total amount earned` (which is the expert net).
- **Add `Expert_Earnings__c`** field to the payload. Source: case's
  `Total amount earned` (or sum of consultation `Amount` fields).
- **No `Type` field on client Account upserts** — the prospect Apex flow sets
  it correctly on first creation; we don't want to overwrite later.

### 1.2 Consultations — `PATCH /crm/consultation/:id`

- **`Opportunity__r.Balo_Case_Number__c`**, NOT `Opportunity__r.Balo_Id__c`.
  Case Opportunities in SF are keyed by `Balo_Case_Number__c`
  (e.g. `"LEA-60666"`), so the FK must use that field. The Bubble case has
  the Case ID — use it directly in the relationship payload.
- **Project meetings — `Project__r.Balo_Id__c`** must be the composite
  `{project_request_uid}-{expert_user_uid}`, **not** `{project_uid}-...`.
  The SF Project__c (project-expert) record is keyed by the request UID,
  not the project UID. If only the project is available on the meeting,
  resolve `project.Project Request` to get the request UID first.
- **`Participants_Present__c`** must be `true` or `false` (boolean), never
  `null`. For meetings without a Bubble `Summary Present [Temp]` value
  (missed / cancelled), default to `false`.

### 1.3 Contacts — `PATCH /crm/contact/:id`

- Drop `Is_Salesforce_Certified__c` from the payload (no longer in SF schema
  per Nick).
- Add `Balo_Role__c` — string of the user's primary active role
  (e.g. `"freelance-expert"`).
- **Add `Balo_Roles__c`** as a **semicolon-separated string**, NOT a JSON
  array. Example: `"freelance-expert;client-admin;client-staff"`.
  (Note: this differs from `/crm/prospect` where `baloRoles` IS still an
  array — those go to the Apex endpoint which expects an array.)
- Add `Description` — expert's bio (Bubble field: `expert.Profile Description`).

### 1.4 Accounts (clients) — `PATCH /crm/account/:id`

- **Do NOT send `Type`** for CLIENT company upserts. The prospect Apex flow
  sets it correctly when creating the Account; our subsequent account updates
  should preserve that value.
- AGENCY and FREELANCE-EXPERT synthetic accounts can still send `Type`
  (those aren't created by the prospect flow).

### 1.5 Project-Experts — `PATCH /crm/project-expert/:id`

- **`Pricing_Method__c`** — send the SF picklist value, not the Bubble slug:
  - `"hourly"` → `"Times & Materials"`
  - `"fixed"` → `"Fixed Price"`
- **`Payment_Terms__c`** — send human-readable string composed from
  `Payment Structure` + `Upfront Percentage`:
  - `full-on-project-completion` → `"100% upon completion"`
  - `full-upfront` → `"100% upfront"`
  - `custom-upfront` with `Upfront Percentage = 0.5` → `"50% upfront and 50% upon completion"`
  - Same pattern for 25%, 30%, 70%, etc.

### 1.6 Multipicklist + Date conventions

- All **multipicklist** SF fields expect **semicolon-separated strings**,
  not arrays (only the Apex `/crm/prospect` endpoint accepts arrays).
- **Date-only SF fields** (e.g. `CloseDate`, `Finalized_Date__c`,
  `EOI_Submitted_Date__c`, `Estimated_Completion_Date__c`,
  `Submitted_Date__c`) should be sent as a Sydney-local `YYYY-MM-DD` date
  string. Sending UTC ISO datetimes causes SF to truncate using UTC and
  display a date one day earlier in AEST. The middleware does NOT currently
  apply this conversion — only the Python sync does.

---

## 2. Bubble data quality / backfill

### 2.1 Missing `Client Company` on project_requests

~28 of 519 project_requests in Bubble have no `Client Company` field set:

- **7 manual-mode** with real-looking titles (Cin7 integration, Testing
  Anonymous user, Reporting support, Salesforce Maps Improvement, etc.)
- **21 AI-mode** mostly titleless drafts

These create orphan Opportunities in SF (no Account linked). Either backfill
the Client Company on those records or update the Bubble flow that creates
project_requests so Client Company is mandatory.

### 2.2 `Title (Manual)` empty on manual-mode project_requests

A handful of manual-mode project_requests have a value in `Title (Final)` but
NOT in `Title (Manual)`. Our transformer now falls back to `(Final)` so these
get rescued, but ideally the Bubble flow should populate both consistently.

### 2.3 EOI "Modified Date" used as Finalized Date proxy

We currently treat `eoi.Modified Date` as the acceptance date when
`eoi.Status == 'finalized'`. This is a proxy — Modified Date changes on ANY
later edit to the EOI.

**Ask:** add an explicit `Date: Finalized` (or `Date: Accepted`) timestamp
field on the EOI object that's set once when the client accepts, and stays
fixed thereafter.

### 2.4 `Summary Present [Temp]` field on meetings

The Bubble field is called `Summary Present [Temp]` — the `[Temp]` suffix
suggests it's a temporary/placeholder field. Confirm whether there's a
canonical field name (or rename it to drop `[Temp]`). Currently used for
`Participants_Present__c` in SF.

---

## 3. Decisions still pending (Yomi)

- **`yomi@getbalo.com` blocked-email Primary_Contact orphans** — 3
  projects (Slack Setup, Service Cloud Foundations, Testing MC Next)
  reference yomi as `Primary_Contact__r`. Since yomi is in
  `BLOCKED_EMAIL_PATTERNS`, the Contact never lands in SF and these
  projects can't link. Options:
  1. Remove yomi@getbalo.com from `BLOCKED_EMAIL_PATTERNS`
  2. Filter projects with blocked Primary_Contact users out of the sync
  3. Accept the orphan
