#!/usr/bin/env python3
"""Balo Bubble.io → sf-middleware-api historic sync.

One subcommand per route. Fetch → transform → send.

    python sync.py --list
    python sync.py prospects --full
    python sync.py accounts --full
    python sync.py contacts --full
    python sync.py cases --limit 5 --dry-run
    python sync.py projects
    python sync.py project-experts
    python sync.py consultations

Shared flags:
    --limit N        stop after N successful sends (skipped rows don't count)
    --dry-run        fetch + transform + log to sync.db, but do NOT POST
    --since <iso>    override the auto-derived modified_since cursor
    --full           ignore the cursor, fetch everything (first run / backfill)
    --verbose, -v    print every request + middleware call to stderr

Cursor:
    Each subcommand's modified_since defaults to the completed_at of the most
    recent finished run of that subcommand (stored in sync.db / sync_runs).
    Use --full for the initial historic backfill. Use --since to override.

Resume-on-crash and "don't resend":
    Every attempt is logged to sync.db before the HTTP call. If a row already
    has a 202 response for the same route, it's skipped on subsequent runs.

On failure:
    Stops on the first non-202 / network error. completed_at is NOT written,
    so the cursor doesn't advance — next run re-attempts from the same point,
    skipping anything already-sent.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

from src.sync_log import SyncLog, open_log


# --- Target registry ---------------------------------------------------------
#
# Each sync target describes:
#   route_template  — path with ":id" placeholder; used as sync_runs.route key
#                     (the cursor is stored per template, not per exact URL).
#   transformer     — which transform_* function to invoke.
#   row_checks      — list of (reason, check_fn) tuples. Each check_fn takes a
#                     row dict and returns True if the row passes. The first
#                     failing check's reason is logged in the audit report.
#   url_key         — column whose value becomes the URL id (and the balo_id
#                     we pass to Sender / sync.db).
#   name_key        — tuple of column names used to build a human-readable label
#                     for the audit report (e.g. ("firstName", "lastName", "email")).
#   payload_keys    — exact list of columns to include in the outgoing JSON.
#                     Source of truth is MIDDLEWARE_ENDPOINTS.md; keep in sync.
#   sender_method   — method name on Sender to call.
#   label           — human-readable tag for logs.

from src.config import EXPERT_OR_ADMIN_ROLES

# Test/internal emails — same list as the middleware (processor.ts BLOCKED_EMAIL_PATTERNS).
BLOCKED_EMAIL_PATTERNS = ("@revido.io", "ylinkz", "yomi@getbalo.com")


def _is_blocked_email(row, field="email"):
    email = (row.get(field) or "").lower()
    return any(p in email for p in BLOCKED_EMAIL_PATTERNS)


TARGETS = {
    "prospects": {
        "route_template": "/crm/prospect",
        "transformer": "transform_prospects_contacts",
        "row_checks": [
            ("not a CLIENT row", lambda r: r.get("_contact_type") == "CLIENT"),
            ("has expert/admin role", lambda r: not EXPERT_OR_ADMIN_ROLES.intersection(r.get("baloRoles", []))),
            ("blocked test email", lambda r: not _is_blocked_email(r)),
        ],
        "url_key": "baloId",
        "name_key": ("firstName", "lastName", "email"),
        "payload_keys": [
            "baloId", "email", "firstName", "lastName", "phone",
            "baloRole", "baloRoles", "prospectStatus", "signupDate",
            "timezone", "currencyCode", "country",
            "baloAccountId", "companyName", "accountType", "baloAccountCreatedDate",
        ],
        "omit_if_empty": (
            "baloAccountId", "companyName", "accountType", "baloAccountCreatedDate",
        ),
        "nullify_empty_strings": True,
        "sender_method": "send_prospect",
        "label": "Client signups → POST /crm/prospect",
    },
    "accounts": {
        "route_template": "/crm/account/:id",
        "transformer": "transform_accounts",
        "row_checks": [
            ("blocked admin email", lambda r: not _is_blocked_email(r, "_admin_email")),
            ("no real client users (expert-only dummy company)", lambda r: (
                r.get("_group") != "CLIENT" or r.get("_has_real_client", True)
            )),
        ],
        "url_key": "Balo_Id__c",
        "name_key": ("Name",),
        "payload_keys": [
            "Name", "Phone", "Website", "Type", "AccountSource",
            "Stripe_Customer_Id__c", "Has_Booked_Consultation__c",
            "Has_Redeemed_Credits__c", "Has_Submitted_Project__c",
            "Balo_Created_Date__c", "Stripe_Seller_ID__c",
            "Stripe_Connection_Status__c",
        ],
        # Type is intentionally empty for CLIENT rows so the /crm/prospect Apex
        # flow's value is preserved. AGENCY/FREELANCE rows send Type as normal.
        "omit_if_empty": ("Type",),
        "sender_method": "send_account",
        "label": "Accounts (clients + agencies) → PATCH /crm/account/:id",
    },
    "contacts": {
        "route_template": "/crm/contact/:id",
        "transformer": "transform_prospects_contacts",
        "row_checks": [
            ("not an EXPERT row", lambda r: r.get("_contact_type") == "EXPERT"),
            ("no expert role in user Roles", lambda r: bool(
                EXPERT_OR_ADMIN_ROLES.intersection(r.get("baloRoles", []))
            )),
            ("profile not approved", lambda r: r.get("Application_Status__c") == "approved"),
            ("blocked test email", lambda r: not _is_blocked_email(r)),
        ],
        "url_key": "baloId",
        "name_key": ("firstName", "lastName", "email"),
        "payload_keys": [
            "firstName", "lastName", "email",
            "RecordTypeId", "Balo_Role__c", "baloRoles",
            "Expert_Type__c",
            "Is_CTA__c", "Is_MVP__c", "Salesforce_Start_Year__c",
            "Years_Experience__c", "Project_Count_Range__c",
            "Consultation_Min_Rate__c", "Average_Rating__c", "Total_Reviews__c",
            "LinkedIn_URL__c", "Trailblazer_URL__c", "Headline__c",
            "Description",
            "Application_Status__c", "Expert_Unique_ID__c", "Cronofy_User_ID__c",
            "MailingCountry", "Account.Balo_Id__c",
        ],
        "key_map": {"firstName": "FirstName", "lastName": "LastName", "email": "Email", "baloRoles": "Balo_Roles__c"},
        "omit_if_empty": ("Account.Balo_Id__c",),
        "sender_method": "send_contact",
        "label": "Expert Contacts → PATCH /crm/contact/:id",
    },
    "cases": {
        "route_template": "/crm/opportunity/case/:id",
        "transformer": "transform_opportunities_cases",
        "row_checks": [],
        "url_key": "Balo_Case_Number__c",
        "name_key": ("Name",),
        "payload_keys": [
            "Name", "CloseDate", "StageName", "RecordTypeId", "Description",
            "Total_Consultation_Minutes__c", "Total_Credits_Used__c", "Amount",
            "Expert_Earnings__c",
            "Balo_Created_Date__c", "Product__c", "Type_of_Support__c",
            "Account.Balo_Id__c", "Primary_Contact__r.Balo_Id__c",
            "Expert__r.Balo_Id__c",
        ],
        "defaults": {"CloseDate": lambda: (date.today() + timedelta(days=365)).isoformat()},
        "omit_if_empty": (
            "Amount", "Expert_Earnings__c", "Total_Consultation_Minutes__c",
            "Total_Credits_Used__c", "Expert__r.Balo_Id__c",
            "Account.Balo_Id__c", "Primary_Contact__r.Balo_Id__c",
        ),
        "sender_method": "send_opportunity_case",
        "label": "Case Opportunities → PATCH /crm/opportunity/case/:id",
    },
    "projects": {
        "route_template": "/crm/opportunity/project/:id",
        "transformer": "transform_opportunities_projects",
        "row_checks": [
            ("empty Name (incomplete draft)", lambda r: bool(r.get("Name"))),
        ],
        "url_key": "Balo_Id__c",
        "name_key": ("Name",),
        "payload_keys": [
            "Name", "CloseDate", "StageName", "Sub_status__c", "RecordTypeId",
            "Description", "Project_Tag__c", "Sourcing_Mode__c", "Package__c",
            "Active_Proposal_Count__c", "Discovery_Insights__c",
            "Submitted_Date__c", "Balo_Created_Date__c", "Product__c",
            "Project_ID__c", "Total_Cost_Inc_Fees__c", "GST_Charged__c",
            "Expert_Earnings__c", "Account.Balo_Id__c",
            "Primary_Contact__r.Balo_Id__c", "Related_Case__r.Balo_Case_Number__c",
        ],
        "defaults": {"CloseDate": lambda: (date.today() + timedelta(days=365)).isoformat()},
        "omit_if_empty": (
            "Submitted_Date__c", "Total_Cost_Inc_Fees__c",
            "GST_Charged__c", "Expert_Earnings__c", "Active_Proposal_Count__c",
            "Project_ID__c", "Related_Case__r.Balo_Case_Number__c",
            "Account.Balo_Id__c", "Primary_Contact__r.Balo_Id__c",
        ),
        "sender_method": "send_opportunity_project",
        "label": "Project Opportunities → PATCH /crm/opportunity/project/:id",
    },
    "project-experts": {
        "route_template": "/crm/project-expert/:id",
        "transformer": "transform_project_experts",
        "row_checks": [
            ("missing composite Balo_Id__c", lambda r: bool(r.get("Balo_Id__c"))),
        ],
        "url_key": "Balo_Id__c",
        "name_key": ("Balo_Id__c",),
        "payload_keys": [
            "EOI_Status__c", "EOI_Submitted_Date__c", "Proposal_Submitted_Date__c",
            "Finalized_Date__c", "Proposal_Status__c", "Estimated_Completion_Date__c",
            "Experts_Proposed_Cost__c", "Pricing_Method__c", "Hourly_Rate__c",
            "Payment_Terms__c", "Customer_Cost__c", "Total_Hours__c",
            "Opportunity__r.Balo_Id__c", "Expert__r.Balo_Id__c",
        ],
        # Project fields are empty for non-finalized EOIs — omit to avoid SF type errors.
        "omit_if_empty": (
            "Finalized_Date__c", "Proposal_Status__c", "Estimated_Completion_Date__c",
            "Experts_Proposed_Cost__c", "Pricing_Method__c", "Hourly_Rate__c",
            "Payment_Terms__c", "Customer_Cost__c", "Total_Hours__c",
            "Proposal_Submitted_Date__c",
        ),
        "sender_method": "send_project_expert",
        "label": "Project-Expert links → PATCH /crm/project-expert/:id",
    },
    "consultations": {
        "route_template": "/crm/consultation/:id",
        "transformer": "transform_consultations",
        "row_checks": [],
        "url_key": "Balo_Id__c",
        "name_key": ("Balo_Id__c",),
        "payload_keys": [
            "Opportunity__r.Balo_Id__c", "Opportunity__r.Balo_Case_Number__c",
            "Project__r.Balo_Id__c",
            "Expert__r.Balo_Id__c", "Scheduled_DateTime__c", "Start_Time__c",
            "End_Time__c", "Actual_End_Time__c", "Duration_Minutes__c",
            "Actual_Duration_Minutes__c", "Status__c", "Billing_Mode__c",
            "Expert_Rate__c", "Estimated_Cost__c", "Final_Cost__c",
            "GST_Amount__c", "Cancellation_Allowed__c",
            "Cancellation_Reason__c", "Cancelled_By__c", "Client_Join_Time__c",
            "Expert_Join_Time__c", "Ended_By_Expert__c", "Ended_By_Client__c",
            "Participants_Present__c", "Balo_Created_Date__c",
        ],
        "omit_if_empty": (
            "Opportunity__r.Balo_Id__c", "Opportunity__r.Balo_Case_Number__c",
            "Project__r.Balo_Id__c",
            "Expert_Rate__c", "Estimated_Cost__c", "Final_Cost__c",
            "GST_Amount__c", "Actual_End_Time__c", "Actual_Duration_Minutes__c",
            "Client_Join_Time__c", "Expert_Join_Time__c",
            "Ended_By_Expert__c", "Ended_By_Client__c",
            "Cancellation_Reason__c", "Cancelled_By__c",
        ),
        "sender_method": "send_consultation",
        "label": "Consultations → PATCH /crm/consultation/:id",
    },
}


_URL_ONLY_KEYS = ("Balo_Id__c", "Balo_Case_Number__c")


def _build_payload(row, payload_keys, omit_if_empty=(), nullify_empty_strings=False,
                   key_map=None, defaults=None):
    """Return the subset of row restricted to payload_keys, in that order.

    Empty-string values are kept by default — PATCH routes use "" as a
    "clear this field" signal (see MIDDLEWARE_ENDPOINTS.md §6 request-only
    variant). Ways to handle them:

    - omit_if_empty: drop only the listed keys when empty (targeted use —
      e.g. Account.Balo_Id__c on a freelance Contact must be omitted, not
      "", or SF tries to resolve "" as an external id).
    - nullify_empty_strings=True: convert "" to None (JSON null). Needed
      for the /crm/prospect Apex endpoint, which 500s on "" but accepts
      null. Keys are kept in the payload so the Apex class sees them.
    - defaults: dict of fallback values for required fields that SF rejects
      when empty (e.g. CloseDate on Opportunity).

    Dot-notation keys (e.g. "Account.Balo_Id__c") are automatically
    converted to nested objects (e.g. {"Account": {"Balo_Id__c": "..."}})
    as required by the SF REST API for relationship fields.
    """
    for k in _URL_ONLY_KEYS:
        assert k not in payload_keys, (
            f"{k} is URL-only per MIDDLEWARE_ENDPOINTS.md — remove from payload_keys"
        )
    out = {}
    for k in payload_keys:
        v = row.get(k, "")
        if v == "" and defaults and k in defaults:
            d = defaults[k]
            v = d() if callable(d) else d
        if v == "" and k in omit_if_empty:
            continue
        if v == "" and nullify_empty_strings:
            v = None
        # Rename key if key_map provides a mapping
        out_key = key_map.get(k, k) if key_map else k
        # Convert dot-notation to nested objects for SF relationship fields
        if "." in out_key:
            parent, child = out_key.split(".", 1)
            if parent not in out:
                out[parent] = {}
            out[parent][child] = v
        else:
            out[out_key] = v
    return out


def _log(msg):
    print(msg, file=sys.stderr)


def _resolve_cursor(log: SyncLog, route_template: str, args) -> str | None:
    if args.full:
        return None
    if args.since:
        return args.since
    return log.latest_cursor(route_template)


def _check_row(row, row_checks):
    """Run row_checks and return (True, None) if all pass, or (False, reason)."""
    for reason, check_fn in row_checks:
        if not check_fn(row):
            return False, reason
    return True, None


def _build_name(row, name_key):
    """Build a human-readable label from the row for the audit report."""
    parts = [str(row.get(k) or "") for k in name_key]
    return " ".join(p for p in parts if p)


def _write_report(target_key, target, cursor_label, total_rows,
                  sent, filtered, skipped, errors, warnings):
    """Write a per-run Markdown audit report to output/reports/."""
    reports_dir = os.path.join("output", "reports")
    os.makedirs(reports_dir, exist_ok=True)

    now = datetime.now(timezone.utc)
    filename = f"{target_key}_{now.strftime('%Y-%m-%d_%H%M%S')}.md"
    filepath = os.path.join(reports_dir, filename)

    lines = []
    lines.append(f"# Sync Report: {target_key}")
    lines.append(f"**Run at:** {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append(f"**Cursor:** {cursor_label}")
    lines.append(f"**Transformer:** {target['transformer']}")
    lines.append(f"**Fetched from Bubble:** {total_rows} rows")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("| Status | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| Sent | {len(sent)} |")
    lines.append(f"| Filtered | {len(filtered)} |")
    lines.append(f"| Skipped (already sent) | {len(skipped)} |")
    lines.append(f"| Errors | {len(errors)} |")
    lines.append(f"| **Total** | {len(sent) + len(filtered) + len(skipped) + len(errors)} |")
    lines.append("")

    # Filtered
    lines.append(f"## Filtered ({len(filtered)})")
    if filtered:
        lines.append("| # | Balo ID | Name | Reason |")
        lines.append("|---|---------|------|--------|")
        for i, (balo_id, name, reason) in enumerate(filtered, 1):
            lines.append(f"| {i} | {balo_id} | {name} | {reason} |")
    else:
        lines.append("(none)")
    lines.append("")

    # Sent
    lines.append(f"## Sent ({len(sent)})")
    if sent:
        lines.append("| # | Balo ID | Name | Job ID | HTTP |")
        lines.append("|---|---------|------|--------|------|")
        for i, (balo_id, name, job_id, http_status) in enumerate(sent, 1):
            lines.append(f"| {i} | {balo_id} | {name} | {job_id} | {http_status} |")
    else:
        lines.append("(none)")
    lines.append("")

    # Skipped
    lines.append(f"## Skipped - already sent ({len(skipped)})")
    if skipped:
        lines.append("| # | Balo ID | Name |")
        lines.append("|---|---------|------|")
        for i, (balo_id, name) in enumerate(skipped, 1):
            lines.append(f"| {i} | {balo_id} | {name} |")
    else:
        lines.append("(none)")
    lines.append("")

    # Errors
    lines.append(f"## Errors ({len(errors)})")
    if errors:
        lines.append("| # | Balo ID | Name | HTTP | Response |")
        lines.append("|---|---------|------|------|----------|")
        for i, (balo_id, name, http_status, response) in enumerate(errors, 1):
            lines.append(f"| {i} | {balo_id} | {name} | {http_status} | {response} |")
    else:
        lines.append("(none)")
    lines.append("")

    # Warnings
    if warnings:
        lines.append(f"## Warnings ({len(warnings)})")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    with open(filepath, "w") as f:
        f.write("\n".join(lines))

    return filepath


def run_target(target_key: str, args) -> int:
    target = TARGETS[target_key]
    _log("=" * 64)
    _log(f"sync.py {target_key}  —  {target['label']}")
    _log("=" * 64)

    with open_log() as log:
        cursor = _resolve_cursor(log, target["route_template"], args)
        if cursor:
            cursor_label = f"modified_since = {cursor}"
        elif args.full:
            cursor_label = "--full (ignoring stored cursor)"
        else:
            cursor_label = "none (first run for this target)"
        _log(f"Cursor: {cursor_label}")

        run_id = log.start_run(
            route=target["route_template"],
            modified_since=cursor,
            notes=_run_notes(args),
        )

        # Lazy import so `--list` works without BALO_API_TOKEN configured.
        from src.api_client import BubbleClient
        from src.fetcher import Fetcher
        from src.sender import Sender, SenderError
        import src.transformer as transformer_mod

        t0 = time.time()
        client = BubbleClient(verbose=args.verbose)
        fetcher = Fetcher(client)
        _log("Phase 1: Fetch")
        store = fetcher.fetch_all_historic(modified_since=cursor)
        _log(f"  fetched in {time.time() - t0:.1f}s "
             f"({client.request_count} Bubble requests)")

        _log("Phase 2: Transform")
        transformer_fn = getattr(transformer_mod, target["transformer"])
        columns, rows, provenance = transformer_fn(store)

        # Separate real rows from separator rows
        all_rows = [
            (row, sources)
            for row, sources in zip(rows, provenance)
            if not row.get("_is_separator")
        ]
        total_rows = len(all_rows)
        _log(f"  {total_rows} data rows from transformer")

        # Audit trail collectors
        report_sent = []      # (balo_id, name, job_id, http_status)
        report_filtered = []  # (balo_id, name, reason)
        report_skipped = []   # (balo_id, name)
        report_errors = []    # (balo_id, name, http_status, response)

        _log("Phase 3: Send")
        sender = Sender(log, dry_run=args.dry_run, verbose=args.verbose)
        send = getattr(sender, target["sender_method"])
        row_checks = target.get("row_checks", [])
        name_key = target.get("name_key", (target["url_key"],))

        attempted_ok = 0
        for row, sources in all_rows:
            balo_id = row.get(target["url_key"]) or ""
            name = _build_name(row, name_key)

            # Check filters
            passed, reason = _check_row(row, row_checks)
            if not passed:
                report_filtered.append((balo_id, name, reason))
                continue

            if not balo_id:
                report_filtered.append((balo_id, name, f"missing {target['url_key']}"))
                continue

            # Check already sent — sender stores the full route URL in sync.db
            # (e.g. "/crm/account/12345"), so build the same URL for the check.
            route_url = target["route_template"].replace(":id", balo_id)
            if log.already_sent(balo_id, route_url):
                report_skipped.append((balo_id, name))
                continue

            payload = _build_payload(
                row,
                target["payload_keys"],
                omit_if_empty=target.get("omit_if_empty", ()),
                nullify_empty_strings=target.get("nullify_empty_strings", False),
                key_map=target.get("key_map"),
                defaults=target.get("defaults"),
            )

            try:
                result = send(balo_id, payload, sources)
                # result is dict {"accepted": true, "jobId": "..."} on 202,
                # None on dry-run. SenderError raised on non-202.
                job_id = ""
                if result and isinstance(result, dict):
                    job_id = result.get("jobId", result.get("job_id", ""))
                report_sent.append((balo_id, name, job_id, 202))
                attempted_ok += 1
            except SenderError as exc:
                report_errors.append((balo_id, name, exc.status_code or 0, str(exc)[:200]))
                _log(f"  [ERROR] {exc}")
                # Non-202 is not fatal for the run — continue with remaining rows.
                # Only network failures (status_code=None) should abort.
                if exc.status_code is None:
                    _log("Network error — aborting run. Cursor will NOT advance.")
                    break

            if args.limit and attempted_ok >= args.limit:
                _log(f"  --limit {args.limit} reached, stopping.")
                break

        log.complete_run(
            run_id,
            records_sent=sender.sent_count,
            records_skipped=sender.skipped_count,
        )

        # Write audit report
        report_path = _write_report(
            target_key, target, cursor_label, total_rows,
            report_sent, report_filtered, report_skipped,
            report_errors, store.warnings,
        )

        _log("-" * 64)
        _log(f"Sent: {len(report_sent)}  Filtered: {len(report_filtered)}  "
             f"Skipped: {len(report_skipped)}  Errors: {len(report_errors)}")
        _log(f"Report: {report_path}")
        if store.warnings:
            _log(f"Warnings: {len(store.warnings)} (first 5 below)")
            for w in store.warnings[:5]:
                _log(f"  - {w}")
        return 0


def _run_notes(args) -> str:
    bits = []
    if args.dry_run:
        bits.append("dry-run")
    if args.full:
        bits.append("full")
    if args.since:
        bits.append(f"since={args.since}")
    if args.limit:
        bits.append(f"limit={args.limit}")
    return ",".join(bits) if bits else ""


def _print_list():
    print("sync.py targets:")
    print()
    key_w = max(len(k) for k in TARGETS) + 2
    route_w = max(len(t["route_template"]) for t in TARGETS.values()) + 2
    for key, target in TARGETS.items():
        print(
            f"  {key.ljust(key_w)}"
            f"{target['route_template'].ljust(route_w)}"
            f"{target['label']}"
        )
    print()
    print("Common flags: --limit N | --dry-run | --since <iso-datetime> | --full | -v")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Balo Bubble.io → sf-middleware-api sync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run `sync.py --list` for the full target table.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        choices=list(TARGETS.keys()),
        help="Which sync target to run.",
    )
    parser.add_argument("--list", action="store_true", help="List targets and exit.")
    parser.add_argument("--limit", type=int, help="Stop after N successful sends.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log to sync.db without POSTing to middleware.")
    parser.add_argument("--since",
                        help="Override the auto-derived modified_since cursor "
                             "(ISO datetime string).")
    parser.add_argument("--full", action="store_true",
                        help="Ignore the stored cursor (first-run backfill).")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print every Bubble / middleware request.")
    args = parser.parse_args(argv)

    if args.list:
        _print_list()
        return 0

    if not args.target:
        parser.error("target is required (or use --list)")

    if args.full and args.since:
        parser.error("--full and --since are mutually exclusive")

    return run_target(args.target, args)


if __name__ == "__main__":
    sys.exit(main())
