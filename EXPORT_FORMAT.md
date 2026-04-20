# Export Format Design

The export tool produces **6 CSV files**, one per Salesforce entity group. Each CSV's columns match the exact SF API payload field names so devs can directly copy values into their API calls.

## File Structure

```
export/
  01_accounts.csv                  → SF Account upserts
  02_prospect_contacts.csv         → SF Prospect + Contact upserts
  03_opportunities_cases.csv       → SF Opportunity (Case) upserts
  04_opportunities_projects.csv    → SF Opportunity (Project) upserts
  05_project_experts.csv           → SF Project__c (Expert-Project link) upserts
  06_consultations.csv             → SF Consultation__c upserts
  README.txt                       → Notes for devs (incl. RecordTypeId flag for Nick)
```

## Test Data Set

The export pulls a coherent set of linked records:

| Group | Entity | Count | Example Names |
|---|---|---|---|
| Client Companies | `👥profile:clientcompany` | 3 | medi Australia, TechCorp Solutions, GreenEnergy Ltd |
| Client Users | `user` (client roles) | ~6 | 2 per company (1 admin + 1 staff) |
| Agencies | `👥profile:agency` | 3 | CELX Digital, CloudForce Partners, SF Experts Co |
| Agency Experts | `user` + `👤profile:expert` | ~6 | 2 per agency |
| Freelance Experts | `user` + `👤profile:expert` | 3 | Independent experts |
| Cases | `📂case` | ~6 | 2 per client company, linking to different experts |
| Projects | `📄project:request` + `📄project` | ~3 | 1 per client company |
| EoIs | `📄project:eoi` | ~6 | 2 experts invited per project |
| Meetings | `📞meeting` + `📞consultation` | ~6 | Mix of consultation and project types |

---

## CSV 1: `01_accounts.csv`

One row per company/agency. Devs use this for `PATCH /sobjects/Account/Balo_Id__c/{id}`.

**Grouping:** Client companies first, then agencies.

```
_group,Balo_Id__c,Name,Phone,Website,Type,AccountSource,Stripe_Customer_Id__c,Has_Booked_Consultation__c,Has_Redeemed_Credits__c,Has_Submitted_Project__c,Balo_Created_Date__c,Stripe_Seller_ID__c,Stripe_Connection_Status__c
CLIENT,1749173177291x476595545502580100,medi Australia,0398765432,,Company,Balo Sourced,cus_R4kL8mN2pQ,,true,false,true,2025-06-15T02:30:00Z,,
CLIENT,1750284288402x587606656513691200,TechCorp Solutions,0287654321,www.techcorp.com.au,Company,Balo Sourced,cus_T7nM9pR3sU,,true,true,false,2025-08-22T05:15:00Z,,
CLIENT,1751395399513x698717767624802300,GreenEnergy Ltd,0376543210,,Company,Balo Sourced,cus_G2hK5nP8qW,,false,false,false,2025-11-03T08:00:00Z,,
AGENCY,1752506510624x809828878735913400,CELX Digital,0412111222,www.celxdigital.com.au,Expert,Balo Sourced,,,,,,acct_1N2cEfGhIjKlMn,true
AGENCY,1753617621735x920939989846024500,CloudForce Partners,0412333444,www.cloudforce.io,Expert,Balo Sourced,,,,,,acct_2O3dFgHiJkLmNo,true
AGENCY,1754728732846x031041090957135600,SF Experts Co,0412555666,www.sfexperts.com,Expert,Balo Sourced,,,,,,acct_3P4eGhIjKlMnOp,false
```

**Key:** `_group` column is for dev readability only, not sent to SF.

---

## CSV 2: `02_prospect_contacts.csv`

One row per user. Contains both Prospect fields AND Contact fields so devs can test both endpoints from the same row.

**Grouping:** Rows are grouped by their company/agency.

