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
import sys
import time

from src.sync_log import SyncLog, open_log


# --- Target registry ---------------------------------------------------------
#
# Each sync target describes:
#   route_template  — path with ":id" placeholder; used as sync_runs.route key
#                     (the cursor is stored per template, not per exact URL).
#   transformer     — which transform_* function to invoke.
#   row_filter      — predicate applied to each non-separator row.
#   url_key         — column whose value becomes the URL id (and the balo_id
#                     we pass to Sender / sync.db).
#   payload_keys    — exact list of columns to include in the outgoing JSON.
#                     Source of truth is MIDDLEWARE_ENDPOINTS.md; keep in sync.
#   sender_method   — method name on Sender to call.
#   label           — human-readable tag for logs.

TARGETS = {
    "prospects": {
        "route_template": "/crm/prospect",
        "transformer": "transform_prospects_contacts",
        "row_filter": lambda r: r.get("_contact_type") == "CLIENT",
        "url_key": "baloId",
        "payload_keys": [
            "baloId", "email", "firstName", "lastName", "phone",
            "baloRole", "baloRoles", "prospectStatus", "signupDate",
            "timezone", "currencyCode", "country",
            "baloAccountId", "companyName", "accountType", "baloAccountCreatedDate",
        ],
        # Freelance experts omit these entirely (MIDDLEWARE_ENDPOINTS.md §1).
        # Under the current CLIENT filter this path is unreachable, but leaving
        # the guard in means a filter change can't silently produce a bad body.
        "omit_if_empty": (
            "baloAccountId", "companyName", "accountType", "baloAccountCreatedDate",
        ),
        # /crm/prospect is handled by Apex REST, which treats "" and null
        # differently — Apex validation / type coercion can 500 on empty
        # strings that it would tolerate as null. Drop every empty-string
        # key from the body. The PATCH routes below keep "" as a legitimate
        # "clear this field" signal, so this flag is target-scoped.
        "omit_empty_strings": True,
        "sender_method": "send_prospect",
        "label": "Client signups → POST /crm/prospect",
    },
    "accounts": {
        "route_template": "/crm/account/:id",
        "transformer": "transform_accounts",
        "row_filter": lambda r: True,
        "url_key": "Balo_Id__c",
        "payload_keys": [
            "Name", "Phone", "Website", "Type", "AccountSource",
            "Stripe_Customer_Id__c", "Has_Booked_Consultation__c",
            "Has_Redeemed_Credits__c", "Has_Submitted_Project__c",
            "Balo_Created_Date__c", "Stripe_Seller_ID__c",
            "Stripe_Connection_Status__c",
        ],
        "sender_method": "send_account",
        "label": "Accounts (clients + agencies) → PATCH /crm/account/:id",
    },
    "contacts": {
        "route_template": "/crm/contact/:id",
        "transformer": "transform_prospects_contacts",
        # Experts only. Client Contacts are created atomically by the
        # /crm/prospect Apex call in Phase 1.
        "row_filter": lambda r: r.get("_contact_type") == "EXPERT",
        "url_key": "baloId",
        "payload_keys": [
            "RecordTypeId", "Expert_Type__c", "Is_Salesforce_Certified__c",
            "Is_CTA__c", "Is_MVP__c", "Salesforce_Start_Year__c",
            "Years_Experience__c", "Project_Count_Range__c",
            "Consultation_Min_Rate__c", "Average_Rating__c", "Total_Reviews__c",
            "LinkedIn_URL__c", "Trailblazer_URL__c", "Headline__c",
            "Application_Status__c", "Expert_Unique_ID__c", "Cronofy_User_ID__c",
            "MailingCountry", "Account.Balo_Id__c",
        ],
        # Freelance experts have no agency; sending an empty Account.Balo_Id__c
        # makes the middleware try to resolve "" as an external id and fail
        # (MIDDLEWARE_ENDPOINTS.md §3 — omit entirely).
        "omit_if_empty": ("Account.Balo_Id__c",),
        "sender_method": "send_contact",
        "label": "Expert Contacts → PATCH /crm/contact/:id",
    },
    "cases": {
        "route_template": "/crm/opportunity/case/:id",
        "transformer": "transform_opportunities_cases",
        "row_filter": lambda r: True,
        # Cases use Balo_Case_Number__c in the URL, not Balo_Id__c.
        "url_key": "Balo_Case_Number__c",
        "payload_keys": [
            "Name", "CloseDate", "StageName", "RecordTypeId", "Description",
            "Total_Consultation_Minutes__c", "Total_Credits_Used__c", "Amount",
            "Balo_Created_Date__c", "Product__c", "Type_Of_Support__c",
            "Account.Balo_Id__c", "Primary_Contact__r.Balo_Id__c",
            "Expert__r.Balo_Id__c",
        ],
        "sender_method": "send_opportunity_case",
        "label": "Case Opportunities → PATCH /crm/opportunity/case/:id",
    },
    "projects": {
        "route_template": "/crm/opportunity/project/:id",
        "transformer": "transform_opportunities_projects",
        "row_filter": lambda r: True,
        "url_key": "Balo_Id__c",
        "payload_keys": [
            "Name", "CloseDate", "StageName", "Sub_status__c", "RecordTypeId",
            "Description", "Project_Tag__c", "Sourcing_Mode__c", "Package__c",
            "Active_Proposal_Count__c", "Discovery_Insights__c",
            "Submitted_Date__c", "Balo_Created_Date__c", "Product__c",
            "Project_ID__c", "Total_Cost_Inc_Fees__c", "GST_Charged__c",
            "Expert_Earnings__c", "Account.Balo_Id__c",
            "Primary_Contact__r.Balo_Id__c", "Related_Case__r.Balo_Id__c",
        ],
        "sender_method": "send_opportunity_project",
        "label": "Project Opportunities → PATCH /crm/opportunity/project/:id",
    },
    "project-experts": {
        "route_template": "/crm/project-expert/:id",
        "transformer": "transform_project_experts",
        "row_filter": lambda r: bool(r.get("Balo_Id__c")),  # skip rows missing composite id
        "url_key": "Balo_Id__c",
        "payload_keys": [
            "Expert_EOI_Status__c", "Opportunity__r.Balo_Id__c",
            "Expert__r.Balo_Id__c",
        ],
        "sender_method": "send_project_expert",
        "label": "Project-Expert links → PATCH /crm/project-expert/:id",
    },
    "consultations": {
        "route_template": "/crm/consultation/:id",
        "transformer": "transform_consultations",
        "row_filter": lambda r: True,
        "url_key": "Balo_Id__c",
        "payload_keys": [
            "Opportunity__r.Balo_Id__c", "Project__r.Balo_Id__c",
            "Expert__r.Balo_Id__c", "Scheduled_DateTime__c", "Start_Time__c",
            "End_Time__c", "Actual_End_Time__c", "Duration_Minutes__c",
            "Actual_Duration_Minutes__c", "Status__c", "Billing_Mode__c",
            "Expert_Rate__c", "Estimated_Cost__c", "Final_Cost__c",
            "GST_Amount__c", "Cancellation_Allowed__c",
            "Cancellation_Reason__c", "Cancelled_By__c", "Client_Join_Time__c",
            "Expert_Join_Time__c", "Ended_By_Expert__c", "Ended_By_Client__c",
            "Participants_Present__c", "Balo_Created_Date__c",
        ],
        "sender_method": "send_consultation",
        "label": "Consultations → PATCH /crm/consultation/:id",
    },
}


