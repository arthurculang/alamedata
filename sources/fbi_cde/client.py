"""HTTP client for the FBI Crime Data Explorer API.

Stdlib only. Every response is written verbatim to a raw snapshot directory
before any parsing happens; parsing failures must never cost us the evidence
of what the API actually said.

ENDPOINT PATHS ARE BEST-EFFORT until `python -m sources.fbi_cde probe` has
been run against the live API (this module was written offline). All paths
live in ENDPOINTS so a drift fix touches exactly one place.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://api.usa.gov/crime/fbi/cde"

# {placeholders} are filled by str.format in CdeClient.get.
ENDPOINTS = {
    # Agency directory for a state; response groups agencies by county.
    "agencies_by_state": "/agency/byStateAbbr/{state}",
    # Monthly summarized counts for one agency and offense.
    # Query params: from=MM-YYYY, to=MM-YYYY.
    "summarized": "/summarized/agency/{ori}/{offense}",
    # NIBRS/SRS participation history for one agency.
    "participation": "/participation/agency/{ori}",
}

# Offense slug used for coverage checks: every reporting agency reports
# property crime, so an empty response here means "did not report", not
# "had none of this offense".
COVERAGE_OFFENSE = "property-crime"

USER_AGENT = (
    "alamedata-ingester/0.1 (+https://github.com/arthurculang/alamedata; "
    "civic crime-data project)"
)

MIN_SECONDS_BETWEEN_REQUESTS = 1.0


@dataclass
class RawSnapshot:
    """One verbatim API response, already persisted to disk."""

    url: str  # with API key redacted
    status: int
    path: Path
    body: bytes

    def json(self):
        return json.loads(self.body)


@dataclass
class CdeClient:
    api_key: str
    raw_root: Path
    base_url: str = BASE_URL
    timeout: float = 30.0
    max_retries: int = 4
    _last_request_at: float = field(default=0.0, repr=False)
    _run_dir: Path | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, raw_root: Path) -> "CdeClient":
        key = os.environ.get("CDE_API_KEY", "").strip()
        if not key:
            raise SystemExit(
                "CDE_API_KEY is not set. Get a free key at "
                "https://api.data.gov/signup/ and `export CDE_API_KEY=...`."
            )
        return cls(api_key=key, raw_root=raw_root)

    # -- snapshot plumbing ---------------------------------------------------

    def run_dir(self) -> Path:
        """One directory per ingest run, timestamped, append-only."""
        if self._run_dir is None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self._run_dir = self.raw_root / stamp
            self._run_dir.mkdir(parents=True, exist_ok=True)
        return self._run_dir

    def _snapshot(self, redacted_url: str, status: int, body: bytes) -> Path:
        safe = urllib.parse.quote(redacted_url, safe="")[:180]
        path = self.run_dir() / f"{time.time_ns()}_{status}_{safe}.json"
        meta = {
            "url": redacted_url,
            "status": status,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2))
        path.write_bytes(body)
        return path

    # -- request path --------------------------------------------------------

    def _throttle(self) -> None:
        wait = MIN_SECONDS_BETWEEN_REQUESTS - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def get(self, endpoint: str, params: dict | None = None, **path_args) -> RawSnapshot:
        """GET an ENDPOINTS entry. Raises CdeHttpError on a final non-2xx."""
        path = ENDPOINTS[endpoint].format(**path_args)
        query = dict(params or {})
        redacted_url = f"{self.base_url}{path}?{urllib.parse.urlencode(query)}"
        query["API_KEY"] = self.api_key
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(query)}"

        delay = 2.0
        for attempt in range(self.max_retries + 1):
            self._throttle()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read()
                    status = resp.status
            except urllib.error.HTTPError as e:
                body = e.read()
                status = e.code
            except urllib.error.URLError as e:
                if attempt == self.max_retries:
                    raise CdeHttpError(redacted_url, 0, str(e.reason)) from e
                time.sleep(delay)
                delay *= 2
                continue

            snap_path = self._snapshot(redacted_url, status, body)

            if 200 <= status < 300:
                return RawSnapshot(redacted_url, status, snap_path, body)
            # 429/5xx are retryable; anything else is a hard fail.
            if status in (429,) or status >= 500:
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
            raise CdeHttpError(redacted_url, status, body[:500].decode("utf-8", "replace"))

        raise AssertionError("unreachable")


class CdeHttpError(Exception):
    def __init__(self, url: str, status: int, detail: str):
        self.url, self.status, self.detail = url, status, detail
        super().__init__(f"HTTP {status} for {url}: {detail}")
