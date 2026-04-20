# Balo → Salesforce Field Mapping

This document maps each Salesforce API endpoint to its Bubble.io data source fields. The export tool will generate CSVs matching these payload structures.

## Overview


| #   | Endpoint                     | SF Object                       | Method | Path                                                         |
| --- | ---------------------------- | ------------------------------- | ------ | ------------------------------------------------------------ |
| 1   | Upsert Prospect (Signup)     | Prospect__c + Account + Contact | POST   | `/services/apexrest/Prospect/`                               |
| 2   | Upsert Account               | Account                         | PATCH  | `/sobjects/Account/Balo_Id__c/{id}`                          |
| 3   | Upsert Contact (Expert)      | Contact                         | PATCH  | `/sobjects/Contact/Balo_Id__c/{user_id}`                     |
| 4   | Upsert Contact (Client)      | Contact                         | PATCH  | `/sobjects/Contact/Balo_Id__c/{user_id}`                     |
| 5   | Upsert Opportunity (Case)    | Opportunity                     | PATCH  | `/sobjects/Opportunity/Balo_Id__c/{case_id}`                 |
| 6   | Upsert Opportunity (Project) | Opportunity                     | PATCH  | `/sobjects/Opportunity/Balo_Id__c/{project_request_id}`      |
| 7   | Upsert Expert for Project    | Project__c                      | PATCH  | `/sobjects/Project__c/Balo_Id__c/{requestId}-{expertUserId}` |
| 8   | Upsert Consultation          | Consultation__c                 | PATCH  | `/sobjects/Consultation__c/Balo_Id__c/{meeting_id}`          |


**Base URL:** `https://balo.expert/api/1.1` (Bubble Data API)
**Auth:** `?api_token=<BALO_API_TOKEN>` (env var)

---

## Endpoint 1: Upsert Prospect (Signup)

**SF Endpoint:** `POST /services/apexrest/Prospect/`
**Creates:** Prospect__c + Account + Contact atomically

### Variants

- **Client with Company** → `accountType: "Company"`, `baloAccountId` = client company `_id`
- **Freelance Expert** → no `baloAccountId`, `companyName`, or `accountType` sent
- **Agency Expert** → `accountType: "Expert"`, `baloAccountId` = agency `_id`

### Field Mapping


| SF Payload Field                                      | Type     | Bubble Field                       | Bubble Table                                    | Notes                                                                                             |
| ----------------------------------------------------- | -------- | ---------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `baloId`                                              | string   | `_id`                              | `user`                                          | External ID for Prospect/Contact                                                                  |
| `email`                                               | string   | email                              | `user`                                          |                                                                                                   |
| `firstName`                                           | string   | `Name: First`                      | `user`                                          |                                                                                                   |
| `lastName`                                            | string   | `Name: Last`                       | `user`                                          |                                                                                                   |
| `phone`                                               | string   | `Phone`                            | `user`                                          |                                                                                                   |
| `baloRole`                                            | string   | `Role: Active` slug                | `user`                                          | Single primary role                                                                               |
| `baloRoles`                                           | array    | `Roles` array slugs                | `user`                                          | All roles, semicolon-joined in SF                                                                 |
| `prospectStatus`                                      | string   | N/A (hardcoded)                    | N/A                                             | Always `"Signed Up"` in CSV output                                                                |
| `signupDate`                                          | datetime | `Created Date`                     | `user`                                          | ISO 8601 format                                                                                   |
| `timezone`                                            | string   | `⚙️ Timezone ID`                   | `user`                                          | e.g. "Australia/Melbourne"                                                                        |
| `currencyCode`                                        | string   | `💱 Currency` (Option set) display | `user`                                          | e.g. "AUD", "USD"                                                                                 |
| `country`                                             | string   | `⚙️ Country` → resolved `Name`     | `user` → `📍country`                            | Resolve country UID to name                                                                       |
| `baloAccountId`                                       | string   | unique id/_id                      | `👥profile:clientcompany` or `👥profile:agency` | Omit for freelance experts                                                                        |
| `companyName`                                         | string   | `Name`                             | `👥profile:clientcompany` or `👥profile:agency` | Omit for freelance experts                                                                        |
| `accountType`                                         | string   | Derived from role                  | —                                               | "Company" (client) / "Expert" (agency) / omit (freelance)                                         |
| `baloAccountCreatedDate`                              | datetime | `Created Date`                     | `👥profile:clientcompany` or `👥profile:agency` | Omit for freelance experts                                                                        |


