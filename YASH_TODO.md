# Bubble-side changes for Yash

Notes for Yash on what needs to change in the Bubble app + real-time webhook
flows that POST to the `sf-middleware-api`. The Python historic sync handles
these transformations server-side, but real-time Bubble payloads bypass the
transformer and hit the middleware directly — so Bubble flows need their own
fixes for parity.

> Maintained by Yomi/Claude as new issues come up. Last updated: 2026-06-19 (#2).

---

## Outstanding for Nick (Salesforce side)

### `Product: bad value for restricted picklist: marketing-cloud-next` (2026-06-19)

A project upsert was rejected because `marketing-cloud-next` isn't in the
`Opportunity.Product__c` picklist. Bubble's product picklist now includes
`marketing-cloud-next` (separate from legacy `marketing-cloud`). Add the
value to the SF picklist (and any related global value set if applicable).

Example payload: project `1781745425148x856406945571799000`
("Marketing Cloud Deployment"), `"Product__c": "marketing-cloud-next"`.

### `ENTITY_IS_DELETED` on `/crm/prospect` for Salesforce-the-company users (2026-06-19)

Two `@salesforce.com` prospects failed with SF 500 in `ProspectAPI.upsertProspect`
line 111:
- Ash Panesar (apanesar@salesforce.com) — Apex `accountId: 001On00000geEosIAE`
- Dishan de Silva (dishan.desilva@salesforce.com) — Apex `accountId: 001On00000geHDFIA2`

```
ENTITY_IS_DELETED, entity is deleted: [] | Class.ProspectAPI.upsertProspect: line 111, column 1
```

Both have `companyName: "Salesforce"`. Looks like the Apex finds an existing
SF Account by some match key, then the subsequent UPDATE on that Account
fails because the Account is in the recycle bin. Nick to investigate
(undelete or change match logic to skip soft-deleted records).

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

### Account.Balo_Id__c not findable after successful upsert (2026-06-01)

After a full project resync we observed ~17 accounts that show **green "SF sync
succeeded"** in #sf-sync-activity, but a subsequent project upsert referencing
the same `Account.Balo_Id__c` value gets `Foreign key external ID: X not found
for field Balo_Id__c in entity Account`.

Example: Account `1778806386672x253092788506382500` (Salesforce / sarah.hunter)
- 2026-06-01 20:10:21 AEST — PATCH /crm/account/:id returned 2xx (green Slack)
- 2026-06-01 20:14:50 AEST — Project upsert references same Balo_Id__c → 4xx
  "not found for field Balo_Id__c in entity Account"

Hypothesis: a Salesforce flow / trigger / dedup-match-policy on Account is
either overwriting `Balo_Id__c` after our upsert, or causing the upsert to
merge into an existing record without preserving the external ID. **Needs
Nick to investigate** — likely related to his recent SF flow changes.

Affected company UIDs (sample): 1739931484647x... (Salesforce - paige.ward),
1778806386672x... (Salesforce - sarah.hunter), 1779260790400x... (Salesforce -
paige.ward), several more.

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
- **Don't push CLIENT account upserts for expert-self-companies.** A company
  qualifies as a real client only if at least one user has a client role
  (`client-admin`/`client-staff`/`client-guest`) AND no expert role. Dual-role
  users (e.g. `freelance-expert` + `client-admin`) don't count — those are
  experts who toggled a client role on their own auto-generated company.
  The Python sync now filters these out (2026-06-19) but the Bubble real-time
  flow still POSTs them. Add the same gate in Bubble before calling
  `PATCH /crm/account/:id`.

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
