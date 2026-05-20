from src.config import (
    get_slug,
    get_display,
    join_array_slugs,
    list_array_slugs,
    PROSPECT_STATUS,
    ACCOUNT_SOURCE,
    RECORD_TYPE_EXPERT_CONTACT,
    RECORD_TYPE_CLIENT_CONTACT,
    RECORD_TYPE_CASE_OPPORTUNITY,
    RECORD_TYPE_PROJECT_OPPORTUNITY,
    SENSITIVE_FIELDS,
    EXPERT_OR_ADMIN_ROLES,
)


# --- Helpers ---

def _safe_get(record, key, default=""):
    if not record:
        return default
    val = record.get(key)
    return val if val is not None else default


def _resolve_country(uid, store, field="Name"):
    if not uid:
        return ""
    country = store.countries.get(uid)
    if not country:
        return ""
    return country.get(field, "")


def _redact(record):
    if not record:
        return record
    redacted = dict(record)
    for field in SENSITIVE_FIELDS:
        if field in redacted:
            redacted[field] = "[REDACTED]"
    return redacted


def _smart_field(record, mode_slug, prefix):
    """Select the correct field version based on Mode (AI/Manual/Final)."""
    if not mode_slug:
        return ""
    label = mode_slug if mode_slug in ("AI", "Manual", "Final") else mode_slug.capitalize()
    if label not in ("AI", "Manual", "Final"):
        label = "Final"  # fallback
    return _safe_get(record, f"{prefix} ({label})")


def _separator_row(label):
    return {"_is_separator": True, "_label": f"--- {label} ---"}


def _expert_user_id(expert_uid, store):
    """Given an expert profile UID, get the linked user _id."""
    expert = store.experts.get(expert_uid)
    if not expert:
        return ""
    return _safe_get(expert, "User", "")


def _freelance_account_name(user):
    """Synthetic SF Account Name for a freelance expert (e.g. 'David Chui (Freelance)').

    Freelance experts have no agency; we mint one Account per expert so the
    Contact has something to link to. `user` here is the profile_expert's
    linked user record (post-_redact is fine — Name fields aren't sensitive).
    """
    first = _safe_get(user, "Name: First").strip()
    last = _safe_get(user, "Name: Last").strip()
    name = f"{first} {last}".strip() or _safe_get(user, "_id", "unknown")
    return f"{name} (Freelance)"


def _user_email(user):
    """Bubble exposes user email at user.authentication.email.email (see
    balo-bubble-data-api-swagger.json). _redact wipes the whole authentication
    object, so email must be pulled out BEFORE redaction runs.
    """
    if not user:
        return ""
    auth = user.get("authentication")
    if isinstance(auth, dict):
        em = auth.get("email")
        if isinstance(em, dict):
            val = em.get("email")
            if val:
                return val
    return user.get("email") or user.get("Email") or ""


def _meeting_type_slug(meeting):
    t = meeting.get("Type")
    if isinstance(t, dict):
        return t.get("slug", "")
    return str(t) if t else ""


# --- Provenance helpers ---
#
# Each transform_* returns (columns, rows, provenance) where provenance[i] is
# the list of {table, _id, label} dicts describing which Bubble records were
# read to build rows[i]. Separator rows get an empty list. `table` uses the
# keys from config.TABLE_PATHS so it stays canonical across the codebase.

def _src(table, _id, label=""):
    """One source tuple, or None if _id is falsy (so caller can filter)."""
    if not _id:
        return None
    return {"table": table, "_id": _id, "label": label}


def _sources(*items):
    return [x for x in items if x is not None]


# --- Sheet Transformers ---