### Allowed Values

- `baloRole`: admin, agency-admin, agency-expert, freelance-expert, client-admin, client-staff, client-guest
- `prospectStatus`: Signed Up, Active, Converted, Churned
- `accountType`: Company, Expert

---

## Endpoint 2: Upsert Account

**SF Endpoint:** `PATCH /sobjects/Account/Balo_Id__c/{id}`
**External ID:** `Balo_Id__c` = client company id or agency `_id`

### Field Mapping


| SF Payload Field              | Type     | Bubble Field                                 | Bubble Table                                    | Notes                                       |
| ----------------------------- | -------- | -------------------------------------------- | ----------------------------------------------- | ------------------------------------------- |
| `Name`                        | string   | `Name`                                       | `👥profile:clientcompany` or `👥profile:agency` |                                             |
| `Phone`                       | string   | Admin user's `Phone`                         | `user` (via `Admin` field)                      |                                             |
| `Website`                     | string   | `Website`                                    | `👥profile:agency`                              | Agencies only                               |
| `Type`                        | string   | Derived                                      | —                                               | "Company" (client) / "Expert" (agency)      |
| `AccountSource`               | string   | —                                            | —                                               | Hardcoded: "Balo Sourced"                   |
| `Stripe_Customer_Id__c`       | string   | `🤑 Stripe: Customer ID`                     | `👥profile:clientcompany`                       |                                             |
| `Has_Booked_Consultation__c`  | boolean  | `☑️ Consultation: Booked at least one`       | `👥profile:clientcompany`                       |                                             |
| `Has_Redeemed_Credits__c`     | boolean  | `☑️ Credits: Redeemed at least one`          | `👥profile:clientcompany`                       |                                             |
| `Has_Submitted_Project__c`    | boolean  | `☑️ Project request: Submitted at least one` | `👥profile:clientcompany`                       |                                             |
| `Balo_Created_Date__c`        | datetime | `Created Date`                               | `👥profile:clientcompany` or `👥profile:agency` |                                             |
| `Stripe_Seller_ID__c`         | string   | `🤑 Stripe: Seller ID`                       | `👥profile:agency`                              |                                             |
| `Stripe_Connection_Status__c` | boolean  | `🤑 Stripe: Connection Active`               | `👥profile:agency`                              |                                             |


### Allowed Values

- `Type`: Company, Expert

---

## Endpoint 3: Upsert Contact (Expert)

**SF Endpoint:** `PATCH /sobjects/Contact/Balo_Id__c/{user_id}`
**External ID:** `Balo_Id__c` = user `_id`
**RecordTypeId:** `012On00000LYlI9IAL` (Expert)

### Field Mapping