```
_group,_contact_type,baloId,email,firstName,lastName,phone,baloRole,baloRoles,prospectStatus,signupDate,timezone,currencyCode,country,baloAccountId,companyName,accountType,baloAccountCreatedDate,RecordTypeId,Expert_Type__c,Is_Salesforce_Certified__c,Is_CTA__c,Is_MVP__c,Salesforce_Start_Year__c,Years_Experience__c,Project_Count_Range__c,Consultation_Min_Rate__c,Average_Rating__c,Total_Reviews__c,LinkedIn_URL__c,Trailblazer_URL__c,Headline__c,Application_Status__c,Expert_Unique_ID__c,Cronofy_User_ID__c,MailingCountry,Account.Balo_Id__c,Balo_Role__c
--- medi Australia ---,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
medi Australia,CLIENT,1771989876338x326599309252931600,molly@medi.au,Molly,Yang,0412345678,client-admin,client-admin,Signed Up,2025-06-15T02:30:00Z,Australia/Sydney,AUD,Australia,1749173177291x476595545502580100,medi Australia,Company,2025-06-15T02:30:00Z,012On00000LYdFm,,,,,,,,,,,,,,,,,1749173177291x476595545502580100,client-admin
medi Australia,CLIENT,1772100987449x437710420363042700,david@medi.au,David,Chen,0412345679,client-staff,client-staff,Signed Up,2025-07-01T08:00:00Z,Australia/Sydney,AUD,Australia,1749173177291x476595545502580100,medi Australia,Company,2025-06-15T02:30:00Z,012On00000LYdFm,,,,,,,,,,,,,,,,,1749173177291x476595545502580100,client-staff
--- TechCorp Solutions ---,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
TechCorp Solutions,CLIENT,1773212098560x548821531474153800,sarah@techcorp.com.au,Sarah,Williams,0287654321,client-admin,client-admin,Signed Up,2025-08-22T05:15:00Z,Australia/Melbourne,AUD,Australia,1750284288402x587606656513691200,TechCorp Solutions,Company,2025-08-22T05:15:00Z,012On00000LYdFm,,,,,,,,,,,,,,,,,1750284288402x587606656513691200,client-admin
--- CELX Digital (Agency) ---,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
CELX Digital,EXPERT,1774323209671x659932642585264900,james@celxdigital.com,James,Rodriguez,0411222333,agency-expert,agency-expert,Signed Up,2025-04-10T01:00:00Z,Australia/Brisbane,AUD,Australia,1752506510624x809828878735913400,CELX Digital,Expert,2025-03-01T00:00:00Z,012On00000LYlI9IAL,Agency,true,false,false,2018,7,10-25,3.50,4.8,23,https://linkedin.com/in/jamesrodriguez,https://trailblazer.me/jamesrodriguez,Senior Sales Cloud Consultant,Approved,1774323209671x659932642585264900_exp,acc_celx_james,AU,1752506510624x809828878735913400,
CELX Digital,EXPERT,1775434320782x770043753696376000,emma@celxdigital.com,Emma,Thompson,0411222334,agency-expert,agency-expert,Signed Up,2025-05-15T03:00:00Z,Australia/Brisbane,AUD,Australia,1752506510624x809828878735913400,CELX Digital,Expert,2025-03-01T00:00:00Z,012On00000LYlI9IAL,Agency,true,true,false,2015,10,25-50,5.00,4.9,31,https://linkedin.com/in/emmathompson,https://trailblazer.me/emmathompson,CTA & Service Cloud Architect,Approved,1775434320782x770043753696376000_exp,acc_celx_emma,AU,1752506510624x809828878735913400,
--- Freelance Experts ---,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
Freelance,EXPERT,1776545431893x881154864807487100,alex@consulting.com,Alex,Kumar,0498765432,freelance-expert,freelance-expert,Signed Up,2025-09-01T06:00:00Z,Australia/Sydney,AUD,Australia,,,,012On00000LYlI9IAL,Freelancer,true,false,true,2016,9,10-25,4.25,4.7,18,https://linkedin.com/in/alexkumar,https://trailblazer.me/alexkumar,Salesforce MVP & Data Cloud Specialist,Approved,1776545431893x881154864807487100_exp,acc_alex_kumar,AU,,
```

**How devs use this:**
- **Prospect endpoint:** Take columns `baloId` through `baloAccountCreatedDate`
- **Contact (Client):** Take `baloId` (as URL param) + `FirstName`=firstName, `LastName`=lastName, `Email`=email, `Phone`=phone, `RecordTypeId`, `Balo_Role__c`, `Account.Balo_Id__c`
- **Contact (Expert):** Take `baloId` (as URL param) + all Expert_* columns + `Account.Balo_Id__c`

---

## CSV 3: `03_opportunities_cases.csv`

One row per case. Devs use this for `PATCH /sobjects/Opportunity/Balo_Id__c/{Balo_Id__c}`.

**Grouping:** By client company.

