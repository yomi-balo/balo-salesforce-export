# Middleware Endpoint Reference

This document maps every sf-middleware route to its Salesforce target, and maps each
transformer function in this export tool to the middleware endpoint it should call.

**Purpose:** When refactoring this tool to send data through the middleware (instead of
directly to Salesforce), use this as the single source of truth for URL construction,
HTTP methods, and payload shapes.

**Middleware base URL:** `https://sf-middleware-api-production.up.railway.app`

**Auth:** Every request must include `Authorization: Bearer <MIDDLEWARE_API_SECRET>`.

**Response:** All routes return `202 Accepted` with `{ "accepted": true, "jobId": "..." }`.
The middleware queues the job and forwards to Salesforce asynchronously.

---

## Quick Reference

| # | Middleware Route | Method | SF Object | SF External ID | Transformer Function |
|---|---|---|---|---|---|
| 1 | `/crm/prospect` | POST | Prospect__c + Account + Contact (Apex) | N/A | `transform_prospects_contacts` |
| 2 | `/crm/account/:id` | PATCH | Account | `Balo_Id__c` | `transform_accounts` |
| 3 | `/crm/contact/:id` | PATCH | Contact | `Balo_Id__c` | `transform_prospects_contacts` |
| 4 | `/crm/lead/:id` | PATCH | Lead | `Balo_Id__c` | *(not currently used by this tool)* |
| 5 | `/crm/opportunity/case/:id` | PATCH | Opportunity | `Balo_Case_Number__c` | `transform_opportunities_cases` |
| 6 | `/crm/opportunity/project/:id` | PATCH | Opportunity | `Balo_Id__c` | `transform_opportunities_projects` |
| 7 | `/crm/booking/:id` | POST | Opportunity | `Balo_Id__c` | *(same SF target as #6 — used by Bubble, not this tool)* |
| 8 | `/crm/project-expert/:id` | PATCH | Project__c | `Balo_Id__c` | `transform_project_experts` |
| 9 | `/crm/consultation/:id` | PATCH | Consultation__c | `Balo_Id__c` | `transform_consultations` |

---

## Endpoint Details

### 1. POST /crm/prospect

**What it does:** Creates Prospect__c, Account, and Contact atomically via Apex REST.

**SF target:** `POST /services/apexrest/Prospect/`

**Transformer:** `transform_prospects_contacts` -> `_build_client_prospect_row` / `_build_expert_prospect_row`

**How to call from Python:**
```python
requests.post(
    f"{MIDDLEWARE_URL}/crm/prospect",
    headers={"Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"},
    json=payload,
)
```

**Payload — Client user:**
```json
{
  "baloId": "<user._id>",
  "email": "<user.email>",
  "firstName": "<user.Name: First>",
  "lastName": "<user.Name: Last>",
  "phone": "<user.Phone>",
  "baloRole": "<user.Role: Active slug>",
  "baloRoles": "<semicolon-joined slugs>",
  "prospectStatus": "Signed Up",
  "signupDate": "<user.Created Date>",
  "timezone": "<user.Timezone ID>",
  "currencyCode": "<user.Currency display>",
  "country": "<resolved country Name>",
  "baloAccountId": "<company._id>",
  "companyName": "<company.Name>",
  "accountType": "Company",
  "baloAccountCreatedDate": "<company.Created Date>"
}
```

**Payload — Expert (agency):**
Same as above, but with:
- `baloAccountId` = agency._id
- `accountType` = "Expert"
- `companyName` = agency Name

**Payload — Expert (freelance):**
Same as above, but `baloAccountId`, `companyName`, `accountType`, and
`baloAccountCreatedDate` are **omitted** (not sent as empty strings — omitted entirely).

**Note:** The prospect endpoint only handles the initial signup fields. Expert-specific
fields (certifications, ratings, etc.) are sent separately via `PATCH /crm/contact/:id`.

---

### 2. PATCH /crm/account/:id

**What it does:** Upserts an Account by `Balo_Id__c`.

**SF target:** `PATCH /services/data/v65.0/sobjects/Account/Balo_Id__c/{id}`

**`:id` param:** The `Balo_Id__c` value (company._id or agency._id).

**Transformer:** `transform_accounts`

**How to call from Python:**
```python
requests.patch(
    f"{MIDDLEWARE_URL}/crm/account/{balo_id}",
    headers={"Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"},
    json=payload,
)
```

**Payload — Client company:**
```json
{
  "Name": "<company.Name>",
  "Phone": "<admin user.Phone>",
  "Website": "",
  "Type": "Company",
  "AccountSource": "Balo Sourced",
  "Stripe_Customer_Id__c": "<company.Stripe: Customer ID>",
  "Has_Booked_Consultation__c": true,
  "Has_Redeemed_Credits__c": false,
  "Has_Submitted_Project__c": true,
  "Balo_Created_Date__c": "<company.Created Date>",
  "Stripe_Seller_ID__c": "",
  "Stripe_Connection_Status__c": ""
}
```

**Payload — Agency:**
```json
{
  "Name": "<agency.Name>",
  "Phone": "<admin user.Phone>",
  "Website": "<agency.Website>",
  "Type": "Expert",
  "AccountSource": "Balo Sourced",
  "Stripe_Customer_Id__c": "",
  "Has_Booked_Consultation__c": "",
  "Has_Redeemed_Credits__c": "",
  "Has_Submitted_Project__c": "",
  "Balo_Created_Date__c": "<agency.Created Date>",
  "Stripe_Seller_ID__c": "<agency.Stripe: Seller ID>",
  "Stripe_Connection_Status__c": "<agency.Stripe: Connection Active>"
}
```

**Important:** Do NOT include `Balo_Id__c` in the body — it's in the URL only (SF requirement for upsert by external ID).

---

### 3. PATCH /crm/contact/:id

**What it does:** Upserts a Contact by `Balo_Id__c`.

**SF target:** `PATCH /services/data/v65.0/sobjects/Contact/Balo_Id__c/{id}`

**`:id` param:** The user._id (not the expert profile _id).

**Transformer:** `transform_prospects_contacts` -> `_build_expert_prospect_row` (Contact-specific fields)

**How to call from Python:**
```python
requests.patch(
    f"{MIDDLEWARE_URL}/crm/contact/{user_id}",
    headers={"Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"},
    json=payload,
)
```

**Payload — Expert contact:**
```json
{
  "RecordTypeId": "012On00000LYlI9IAL",
  "Expert_Type__c": "<expert.Expert type slug>",
  "Is_Salesforce_Certified__c": true,
  "Is_CTA__c": false,
  "Is_MVP__c": false,
  "Salesforce_Start_Year__c": "2018",
  "Years_Experience__c": "8",
  "Project_Count_Range__c": "<slug>",
  "Consultation_Min_Rate__c": 2.50,
  "Average_Rating__c": 4.8,
  "Total_Reviews__c": 23,
  "LinkedIn_URL__c": "https://...",
  "Trailblazer_URL__c": "https://...",
  "Headline__c": "<expert.Profile Headline>",
  "Application_Status__c": "<slug>",
  "Expert_Unique_ID__c": "<expert._id>",
  "Cronofy_User_ID__c": "<expert.Cronofy User ID>",
  "MailingCountry": "<Alpha-2 code>",
  "Account.Balo_Id__c": "<agency._id>"
}
```

**Payload — Client contact:**
```json
{
  "RecordTypeId": "012On00000LYdFm",
  "Balo_Role__c": "<user.Role: Active slug>",
  "Account.Balo_Id__c": "<company._id>"
}
```

**Note:** `Account.Balo_Id__c` is omitted for freelance experts (no agency).

---

### 4. PATCH /crm/lead/:id

**What it does:** Upserts a Lead by `Balo_Id__c`.

**SF target:** `PATCH /services/data/v65.0/sobjects/Lead/Balo_Id__c/{id}`

**Not currently used by the export tool.** This route exists in the middleware for
Bubble's direct lead upserts. Included here for completeness.

---

### 5. PATCH /crm/opportunity/case/:id

**What it does:** Upserts a Case Opportunity by `Balo_Case_Number__c`.

**SF target:** `PATCH /services/data/v65.0/sobjects/Opportunity/Balo_Case_Number__c/{id}`

**`:id` param:** The case's `Case ID` field (NOT the case._id).

**Transformer:** `transform_opportunities_cases`

**How to call from Python:**
```python
case_number = row["Balo_Case_Number__c"]
requests.patch(
    f"{MIDDLEWARE_URL}/crm/opportunity/case/{case_number}",
    headers={"Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"},
    json=payload,
)
```

**Payload:**
```json
{
  "Name": "<case.Title>",
  "CloseDate": "",
  "StageName": "<case.Status slug>",
  "RecordTypeId": "012On00000L9nDVIAZ",
  "Description": "<case.Description>",
  "Total_Consultation_Minutes__c": 120,
  "Total_Credits_Used__c": 5,
  "Amount": 450.00,
  "Balo_Created_Date__c": "<case.Created Date>",
  "Product__c": "sales-cloud;service-cloud",
  "Type_Of_Support__c": "implementation;consulting",
  "Account.Balo_Id__c": "<company._id>",
  "Primary_Contact__r.Balo_Id__c": "<client user._id>",
  "Expert__r.Balo_Id__c": "<expert user._id>"
}
```

**Important:** The `:id` in the URL is `Balo_Case_Number__c` (the human-readable Case ID),
NOT `Balo_Id__c`. This is different from all other upsert routes.

---

### 6. PATCH /crm/opportunity/project/:id

**What it does:** Upserts a Project Opportunity by `Balo_Id__c`.

**SF target:** `PATCH /services/data/v65.0/sobjects/Opportunity/Balo_Id__c/{id}`

**`:id` param:** The project request._id.

**Transformer:** `transform_opportunities_projects`

**How to call from Python:**
```python
requests.patch(
    f"{MIDDLEWARE_URL}/crm/opportunity/project/{request_id}",
    headers={"Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"},
    json=payload,
)
```

**Payload (finalized project):**
```json
{
  "Name": "<project.Project title>",
  "CloseDate": "<project.Estimated Completion Date>",
  "StageName": "Project",
  "Sub_status__c": "<project.Status slug>",
  "RecordTypeId": "012On00000L9nILIAZ",
  "Description": "<project.Project description (RT)>",
  "Project_Tag__c": "<semicolon-joined tags>",
  "Sourcing_Mode__c": "<request.Mode slug>",
  "Package__c": "<request.Package>",
  "Active_Proposal_Count__c": 3,
  "Discovery_Insights__c": "<request.Discovery Call Insights>",
  "Submitted_Date__c": "<request.Submitted Date>",
  "Balo_Created_Date__c": "<project.Created Date>",
  "Product__c": "<semicolon-joined products>",
  "Project_ID__c": "<project._id>",
  "Total_Cost_Inc_Fees__c": 5000,
  "GST_Charged__c": 100,
  "Expert_Earnings__c": 4500,
  "Account.Balo_Id__c": "<company._id>",
  "Primary_Contact__r.Balo_Id__c": "<client user._id>",
  "Related_Case__r.Balo_Id__c": "<case._id>"
}
```

**Payload (request only, no finalized project):**
Same structure but:
- `Name` = smart-field from request (AI/Manual/Final variant)
- `StageName` = "Request"
- `Sub_status__c` = request status slug
- `CloseDate`, `Project_ID__c`, `Total_Cost_Inc_Fees__c`, `GST_Charged__c`, `Expert_Earnings__c` = empty

**Smart field selection:** Based on `request.Mode` slug:
- `"AI"` -> use `Title (AI)`, `Description (AI)`, `Products (AI)`, `Project Tag (AI)`
- `"Manual"` -> use `Title (Manual)`, `Description (Manual)`, etc.
- `"Final"` or other -> use `Title (Final)`, `Description (Final)`, etc.

**Note:** Do not include `_source_stage` or `RecordTypeId_CONFIRM` in the API payload.
These are helper columns for the Excel output only.

---

### 7. POST /crm/booking/:id

**What it does:** Upserts an Opportunity by `Balo_Id__c` (same SF target as #6).

**SF target:** `PATCH /services/data/v65.0/sobjects/Opportunity/Balo_Id__c/{id}`

**This route is used by Bubble for lead-to-booking conversion, not by this export tool.**
It hits the same SF endpoint as `/crm/opportunity/project/:id` but via POST from Bubble.
Included for completeness.

---

### 8. PATCH /crm/project-expert/:id

**What it does:** Upserts a Project__c (expert-project link) by `Balo_Id__c`.

**SF target:** `PATCH /services/data/v65.0/sobjects/Project__c/Balo_Id__c/{id}`

**`:id` param:** Composite key: `{request._id}-{expert_user._id}`

**Transformer:** `transform_project_experts`

**How to call from Python:**
```python
composite_id = f"{request_id}-{expert_user_id}"
requests.patch(
    f"{MIDDLEWARE_URL}/crm/project-expert/{composite_id}",
    headers={"Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"},
    json=payload,
)
```

**Payload:**
```json
{
  "Expert_EOI_Status__c": "<eoi.Status slug>",
  "Opportunity__r.Balo_Id__c": "<request._id>",
  "Expert__r.Balo_Id__c": "<expert user._id>"
}
```

**Note:** Only 3 fields. The composite external ID in the URL links the expert to the
opportunity. `Expert__r.Balo_Id__c` uses the user._id (not the expert profile._id).

---

### 9. PATCH /crm/consultation/:id

**What it does:** Upserts a Consultation__c by `Balo_Id__c`.

**SF target:** `PATCH /services/data/v65.0/sobjects/Consultation__c/Balo_Id__c/{id}`

**`:id` param:** The meeting._id.

**Transformer:** `transform_consultations` -> `_build_meeting_row`

**How to call from Python:**
```python
requests.patch(
    f"{MIDDLEWARE_URL}/crm/consultation/{meeting_id}",
    headers={"Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"},
    json=payload,
)
```

**Payload (consultation type):**
```json
{
  "Opportunity__r.Balo_Id__c": "<consultation.Case>",
  "Project__r.Balo_Id__c": "",
  "Expert__r.Balo_Id__c": "<expert user._id>",
  "Scheduled_DateTime__c": "<meeting.Created Date>",
  "Start_Time__c": "<meeting.Date: Start (Booked)>",
  "End_Time__c": "<meeting.Date: End (Booked)>",
  "Actual_End_Time__c": "<meeting.Date: End (Actual)>",
  "Duration_Minutes__c": 30,
  "Actual_Duration_Minutes__c": 28,
  "Status__c": "Completed",
  "Billing_Mode__c": "Metered",
  "Expert_Rate__c": 2.50,
  "Estimated_Cost__c": 75.00,
  "Final_Cost__c": 70.00,
  "GST_Amount__c": 7.00,
  "Cancellation_Allowed__c": true,
  "Cancellation_Reason__c": "",
  "Cancelled_By__c": "",
  "Client_Join_Time__c": "<meeting.Invitor Join time>",
  "Expert_Join_Time__c": "<meeting.Organiser Join time>",
  "Ended_By_Expert__c": true,
  "Ended_By_Client__c": false,
  "Participants_Present__c": "",
  "Balo_Created_Date__c": "<meeting.Created Date>"
}
```

**Payload (project meeting type):**
Same structure but:
- `Opportunity__r.Balo_Id__c` = empty
- `Project__r.Balo_Id__c` = composite `{request._id}-{expert_user._id}`
- `Expert_Rate__c`, `Estimated_Cost__c`, `Final_Cost__c`, `GST_Amount__c` = empty

**Cancelled_By__c resolution:**
- If `meeting.Cancelled By` == `meeting.Invitor` -> `"Client"`
- If `meeting.Cancelled By` == `meeting.Organiser` -> `"Expert"`
- Default -> `"Client"`

**Status__c / Billing_Mode__c:** Converted from Bubble option set format to display
string, capitalized (e.g. `"completed"` -> `"Completed"`).

**Note:** Do not include `_meeting_type` in the API payload — it's a helper column for
the Excel output only.

---

## Refactoring Guide

When updating this tool to send data through the middleware instead of generating Excel:

### Fields to exclude from API payloads

These are Excel helper columns and must NOT be sent to the middleware:
- `_group`
- `_contact_type`
- `_meeting_type`
- `_source_stage`
- `_is_separator` / `_label` (separator rows)
- `RecordTypeId_CONFIRM` (flag column)
- `Balo_Id__c` (for upsert routes — it goes in the URL, not the body)

### Calling order

For coherent test data, send records in this order (foreign keys must exist first):

1. **Prospects** (`POST /crm/prospect`) — creates Account + Contact atomically
2. **Accounts** (`PATCH /crm/account/:id`) — updates Account with additional fields
3. **Contacts** (`PATCH /crm/contact/:id`) — updates Contact with expert/client-specific fields
4. **Opportunities - Cases** (`PATCH /crm/opportunity/case/:id`)
5. **Opportunities - Projects** (`PATCH /crm/opportunity/project/:id`)
6. **Project Experts** (`PATCH /crm/project-expert/:id`)
7. **Consultations** (`PATCH /crm/consultation/:id`)

### Rate limiting

The middleware returns `202 Accepted` immediately (it queues internally), so you don't
need to wait for SF responses. However, avoid flooding — a 100ms delay between requests
is sufficient.

### Error handling

The middleware handles retries internally. If the middleware itself returns a non-202
status, that means:
- `401` — invalid `MIDDLEWARE_API_SECRET`
- `404` — wrong route/method
- `5xx` — middleware is down

Check `#sf-sync-errors` in Slack for Salesforce-side failures.