| SF Payload Field             | Type    | Bubble Field                            | Bubble Table                     | Notes                                 |
| ---------------------------- | ------- | --------------------------------------- | -------------------------------- | ------------------------------------- |
| `FirstName`                  | string  | `Name: First`                           | `user`                           | Via `👤profile:expert.User`           |
| `LastName`                   | string  | `Name: Last`                            | `user`                           | Via `👤profile:expert.User`           |
| `Email`                      | string  | email                                   | `user`                           |                                       |
| `Phone`                      | string  | `Phone`                                 | `user`                           |                                       |
| `RecordTypeId`               | string  | —                                       | —                                | Hardcoded: `012On00000LYlI9IAL`       |
| `Expert_Type__c`             | string  | `Expert type` slug                      | `👤profile:expert`               | "freelancer" or "agency"              |
| `Is_Salesforce_Certified__c` | boolean | `Certifications` has any?               | `👤profile:expert`               | Derived: true if certifications exist |
| `Is_CTA__c`                  | boolean | `Salesforce CTA?`                       | `👤profile:expert`               |                                       |
| `Is_MVP__c`                  | boolean | `Salesforce MVP?`                       | `👤profile:expert`               |                                       |
| `Salesforce_Start_Year__c`   | string  | `Started at Salesforce (Year)` → string | `👤profile:expert`               | Number → string                       |
| `Years_Experience__c`        | string  | `Years of experience` → string          | `👤profile:expert`               | Number → string                       |
| `Project_Count_Range__c`     | string  | `No. Salesforce projects involved` slug | `👤profile:expert`               | Option set value                      |
| `Consultation_Min_Rate__c`   | number  | `Rate (per min)`                        | `👤profile:expert`               |                                       |
| `Average_Rating__c`          | number  | `Average Rating`                        | `👤profile:expert`               |                                       |
| `Total_Reviews__c`           | number  | `Total Reviews`                         | `👤profile:expert`               |                                       |
| `LinkedIn_URL__c`            | string  | `Linkedin URL`                          | `👤profile:expert`               |                                       |
| `Trailblazer_URL__c`         | string  | `Trailblazer profile URL`               | `👤profile:expert`               |                                       |
| `Headline__c`                | string  | `Profile Headline`                      | `👤profile:expert`               |                                       |
| `Application_Status__c`      | string  | `Application: Status` slug              | `👤profile:expert`               |                                       |
| `Expert_Unique_ID__c`        | string  | `_id`                                   | `👤profile:expert`               | Expert profile ID (not user ID)       |
| `Cronofy_User_ID__c`         | string  | `⚙️ Cronofy User ID`                    | `👤profile:expert`               |                                       |
| `MailingCountry`             | string  | `Country` → `Alpha-2 code`              | `👤profile:expert` → `📍country` | Resolve to ISO alpha-2                |
| `Account.Balo_Id__c`         | string  | `Agency._id`                            | `👥profile:agency`               | Only for agency experts               |


### Allowed Values

- `Expert_Type__c`: Freelancer, Agency
- `Application_Status__c`: Pending, Submitted, Approved, Rejected, Waitlisted

---

## Endpoint 4: Upsert Contact (Client)

**SF Endpoint:** `PATCH /sobjects/Contact/Balo_Id__c/{user_id}`
**External ID:** `Balo_Id__c` = user `_id`
**RecordTypeId:** `012On00000LYdFm` (Client)

### Field Mapping


| SF Payload Field     | Type   | Bubble Field        | Bubble Table              | Notes                        |
| -------------------- | ------ | ------------------- | ------------------------- | ---------------------------- |
| `FirstName`          | string | `Name: First`       | `user`                    |                              |
| `LastName`           | string | `Name: Last`        | `user`                    |                              |
| `Email`              | string | email               | `user`                    |                              |
| `Phone`              | string | `Phone`             | `user`                    |                              |
| `RecordTypeId`       | string | —                   | —                         | Hardcoded: `012On00000LYdFm` |
| `Balo_Role__c`       | string | `Role: Active` slug | `user`                    |                              |
| `Account.Balo_Id__c` | string | `Company._id`       | `👥profile:clientcompany` | Resolve user.Company to _id  |


### Allowed Values

- `Balo_Role__c`: admin, agency-admin, agency-expert, freelance-expert, client-admin, client-staff, client-guest

---

## Endpoint 5: Upsert Opportunity (Case)

**SF Endpoint:** `PATCH /sobjects/Opportunity/Balo_Id__c/{case_id}`
**External ID:** `Balo_Id__c` = case `_id`
**RecordTypeId:** `012On00000L9nDVIAZ` (Case)

### Field Mapping


