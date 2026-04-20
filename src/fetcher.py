import sys

from src.config import TABLE_PATHS, ENV_COMPANY_IDS, ENV_AGENCY_IDS
from src.manifest import get_exported_ids


class DataStore:
    """Holds all fetched records, keyed by table name.

    List tables store records as lists (order matters for output).
    Lookup tables store records as {uid: record} dicts for fast access.
    """

    def __init__(self):
        # List tables (ordered, for iteration)
        self.clientcompanies = []
        self.agencies = []
        self.cases = []
        self.project_requests = []
        self.project_eois = []
        self.meetings = []

        # Lookup tables (keyed by _id)
        self.users = {}
        self.experts = {}
        self.countries = {}
        self.projects = {}
        self.consultations = {}
        self.projectmeetings = {}
        self.packages = {}

        # Warnings accumulated during fetch
        self.warnings = []


class Fetcher:
    def __init__(self, client, company_ids=None, agency_ids=None):
        self.client = client
        self.store = DataStore()
        self.company_ids = company_ids or ENV_COMPANY_IDS
        self.agency_ids = agency_ids or ENV_AGENCY_IDS
        self._fetched_uids = {}  # {table_key: set()} for deduplication

    def _log(self, msg):
        print(f"  {msg}", file=sys.stderr)

    def _uid_seen(self, table_key, uid):
        if table_key not in self._fetched_uids:
            self._fetched_uids[table_key] = set()
        if uid in self._fetched_uids[table_key]:
            return True
        self._fetched_uids[table_key].add(uid)
        return False

    def _ensure_user(self, uid):
        if not uid or uid in self.store.users:
            return self.store.users.get(uid)
        if self._uid_seen("user", uid):
            return self.store.users.get(uid)
        record = self.client.fetch_record(TABLE_PATHS["user"], uid)
        if record:
            self.store.users[uid] = record
        else:
            self.store.warnings.append(f"User not found: {uid}")
        return record

    def _ensure_expert(self, uid):
        if not uid or uid in self.store.experts:
            return self.store.experts.get(uid)
        if self._uid_seen("profile_expert", uid):
            return self.store.experts.get(uid)
        record = self.client.fetch_record(TABLE_PATHS["profile_expert"], uid)
        if record:
            self.store.experts[uid] = record
            # Also fetch the linked user
            user_uid = record.get("User")
            if user_uid:
                self._ensure_user(user_uid)
        else:
            self.store.warnings.append(f"Expert profile not found: {uid}")
        return record

    def fetch_all(self):
        self._round1_anchors()
        self._round2_users_experts()
        self._round3_cases_projects()
        self._round4_meetings()
        self._round5_packages()
        return self.store

    # --- Round 1: Anchor entities ---

    def _round1_anchors(self):
        self._log("Round 1: Fetching anchor entities...")

        # Client companies
        if self.company_ids:
            self._log(f"  Fetching {len(self.company_ids)} specified companies")
            for cid in self.company_ids:
                record = self.client.fetch_record(TABLE_PATHS["profile_clientcompany"], cid)
                if record:
                    self.store.clientcompanies.append(record)
                else:
                    self.store.warnings.append(f"Company not found: {cid}")
        else:
            self._log("  Scouting for data-rich companies...")
            all_companies = self.client.fetch_all_pages(
                TABLE_PATHS["profile_clientcompany"], max_pages=5
            )
            # Exclude already-exported companies
            prev_exported = get_exported_ids("clientcompanies")
            if prev_exported:
                self._log(f"  Excluding {len(prev_exported)} previously exported companies")

            # Score by data richness: cases, consultations, projects, staff, stripe
            scored = []
            for c in all_companies:
                if c["_id"] in prev_exported:
                    continue
                score = 0
                if c.get("☑️ Consultation: Booked at least one"): score += 3
                if c.get("☑️ Project request: Submitted at least one"): score += 3
                if c.get("☑️ Credits: Redeemed at least one"): score += 2
                score += len(c.get("Staff", []))
                score += len(c.get("Case", []))
                if c.get("Admin"): score += 1
                if c.get("🤑 Stripe: Customer ID"): score += 1
                scored.append((score, c))
            scored.sort(key=lambda x: -x[0])
            self.store.clientcompanies = [c for _, c in scored[:3]]
            for _, c in scored[:3]:
                self._log(f"    Selected: {c.get('Name', 'N/A')} (score {_})")

        self._log(f"  -> {len(self.store.clientcompanies)} companies")

        # Agencies
        if self.agency_ids:
            self._log(f"  Fetching {len(self.agency_ids)} specified agencies")
            for aid in self.agency_ids:
                record = self.client.fetch_record(TABLE_PATHS["profile_agency"], aid)
                if record:
                    self.store.agencies.append(record)
                else:
                    self.store.warnings.append(f"Agency not found: {aid}")
        else:
            self._log("  Scouting for data-rich agencies...")
            all_agencies = self.client.fetch_all_pages(
                TABLE_PATHS["profile_agency"], max_pages=3
            )
            # Exclude already-exported agencies
            prev_exported = get_exported_ids("agencies")
            if prev_exported:
                self._log(f"  Excluding {len(prev_exported)} previously exported agencies")

            # Score by data richness: experts, stripe, website
            scored = []
            for a in all_agencies:
                if a["_id"] in prev_exported:
                    continue
                score = 0
                score += len(a.get("Expert Profiles", [])) * 2
                if a.get("🤑 Stripe: Seller ID"): score += 2
                if a.get("🤑 Stripe: Connection Active"): score += 2
                if a.get("Admin"): score += 1
                if a.get("Website"): score += 1
                scored.append((score, a))
            scored.sort(key=lambda x: -x[0])
            self.store.agencies = [a for _, a in scored[:3]]
            for _, a in scored[:3]:
                self._log(f"    Selected: {a.get('Name', 'N/A')} (score {_})")

        self._log(f"  -> {len(self.store.agencies)} agencies")

        # Countries (full reference table)
        self._log("  Fetching countries (reference table)")
        countries = self.client.fetch_all_pages(TABLE_PATHS["country"])
        for c in countries:
            self.store.countries[c["_id"]] = c
        self._log(f"  -> {len(self.store.countries)} countries")

    # --- Round 2: Users & Experts ---

    def _round2_users_experts(self):
        self._log("Round 2: Fetching users and experts...")

        # Client users (for each company)
        for company in self.store.clientcompanies:
            cid = company["_id"]
            company_name = company.get("Name", cid)

            # Fetch users linked to this company
            resp = self.client.fetch_list(
                TABLE_PATHS["user"],
                constraints=[{"key": "Company", "constraint_type": "equals", "value": cid}],
                limit=10,
            )
            for user in resp.get("results", []):
                self.store.users[user["_id"]] = user

            # Also ensure the Admin user is fetched
            admin_uid = company.get("Admin")
            if admin_uid:
                self._ensure_user(admin_uid)

            self._log(f"  -> {company_name}: fetched users")

        # Agency experts (for each agency)
        for agency in self.store.agencies:
            aid = agency["_id"]
            agency_name = agency.get("Name", aid)

            resp = self.client.fetch_list(
                TABLE_PATHS["profile_expert"],
                constraints=[{"key": "Agency", "constraint_type": "equals", "value": aid}],
                limit=5,
            )
            for expert in resp.get("results", []):
                self.store.experts[expert["_id"]] = expert
                user_uid = expert.get("User")
                if user_uid:
                    self._ensure_user(user_uid)

            # Also ensure agency admin user
            admin_uid = agency.get("Admin")
            if admin_uid:
                self._ensure_user(admin_uid)

            self._log(f"  -> {agency_name}: fetched experts + users")

        # Freelance experts — prefer ones with ratings/activity
        self._log("  Fetching freelance experts (with ratings)")
        resp = self.client.fetch_list(
            TABLE_PATHS["profile_expert"],
            constraints=[
                {"key": "Expert type", "constraint_type": "equals", "value": "freelancer"},
                {"key": "Total Reviews", "constraint_type": "greater than", "value": 0},
            ],
            limit=3,
        )
        if not resp.get("results"):
            self._log("  No rated freelancers found, trying any freelancers...")
            resp = self.client.fetch_list(
                TABLE_PATHS["profile_expert"],
                constraints=[{"key": "Expert type", "constraint_type": "equals", "value": "freelancer"}],
                limit=3,
            )
        for expert in resp.get("results", []):
            self.store.experts[expert["_id"]] = expert
            user_uid = expert.get("User")
            if user_uid:
                self._ensure_user(user_uid)

        self._log(f"  -> Total users: {len(self.store.users)}, experts: {len(self.store.experts)}")

    # --- Round 3: Cases & Projects ---

    def _round3_cases_projects(self):
        self._log("Round 3: Fetching cases and projects...")

        company_ids = [c["_id"] for c in self.store.clientcompanies]

        # Cases (2 per company)
        for cid in company_ids:
            resp = self.client.fetch_list(
                TABLE_PATHS["case"],
                constraints=[{"key": "Client company", "constraint_type": "equals", "value": cid}],
                limit=2,
            )
            for case in resp.get("results", []):
                self.store.cases.append(case)
                # Ensure experts referenced in this case are fetched
                for expert_uid in case.get("Expert Profiles", []):
                    self._ensure_expert(expert_uid)

        self._log(f"  -> {len(self.store.cases)} cases")

        # Project requests — first try per company, then supplement with data-rich ones
        seen_request_ids = set()
        for cid in company_ids:
            resp = self.client.fetch_list(
                TABLE_PATHS["project_request"],
                constraints=[{"key": "Client Company", "constraint_type": "equals", "value": cid}],
                limit=2,
            )
            for req in resp.get("results", []):
                if req["_id"] not in seen_request_ids:
                    self.store.project_requests.append(req)
                    seen_request_ids.add(req["_id"])

        # If we have fewer than 3, fetch ones that have finalized projects (richer data)
        if len(self.store.project_requests) < 3:
            self._log("  Supplementing with project requests that have finalized projects...")
            resp = self.client.fetch_list(
                TABLE_PATHS["project_request"],
                constraints=[
                    {"key": "Final Project/Proposal", "constraint_type": "is_not_empty"},
                ],
                limit=3,
            )
            for req in resp.get("results", []):
                if req["_id"] not in seen_request_ids:
                    self.store.project_requests.append(req)
                    seen_request_ids.add(req["_id"])

        # If still fewer than 3, fetch ones with EOIs
        if len(self.store.project_requests) < 3:
            self._log("  Supplementing with project requests that have EOIs...")
            resp = self.client.fetch_list(
                TABLE_PATHS["project_request"],
                constraints=[
                    {"key": "EoIs", "constraint_type": "is_not_empty"},
                ],
                limit=3,
            )
            for req in resp.get("results", []):
                if req["_id"] not in seen_request_ids:
                    self.store.project_requests.append(req)
                    seen_request_ids.add(req["_id"])

        self._log(f"  -> {len(self.store.project_requests)} project requests")

        # Projects (for finalized requests)
        for req in self.store.project_requests:
            proj_uid = req.get("Final Project/Proposal")
            if proj_uid and proj_uid not in self.store.projects:
                record = self.client.fetch_record(TABLE_PATHS["project"], proj_uid)
                if record:
                    self.store.projects[proj_uid] = record

        self._log(f"  -> {len(self.store.projects)} finalized projects")

        # EOIs (for our project requests)
        for req in self.store.project_requests:
            eoi_ids = req.get("EoIs", [])
            for eoi_id in eoi_ids:
                if not self._uid_seen("project_eoi", eoi_id):
                    record = self.client.fetch_record(TABLE_PATHS["project_eoi"], eoi_id)
                    if record:
                        self.store.project_eois.append(record)
                        # Ensure the expert is fetched
                        expert_uid = record.get("Expert")
                        if expert_uid:
                            self._ensure_expert(expert_uid)

        self._log(f"  -> {len(self.store.project_eois)} EOIs")

    # --- Round 4: Meetings & Consultations ---

    def _round4_meetings(self):
        self._log("Round 4: Fetching meetings and consultations...")

        company_ids = [c["_id"] for c in self.store.clientcompanies]

        # Meetings (by client company)
        for cid in company_ids:
            resp = self.client.fetch_list(
                TABLE_PATHS["meeting"],
                constraints=[{"key": "Client Company", "constraint_type": "equals", "value": cid}],
                limit=5,
            )
            for meeting in resp.get("results", []):
                self.store.meetings.append(meeting)

        self._log(f"  -> {len(self.store.meetings)} meetings")

        # For each meeting, fetch linked consultation or projectmeeting
        for meeting in self.store.meetings:
            meeting_type = meeting.get("Type")
            type_slug = meeting_type if isinstance(meeting_type, str) else (meeting_type.get("slug", "") if isinstance(meeting_type, dict) else "")

            if type_slug == "consultation":
                consult_uid = meeting.get("🆕 Consultation")
                if consult_uid and consult_uid not in self.store.consultations:
                    record = self.client.fetch_record(TABLE_PATHS["consultation"], consult_uid)
                    if record:
                        self.store.consultations[consult_uid] = record
            else:
                pm_uid = meeting.get("🆕 Project Meeting")
                if pm_uid and pm_uid not in self.store.projectmeetings:
                    record = self.client.fetch_record(TABLE_PATHS["projectmeeting"], pm_uid)
                    if record:
                        self.store.projectmeetings[pm_uid] = record

            # Ensure expert profile is fetched
            expert_uid = meeting.get("Profile Expert")
            if expert_uid:
                self._ensure_expert(expert_uid)

        self._log(f"  -> {len(self.store.consultations)} consultations, {len(self.store.projectmeetings)} project meetings")

    # --- Round 5: Packages ---

    def _round5_packages(self):
        self._log("Round 5: Fetching packages...")

        for req in self.store.project_requests:
            pkg_uid = req.get("Package")
            if pkg_uid and pkg_uid not in self.store.packages:
                record = self.client.fetch_record(TABLE_PATHS["package"], pkg_uid)
                if record:
                    self.store.packages[pkg_uid] = record

        self._log(f"  -> {len(self.store.packages)} packages")
