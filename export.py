#!/usr/bin/env python3
"""Balo Bubble.io → Salesforce Test Data Export Tool.

Fetches data from the Bubble.io Data API, maps fields to Salesforce API
payload format, and generates a professional Excel spreadsheet for developers.

Usage:
    python export.py
    python export.py --companies ID1,ID2,ID3
    python export.py --output path/to/output.xlsx
    python export.py --dry-run --verbose
"""

import argparse
import sys
import time


def main():
    parser = argparse.ArgumentParser(
        description="Export Balo Bubble.io data as Salesforce test data (XLSX)"
    )
    parser.add_argument(
        "--output", "-o",
        default="output/Balo_SF_Test_Data.xlsx",
        help="Output XLSX file path (default: output/Balo_SF_Test_Data.xlsx)",
    )
    parser.add_argument(
        "--companies",
        help="Comma-separated client company Bubble IDs to export",
    )
    parser.add_argument(
        "--agencies",
        help="Comma-separated agency Bubble IDs to export",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and transform data but do not write the XLSX file",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print every API call to stderr",
    )
    args = parser.parse_args()

    # Parse optional IDs
    company_ids = [x.strip() for x in args.companies.split(",") if x.strip()] if args.companies else None
    agency_ids = [x.strip() for x in args.agencies.split(",") if x.strip()] if args.agencies else None

    # --- Phase 1: Fetch ---
    print("=" * 60, file=sys.stderr)
    print("BALO → SALESFORCE DATA EXPORT", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(file=sys.stderr)

    print("Phase 1: Fetching data from Bubble.io...", file=sys.stderr)
    start = time.time()

    from src.api_client import BubbleClient
    from src.fetcher import Fetcher

    client = BubbleClient(verbose=args.verbose)
    fetcher = Fetcher(client, company_ids=company_ids, agency_ids=agency_ids)
    store = fetcher.fetch_all()

    fetch_time = time.time() - start
    print(f"\nFetch complete in {fetch_time:.1f}s ({client.request_count} API requests)", file=sys.stderr)
    print(f"  Companies: {len(store.clientcompanies)}", file=sys.stderr)
    print(f"  Agencies:  {len(store.agencies)}", file=sys.stderr)
    print(f"  Users:     {len(store.users)}", file=sys.stderr)
    print(f"  Experts:   {len(store.experts)}", file=sys.stderr)
    print(f"  Countries: {len(store.countries)}", file=sys.stderr)
    print(f"  Cases:     {len(store.cases)}", file=sys.stderr)
    print(f"  Proj Reqs: {len(store.project_requests)}", file=sys.stderr)
    print(f"  Projects:  {len(store.projects)}", file=sys.stderr)
    print(f"  EOIs:      {len(store.project_eois)}", file=sys.stderr)
    print(f"  Meetings:  {len(store.meetings)}", file=sys.stderr)
    print(f"  Consults:  {len(store.consultations)}", file=sys.stderr)
    print(f"  Packages:  {len(store.packages)}", file=sys.stderr)
    print(file=sys.stderr)

    # --- Phase 2: Transform ---
    print("Phase 2: Transforming data...", file=sys.stderr)

    from src.transformer import transform_all

    sheets_data = transform_all(store)

    for name, (cols, rows) in sheets_data.items():
        data_rows = [r for r in rows if not r.get("_is_separator")]
        print(f"  {name}: {len(data_rows)} rows, {len(cols)} columns", file=sys.stderr)
    print(file=sys.stderr)

    # --- Phase 3: Write ---
    if args.dry_run:
        print("Dry run — skipping XLSX generation.", file=sys.stderr)
    else:
        print(f"Phase 3: Writing {args.output}...", file=sys.stderr)

        from src.excel_writer import write_workbook

        write_workbook(sheets_data, args.output, warnings=store.warnings)
        print(f"Done! Output: {args.output}", file=sys.stderr)

    # --- Phase 4: Save manifest ---
    from src.manifest import save_manifest
    manifest_path = save_manifest(store)
    print(f"Manifest saved: {manifest_path}", file=sys.stderr)

    # --- Warnings ---
    if store.warnings:
        print(f"\n{'=' * 60}", file=sys.stderr)
        print(f"WARNINGS ({len(store.warnings)}):", file=sys.stderr)
        for w in store.warnings:
            print(f"  - {w}", file=sys.stderr)
        print(file=sys.stderr)

    print("Export complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