| SF Payload Field                | Type     | Bubble Field                              | Bubble Table                | Notes                            |
| ------------------------------- | -------- | ----------------------------------------- | --------------------------- | -------------------------------- |
| `Name`                          | string   | `Title`                                   | `📂case`                    |                                  |
| `CloseDate`                     | date     | N/A                                       | —                           | Leave blank                      |
| `StageName`                     | string   | `Status` slug → mapped                    | `📂case`                    | See allowed values               |
| `RecordTypeId`                  | string   | —                                         | —                           | Hardcoded: `012On00000L9nDVIAZ`  |
| `Balo_Case_Number__c`           | string   | `Case ID`                                 | `📂case`                    | Human-readable case number       |
| `Description`                   | string   | `Description`                             | `📂case`                    |                                  |
| `Total_Consultation_Minutes__c` | number   | `Total consultation minutes`              | `📂case`                    |                                  |
| `Total_Credits_Used__c`         | number   | `Total credits used`                      | `📂case`                    |                                  |
| `Amount`                        | number   | `Total amount earned`                     | `📂case`                    |                                  |
| `Balo_Created_Date__c`          | datetime | `Created Date`                            | `📂case`                    |                                  |
| `Product__c`                    | string   | `Products` array → semicolon-joined slugs | `📂case`                    | e.g. "sales-cloud;service-cloud" |
| `Type_Of_Support__c`            | string   | `Support` → semicolon-joined slugs        | `📂case`                    | Can be multiple                  |
| `Account.Balo_Id__c`            | string   | `Client company` → `_id`                  | `👥profile:clientcompany`   | Resolve to company _id           |
| `Primary_Contact__r.Balo_Id__c` | string   | `Client user` → `_id`                     | `user`                      | Resolve to user _id              |
| `Expert__r.Balo_Id__c`          | string   | `Expert Profiles[0]` → `User._id`         | `👤profile:expert` → `user` | First expert's user _id          |


### Allowed Values

- `StageName`: Draft, Ongoing, Completed
- `Type_Of_Support__c`: technical-fix-and-development, architecture-and-integrations, strategy-and-best-practices, platform-training
- `Product__c`: semicolon-separated product slugs (e.g. sales-cloud, service-cloud, agentforce, data-cloud, cpq, marketing-cloud, experience-cloud)

---

## Endpoint 6: Upsert Opportunity (Project)

**SF Endpoint:** `PATCH /sobjects/Opportunity/Balo_Id__c/{project_request_id}`
**External ID:** `Balo_Id__c` = project request `_id`
**RecordTypeId:** `012On00000L9nILIAZ` (Project)

> **FLAG FOR NICK:** RecordTypeId discrepancy — Postman collection uses `012On00000L9nDVIAZ` (same as Case) but Nick's Slack message used `012On00000L9nILIAZ`. The export will output both values with a warning flag so Nick can confirm which is correct.

### Field Mapping