def transform_accounts(store):
    """Sheet 1: Accounts — client companies + agencies."""
    columns = [
        "_group", "Balo_Id__c", "Name", "Phone", "Website", "Type",
        "AccountSource", "Stripe_Customer_Id__c", "Has_Booked_Consultation__c",
        "Has_Redeemed_Credits__c", "Has_Submitted_Project__c",
        "Balo_Created_Date__c", "Stripe_Seller_ID__c", "Stripe_Connection_Status__c",
    ]
    rows = []
    provenance = []

    # Client companies
    rows.append(_separator_row("Client Companies"))
    provenance.append([])
    for company in store.clientcompanies:
        admin_uid = _safe_get(company, "Admin")
        admin_user = store.users.get(admin_uid, {}) if admin_uid else {}

        # A company is "real" if at least one user has pure client roles (no expert roles).
        company_users = [u for u in store.users.values() if u.get("Company") == company["_id"]]
        has_real_client = any(
            not EXPERT_OR_ADMIN_ROLES.intersection(list_array_slugs(u.get("Roles", [])))
            for u in company_users
        ) if company_users else False

        rows.append({
            "_group": "CLIENT",
            "_has_real_client": has_real_client,
            "_admin_roles": list_array_slugs(admin_user.get("Roles", [])),
            "_admin_email": _safe_get(admin_user, "email", _safe_get(admin_user, "Email")),
            "Balo_Id__c": company["_id"],
            "Name": _safe_get(company, "Name"),
            "Phone": _safe_get(admin_user, "Phone"),
            "Website": "",
            "Type": "Company",
            "AccountSource": ACCOUNT_SOURCE,
            "Stripe_Customer_Id__c": _safe_get(company, "🤑 Stripe: Customer ID"),
            "Has_Booked_Consultation__c": _safe_get(company, "☑️ Consultation: Booked at least one"),
            "Has_Redeemed_Credits__c": _safe_get(company, "☑️ Credits: Redeemed at least one"),
            "Has_Submitted_Project__c": _safe_get(company, "☑️ Project request: Submitted at least one"),
            "Balo_Created_Date__c": _safe_get(company, "Created Date"),
            "Stripe_Seller_ID__c": "",
            "Stripe_Connection_Status__c": "",
        })
        provenance.append(_sources(
            _src("profile_clientcompany", company["_id"], "primary"),
            _src("user", admin_uid, "admin (Phone)"),
        ))

    # Agencies
    rows.append(_separator_row("Agencies"))
    provenance.append([])
    for agency in store.agencies:
        admin_uid = _safe_get(agency, "Admin")
        admin_user = store.users.get(admin_uid, {}) if admin_uid else {}

        rows.append({
            "_group": "AGENCY",
            "_admin_roles": list_array_slugs(admin_user.get("Roles", [])),
            "_admin_email": _safe_get(admin_user, "email", _safe_get(admin_user, "Email")),
            "Balo_Id__c": agency["_id"],
            "Name": _safe_get(agency, "Name"),
            "Phone": _safe_get(admin_user, "Phone"),
            "Website": _safe_get(agency, "Website"),
            "Type": "Expert",
            "AccountSource": ACCOUNT_SOURCE,
            "Stripe_Customer_Id__c": "",
            "Has_Booked_Consultation__c": "",
            "Has_Redeemed_Credits__c": "",
            "Has_Submitted_Project__c": "",
            "Balo_Created_Date__c": _safe_get(agency, "Created Date"),
            "Stripe_Seller_ID__c": _safe_get(agency, "🤑 Stripe: Seller ID"),
            "Stripe_Connection_Status__c": _safe_get(agency, "🤑 Stripe: Connection Active"),
        })
        provenance.append(_sources(
            _src("profile_agency", agency["_id"], "primary"),
            _src("user", admin_uid, "admin (Phone)"),
        ))

    # Freelance experts — one synthetic Account per expert so freelance
    # Contacts have an Account to link to. Balo_Id__c = profile_expert._id.
    rows.append(_separator_row("Freelance Experts (synthetic accounts)"))
    provenance.append([])
    for eid, expert in store.experts.items():
        if get_slug(expert.get("Expert type")) != "freelancer":
            continue
        user_uid = _safe_get(expert, "User")
        user = store.users.get(user_uid, {})

        rows.append({
            "_group": "FREELANCE",
            "Balo_Id__c": expert["_id"],
            "Name": _freelance_account_name(user),
            "Phone": _safe_get(user, "Phone"),
            "Website": "",
            "Type": "Expert",
            "AccountSource": ACCOUNT_SOURCE,
            "Stripe_Customer_Id__c": "",
            "Has_Booked_Consultation__c": "",
            "Has_Redeemed_Credits__c": "",
            "Has_Submitted_Project__c": "",
            "Balo_Created_Date__c": _safe_get(expert, "Created Date"),
            "Stripe_Seller_ID__c": "",
            "Stripe_Connection_Status__c": "",
        })
        provenance.append(_sources(
            _src("profile_expert", expert["_id"], "primary"),
            _src("user", user_uid, "user (Phone, Name)"),
        ))

    return columns, rows, provenance