```
_group,Balo_Id__c,Name,CloseDate,StageName,RecordTypeId,Balo_Case_Number__c,Description,Total_Consultation_Minutes__c,Total_Credits_Used__c,Amount,Balo_Created_Date__c,Product__c,Type_Of_Support__c,Account.Balo_Id__c,Primary_Contact__r.Balo_Id__c,Expert__r.Balo_Id__c
medi Australia,1780000000001x111111111111111100,Agentforce Config Fix,,Ongoing,012On00000L9nDVIAZ,CASE-001,Client needs help configuring Agentforce triggers for Service Cloud,60,330.00,330.00,2026-01-18T07:34:00Z,agentforce;service-cloud,technical-fix-and-development,1749173177291x476595545502580100,1771989876338x326599309252931600,1774323209671x659932642585264900
medi Australia,1780000000002x222222222222222200,Sales Cloud Data Migration,,Completed,012On00000L9nDVIAZ,CASE-002,Migration of legacy CRM data into Sales Cloud,120,990.00,990.00,2025-11-05T03:00:00Z,sales-cloud,architecture-and-integrations,1749173177291x476595545502580100,1771989876338x326599309252931600,1776545431893x881154864807487100
TechCorp Solutions,1780000000003x333333333333333300,CPQ Pricing Strategy,,Ongoing,012On00000L9nDVIAZ,CASE-003,Review and optimize CPQ pricing rules and approval workflows,45,247.50,247.50,2026-02-10T05:00:00Z,cpq,strategy-and-best-practices,1750284288402x587606656513691200,1773212098560x548821531474153800,1775434320782x770043753696376000
TechCorp Solutions,1780000000004x444444444444444400,Service Cloud Training,,Draft,012On00000L9nDVIAZ,CASE-004,Platform training for new Service Cloud deployment,0,0,0,2026-03-15T02:00:00Z,service-cloud,platform-training,1750284288402x587606656513691200,1773212098560x548821531474153800,1774323209671x659932642585264900
```

**Note:** `CloseDate` is intentionally blank per mapping spec.

---

## CSV 4: `04_opportunities_projects.csv`

One row per project request. Devs use this for `PATCH /sobjects/Opportunity/Balo_Id__c/{Balo_Id__c}`.

**Grouping:** By client company. Includes the conditional logic result.

```
_group,_source_stage,Balo_Id__c,Name,CloseDate,StageName,Sub_status__c,RecordTypeId,RecordTypeId_CONFIRM,Description,Project_Tag__c,Sourcing_Mode__c,Package__c,Active_Proposal_Count__c,Discovery_Insights__c,Submitted_Date__c,Balo_Created_Date__c,Product__c,Project_ID__c,Total_Cost_Inc_Fees__c,GST_Charged__c,Expert_Earnings__c,Account.Balo_Id__c,Primary_Contact__r.Balo_Id__c,Related_Case__r.Balo_Id__c
medi Australia,Project (finalized),1790000000001x111111111111111100,Agentforce Full Implementation,2026-09-30,Project,in-progress,012On00000L9nILIAZ,FLAG: confirm 012On00000L9nILIAZ vs 012On00000L9nDVIAZ,Full Agentforce implementation with Service Cloud integration,project-stage&&&new-implementation,Final,,2,Client needs Agentforce integrated with existing Service Cloud setup,2026-02-01,2026-01-20T05:00:00Z,agentforce;service-cloud,1790000000001x111111111111111100_proj,12500.00,1136.36,10000.00,1749173177291x476595545502580100,1771989876338x326599309252931600,1780000000001x111111111111111100
TechCorp Solutions,Request (no final EOI),1790000000002x222222222222222200,CPQ Optimization & Training,,Request,experts-invited,012On00000L9nILIAZ,FLAG: confirm 012On00000L9nILIAZ vs 012On00000L9nDVIAZ,,project-stage&&&optimization,AI,,3,CPQ rules need restructuring after recent product catalog update,2026-03-10,2026-03-08T02:00:00Z,cpq;sales-cloud,,,,,,1750284288402x587606656513691200,1773212098560x548821531474153800,1780000000003x333333333333333300
GreenEnergy Ltd,Request (no final EOI),1790000000003x333333333333333300,Data Cloud Setup,,Request,draft-project-request,012On00000L9nILIAZ,FLAG: confirm 012On00000L9nILIAZ vs 012On00000L9nDVIAZ,,project-stage&&&new-implementation,Manual,,0,,2026-03-20,2026-03-19T08:00:00Z,data-cloud,,,,,,1751395399513x698717767624802300,1774434320782x770043753696376000,
```