| SF Payload Field                | Type     | Bubble Field                                | Bubble Table                      | Notes                                                                                                                                                                                                                      |
| ------------------------------- | -------- | ------------------------------------------- | --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Name`                          | string   | Conditional (see logic below)               | `📄project:request` or `📄project` | If `Final EOI`/`Final Project/Proposal` NOT attached → Title from `📄project:request` (based on Mode). If attached → `Project title` from `📄project`  |
| `CloseDate`                     | date     | `Estimated Completion Date` or derived      | `📄project`                       |                                                                                                                                                         |
| `StageName`                     | string   | Conditional (see logic below)               | —                                 | If `Final EOI`/`Final Project/Proposal` NOT attached → `"Request"`. If attached → `"Project"`                                                           |
| `Sub_status__c`                 | string   | Conditional (see logic below)               | `📄project:request` or `📄project` | If `Final EOI`/`Final Project/Proposal` NOT attached → `Status` from `📄project:request`. If attached → `Status` from `📄project`                      |
| `RecordTypeId`                  | string   | —                                           | —                                 | `012On00000L9nILIAZ` (confirm)                                                                                                                                                                                             |
| `Description`                   | string   | `Project description (RT)`                  | `📄project`                       | Rich text — may need stripping                                                                                                                                                                                             |
| `Project_Tag__c`                | string   | Tags (based on Mode) → semicolon-joined     | `📄project:request`               | Tag values contain `&&&` as part of their name. **FLAG FOR NICK:** Does this field accept multiple values? If so, what separator? (semicolon like `Product__c`?) Not confirmed on Slack. |
| `Sourcing_Mode__c`              | string   | `Mode` slug                                 | `📄project:request`               | AI, Manual, Final                                                                                                                                                                                                          |
| `Package__c`                    | string   | `Package._id`                               | `📄project:request` → `📄package` | Package Bubble ID                                                                                                                                                                                                          |
| `Active_Proposal_Count__c`      | number   | `Active Proposal Count`                     | `📄project:request`               |                                                                                                                                                                                                                            |
| `Discovery_Insights__c`         | string   | `Discovery Call Insights`                   | `📄project:request`               |                                                                                                                                                                                                                            |
| `Submitted_Date__c`             | date     | `Submitted Date`                            | `📄project:request`               |                                                                                                                                                                                                                            |
| `Balo_Created_Date__c`          | datetime | `Created Date`                              | `📄project`                       |                                                                                                                                                                                                                            |
| `Product__c`                    | string   | Products → semicolon-joined (based on Mode) | `📄project:request`               | Uses AI/Manual/Final based on Mode                                                                                                                                                                                         |
| `Project_ID__c`                 | string   | `_id`                                       | `📄project`                       |                                                                                                                                                                                                                            |
| `Total_Cost_Inc_Fees__c`        | number   | `Total Cost (Including Fees)`               | `📄project`                       |                                                                                                                                                                                                                            |
| `GST_Charged__c`                | number   | Check `📄project` table first               | `📄project`                       | Use value from project table if present, otherwise leave empty                                                                                                                                                             |
| `Expert_Earnings__c`            | number   | `Total Cost (Excluding Fees)`               | `📄project`                       |                                                                                                                                                                                                                            |
| `Account.Balo_Id__c`            | string   | `Client Company._id`                        | `👥profile:clientcompany`         |                                                                                                                                                                                                                            |
| `Primary_Contact__r.Balo_Id__c` | string   | `Client User._id`                           | `user`                            |                                                                                                                                                                                                                            |
| `Related_Case__r.Balo_Id__c`    | string   | `Case._id`                                  | `📂case`                          | Linked case Bubble ID                                                                                                                                                                                                      |


### Allowed Values

- `StageName`: Request, Project (no "Proposal" stage — see conditional logic above)
- `Sub_status__c`: draft-project-request, requested, matching-experts, discovery-call-required, experts-invited, archived, draft-project, awaiting-kick-off-approval, declined, ready-to-start, approved, in-progress, awaiting-completion-approval, completed
- `Sourcing_Mode__c`: AI, Manual, Final
- `Product__c`: semicolon-separated product slugs

### Smart Field Selection (Project Request)

The `📄project:request` type has three versions of content fields based on `Mode`. The export tool selects the correct version at runtime.


| SF Field                 | Mode = AI           | Mode = Manual           | Mode = Final           |
| ------------------------ | ------------------- | ----------------------- | ---------------------- |
| `Name` (via Description) | `Title (AI)`        | `Title (Manual)`        | `Title (Final)`        |
| `Description`            | `Description (AI)`  | `Description (Manual)`  | `Description (Final)`  |
| `Product__c`             | `Products (AI)`     | `Products (Manual)`     | `Products (Final)`     |
| `Project_Tag__c`         | `Project Tag (AI)`  | `Project Tag (Manual)`  | `Project Tag (Final)`  |
| `Type_Of_Support__c`     | `Project Type (AI)` | `Project Type (Manual)` | `Project Type (Final)` |
| Files (not in SF)        | `Files (AI)`        | `Files (Manual)`        | `Files (Final)`        |


### Full `📄project:request` Schema (from Swagger)


| Field                     | Type                | Notes                           |
| ------------------------- | ------------------- | ------------------------------- |
| `_id`                     | string              | Bubble unique ID                |
| `Status`                  | option set          | 🔘 Status: Project Request      |
| `Mode`                    | option set          | AI / Manual / Final             |
| `Title (AI)`              | string              | AI-generated title              |
| `Title (Manual)`          | string              | Client-edited title             |
| `Title (Final)`           | string              | Approved title                  |
| `Description (AI)`        | string              | AI-generated description        |
| `Description (Manual)`    | string              | Client-edited description       |
| `Description (Final)`     | string              | Approved description            |
| `Products (AI)`           | array of option set | AI-suggested products           |
| `Products (Manual)`       | array of option set | Client-selected products        |
| `Products (Final)`        | array of option set | Approved products               |
| `Project Tag (AI)`        | array of option set | AI-suggested tags               |
| `Project Tag (Manual)`    | array of option set | Client-selected tags            |
| `Project Tag (Final)`     | array of option set | Approved tags                   |
| `Project Type (AI)`       | array of option set | AI-suggested support types      |
| `Project Type (Manual)`   | array of option set | Client-selected support types   |
| `Project Type (Final)`    | array of option set | Approved support types          |
| `Files (AI)`              | array of string     | 🗃️file UIDs                    |
| `Files (Manual)`          | array of string     | 🗃️file UIDs                    |
| `Files (Final)`           | array of string     | 🗃️file UIDs                    |
| `Discovery Call Insights` | string              |                                 |
| `Active Proposal Count`   | number              |                                 |
| `Submitted Date`          | datetime            |                                 |
| `Package`                 | string              | → `📄package` UID               |
| `Client Company`          | string              | → `👥profile:clientcompany` UID |
| `Client User`             | string              | → `user` UID                    |
| `Selected Case`           | string              | → `📂case` UID                  |
| `Selected Expert`         | string              | → `👤profile:expert` UID        |
| `⚙️ EOI Experts`          | array of string     | → `👤profile:expert` UIDs       |
| `Assigned Experts`        | array of string     | → `👤profile:expert` UIDs       |
| `EoIs`                    | array of string     | → `📄project:eoi` UIDs          |
| `Final EOI`               | string              | → `📄project:eoi` UID           |
| `Final Project/Proposal`  | string              | → `📄project` UID               |
| `Participants (Internal)` | array of string     | → `user` UIDs                   |
| `Created Date`            | datetime            |                                 |
| `Modified Date`           | datetime            |                                 |
| `Created By`              | string              | → `user` UID                    |
| `Slug`                    | string              |                                 |


---

## Endpoint 7: Upsert Expert for Project

**SF Endpoint:** `PATCH /sobjects/Project__c/Balo_Id__c/{requestId}-{expertUserId}`
**External ID:** `Balo_Id__c` = `{ProjectRequest._id}-{Expert.User._id}`

### Field Mapping


| SF Payload Field            | Type   | Bubble Field      | Bubble Table                                  | Notes                                    |
| --------------------------- | ------ | ----------------- | --------------------------------------------- | ---------------------------------------- |
| `Expert_EOI_Status__c`      | string | `Status` slug     | `📄project:eoi`                               |                                          |
| `Opportunity__r.Balo_Id__c` | string | `Request._id`     | `📄project:eoi` → `📄project:request`         | Links to Opportunity, project request ID |
| `Expert__r.Balo_Id__c`      | string | `Expert.User._id` | `📄project:eoi` → `👤profile:expert` → `user` | Expert's user _id                        |


### Allowed Values

- `Expert_EOI_Status__c`: invited, interested, proposal-requested, proposed, declined, not-interested, finalized

---

## Endpoint 8: Upsert Consultation

**SF Endpoint:** `PATCH /sobjects/Consultation__c/Balo_Id__c/{meeting_id}`
**External ID:** `Balo_Id__c` = meeting `_id`

> **Status:** Nick flagged this endpoint as still needing review (March 23, 2026).

### Conditional Logic

Primary table is `📞meeting`. Lookups depend on meeting `Type`:
- **Type = `consultation`** → look up `📞consultation` via `Meeting.🆕 Consultation` for financial fields and Case link
- **Type ≠ `consultation`** → look up `🆕📞projectmeeting` via `Meeting.🆕 Project Meeting` for Project link

### Field Mapping

| SF Payload Field | Type | Bubble Field | Bubble Table | Notes |
|---|---|---|---|---|
| `Opportunity__r.Balo_Id__c` | string | `Case._id` | `📞meeting` → `📞consultation` → `📂case` | Only if Type = `consultation`, otherwise leave empty |
| `Project__r.Balo_Id__c` | string | Via Project Meeting link | `📞meeting` → `🆕📞projectmeeting` | Only if Type ≠ `consultation`, otherwise leave empty |
| `Expert__r.Balo_Id__c` | string | `Profile Expert.User._id` | `📞meeting` | |
| `Scheduled_DateTime__c` | datetime | `Created Date` | `📞meeting` | |
| `Start_Time__c` | datetime | `Date: Start (Booked)` | `📞meeting` | |
| `End_Time__c` | datetime | `Date: End (Booked)` | `📞meeting` | |
| `Actual_End_Time__c` | datetime | `Date: End (Actual)` | `📞meeting` | |
| `Duration_Minutes__c` | number | `Scheduled Duration` | `📞meeting` | In minutes |
| `Actual_Duration_Minutes__c` | number | `Actual Duration` | `📞meeting` | In minutes |
| `Status__c` | string | `Status` slug → mapped | `📞meeting` | See allowed values |
| `Billing_Mode__c` | string | `🆕 Billing Mode` slug → mapped | `📞meeting` | See allowed values |
| `Expert_Rate__c` | number | `Expert Rate` | `📞meeting` → `📞consultation` | Only if Type = `consultation`, otherwise leave empty |
| `Estimated_Cost__c` | number | `Cost estimated` | `📞meeting` → `📞consultation` | Only if Type = `consultation`, otherwise leave empty |
| `Final_Cost__c` | number | `Cost Incurred Final` | `📞meeting` → `📞consultation` | Only if Type = `consultation`, otherwise leave empty |
| `GST_Amount__c` | number | `GST Charged` | `📞meeting` → `📞consultation` | Only if Type = `consultation`, otherwise leave empty |
| `Cancellation_Allowed__c` | datetime | `Cancellation Allowed` | `📞meeting` | Deadline datetime |
| `Cancellation_Reason__c` | string | `Cancellation Reason` | `📞meeting` | |
| `Cancelled_By__c` | string | `Cancelled By` → resolved | `📞meeting` | Derive "Client" or "Expert" |
| `Client_Join_Time__c` | datetime | `Invitor Join time` | `📞meeting` | Client = Invitor |
| `Expert_Join_Time__c` | datetime | `Organiser Join time` | `📞meeting` | Expert = Organiser |
| `Ended_By_Expert__c` | datetime | `Ended by Organizer` | `📞meeting` | |
| `Ended_By_Client__c` | datetime | `Ended by Invitor` | `📞meeting` | |
| `Participants_Present__c` | boolean | N/A | — | Leave empty |
| `Balo_Created_Date__c` | datetime | `Created Date` | `📞meeting` | |

### Allowed Values

- `Status__c`: Upcoming, Completed, Cancelled, Missed
- `Billing_Mode__c`: Free, Metered, Fixed
- `Cancelled_By__c`: Client, Expert

---

## Bubble Tables Required for Export


| Bubble Table              | Used By Endpoints      | Needs API Exposure             |
| ------------------------- | ---------------------- | ------------------------------ |
| `user`                    | 1, 2, 3, 4, 5, 6, 7, 8 | Already exposed                |
| `👤profile:expert`        | 1, 3, 5, 6, 7, 8       | Already exposed                |
| `👥profile:agency`        | 1, 2, 3                | Already exposed                |
| `👥profile:clientcompany` | 1, 2, 4, 5, 6          | Already exposed                |
| `📂case`                  | 5, 6, 8                | Already exposed                |
| `📄project`               | 6                      | Already exposed                |
| `📄project:request`       | 6, 7                   | Now exposed (added to Swagger) |
| `📄project:eoi`           | 7                      | Already exposed                |
| `📞consultation`          | 8                      | Already exposed                |
| `📞meeting`               | 8                      | Already exposed                |
| `📍country`               | 1, 3                   | Already exposed                |
| `📄package`               | 6                      | Already exposed (just _id)     |


---

## Sensitive Fields (Redacted in CSV)

These fields will be replaced with `[REDACTED]` using deterministic code:

- `Cronofy Access token` (from `user`)
- `Cronofy Refresh token` (from `user`)
- `Cronofy Temp Link Token` (from `user`)
- `authentication` object (from `user`)

**Not redacted:** email, phone, Stripe IDs, Cronofy User ID, Daily.co tokens

---

## Open Items

- **FLAG FOR NICK:** Confirm Project Opportunity RecordTypeId: `012On00000L9nILIAZ` vs `012On00000L9nDVIAZ`
- **FLAG FOR NICK:** Does `Project_Tag__c` accept multiple values? If so, what separator? (not confirmed on Slack)
- Finalize Consultation endpoint (Nick flagged as needs review)
- ~~Expose `📄project:request` in Bubble Data API and update Swagger~~ **DONE**
- ~~Provide option set values for any missing enums~~ **DONE** (sourced from Bubble app documentation)