def transform_prospects_contacts(store):
    """Sheet 2: Prospects & Contacts — wide row covering both endpoints."""
    columns = [
        "_group", "_contact_type",
        # Prospect fields
        "baloId", "email", "firstName", "lastName", "phone",
        "baloRole", "baloRoles", "prospectStatus", "signupDate",
        "timezone", "currencyCode", "country",
        "baloAccountId", "companyName", "accountType", "baloAccountCreatedDate",
        # Contact fields
        "RecordTypeId", "Expert_Type__c", "Is_Salesforce_Certified__c",
        "Is_CTA__c", "Is_MVP__c", "Salesforce_Start_Year__c",
        "Years_Experience__c", "Project_Count_Range__c",
        "Consultation_Min_Rate__c", "Average_Rating__c", "Total_Reviews__c",
        "LinkedIn_URL__c", "Trailblazer_URL__c", "Headline__c",
        "Application_Status__c", "Expert_Unique_ID__c", "Cronofy_User_ID__c",
        "MailingCountry", "Account.Balo_Id__c", "Balo_Role__c",
    ]
    rows = []
    provenance = []

    # Users that back a profile_expert record route via /crm/account + /crm/contact,
    # NOT /crm/prospect — even if they also have a client Company link.
    expert_user_ids = {
        expert.get("User")
        for expert in store.experts.values()
        if expert.get("User")
    }

    # --- Client users grouped by company ---
    for company in store.clientcompanies:
        cid = company["_id"]
        company_name = _safe_get(company, "Name", cid)
        rows.append(_separator_row(company_name))
        provenance.append([])

        for uid, user in store.users.items():
            if uid in expert_user_ids:
                continue  # routed as expert (Account + Contact), not prospect
            email = _user_email(user)
            user = _redact(user)
            if _safe_get(user, "Company") != cid:
                continue
            row, sources = _build_client_prospect_row(user, email, company, store)
            rows.append(row)
            provenance.append(sources)

    # --- Agency experts grouped by agency ---
    for agency in store.agencies:
        aid = agency["_id"]
        agency_name = _safe_get(agency, "Name", aid)
        rows.append(_separator_row(f"{agency_name} (Agency)"))
        provenance.append([])

        for eid, expert in store.experts.items():
            if _safe_get(expert, "Agency") != aid:
                continue
            user_uid = _safe_get(expert, "User")
            raw_user = store.users.get(user_uid, {})
            email = _user_email(raw_user)
            user = _redact(raw_user)
            row, sources = _build_expert_prospect_row(user, email, expert, agency_name, aid, "Expert", agency, store)
            rows.append(row)
            provenance.append(sources)

    # --- Freelance experts ---
    rows.append(_separator_row("Freelance Experts"))
    provenance.append([])
    for eid, expert in store.experts.items():
        expert_type = get_slug(expert.get("Expert type"))
        if expert_type != "freelancer":
            continue
        user_uid = _safe_get(expert, "User")
        raw_user = store.users.get(user_uid, {})
        email = _user_email(raw_user)
        user = _redact(raw_user)
        # Per-expert synthetic Account — Balo_Id__c = profile_expert._id.
        # The corresponding Account row is emitted by transform_accounts.
        synth_name = _freelance_account_name(user)
        synth_id = expert["_id"]
        row, sources = _build_expert_prospect_row(
            user, email, expert, synth_name, synth_id, "Expert", None, store
        )
        rows.append(row)
        provenance.append(sources)

    return columns, rows, provenance


def _build_client_prospect_row(user, email, company, store):
    row = {
        "_group": _safe_get(company, "Name"),
        "_contact_type": "CLIENT",
        "baloId": _safe_get(user, "_id"),
        "email": email,
        "firstName": _safe_get(user, "Name: First"),
        "lastName": _safe_get(user, "Name: Last"),
        "phone": _safe_get(user, "Phone"),
        "baloRole": get_slug(user.get("Role: Active")),
        "baloRoles": list_array_slugs(user.get("Roles", [])),
        "prospectStatus": PROSPECT_STATUS,
        "signupDate": _safe_get(user, "Created Date"),
        "timezone": _safe_get(user, "⚙️ Timezone ID"),
        "currencyCode": get_display(user.get("💱 Currency")),
        "country": _resolve_country(_safe_get(user, "⚙️ Country"), store, "Name"),
        "baloAccountId": company["_id"],
        "companyName": _safe_get(company, "Name"),
        "accountType": "Prospect",
        "baloAccountCreatedDate": _safe_get(company, "Created Date"),
        "RecordTypeId": RECORD_TYPE_CLIENT_CONTACT,
        "Expert_Type__c": "", "Is_Salesforce_Certified__c": "",
        "Is_CTA__c": "", "Is_MVP__c": "",
        "Salesforce_Start_Year__c": "", "Years_Experience__c": "",
        "Project_Count_Range__c": "", "Consultation_Min_Rate__c": "",
        "Average_Rating__c": "", "Total_Reviews__c": "",
        "LinkedIn_URL__c": "", "Trailblazer_URL__c": "",
        "Headline__c": "", "Application_Status__c": "",
        "Expert_Unique_ID__c": "", "Cronofy_User_ID__c": "",
        "MailingCountry": "",
        "Account.Balo_Id__c": company["_id"],
        "Balo_Role__c": get_slug(user.get("Role: Active")),
    }
    sources = _sources(
        _src("user", _safe_get(user, "_id"), "primary"),
        _src("profile_clientcompany", company["_id"], "company"),
        _src("country", _safe_get(user, "⚙️ Country"), "country (Name)"),
    )
    return row, sources