**Key columns for devs:**
- `_source_stage` — tells dev whether data came from `📄project:request` (Request) or `📄project` (Project)
- `RecordTypeId_CONFIRM` — **FLAG FOR NICK** about the RecordTypeId discrepancy
- `Description` is blank for "Request" stage (no project description yet)
- Financial fields (`Total_Cost_Inc_Fees__c`, etc.) are blank for "Request" stage
- `Project_ID__c` is blank for "Request" stage (no `📄project` exists yet)

---

## CSV 5: `05_project_experts.csv`

One row per expert-project link. Devs use this for `PATCH /sobjects/Project__c/Balo_Id__c/{Balo_Id__c}`.

```
_group,Balo_Id__c,Expert_EOI_Status__c,Opportunity__r.Balo_Id__c,Expert__r.Balo_Id__c
medi Australia - Agentforce,1790000000001x111111111111111100-1774323209671x659932642585264900,finalized,1790000000001x111111111111111100,1774323209671x659932642585264900
medi Australia - Agentforce,1790000000001x111111111111111100-1776545431893x881154864807487100,declined,1790000000001x111111111111111100,1776545431893x881154864807487100
TechCorp - CPQ,1790000000002x222222222222222200-1775434320782x770043753696376000,proposed,1790000000002x222222222222222200,1775434320782x770043753696376000
TechCorp - CPQ,1790000000002x222222222222222200-1774323209671x659932642585264900,interested,1790000000002x222222222222222200,1774323209671x659932642585264900
TechCorp - CPQ,1790000000002x222222222222222200-1776545431893x881154864807487100,invited,1790000000002x222222222222222200,1776545431893x881154864807487100
```

**Key:** `Balo_Id__c` = `{ProjectRequest._id}-{Expert.User._id}` composite key.

---

## CSV 6: `06_consultations.csv`

One row per meeting. Devs use this for `PATCH /sobjects/Consultation__c/Balo_Id__c/{Balo_Id__c}`.

**Grouping:** By meeting type (consultation vs project).

```
_group,_meeting_type,Balo_Id__c,Opportunity__r.Balo_Id__c,Project__r.Balo_Id__c,Expert__r.Balo_Id__c,Scheduled_DateTime__c,Start_Time__c,End_Time__c,Actual_End_Time__c,Duration_Minutes__c,Actual_Duration_Minutes__c,Status__c,Billing_Mode__c,Expert_Rate__c,Estimated_Cost__c,Final_Cost__c,GST_Amount__c,Cancellation_Allowed__c,Cancellation_Reason__c,Cancelled_By__c,Client_Join_Time__c,Expert_Join_Time__c,Ended_By_Expert__c,Ended_By_Client__c,Participants_Present__c,Balo_Created_Date__c
--- Consultations (metered billing) ---,,,,,,,,,,,,,,,,,,,,,,,,,,
medi Australia,consultation,1795000000001x111111111111111100,1780000000001x111111111111111100,,1774323209671x659932642585264900,2026-01-20T03:00:00Z,2026-01-20T03:00:00Z,2026-01-20T04:00:00Z,2026-01-20T03:55:00Z,60,55,Completed,Metered,3.50,210.00,192.50,17.50,2026-01-19T03:00:00Z,,,2026-01-20T03:01:00Z,2026-01-20T03:00:30Z,2026-01-20T03:55:00Z,2026-01-20T03:54:00Z,,2026-01-18T07:34:00Z
medi Australia,consultation,1795000000002x222222222222222200,1780000000002x222222222222222200,,1776545431893x881154864807487100,2025-12-10T02:00:00Z,2025-12-10T02:00:00Z,2025-12-10T03:00:00Z,2025-12-10T02:45:00Z,60,45,Completed,Metered,4.25,255.00,191.25,17.39,2025-12-09T02:00:00Z,,,2025-12-10T02:02:00Z,2025-12-10T02:00:15Z,2025-12-10T02:45:00Z,2025-12-10T02:44:00Z,,2025-11-28T03:00:00Z
TechCorp Solutions,consultation,1795000000003x333333333333333300,1780000000003x333333333333333300,,1775434320782x770043753696376000,2026-02-15T04:00:00Z,2026-02-15T04:00:00Z,2026-02-15T04:30:00Z,,30,,Cancelled,Metered,5.00,,,,2026-02-14T04:00:00Z,Client rescheduled,Client,,,,,2026-02-10T05:00:00Z
TechCorp Solutions,consultation,1795000000004x444444444444444400,1780000000004x444444444444444400,,1774323209671x659932642585264900,2026-03-20T01:00:00Z,2026-03-20T01:00:00Z,2026-03-20T01:15:00Z,,15,,Upcoming,Free,,,,,,,,,,,,2026-03-15T02:00:00Z
--- Project Meetings (free) ---,,,,,,,,,,,,,,,,,,,,,,,,,,
medi Australia,project-call,1795000000005x555555555555555500,,1790000000001x111111111111111100-1774323209671x659932642585264900,1774323209671x659932642585264900,2026-02-05T03:00:00Z,2026-02-05T03:00:00Z,2026-02-05T04:00:00Z,2026-02-05T03:50:00Z,60,50,Completed,Free,,,,,,,2026-02-05T03:02:00Z,2026-02-05T03:00:00Z,2026-02-05T03:50:00Z,,,2026-02-01T05:00:00Z
TechCorp Solutions,eoi-call,1795000000006x666666666666666600,,1790000000002x222222222222222200-1775434320782x770043753696376000,1775434320782x770043753696376000,2026-03-12T04:00:00Z,2026-03-12T04:00:00Z,2026-03-12T04:30:00Z,2026-03-12T04:25:00Z,30,25,Completed,Free,,,,,,,2026-03-12T04:01:00Z,2026-03-12T04:00:00Z,2026-03-12T04:25:00Z,,,2026-03-10T02:00:00Z
```

