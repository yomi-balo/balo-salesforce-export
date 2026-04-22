#!/usr/bin/env python3
"""Inspect sync.db — the log of every payload sent to sf-middleware-api.

    python inspect.py <balo_id>
        Show every event recorded for this balo_id (newest first): ts, route,
        http_status, sf_status, jobId, pretty-printed payload, source records
        that were read to build it.

    python inspect.py <balo_id> --refetch
        Above, plus: re-fetch each source record from Bubble now and flag
        whichever ones have a Modified Date newer than the event's ts ("has
        the data drifted since we sent?"). Prints the current raw source JSON
        so the operator can diff by eye. Requires BALO_API_TOKEN.

    python inspect.py --status pending|landed|failed
        List every sync_events row with that sf_status.

The sf_status column starts as 'pending' on every send and is updated to
'landed' / 'failed' either manually (sqlite CLI) or by a future reconciler.
"""

from __future__ import annotations

import argparse
import json
import sys

from src.sync_log import SyncLog


STATUS_CHOICES = ("pending", "landed", "failed")


def _fmt_event_header(ev):
    http = ev["http_status"] if ev.get("http_status") is not None else "—"
    dur = ev["duration_ms"] if ev.get("duration_ms") is not None else "—"
    return (
        f"[{ev['id']}] {ev['ts']}   {ev['route']}\n"
        f"    sf_object={ev['sf_object']}   balo_id={ev['balo_id']}\n"
        f"    http={http}   sf_status={ev.get('sf_status', '')}"
        f"   job_id={ev.get('job_id') or '—'}"
        f"   duration={dur}ms"
    )


def _print_event(ev):
    print(_fmt_event_header(ev))
    if ev.get("sf_error"):
        print(f"    sf_error: {ev['sf_error']}")
    if ev.get("response_body"):
        body = ev["response_body"]
        if len(body) > 400:
            body = body[:400] + "… (truncated)"
        print(f"    response: {body}")
    print()
    print("    Sources:")
    sources = ev.get("sources") or []
    if not sources:
        print("      (none)")
    else:
        for s in sources:
            label = f" — {s['label']}" if s.get("label") else ""
            print(f"      {s['table']:26s}  {s['_id']}{label}")
    print()
    print("    Payload:")
    payload = ev.get("payload") or {}
    # Indent 2 for readability; sort keys so diffs are stable across runs.
    rendered = json.dumps(payload, indent=2, sort_keys=True, default=str, ensure_ascii=False)
    for line in rendered.splitlines():
        print("      " + line)
    print()


def _cmd_show(balo_id: str, refetch: bool) -> int:
    with SyncLog() as log:
        events = log.lookup(balo_id)
        if not events:
            print(f"No sync_events rows for balo_id={balo_id}")
            return 1
        print(f"{len(events)} event(s) for balo_id={balo_id}\n")
        print("=" * 72)
        for ev in events:
            _print_event(ev)
            print("=" * 72)

        if refetch:
            # Refetch only against the newest event's sources (most useful
            # case — "what does it look like now vs the last time we sent?").
            newest = events[0]
            _refetch_and_compare(newest)
    return 0


def _cmd_status(status: str) -> int:
    with SyncLog() as log:
        events = log.list_by_status(status)
        if not events:
            print(f"No events with sf_status={status!r}")
            return 0
        print(f"{len(events)} event(s) with sf_status={status!r}:\n")
        for ev in events:
            http = ev["http_status"] if ev.get("http_status") is not None else "—"
            print(
                f"  [{ev['id']:>5}] {ev['ts']}  {ev['route']:40s}  "
                f"balo={ev['balo_id']}  http={http}"
            )
    return 0


def _refetch_and_compare(ev):
    """Re-fetch each source record from Bubble, flag drift against ev.ts."""
    from src.api_client import BubbleClient
    from src.config import TABLE_PATHS

    sources = ev.get("sources") or []
    if not sources:
        print("(No sources recorded — nothing to refetch.)")
        return

    print("-" * 72)
    print(f"REFETCH against newest event [{ev['id']}]  (sent at {ev['ts']})")
    print("-" * 72)

    client = BubbleClient(verbose=False)
    for src in sources:
        table_key = src.get("table")
        uid = src.get("_id")
        label = src.get("label") or ""
        print(f"\n{table_key}  {uid}   {label}")
        path = TABLE_PATHS.get(table_key)
        if not path:
            print(f"  (unknown table_key — cannot refetch)")
            continue
        record = client.fetch_record(path, uid)
        if record is None:
            print("  [GONE] Bubble returned no record (deleted or 404).")
            continue
        modified = record.get("Modified Date") or record.get("modified_date") or ""
        drift = ""
        if modified and modified > ev["ts"]:
            drift = f"  ⚠ DRIFT — modified after send (ts={ev['ts']})"
        elif modified:
            drift = "  (unchanged since send)"
        print(f"  Modified Date: {modified}{drift}")
        # Raw current JSON — abridged if huge.
        rendered = json.dumps(record, indent=2, sort_keys=True, default=str, ensure_ascii=False)
        if len(rendered) > 2000:
            rendered = rendered[:2000] + "\n… (truncated)"
        for line in rendered.splitlines():
            print("    " + line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect sync.db (the Balo → middleware send log)",
    )
    parser.add_argument("balo_id", nargs="?", help="Show events for this balo_id.")
    parser.add_argument(
        "--status",
        choices=STATUS_CHOICES,
        help="List every event with this sf_status.",
    )
    parser.add_argument(
        "--refetch",
        action="store_true",
        help="Re-fetch each source record from Bubble and flag drift "
             "(requires BALO_API_TOKEN).",
    )
    args = parser.parse_args(argv)

    if args.status and args.balo_id:
        parser.error("pass either <balo_id> or --status, not both")
    if args.refetch and not args.balo_id:
        parser.error("--refetch needs a <balo_id>")
    if not args.status and not args.balo_id:
        parser.error("pass a <balo_id> or --status")

    if args.status:
        return _cmd_status(args.status)
    return _cmd_show(args.balo_id, refetch=args.refetch)


if __name__ == "__main__":
    sys.exit(main())
