"""Export manifest — tracks all previously exported records.

Writes a JSON manifest after each export run. On subsequent runs, the fetcher
can read it to skip already-exported records and pick fresh ones.
"""

import json
import os
from datetime import datetime

MANIFEST_PATH = "output/export_manifest.json"


def load_manifest():
    """Load the manifest file. Returns empty structure if not found."""
    if not os.path.exists(MANIFEST_PATH):
        return {"runs": [], "exported_ids": {}}

    with open(MANIFEST_PATH, "r") as f:
        return json.load(f)


def get_exported_ids(table_key):
    """Get set of already-exported IDs for a given table."""
    manifest = load_manifest()
    return set(manifest.get("exported_ids", {}).get(table_key, []))


def save_manifest(store):
    """Save a manifest recording everything exported in this run.

    Merges with previous runs so the full history is preserved.
    """
    manifest = load_manifest()

    # Build this run's record
    run_record = {
        "timestamp": datetime.now().isoformat(),
        "counts": {
            "clientcompanies": len(store.clientcompanies),
            "agencies": len(store.agencies),
            "users": len(store.users),
            "experts": len(store.experts),
            "cases": len(store.cases),
            "project_requests": len(store.project_requests),
            "projects": len(store.projects),
            "project_eois": len(store.project_eois),
            "meetings": len(store.meetings),
            "consultations": len(store.consultations),
            "packages": len(store.packages),
        },
        "records": {},
    }

    # Collect IDs with human-readable names for this run
    this_run = {}

    this_run["clientcompanies"] = [
        {"_id": c["_id"], "name": c.get("Name", "")}
        for c in store.clientcompanies
    ]
    this_run["agencies"] = [
        {"_id": a["_id"], "name": a.get("Name", "")}
        for a in store.agencies
    ]
    this_run["users"] = [
        {"_id": uid, "name": f"{u.get('Name: First', '')} {u.get('Name: Last', '')}".strip()}
        for uid, u in store.users.items()
    ]
    this_run["experts"] = [
        {"_id": eid, "name": e.get("Name: Full", e.get("Profile Headline", ""))}
        for eid, e in store.experts.items()
    ]
    this_run["cases"] = [
        {"_id": c["_id"], "title": c.get("Title", ""), "case_id": c.get("Case ID", "")}
        for c in store.cases
    ]
    this_run["project_requests"] = [
        {"_id": r["_id"], "status": r.get("Status", "")}
        for r in store.project_requests
    ]
    this_run["projects"] = [
        {"_id": pid, "title": p.get("Project title", "")}
        for pid, p in store.projects.items()
    ]
    this_run["project_eois"] = [
        {"_id": e["_id"], "status": e.get("Status", "")}
        for e in store.project_eois
    ]
    this_run["meetings"] = [
        {"_id": m["_id"], "type": m.get("Type", ""), "status": m.get("Status", "")}
        for m in store.meetings
    ]
    this_run["consultations"] = [
        {"_id": cid, "status": c.get("Status", "")}
        for cid, c in store.consultations.items()
    ]
    this_run["packages"] = [
        {"_id": pid, "title": p.get("Package title", "")}
        for pid, p in store.packages.items()
    ]

    run_record["records"] = this_run
    manifest["runs"].append(run_record)

    # Merge IDs into the cumulative exported_ids sets
    exported = manifest.get("exported_ids", {})
    for table_key, records in this_run.items():
        if table_key not in exported:
            exported[table_key] = []
        existing = set(exported[table_key])
        for r in records:
            existing.add(r["_id"])
        exported[table_key] = sorted(existing)

    manifest["exported_ids"] = exported

    os.makedirs(os.path.dirname(MANIFEST_PATH) or ".", exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    return MANIFEST_PATH