def _build_expert_prospect_row(user, email, expert, account_name, account_id, account_type, account_record, store):
    certs = expert.get("Certifications", expert.get("Case", []))
    # Certifications may be stored as array; check if expert has any certification-related fields
    has_certs = bool(expert.get("Certifications")) or bool(expert.get("Certified Salesforce Trainer?"))

    row = {
        "_group": account_name or "Freelance",
        "_contact_type": "EXPERT",
        "baloId": _safe_get(user, "_id"),
        "email": email,
        "firstName": _safe_get(user, "Name: First"),
        "lastName": _safe_get(user, "Name: Last"),
        "phone": _safe_get(user, "Phone"),
        "baloRole": get_slug(user.get("Role: Active")),
        "baloRoles": list_array_slugs(user.get("Roles", [])),
        "prospectStatus": PROSPECT_STATUS,
        "signupDate": _safe_get(user, "Created Date"),
        "timezone": _safe_get(user, "⚙️ Timezone ID"),
        "currencyCode": get_display(user.get("💱 Currency")),
        "country": _resolve_country(_safe_get(user, "⚙️ Country"), store, "Name"),
        "baloAccountId": account_id if account_id else "",
        "companyName": account_name if account_name else "",
        "accountType": account_type if account_type else "",
        "baloAccountCreatedDate": _safe_get(account_record, "Created Date") if account_record else "",
        "RecordTypeId": RECORD_TYPE_EXPERT_CONTACT,
        "Expert_Type__c": get_slug(expert.get("Expert type")),
        "Is_Salesforce_Certified__c": has_certs,
        "Is_CTA__c": _safe_get(expert, "Salesforce CTA?"),
        "Is_MVP__c": _safe_get(expert, "Salesforce MVP?"),
        "Salesforce_Start_Year__c": str(int(_safe_get(expert, "Started at Salesforce (Year)", 0) or 0)) if _safe_get(expert, "Started at Salesforce (Year)") else "",
        "Years_Experience__c": str(int(_safe_get(expert, "Years of experience", 0) or 0)) if _safe_get(expert, "Years of experience") else "",
        "Project_Count_Range__c": get_slug(expert.get("No. Salesforce projects involved")),
        "Consultation_Min_Rate__c": _safe_get(expert, "Rate (per min)"),
        "Average_Rating__c": _safe_get(expert, "Average Rating"),
        "Total_Reviews__c": _safe_get(expert, "Total Reviews"),
        "LinkedIn_URL__c": _safe_get(expert, "Linkedin URL"),
        "Trailblazer_URL__c": _safe_get(expert, "Trailblazer profile URL"),
        "Headline__c": _safe_get(expert, "Profile Headline"),
        "Application_Status__c": get_slug(expert.get("Application: Status")),
        "Expert_Unique_ID__c": expert["_id"],
        "Cronofy_User_ID__c": _safe_get(expert, "⚙️ Cronofy User ID"),
        "MailingCountry": _resolve_country(_safe_get(expert, "Country"), store, "Alpha-2 code"),
        "Account.Balo_Id__c": account_id if account_id else "",
        "Balo_Role__c": "",
    }
    sources = _sources(
        _src("user", _safe_get(user, "_id"), "primary"),
        _src("profile_expert", expert.get("_id"), "expert profile"),
        _src("profile_agency", account_id, "agency") if account_type == "Expert" else None,
        _src("country", _safe_get(expert, "Country"), "MailingCountry (Alpha-2)"),
    )
    return row, sources