**Key columns for devs:**
- `_meeting_type` — tells dev the meeting Type (determines conditional logic)
- `Opportunity__r.Balo_Id__c` — populated only for `consultation` type (links to Case)
- `Project__r.Balo_Id__c` — populated only for non-consultation types (links to Project__c composite key)
- Financial fields (`Expert_Rate__c`, `Final_Cost__c`, etc.) — populated only for `consultation` type
- `Participants_Present__c` — always empty per spec

---

## Cross-Reference Guide

The `README.txt` in the export will include a quick-reference showing how IDs link across CSVs:

```
HOW TO USE THIS TEST DATA
=========================

Each CSV maps to a Salesforce API endpoint. Column names = SF payload field names.
Use the _group column to find related records across files.

CROSS-REFERENCE (how entities link):
  Account (01)  ←──  baloAccountId in Prospect (02)
  Account (01)  ←──  Account.Balo_Id__c in Contact (02)
  Account (01)  ←──  Account.Balo_Id__c in Opportunity Case (03)
  Account (01)  ←──  Account.Balo_Id__c in Opportunity Project (04)
  Contact (02)  ←──  Primary_Contact__r.Balo_Id__c in Opportunity (03, 04)
  Contact (02)  ←──  Expert__r.Balo_Id__c in Opportunity Case (03)
  Contact (02)  ←──  Expert__r.Balo_Id__c in Consultation (06)
  Opp Case (03) ←──  Opportunity__r.Balo_Id__c in Consultation (06)
  Opp Proj (04) ←──  Opportunity__r.Balo_Id__c in Project Expert (05)
  Proj Expert(05)←── Project__r.Balo_Id__c in Consultation (06) [for project meetings]

EXAMPLE FLOW - Test a full client journey:
  1. POST Prospect: Row "Molly Yang" from 02_prospect_contacts.csv
  2. PATCH Account: Row "medi Australia" from 01_accounts.csv
  3. PATCH Contact: Row "Molly Yang" (client columns) from 02_prospect_contacts.csv
  4. PATCH Opportunity: Row "CASE-001" from 03_opportunities_cases.csv
  5. PATCH Consultation: Row with matching Opportunity__r from 06_consultations.csv

FLAGS FOR NICK:
  - RecordTypeId for Project Opportunity: confirm 012On00000L9nILIAZ vs 012On00000L9nDVIAZ
  - Does Project_Tag__c accept multiple values? What separator?
```

---

## Naming Conventions in Export

| Column prefix | Meaning |
|---|---|
| `_group` | Human-readable grouping label (not sent to SF) |
| `_contact_type` | CLIENT or EXPERT (not sent to SF) |
| `_meeting_type` | Meeting Type value from Bubble (not sent to SF) |
| `_source_stage` | Whether data came from project:request or project table (not sent to SF) |
| All other columns | Exact SF API field names — use directly in payloads |
