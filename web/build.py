#!/usr/bin/env python3
"""Build the alamedata site from the committed source snapshot.

Reads  data/source/Crime_Reports_Jul2022_Present.geojson  (verbatim ACSO
export from the Alameda County Open Data Hub) and writes:

  web/arrests.data.js   compact cleaned dataset (string tables + rows)
  dist/index.html       single-file site: web/index.html with data inlined

Cleaning is deliberately conservative and every transform is listed in the
site's Method section. Run from the repo root:  python3 web/build.py
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "source" / "Crime_Reports_Jul2022_Present.geojson"
DATA_JS = ROOT / "web" / "arrests.data.js"
TEMPLATE = ROOT / "web" / "index.html"
DIST = ROOT / "dist" / "index.html"

# Obvious truncations / variants seen in the export, normalized to the full
# name. Anything not mapped passes through title-cased.
CITY_FIX = {
    "OA": "OAKLAND", "CAS": "CASTRO VALLEY", "HA": "HAYWARD", "LI": "LIVERMORE",
    "ALCO": "ALAMEDA COUNTY", "SL": "SAN LEANDRO", "SLZ": "SAN LORENZO",
    "": "UNKNOWN", None: "UNKNOWN",
}

# A trailing " - <tail>" is a category only when the tail is a NIBRS-style
# "520 Weapon Law Violations" label or a warrant marker. Other tails (tow
# codes, "RECKLESS DRIVING") are part of the offense text and stay put.
CODE_PREFIX = re.compile(r"^\d{2,3}[A-Z]?\s+")
WARRANT_TAILS = {"LOCAL WARRANT", "OUT WARRANT", "Warrant Felony / Misdemeanor"}
DUI_STATUTE = re.compile(r"^VC 2315[23]")  # VC 23152/23153: DUI / DUI w/ injury

CAT_RENAME = {
    "Trespass of Real": "Trespassing",  # truncated "Trespass of Real Property"
    "All Other Offenses": "Other offenses",
}


def parse_desc(desc: str | None, code: str | None) -> tuple[str, str]:
    """Return (offense_text, category) for one charge row."""
    d = (desc or "").strip()
    if d in WARRANT_TAILS:
        return d, "Warrant service"
    if " - " in d:
        head, tail = (s.strip() for s in d.rsplit(" - ", 1))
        if tail in WARRANT_TAILS:
            return head, "Warrant service"
        if CODE_PREFIX.match(tail):
            name = CODE_PREFIX.sub("", tail)
            return head, CAT_RENAME.get(name, name)
    # No recognized category tail: whole string is the offense. 1,304 rows
    # have an empty description — fall back to the statute code alone.
    offense = d or (f"Code {code.strip()}" if code and code.strip() else "(no charge text)")
    # Statute assist for the one category this project cares about tracking:
    # dash-less "VC 23152(A) DRIVING UNDER INFLUENCE…" rows are DUI arrests.
    cat = "Driving Under the Influence" if DUI_STATUTE.match(d) else "Uncategorized"
    return offense, cat


def city_of(raw: str | None) -> str:
    c = (raw or "").strip().upper()
    c = CITY_FIX.get(c, c)
    return c.title().replace("'S", "'s")


def main() -> None:
    feats = json.loads(SOURCE.read_text())["features"]

    seen = set()
    rows, cities, cats, offs = [], {}, {}, {}
    dupes = dropped_geo = 0

    def intern(table: dict, value: str) -> int:
        return table.setdefault(value, len(table))

    for f in feats:
        p = f["properties"]
        key = (p.get("Arrest_id"), p.get("CrimeCode"), p.get("DateTime"))
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        g = f.get("geometry") or {}
        coords = g.get("coordinates") or [None, None]
        lon, lat = coords[0], coords[1]
        if lat is None or not (36.5 < lat < 39) or not (-123.5 < lon < -121):
            dropped_geo += 1
            continue
        t = datetime.fromisoformat(p["DateTime"].replace("Z", "+00:00"))
        offense, cat = parse_desc(p.get("CrimeDescription"), p.get("CrimeCode"))
        rows.append([
            int(t.timestamp() // 60),          # epoch minutes
            round(lat, 4), round(lon, 4),      # ~11 m; Street field dropped
            intern(cities, city_of(p.get("City"))),
            intern(cats, cat),
            intern(offs, offense),
            (p.get("Block") or "").strip().title(),
        ])

    rows.sort(key=lambda r: r[0])

    months = Counter(datetime.fromtimestamp(r[0] * 60, tz=timezone.utc).strftime("%Y-%m") for r in rows)
    first, last = min(months), max(months)

    data = {
        "meta": {
            "source": "Alameda County Sheriff's Office via Alameda County Open Data Hub",
            "file": SOURCE.name,
            "retrieved": "2026-08-15",
            "built": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "rows": len(rows),
            "dupesRemoved": dupes,
            "droppedNoGeo": dropped_geo,
            "partialMonths": [first, last],  # export starts/ends mid-month
        },
        "cities": list(cities),
        "cats": list(cats),
        "offs": list(offs),
        "rows": rows,
    }

    payload = "const ALAMEDATA=" + json.dumps(data, separators=(",", ":")) + ";"
    DATA_JS.write_text("// generated by web/build.py — do not edit\n" + payload + "\n")

    html = TEMPLATE.read_text()
    tag = '<script src="arrests.data.js"></script>'
    assert tag in html, "data script tag missing from template"
    DIST.parent.mkdir(exist_ok=True)
    DIST.write_text(html.replace(tag, "<script>" + payload + "</script>"))

    kb = DATA_JS.stat().st_size // 1024
    print(f"rows={len(rows)} dupes={dupes} no/bad-geo={dropped_geo} "
          f"cities={len(cities)} cats={len(cats)} offenses={len(offs)}")
    print(f"months {first}..{last} | arrests.data.js {kb} KB | dist {DIST.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
