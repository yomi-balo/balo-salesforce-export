import json
import time
import sys

import requests

from src.config import (
    BASE_URL,
    BALO_API_TOKEN,
    RATE_LIMIT_DELAY,
    RATE_LIMIT_MAX_RETRIES,
    RATE_LIMIT_BACKOFF_BASE,
)


class BubbleClient:
    def __init__(self, verbose=False):
        self.token = BALO_API_TOKEN
        self.base_url = BASE_URL
        self.verbose = verbose
        self.request_count = 0
        self.session = requests.Session()

    def _get(self, path, params=None):
        params = params or {}
        params["api_token"] = self.token

        time.sleep(RATE_LIMIT_DELAY)

        for attempt in range(RATE_LIMIT_MAX_RETRIES):
            self.request_count += 1
            url = f"{self.base_url}/{path}"

            if self.verbose:
                print(f"  [{self.request_count}] GET {url}", file=sys.stderr)

            try:
                resp = self.session.get(url, params=params, timeout=30)
            except requests.ConnectionError:
                if attempt < 2:
                    print(f"  [WARN] Connection error, retrying in 2s (attempt {attempt + 1})", file=sys.stderr)
                    time.sleep(2)
                    continue
                raise
            except requests.Timeout:
                if attempt < 2:
                    print(f"  [WARN] Timeout, retrying in 2s (attempt {attempt + 1})", file=sys.stderr)
                    time.sleep(2)
                    continue
                raise

            if resp.status_code == 401:
                raise PermissionError("Invalid API token. Check your .env file.")

            if resp.status_code == 429:
                wait = RATE_LIMIT_BACKOFF_BASE ** attempt
                print(f"  [WARN] Rate limited (429). Waiting {wait}s (attempt {attempt + 1}/{RATE_LIMIT_MAX_RETRIES})", file=sys.stderr)
                time.sleep(wait)
                continue

            if resp.status_code == 404:
                return None

            if resp.status_code == 400:
                # Bad request — likely invalid constraint. Return empty rather than crash.
                if self.verbose:
                    print(f"  [WARN] 400 Bad Request: {resp.text[:200]}", file=sys.stderr)
                return None

            if resp.status_code >= 500:
                if attempt == 0:
                    print(f"  [WARN] Server error {resp.status_code}, retrying in 5s", file=sys.stderr)
                    time.sleep(5)
                    continue
                resp.raise_for_status()

            resp.raise_for_status()
            return resp.json()

        raise RuntimeError(f"Max retries ({RATE_LIMIT_MAX_RETRIES}) exceeded on rate limit for {path}")

    def fetch_list(self, table_path, constraints=None, limit=100, cursor=0):
        params = {"limit": limit, "cursor": cursor}
        if constraints:
            params["constraints"] = json.dumps(constraints)
        result = self._get(f"obj/{table_path}", params)
        if result is None:
            return {"results": [], "cursor": 0, "count": 0, "remaining": 0}
        return result["response"]

    def fetch_record(self, table_path, uid):
        result = self._get(f"obj/{table_path}/{uid}")
        if result is None:
            return None
        return result["response"]

    def fetch_all_pages(self, table_path, constraints=None, max_pages=None):
        all_records = []
        cursor = 0
        page = 0

        while True:
            resp = self.fetch_list(table_path, constraints=constraints, limit=100, cursor=cursor)
            all_records.extend(resp.get("results", []))
            remaining = resp.get("remaining", 0)
            count = resp.get("count", 0)
            page += 1

            if remaining == 0 or count == 0:
                break
            if max_pages and page >= max_pages:
                break

            cursor += count

        return all_records