def transform_opportunities_cases(store):
    """Sheet 3: Opportunities (Cases)."""
    columns = [
        "_group", "Balo_Id__c", "Name", "CloseDate", "StageName", "RecordTypeId",
        "Balo_Case_Number__c", "Description", "Total_Consultation_Minutes__c",
        "Total_Credits_Used__c", "Amount", "Expert_Earnings__c", "Balo_Created_Date__c",
        "Product__c", "Type_of_Support__c",
        "Account.Balo_Id__c", "Primary_Contact__r.Balo_Id__c", "Expert__r.Balo_Id__c",
    ]
    rows = []
    provenance = []

    # Group cases by client company
    company_map = {c["_id"]: c for c in store.clientcompanies}

    current_company = None
    for case in store.cases:
        cc_uid = _safe_get(case, "Client company")
        company = company_map.get(cc_uid, {})
        company_name = _safe_get(company, "Name", cc_uid)

        if cc_uid != current_company:
            rows.append(_separator_row(company_name))
            provenance.append([])
            current_company = cc_uid

        # Support field: may be single option set or array
        support = case.get("Support")
        if isinstance(support, list):
            type_of_support = ";".join(get_slug(s) for s in support if get_slug(s))
        else:
            type_of_support = get_slug(support)

        # First expert's user _id
        expert_profiles = case.get("Expert Profiles", [])
        expert_profile_uid = expert_profiles[0] if expert_profiles else ""
        expert_user_uid = _expert_user_id(expert_profile_uid, store) if expert_profile_uid else ""

        # StageName: SF picklist expects Title-case ("Ongoing"), Bubble stores slugs ("ongoing").
        status_val = case.get("Status")
        stage_name = get_display(status_val) if isinstance(status_val, dict) else (str(status_val).capitalize() if status_val else "")

        rows.append({
            "_group": company_name,
            "Balo_Id__c": case["_id"],
            "Name": _safe_get(case, "Title"),
            "CloseDate": "",  # intentionally blank
            "StageName": stage_name,
            "RecordTypeId": RECORD_TYPE_CASE_OPPORTUNITY,
            "Balo_Case_Number__c": _safe_get(case, "Case ID"),
            "Description": _safe_get(case, "Description"),
            "Total_Consultation_Minutes__c": _safe_get(case, "Total consultation minutes"),
            "Total_Credits_Used__c": _safe_get(case, "Total credits used"),
            "Amount": _safe_get(case, "Total credits used"),
            "Expert_Earnings__c": _safe_get(case, "Total amount earned"),
            "Balo_Created_Date__c": _safe_get(case, "Created Date"),
            "Product__c": join_array_slugs(case.get("Products", [])),
            "Type_of_Support__c": type_of_support,
            "Account.Balo_Id__c": cc_uid,
            "Primary_Contact__r.Balo_Id__c": _safe_get(case, "Client user"),
            "Expert__r.Balo_Id__c": expert_user_uid,
        })
        provenance.append(_sources(
            _src("case", case["_id"], "primary"),
            _src("profile_clientcompany", cc_uid, "client company"),
            _src("profile_expert", expert_profile_uid, "first expert profile"),
        ))

    return columns, rows, provenance


