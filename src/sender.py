"""Middleware HTTP client: wraps sf-middleware-api POST/PATCH calls.

Every call is written to sync.db via SyncLog BEFORE the HTTP request so a
crashed run still leaves a pending row. The response (http_status, jobId,
duration) is patched onto the same row after the call returns.

Routes are documented in MIDDLEWARE_ENDPOINTS.md.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Iterable

import requests

from src.config import (
    MIDDLEWARE_API_SECRET,
    MIDDLEWARE_BACKOFF_BASE,
    MIDDLEWARE_MAX_RETRIES,
    MIDDLEWARE_MIN_INTERVAL,
    MIDDLEWARE_TIMEOUT,
    MIDDLEWARE_URL,
)
from src.sync_log import SyncLog


class SenderError(RuntimeError):
    """Raised when a middleware request fails after all retries.

    status_code is the last observed HTTP status when known (set for 401,
    404, and 5xx-exhausted paths); None for network-error exhaustion.
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class Sender:
    def __init__(
        self,
        log: SyncLog,
        *,
        dry_run: bool = False,
        verbose: bool = False,
        base_url: str | None = None,
        secret: str | None = None,
    ) -> None:
        self.log = log
        self.dry_run = dry_run
        self.verbose = verbose
        self.base_url = (base_url or MIDDLEWARE_URL).rstrip("/")
        self.secret = secret if secret is not None else MIDDLEWARE_API_SECRET
        self.session = requests.Session()
        self._last_request_at = 0.0
        self.sent_count = 0
        self.skipped_count = 0

        if not self.dry_run and not self.secret:
            raise EnvironmentError(
                "MIDDLEWARE_API_SECRET is not set. Add it to .env or pass --dry-run."
            )

    # --- Route methods ------------------------------------------------------

    def send_prospect(self, balo_id: str, payload: dict, sources: Iterable[dict], *, store_payload: dict | None = None) -> dict | None:
        return self._send(
            method="POST",
            route="/crm/prospect",
            sf_object="Prospect__c",
            balo_id=balo_id,
            payload=payload,
            sources=sources,
            store_payload=store_payload,
        )

    def send_account(self, balo_id: str, payload: dict, sources: Iterable[dict], *, store_payload: dict | None = None) -> dict | None:
        return self._send(
            method="PATCH",
            route=f"/crm/account/{balo_id}",
            sf_object="Account",
            balo_id=balo_id,
            payload=payload,
            sources=sources,
            store_payload=store_payload,
        )

    def send_contact(self, balo_id: str, payload: dict, sources: Iterable[dict], *, store_payload: dict | None = None) -> dict | None:
        return self._send(
            method="PATCH",
            route=f"/crm/contact/{balo_id}",
            sf_object="Contact",
            balo_id=balo_id,
            payload=payload,
            sources=sources,
            store_payload=store_payload,
        )

    def send_opportunity_case(self, case_number: str, payload: dict, sources: Iterable[dict], *, store_payload: dict | None = None) -> dict | None:
        return self._send(
            method="PATCH",
            route=f"/crm/opportunity/case/{case_number}",
            sf_object="Opportunity",
            balo_id=case_number,
            payload=payload,
            sources=sources,
            store_payload=store_payload,
        )

    def send_opportunity_project(self, request_id: str, payload: dict, sources: Iterable[dict], *, store_payload: dict | None = None) -> dict | None:
        return self._send(
            method="PATCH",
            route=f"/crm/opportunity/project/{request_id}",
            sf_object="Opportunity",
            balo_id=request_id,
            payload=payload,
            sources=sources,
            store_payload=store_payload,
        )

    def send_project_expert(self, composite_id: str, payload: dict, sources: Iterable[dict], *, store_payload: dict | None = None) -> dict | None:
        return self._send(
            method="PATCH",
            route=f"/crm/project-expert/{composite_id}",
            sf_object="Project__c",
            balo_id=composite_id,
            payload=payload,
            sources=sources,
            store_payload=store_payload,
        )

    def send_consultation(self, meeting_id: str, payload: dict, sources: Iterable[dict], *, store_payload: dict | None = None) -> dict | None:
        return self._send(
            method="PATCH",
            route=f"/crm/consultation/{meeting_id}",
            sf_object="Consultation__c",
            balo_id=meeting_id,
            payload=payload,
            sources=sources,
            store_payload=store_payload,
        )

    # --- Core ---------------------------------------------------------------

    def _send(
        self,
        *,
        method: str,
        route: str,
        sf_object: str,
        balo_id: str,
        payload: dict,
        sources: Iterable[dict],
        store_payload: dict | None = None,
    ) -> dict | None:
        """Send `payload` over HTTP; log `store_payload` (or `payload`) to sync.db.

        Distinguishing wire vs. stored payload lets sync.py send a partial
        diff to SF while still recording the full current Bubble state as the
        baseline for next run's diff.
        """
        event_id = self.log.log_send(
            sf_object=sf_object,
            route=route,
            balo_id=balo_id,
            payload=store_payload if store_payload is not None else payload,
            sources=sources,
        )

        if self.dry_run:
            self.sent_count += 1
            if self.verbose:
                print(f"  [dry-run] {method} {route}", file=sys.stderr)
            return None

        url = f"{self.base_url}{route}"
        headers = {
            "Authorization": f"Bearer {self.secret}",
            "Content-Type": "application/json",
        }

        started = time.monotonic()
        try:
            resp = self._request_with_retries(method, url, headers=headers, json_body=payload)
        except SenderError as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            self.log.update_result(
                event_id,
                http_status=exc.status_code,
                job_id=None,
                response_body=str(exc)[:2000],
                duration_ms=duration_ms,
            )
            raise

        duration_ms = int((time.monotonic() - started) * 1000)
        body_text = resp.text[:4000] if resp.text else ""
        job_id = None
        parsed: dict | None = None
        try:
            parsed = resp.json()
            if isinstance(parsed, dict):
                job_id = parsed.get("jobId") or parsed.get("job_id")
        except ValueError:
            parsed = None

        self.log.update_result(
            event_id,
            http_status=resp.status_code,
            job_id=job_id,
            response_body=body_text,
            duration_ms=duration_ms,
        )

        if resp.status_code != 202:
            raise SenderError(
                f"{method} {route} returned {resp.status_code}: {body_text[:300]}"
            )

        self.sent_count += 1
        if self.verbose:
            print(
                f"  [ok] {method} {route} -> {resp.status_code} jobId={job_id} ({duration_ms}ms)",
                file=sys.stderr,
            )
        return parsed

    def _request_with_retries(
        self,
        method: str,
        url: str,
        *,
        headers: dict,
        json_body: dict,
    ) -> requests.Response:
        last_exc: Exception | None = None
        last_status: int | None = None

        for attempt in range(MIDDLEWARE_MAX_RETRIES):
            self._throttle()
            try:
                resp = self.session.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                    timeout=MIDDLEWARE_TIMEOUT,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                wait = MIDDLEWARE_BACKOFF_BASE ** attempt
                # Always print after attempt 3 so the operator can Ctrl-C
                # instead of waiting out the full 1+2+4+8+16s backoff.
                if self.verbose or attempt >= 2:
                    print(
                        f"  [WARN] network error ({exc.__class__.__name__}), retry in {wait}s "
                        f"(attempt {attempt + 1}/{MIDDLEWARE_MAX_RETRIES})",
                        file=sys.stderr,
                    )
                time.sleep(wait)
                continue

            if resp.status_code == 401:
                raise SenderError(
                    "401 from middleware — MIDDLEWARE_API_SECRET is invalid",
                    status_code=401,
                )
            if resp.status_code == 404:
                raise SenderError(
                    f"404 from middleware — route not found: {url}",
                    status_code=404,
                )

            if resp.status_code >= 500:
                last_status = resp.status_code
                wait = MIDDLEWARE_BACKOFF_BASE ** attempt
                if self.verbose or attempt >= 2:
                    print(
                        f"  [WARN] {resp.status_code} from middleware, retry in {wait}s "
                        f"(attempt {attempt + 1}/{MIDDLEWARE_MAX_RETRIES})",
                        file=sys.stderr,
                    )
                time.sleep(wait)
                continue

            return resp

        if last_exc is not None:
            raise SenderError(
                f"network error after {MIDDLEWARE_MAX_RETRIES} attempts: {last_exc}",
                status_code=None,
            )
        raise SenderError(
            f"5xx from middleware after {MIDDLEWARE_MAX_RETRIES} attempts",
            status_code=last_status,
        )

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIDDLEWARE_MIN_INTERVAL:
            time.sleep(MIDDLEWARE_MIN_INTERVAL - elapsed)
        self._last_request_at = time.monotonic()
