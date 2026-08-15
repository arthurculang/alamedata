"""Peer agency roster and ORI resolution.

ORIs are resolved from the live CDE agency directory by name, never
hardcoded: a mistyped ORI silently returns some other agency's data, which
is the worst failure this pipeline can have. Resolved ORIs are cached in a
committed JSON file so resolution changes show up in review.

Note on Lafayette: it appears in the roster because the WhatsApp thread
joked about moving there, but it is in Contra Costa County and is policed
under contract with the county sheriff — its reporting identity on CDE may
differ from a standalone city PD. The resolver will surface whatever the
directory actually contains; treat a miss as information, not an error.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .client import CdeClient

ORI_CACHE = Path(__file__).parent / "ori_cache.json"

# (display name, state, name patterns tried in order against the directory)
PEER_AGENCIES = [
    ("Alameda PD", "CA", [r"^alameda\b(?!.*(county|sheriff))"]),
    ("Berkeley PD", "CA", [r"^berkeley\b"]),
    ("Oakland PD", "CA", [r"^oakland\b"]),
    ("San Leandro PD", "CA", [r"^san leandro\b"]),
    ("Albany PD", "CA", [r"^albany\b"]),
    ("Piedmont PD", "CA", [r"^piedmont\b"]),
    ("Emeryville PD", "CA", [r"^emeryville\b"]),
    ("Alameda County Sheriff", "CA", [r"^alameda county"]),
    ("Lafayette", "CA", [r"^lafayette\b"]),
]


@dataclass
class ResolvedAgency:
    display_name: str
    directory_name: str
    ori: str
    county: str | None = None


def _iter_directory_agencies(payload) -> list[dict]:
    """Flatten the byStateAbbr response defensively.

    The directory response has been seen as {county: [agency, ...]} but the
    shape is unverified offline (see README); accept a plain list too, and
    fail loudly on anything else so `probe` output gets consulted.
    """
    if isinstance(payload, list):
        return [a for a in payload if isinstance(a, dict)]
    if isinstance(payload, dict):
        out = []
        for county, agencies in payload.items():
            if not isinstance(agencies, list):
                raise ValueError(
                    f"Unexpected agency-directory shape under key {county!r}; "
                    "run `python -m sources.fbi_cde probe` and inspect the snapshot."
                )
            for a in agencies:
                if isinstance(a, dict):
                    a.setdefault("_county", county)
                    out.append(a)
        return out
    raise ValueError("Unexpected agency-directory payload type: " + type(payload).__name__)


def _agency_name(a: dict) -> str:
    for key in ("agency_name", "ncic_agency_name", "pub_agency_name", "name"):
        if a.get(key):
            return str(a[key])
    return ""


def _agency_ori(a: dict) -> str:
    for key in ("ori", "ORI", "agency_ori"):
        if a.get(key):
            return str(a[key])
    return ""


def resolve(client: CdeClient, state: str = "CA") -> list[ResolvedAgency]:
    snap = client.get("agencies_by_state", state=state)
    directory = _iter_directory_agencies(snap.json())

    resolved: list[ResolvedAgency] = []
    for display, st, patterns in PEER_AGENCIES:
        if st != state:
            continue
        match = None
        for pat in patterns:
            rx = re.compile(pat, re.IGNORECASE)
            candidates = [a for a in directory if rx.search(_agency_name(a).strip())]
            if candidates:
                # Prefer the shortest name: "Alameda Police Department" over
                # "Alameda Housing Authority PD" style near-misses.
                match = min(candidates, key=lambda a: len(_agency_name(a)))
                break
        if match is None:
            print(f"  MISS  {display}: no directory entry matched {patterns}")
            continue
        ori = _agency_ori(match)
        if not ori:
            print(f"  MISS  {display}: matched {_agency_name(match)!r} but found no ORI field")
            continue
        resolved.append(
            ResolvedAgency(display, _agency_name(match).strip(), ori, match.get("_county"))
        )
        print(f"  OK    {display}: {ori}  ({_agency_name(match).strip()})")

    return resolved


def save_cache(agencies: list[ResolvedAgency]) -> None:
    ORI_CACHE.write_text(
        json.dumps([a.__dict__ for a in agencies], indent=2, sort_keys=True) + "\n"
    )


def load_cache() -> list[ResolvedAgency]:
    if not ORI_CACHE.exists():
        raise SystemExit(
            "No ORI cache yet — run `python -m sources.fbi_cde agencies` first."
        )
    return [ResolvedAgency(**d) for d in json.loads(ORI_CACHE.read_text())]