def transform_opportunities_projects(store):
    """Sheet 4: Opportunities (Projects) — with conditional stage logic."""
    columns = [
        "_group", "_source_stage", "Balo_Id__c", "Name", "CloseDate",
        "StageName", "Sub_status__c", "RecordTypeId", "RecordTypeId_CONFIRM",
        "Description", "Project_Tag__c", "Sourcing_Mode__c", "Package__c",
        "Active_Proposal_Count__c", "Discovery_Insights__c", "Submitted_Date__c",
        "Balo_Created_Date__c", "Product__c", "Project_ID__c",
        "Total_Cost_Inc_Fees__c", "GST_Charged__c", "Expert_Earnings__c",
        "Account.Balo_Id__c", "Primary_Contact__r.Balo_Id__c",
        "Related_Case__r.Balo_Id__c",
    ]
    rows = []
    provenance = []

    company_map = {c["_id"]: c for c in store.clientcompanies}
    case_map = {c["_id"]: c for c in store.cases}

    for req in store.project_requests:
        cc_uid = _safe_get(req, "Client Company")
        company = company_map.get(cc_uid, {})
        company_name = _safe_get(company, "Name", cc_uid)

        has_final = bool(req.get("Final EOI") or req.get("Final Project/Proposal"))
        mode_slug = get_slug(req.get("Mode"))
        proj_uid = ""

        if has_final:
            proj_uid = req.get("Final Project/Proposal") or ""
            proj = store.projects.get(proj_uid, {})
            name = _safe_get(proj, "Project title")
            stage_name = "Project"
            sub_status = get_slug(proj.get("Status"))
            close_date = _safe_get(proj, "Estimated Completion Date")
            description = _safe_get(proj, "Project description (RT)")
            created_date = _safe_get(proj, "Created Date")
            project_id = _safe_get(proj, "_id")
            total_cost = _safe_get(proj, "Total Cost (Including Fees)")
            gst = _safe_get(proj, "GST Charged", "")  # may not exist
            expert_earnings = _safe_get(proj, "Total Cost (Excluding Fees)")
            source_stage = "Project (finalized)"
        else:
            name = _smart_field(req, mode_slug, "Title")
            stage_name = "Request"
            sub_status = get_slug(req.get("Status"))
            close_date = ""
            description = _smart_field(req, mode_slug, "Description")
            created_date = _safe_get(req, "Created Date")
            project_id = ""
            total_cost = ""
            gst = ""
            expert_earnings = ""
            source_stage = "Request (no final EOI)"

        # Mode-based fields (always from project:request)
        product_arr = _smart_field(req, mode_slug, "Products")
        tag_arr = _smart_field(req, mode_slug, "Project Tag")

        rows.append({
            "_group": company_name,
            "_source_stage": source_stage,
            "Balo_Id__c": req["_id"],
            "Name": name,
            "CloseDate": close_date,
            "StageName": stage_name,
            "Sub_status__c": sub_status,
            "RecordTypeId": RECORD_TYPE_PROJECT_OPPORTUNITY,
            "RecordTypeId_CONFIRM": f"FLAG: confirm {RECORD_TYPE_PROJECT_OPPORTUNITY} vs {RECORD_TYPE_CASE_OPPORTUNITY}",
            "Description": description,
            "Project_Tag__c": join_array_slugs(tag_arr) if isinstance(tag_arr, list) else str(tag_arr or ""),
            "Sourcing_Mode__c": mode_slug,
            "Package__c": _safe_get(req, "Package"),
            "Active_Proposal_Count__c": _safe_get(req, "Active Proposal Count"),
            "Discovery_Insights__c": _safe_get(req, "Discovery Call Insights"),
            "Submitted_Date__c": _safe_get(req, "Submitted Date"),
            "Balo_Created_Date__c": created_date,
            "Product__c": join_array_slugs(product_arr) if isinstance(product_arr, list) else str(product_arr or ""),
            "Project_ID__c": project_id,
            "Total_Cost_Inc_Fees__c": total_cost,
            "GST_Charged__c": gst,
            "Expert_Earnings__c": expert_earnings,
            "Account.Balo_Id__c": cc_uid,
            "Primary_Contact__r.Balo_Id__c": _safe_get(req, "Client User"),
            "Related_Case__r.Balo_Case_Number__c": _safe_get(
                case_map.get(_safe_get(req, "Selected Case"), {}), "Case ID"
            ),
        })
        provenance.append(_sources(
            _src("project_request", req["_id"], "request"),
            _src("project", proj_uid, "finalized project") if has_final else None,
            _src("profile_clientcompany", cc_uid, "client company"),
        ))

    return columns, rows, provenance


def transform_project_experts(store):
    """Sheet 5: Expert-Project links (Project__c)."""
    columns = [
        "_group", "Balo_Id__c",
        "EOI_Status__c", "EOI_Submitted_Date__c", "Proposal_Submitted_Date__c",
        "Finalized_Date__c", "Proposal_Status__c", "Estimated_Completion_Date__c",
        "Experts_Proposed_Cost__c", "Pricing_Method__c", "Hourly_Rate__c",
        "Payment_Terms__c", "Customer_Cost__c", "Total_Hours__c",
        "Opportunity__r.Balo_Id__c", "Expert__r.Balo_Id__c",
    ]
    rows = []
    provenance = []

    req_map = {r["_id"]: r for r in store.project_requests}
    company_map = {c["_id"]: c for c in store.clientcompanies}

    # Pre-compute total hours per project from deliverables
    project_hours = {}
    for d in store.deliverables:
        proj_uid = _safe_get(d, "Project")
        hours = _safe_get(d, "Hours", 0)
        if proj_uid and hours:
            try:
                project_hours[proj_uid] = project_hours.get(proj_uid, 0) + float(hours)
            except (ValueError, TypeError):
                pass

    for eoi in store.project_eois:
        req_uid = _safe_get(eoi, "Request")
        req = req_map.get(req_uid, {})
        cc_uid = _safe_get(req, "Client Company")
        company = company_map.get(cc_uid, {})
        company_name = _safe_get(company, "Name", "")

        expert_uid = _safe_get(eoi, "Expert")
        expert_user_uid = _expert_user_id(expert_uid, store)

        # EOI.Proposal links directly to the Project (if one exists)
        proj_uid = _safe_get(eoi, "Proposal")
        proj = store.projects.get(proj_uid, {}) if proj_uid else {}

        # Total hours from deliverables (if available)
        total_hours = project_hours.get(proj_uid, "") if proj_uid else ""

        rows.append({
            "_group": company_name,
            "Balo_Id__c": f"{req_uid}-{expert_user_uid}" if req_uid and expert_user_uid else "",
            # EOI fields
            "EOI_Status__c": get_slug(eoi.get("Status")),
            "EOI_Submitted_Date__c": _safe_get(eoi, "Created Date"),
            "Proposal_Submitted_Date__c": _safe_get(eoi, "Pitch Submitted at"),
            # Project fields (empty if no finalized project)
            "Finalized_Date__c": _safe_get(proj, "Created Date"),
            "Proposal_Status__c": get_slug(proj.get("Status")),
            "Estimated_Completion_Date__c": _safe_get(proj, "Estimated Completion Date"),
            "Experts_Proposed_Cost__c": _safe_get(proj, "Total Cost (Excluding Fees)"),
            "Pricing_Method__c": _safe_get(proj, "Pricing Model"),
            "Hourly_Rate__c": _safe_get(proj, "Hourly Rate (Excluding fees)"),
            "Payment_Terms__c": _safe_get(proj, "Payment Structure"),
            "Customer_Cost__c": _safe_get(proj, "Total Cost (Including Fees)"),
            "Total_Hours__c": total_hours,
            "Opportunity__r.Balo_Id__c": req_uid,
            "Expert__r.Balo_Id__c": expert_user_uid,
        })
        provenance.append(_sources(
            _src("project_eoi", eoi["_id"], "primary"),
            _src("project_request", req_uid, "request"),
            _src("project", proj_uid, "finalized project") if proj_uid else None,
            _src("profile_expert", expert_uid, "expert profile"),
            _src("profile_clientcompany", cc_uid, "client company"),
        ))

    return columns, rows, provenance


