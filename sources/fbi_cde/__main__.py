"""CLI for the FBI CDE ingester. See README.md in this directory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import agencies as agencies_mod
from .client import CdeClient, CdeHttpError, ENDPOINTS

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO_ROOT / "raw" / "fbi_cde"
OUT_DIR = REPO_ROOT / "out" / "fbi_cde"

# Oakland PD — a large agency certain to exist in the directory, used only
# to give `probe` a real ORI to exercise the per-agency endpoints with.
PROBE_FALLBACK_ORI = None  # resolved live; never hardcoded


def cmd_probe(_args) -> int:
    """Hit each endpoint once and report what actually answered.

    This is the first thing to run: the endpoint paths were written offline
    and are unverified (see README). Exit 0 = all endpoints answered.
    """
    client = CdeClient.from_env(RAW_ROOT)
    failures = 0

    print("1/3 agency directory …")
    try:
        snap = client.get("agencies_by_state", state="CA")
        payload = snap.json()
        flat = agencies_mod._iter_directory_agencies(payload)
        print(f"      OK — {len(flat)} agencies. Snapshot: {snap.path}")
        probe_ori = next(
            (agencies_mod._agency_ori(a) for a in flat if agencies_mod._agency_ori(a)), None
        )
    except (CdeHttpError, ValueError) as e:
        print(f"      FAIL — {e}")
        print("      Fix ENDPOINTS['agencies_by_state'] in client.py before proceeding.")
        return 1

    for label, endpoint, kwargs in [
        ("2/3 summarized counts", "summarized",
         dict(params={"from": "01-2023", "to": "12-2023", "type": "counts"},
              ori=probe_ori, offense="property-crime")),
        ("3/3 participation", "participation", dict(ori=probe_ori)),
    ]:
        print(f"{label} (ori={probe_ori}) …")
        try:
            snap = client.get(endpoint, **kwargs)
            body = snap.json()
            keys = list(body)[:8] if isinstance(body, dict) else f"list[{len(body)}]"
            print(f"      OK — top-level shape: {keys}. Snapshot: {snap.path}")
        except (CdeHttpError, json.JSONDecodeError) as e:
            print(f"      FAIL — {e}")
            print(f"      Fix ENDPOINTS[{endpoint!r}] in client.py.")
            failures += 1

    print("\nAll raw responses snapshotted under", client.run_dir())
    return 1 if failures else 0


def cmd_agencies(_args) -> int:
    client = CdeClient.from_env(RAW_ROOT)
    print("Resolving peer agencies from the live CA directory …")
    resolved = agencies_mod.resolve(client)
    if not resolved:
        print("No agencies resolved — inspect the snapshot in", client.run_dir())
        return 1
    agencies_mod.save_cache(resolved)
    print(f"\nWrote {len(resolved)} agencies to {agencies_mod.ORI_CACHE}")
    print("Review the diff of ori_cache.json before trusting downstream output.")
    return 0


def cmd_coverage(args) -> int:
    from . import coverage as coverage_mod

    client = CdeClient.from_env(RAW_ROOT)
    roster = agencies_mod.load_cache()
    print(f"Coverage {args.from_year}–{args.to_year} for {len(roster)} agencies "
          f"({(args.to_year - args.from_year + 1) * len(roster)} requests at ≤1/s):")
    rows = coverage_mod.build_matrix(client, roster, args.from_year, args.to_year)
    coverage_mod.write_outputs(rows, OUT_DIR, args.from_year, args.to_year)

    errors = [r for r in rows if r.status == coverage_mod.STATUS_ERROR]
    print(f"\nWrote {OUT_DIR / 'coverage.csv'} and coverage.md")
    if errors:
        print(f"{len(errors)} year-cells errored — those are unknowns, not gaps. "
              "Re-run or inspect snapshots before drawing conclusions.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="fbi_cde")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="verify endpoint assumptions against the live API")
    sub.add_parser("agencies", help="resolve peer-agency ORIs from the live directory")
    cov = sub.add_parser("coverage", help="build the reporting-coverage matrix")
    cov.add_argument("--from-year", type=int, default=2015)
    cov.add_argument("--to-year", type=int, default=2025)
    args = p.parse_args(argv)
    return {"probe": cmd_probe, "agencies": cmd_agencies, "coverage": cmd_coverage}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
