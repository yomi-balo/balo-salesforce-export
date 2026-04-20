import os
import urllib.parse

from dotenv import load_dotenv

load_dotenv()

# --- API ---
BALO_API_TOKEN = os.getenv("BALO_API_TOKEN")
if not BALO_API_TOKEN:
    raise EnvironmentError(
        "BALO_API_TOKEN is not set. Copy .env.example to .env and add your Bubble API token."
    )

BASE_URL = "https://balo.expert/api/1.1"

# --- Optional record IDs from env ---
def _parse_ids(key):
    val = os.getenv(key, "").strip()
    return [v.strip() for v in val.split(",") if v.strip()] if val else []

ENV_COMPANY_IDS = _parse_ids("BALO_COMPANY_IDS")
ENV_AGENCY_IDS = _parse_ids("BALO_AGENCY_IDS")

# --- Bubble table URL paths (emoji-encoded) ---
def _encode(name):
    return urllib.parse.quote(name, safe="")

TABLE_PATHS = {
    "user":                 "user",
    "profile_expert":       _encode("👤profile:expert"),
    "profile_agency":       _encode("👥profile:agency"),
    "profile_clientcompany": _encode("👥profile:clientcompany"),
    "case":                 _encode("📂case"),
    "project":              _encode("📄project"),
    "project_request":      _encode("📄project:request"),
    "project_eoi":          _encode("📄project:eoi"),
    "consultation":         _encode("📞consultation"),
    "meeting":              _encode("📞meeting"),
    "country":              _encode("📍country"),
    "package":              _encode("📄package"),
    "projectmeeting":       _encode("🆕📞projectmeeting"),
}

# --- Rate limiting ---
RATE_LIMIT_DELAY = 1.0       # seconds between requests
RATE_LIMIT_MAX_RETRIES = 5
RATE_LIMIT_BACKOFF_BASE = 2  # exponential backoff multiplier

# --- Salesforce RecordTypeIds ---
RECORD_TYPE_EXPERT_CONTACT = "012On00000LYlI9IAL"
RECORD_TYPE_CLIENT_CONTACT = "012On00000LYdFm"
RECORD_TYPE_CASE_OPPORTUNITY = "012On00000L9nDVIAZ"
RECORD_TYPE_PROJECT_OPPORTUNITY = "012On00000L9nILIAZ"  # FLAG FOR NICK: confirm vs 012On00000L9nDVIAZ

# --- Hardcoded SF values ---
PROSPECT_STATUS = "Signed Up"
ACCOUNT_SOURCE = "Balo Sourced"

# --- Sensitive fields to redact ---
SENSITIVE_FIELDS = [
    "Cronofy Access token",
    "Cronofy Refresh token",
    "Cronofy Temp Link Token",
    "authentication",
]

# --- Option set helpers ---
def get_slug(val):
    if val is None:
        return ""
    if isinstance(val, dict):
        return val.get("slug", val.get("display", ""))
    return str(val)

def get_display(val):
    if val is None:
        return ""
    if isinstance(val, dict):
        return val.get("display", val.get("slug", ""))
    return str(val)

def join_array_slugs(arr):
    if not arr:
        return ""
    return ";".join(get_slug(v) for v in arr if get_slug(v))

def join_array_display(arr):
    if not arr:
        return ""
    return ";".join(get_display(v) for v in arr if get_display(v))