def transform_consultations(store):
    """Sheet 6: Consultations — primary table is meeting."""
    columns = [
        "_group", "_meeting_type", "Balo_Id__c",
        "Opportunity__r.Balo_Id__c", "Project__r.Balo_Id__c",
        "Expert__r.Balo_Id__c", "Scheduled_DateTime__c",
        "Start_Time__c", "End_Time__c", "Actual_End_Time__c",
        "Duration_Minutes__c", "Actual_Duration_Minutes__c",
        "Status__c", "Billing_Mode__c",
        "Expert_Rate__c", "Estimated_Cost__c", "Final_Cost__c", "GST_Amount__c",
        "Cancellation_Allowed__c", "Cancellation_Reason__c", "Cancelled_By__c",
        "Client_Join_Time__c", "Expert_Join_Time__c",
        "Ended_By_Expert__c", "Ended_By_Client__c",
        "Participants_Present__c", "Balo_Created_Date__c",
    ]
    rows = []
    provenance = []

    company_map = {c["_id"]: c for c in store.clientcompanies}

    # Separate consultation and project meetings
    consult_meetings = []
    project_meetings = []

    for meeting in store.meetings:
        type_slug = _meeting_type_slug(meeting)
        if type_slug == "consultation":
            consult_meetings.append(meeting)
        else:
            project_meetings.append(meeting)

    # Consultation meetings first
    if consult_meetings:
        rows.append(_separator_row("Consultations (metered billing)"))
        provenance.append([])
    for meeting in consult_meetings:
        row, sources = _build_meeting_row(meeting, store, company_map)
        rows.append(row)
        provenance.append(sources)

    # Project meetings
    if project_meetings:
        rows.append(_separator_row("Project Meetings (free)"))
        provenance.append([])
    for meeting in project_meetings:
        row, sources = _build_meeting_row(meeting, store, company_map)
        rows.append(row)
        provenance.append(sources)

    return columns, rows, provenance


