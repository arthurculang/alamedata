"""Coverage matrix: which agencies actually reported, for which years.

This runs before any analytics. `reported` means the summarized endpoint
returned nonzero monthly counts for the coverage offense (property crime —
chosen because any reporting agency has some). `absent` means the API
answered but had no data for that year. `error` means we don't know, and
the two must never be conflated: an `absent` rendered as a decline is a
fabricated crime drop.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .agencies import ResolvedAgency
from .client import CdeClient, CdeHttpError, COVERAGE_OFFENSE

STATUS_REPORTED = "reported"
STATUS_PARTIAL = "partial"  # some but not all months present
STATUS_ABSENT = "absent"
STATUS_ERROR = "error"

GLYPH = {
    STATUS_REPORTED: "█",
    STATUS_PARTIAL: "▒",
    STATUS_ABSENT: "·",
    STATUS_ERROR: "?",
}


@dataclass
class YearCoverage:
    ori: str
    display_name: str
    year: int
    months_with_data: int
    status: str
    note: str = ""


def _extract_monthly_counts(payload, year: int) -> list:
    """Pull per-month entries for `year` from a summarized response.

    Handles the shapes seen in CDE responses ({"offenses": {"actuals":
    {agency: {"MM-YYYY": n}}}} or a flat list of month records); anything
    unrecognized raises so the caller records `error` rather than `absent`.
    """
    months = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                # keys like "01-2023" / "2023-01"
                ks = str(k)
                if (ks.endswith(f"-{year}") or ks.startswith(f"{year}-")) and isinstance(
                    v, (int, float)
                ):
                    months.append((ks, v))
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, dict) and any(
                    str(item.get(f)) == str(year) for f in ("data_year", "year")
                ):
                    months.append((item.get("month", "?"), item.get("count", item.get("actual", 0))))
                else:
                    walk(item)

    walk(payload)
    return months


def year_coverage(
    client: CdeClient, agency: ResolvedAgency, year: int
) -> YearCoverage:
    try:
        snap = client.get(
            "summarized",
            params={"from": f"01-{year}", "to": f"12-{year}", "type": "counts"},
            ori=agency.ori,
            offense=COVERAGE_OFFENSE,
        )
        months = _extract_monthly_counts(snap.json(), year)
    except CdeHttpError as e:
        return YearCoverage(agency.ori, agency.display_name, year, 0, STATUS_ERROR, f"HTTP {e.status}")
    except ValueError as e:
        return YearCoverage(agency.ori, agency.display_name, year, 0, STATUS_ERROR, str(e)[:120])

    nonzero = [m for m in months if m[1]]
    n = len({m[0] for m in nonzero})
    if n >= 12:
        status = STATUS_REPORTED
    elif n > 0:
        status = STATUS_PARTIAL
    else:
        status = STATUS_ABSENT
    return YearCoverage(agency.ori, agency.display_name, year, n, status)


def build_matrix(
    client: CdeClient,
    agencies: list[ResolvedAgency],
    from_year: int,
    to_year: int,
) -> list[YearCoverage]:
    rows = []
    for agency in agencies:
        for year in range(from_year, to_year + 1):
            yc = year_coverage(client, agency, year)
            rows.append(yc)
        line = "".join(
            GLYPH[r.status] for r in rows if r.ori == agency.ori
        )
        print(f"  {agency.display_name:<28} {from_year}–{to_year}  {line}")
    return rows


def write_outputs(rows: list[YearCoverage], out_dir: Path, from_year: int, to_year: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "coverage.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ori", "agency", "year", "months_with_data", "status", "note"])
        for r in rows:
            w.writerow([r.ori, r.display_name, r.year, r.months_with_data, r.status, r.note])

    years = list(range(from_year, to_year + 1))
    by_agency: dict[str, dict[int, YearCoverage]] = {}
    for r in rows:
        by_agency.setdefault(r.display_name, {})[r.year] = r

    lines = [
        "# FBI CDE reporting coverage",
        "",
        f"Coverage offense: `{COVERAGE_OFFENSE}` (proxy for 'agency reported at all').",
        "█ = all 12 months · ▒ = partial year · `·` = no data in API · ? = request failed",
        "",
        "**Rule: `·` and `?` render as gaps in every downstream chart — never as zero.**",
        "",
        "| Agency | " + " | ".join(str(y) for y in years) + " |",
        "|---|" + "|".join("---" for _ in years) + "|",
    ]
    for name, yearly in by_agency.items():
        cells = [GLYPH.get(yearly[y].status, "?") if y in yearly else "?" for y in years]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    (out_dir / "coverage.md").write_text("\n".join(lines) + "\n")