_URL_ONLY_KEYS = ("Balo_Id__c", "Balo_Case_Number__c")


def _build_payload(row, payload_keys, omit_if_empty=(), omit_empty_strings=False):
    """Return the subset of row restricted to payload_keys, in that order.

    Empty-string values are kept by default — PATCH routes use "" as a
    "clear this field" signal (see MIDDLEWARE_ENDPOINTS.md §6 request-only
    variant). Two ways to drop them:

    - omit_if_empty: drop only the listed keys when empty (targeted use —
      e.g. Account.Balo_Id__c on a freelance Contact must be omitted, not
      "", or SF tries to resolve "" as an external id).
    - omit_empty_strings=True: drop every empty-string key. Needed for the
      /crm/prospect Apex endpoint, which 500s on "" where it would accept
      null.
    """
    for k in _URL_ONLY_KEYS:
        assert k not in payload_keys, (
            f"{k} is URL-only per MIDDLEWARE_ENDPOINTS.md — remove from payload_keys"
        )
    out = {}
    for k in payload_keys:
        v = row.get(k, "")
        if v == "" and (omit_empty_strings or k in omit_if_empty):
            continue
        out[k] = v
    return out


def _log(msg):
    print(msg, file=sys.stderr)


def _resolve_cursor(log: SyncLog, route_template: str, args) -> str | None:
    if args.full:
        return None
    if args.since:
        return args.since
    return log.latest_cursor(route_template)


def run_target(target_key: str, args) -> int:
    target = TARGETS[target_key]
    _log("=" * 64)
    _log(f"sync.py {target_key}  —  {target['label']}")
    _log("=" * 64)

    with open_log() as log:
        cursor = _resolve_cursor(log, target["route_template"], args)
        if cursor:
            _log(f"Cursor: modified_since = {cursor}")
        elif args.full:
            _log("Cursor: --full (ignoring stored cursor)")
        else:
            _log("Cursor: none (first run for this target)")

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

        candidate = [
            (row, sources)
            for row, sources in zip(rows, provenance)
            if not row.get("_is_separator") and target["row_filter"](row)
        ]
        _log(f"  {len(candidate)} candidate rows (after filter)")

        _log("Phase 3: Send")
        sender = Sender(log, dry_run=args.dry_run, verbose=args.verbose)
        send = getattr(sender, target["sender_method"])

        attempted_ok = 0
        for row, sources in candidate:
            balo_id = row.get(target["url_key"])
            if not balo_id:
                store.warnings.append(
                    f"Skipping row with missing {target['url_key']}: {row}"
                )
                continue

            payload = _build_payload(
                row,
                target["payload_keys"],
                omit_if_empty=target.get("omit_if_empty", ()),
                omit_empty_strings=target.get("omit_empty_strings", False),
            )

            before_sent = sender.sent_count
            try:
                send(balo_id, payload, sources)
            except SenderError as exc:
                _log(f"  [ABORT] {exc}")
                _log("Run left incomplete — cursor will NOT advance. Fix and rerun.")
                return 2

            # sent_count only increments on a genuine (or dry-run) send, not on
            # already_sent skips. That's what --limit should gate against.
            if sender.sent_count > before_sent:
                attempted_ok += 1
            if args.limit and attempted_ok >= args.limit:
                _log(f"  --limit {args.limit} reached, stopping.")
                break

        log.complete_run(
            run_id,
            records_sent=sender.sent_count,
            records_skipped=sender.skipped_count,
        )

        _log("-" * 64)
        _log(f"Sent: {sender.sent_count}  Skipped (already sent): {sender.skipped_count}")
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