def _build_meeting_row(meeting, store, company_map):
    type_slug = _meeting_type_slug(meeting)
    is_consultation = type_slug == "consultation"

    cc_uid = _safe_get(meeting, "Client Company")
    company = company_map.get(cc_uid, {})
    company_name = _safe_get(company, "Name", cc_uid)

    # Expert user ID
    expert_profile_uid = _safe_get(meeting, "Profile Expert")
    expert_user_uid = _expert_user_id(expert_profile_uid, store)

    # Conditional fields
    opp_id = ""
    proj_id = ""
    expert_rate = ""
    estimated_cost = ""
    final_cost = ""
    gst_amount = ""
    consult_uid = ""
    pm_uid = ""
    pm_expert_uid = ""

    if is_consultation:
        consult_uid = _safe_get(meeting, "🆕 Consultation")
        consult = store.consultations.get(consult_uid, {})
        opp_id = _safe_get(consult, "Case")
        expert_rate = _safe_get(consult, "Expert Rate")
        estimated_cost = _safe_get(consult, "Cost estimated")
        final_cost = _safe_get(consult, "Cost Incurred Final")
        gst_amount = _safe_get(consult, "GST Charged")
    else:
        pm_uid = _safe_get(meeting, "🆕 Project Meeting")
        pm = store.projectmeetings.get(pm_uid, {})
        pr_uid = _safe_get(pm, "Project Request", _safe_get(pm, "Project"))
        pm_expert_uid = _safe_get(pm, "Expert")
        pm_expert_user = _expert_user_id(pm_expert_uid, store) if pm_expert_uid else ""
        if pr_uid and pm_expert_user:
            proj_id = f"{pr_uid}-{pm_expert_user}"

    # Cancelled By: resolve user UID to "Client" or "Expert"
    cancelled_by_uid = _safe_get(meeting, "Cancelled By")
    cancelled_by = ""
    if cancelled_by_uid:
        # Check if this user is the Invitor (client) or Organiser (expert)
        if cancelled_by_uid == _safe_get(meeting, "Invitor"):
            cancelled_by = "Client"
        elif cancelled_by_uid == _safe_get(meeting, "Organiser"):
            cancelled_by = "Expert"
        else:
            cancelled_by = "Client"  # default

    # Status and Billing Mode: capitalize for SF
    status_val = meeting.get("Status")
    status = get_display(status_val) if isinstance(status_val, dict) else (str(status_val).capitalize() if status_val else "")

    billing_val = meeting.get("🆕 Billing Mode")
    billing = get_display(billing_val) if isinstance(billing_val, dict) else (str(billing_val).capitalize() if billing_val else "")

    row = {
        "_group": company_name,
        "_meeting_type": type_slug,
        "Balo_Id__c": meeting["_id"],
        "Opportunity__r.Balo_Id__c": opp_id,
        "Project__r.Balo_Id__c": proj_id,
        "Expert__r.Balo_Id__c": expert_user_uid,
        "Scheduled_DateTime__c": _safe_get(meeting, "Created Date"),
        "Start_Time__c": _safe_get(meeting, "Date: Start (Booked)"),
        "End_Time__c": _safe_get(meeting, "Date: End (Booked)"),
        "Actual_End_Time__c": _safe_get(meeting, "Date: End (Actual)"),
        "Duration_Minutes__c": _safe_get(meeting, "Scheduled Duration"),
        "Actual_Duration_Minutes__c": _safe_get(meeting, "Actual Duration"),
        "Status__c": status,
        "Billing_Mode__c": billing,
        "Expert_Rate__c": expert_rate,
        "Estimated_Cost__c": estimated_cost,
        "Final_Cost__c": final_cost,
        "GST_Amount__c": gst_amount,
        "Cancellation_Allowed__c": _safe_get(meeting, "Cancellation Allowed"),
        "Cancellation_Reason__c": _safe_get(meeting, "Cancellation Reason"),
        "Cancelled_By__c": cancelled_by,
        "Client_Join_Time__c": _safe_get(meeting, "Invitor Join time"),
        "Expert_Join_Time__c": _safe_get(meeting, "Organiser Join time"),
        "Ended_By_Expert__c": _safe_get(meeting, "Ended by Organizer"),
        "Ended_By_Client__c": _safe_get(meeting, "Ended by Invitor"),
        # SF requires True/False (not null). Bubble only computes "Summary Present [Temp]"
        # for completed meetings — missed/cancelled meetings have no value, default to False.
        "Participants_Present__c": bool(meeting.get("Summary Present [Temp]")),
        "Balo_Created_Date__c": _safe_get(meeting, "Created Date"),
    }
    sources = _sources(
        _src("meeting", meeting["_id"], "primary"),
        _src("consultation", consult_uid, "consultation") if is_consultation else None,
        _src("projectmeeting", pm_uid, "project meeting") if not is_consultation else None,
        _src("profile_expert", expert_profile_uid, "meeting expert profile"),
        _src("profile_expert", pm_expert_uid, "PM expert profile") if not is_consultation else None,
        _src("profile_clientcompany", cc_uid, "client company"),
    )
    return row, sources


def transform_all(store):
    """Run all transformers and return a dict of {sheet_name: (columns, rows, provenance)}.

    provenance[i] is the list of {table, _id, label} dicts describing which
    Bubble records were read to build rows[i]. Separator rows have [].
    """
    return {
        "Accounts": transform_accounts(store),
        "Prospects & Contacts": transform_prospects_contacts(store),
        "Opportunities - Cases": transform_opportunities_cases(store),
        "Opportunities - Projects": transform_opportunities_projects(store),
        "Project Experts": transform_project_experts(store),
        "Consultations": transform_consultations(store),
    }
