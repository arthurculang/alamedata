"""Offline tests for the FBI CDE ingester.

The live API is exercised by `probe`; these tests pin the parsing and
matrix logic against fixture payloads in both response shapes the code
claims to handle.

Run: python -m unittest sources.fbi_cde.test_fbi_cde
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from . import agencies as agencies_mod
from . import coverage as coverage_mod
from .agencies import ResolvedAgency
from .client import CdeHttpError, RawSnapshot


class FakeClient:
    """Duck-types CdeClient.get; serves canned payloads keyed by endpoint."""

    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def get(self, endpoint, params=None, **path_args):
        self.calls.append((endpoint, params, path_args))
        result = self.payloads[endpoint]
        if callable(result):
            result = result(params, path_args)
        if isinstance(result, Exception):
            raise result
        body = json.dumps(result).encode()
        return RawSnapshot("fake://" + endpoint, 200, Path("/dev/null"), body)


DIRECTORY_BY_COUNTY = {
    "ALAMEDA": [
        {"ori": "CA0010100", "agency_name": "Alameda Police Department"},
        {"ori": "CA0010000", "agency_name": "Alameda County Sheriff's Office"},
        {"ori": "CA0010200", "agency_name": "Albany Police Department"},
        {"ori": "CA0010300", "agency_name": "Berkeley Police Department"},
        {"ori": "CA0010900", "agency_name": "Oakland Police Department"},
        {"ori": "CA0011100", "agency_name": "Piedmont Police Department"},
        {"ori": "CA0011200", "agency_name": "San Leandro Police Department"},
        {"ori": "CA0010500", "agency_name": "Emeryville Police Department"},
    ],
    "CONTRA COSTA": [
        {"ori": "CA0070500", "agency_name": "Lafayette Police Department"},
    ],
}


class DirectoryTests(unittest.TestCase):
    def test_flatten_by_county_shape(self):
        flat = agencies_mod._iter_directory_agencies(DIRECTORY_BY_COUNTY)
        self.assertEqual(len(flat), 9)
        self.assertEqual(flat[0]["_county"], "ALAMEDA")

    def test_flatten_plain_list_shape(self):
        flat = agencies_mod._iter_directory_agencies(list(DIRECTORY_BY_COUNTY["ALAMEDA"]))
        self.assertEqual(len(flat), 8)

    def test_unexpected_shape_raises(self):
        with self.assertRaises(ValueError):
            agencies_mod._iter_directory_agencies({"ALAMEDA": {"not": "a list"}})

    def test_resolve_picks_city_pd_not_county(self):
        client = FakeClient({"agencies_by_state": DIRECTORY_BY_COUNTY})
        resolved = {a.display_name: a for a in agencies_mod.resolve(client)}
        self.assertEqual(resolved["Alameda PD"].ori, "CA0010100")
        self.assertEqual(resolved["Alameda County Sheriff"].ori, "CA0010000")
        self.assertEqual(resolved["Lafayette"].ori, "CA0070500")
        self.assertEqual(len(resolved), len(agencies_mod.PEER_AGENCIES))


def summarized_nested(year, months=12, count=40):
    return {
        "offenses": {
            "actuals": {
                "Agency": {f"{m:02d}-{year}": count for m in range(1, months + 1)}
            }
        }
    }


def summarized_flat_list(year, months=12, count=40):
    return [
        {"data_year": year, "month": m, "count": count} for m in range(1, months + 1)
    ]


AGENCY = ResolvedAgency("Alameda PD", "Alameda Police Department", "CA0010100")


class CoverageTests(unittest.TestCase):
    def _one_year(self, payload, year=2023):
        client = FakeClient({"summarized": payload})
        return coverage_mod.year_coverage(client, AGENCY, year)

    def test_full_year_nested_shape(self):
        yc = self._one_year(summarized_nested(2023))
        self.assertEqual((yc.status, yc.months_with_data), ("reported", 12))

    def test_full_year_flat_list_shape(self):
        yc = self._one_year(summarized_flat_list(2023))
        self.assertEqual((yc.status, yc.months_with_data), ("reported", 12))

    def test_partial_year(self):
        yc = self._one_year(summarized_nested(2023, months=5))
        self.assertEqual((yc.status, yc.months_with_data), ("partial", 5))

    def test_zero_counts_are_absent_not_reported(self):
        yc = self._one_year(summarized_nested(2023, count=0))
        self.assertEqual(yc.status, "absent")

    def test_empty_payload_is_absent(self):
        yc = self._one_year({"offenses": {"actuals": {}}})
        self.assertEqual(yc.status, "absent")

    def test_http_error_is_error_not_absent(self):
        yc = self._one_year(CdeHttpError("u", 503, "boom"))
        self.assertEqual(yc.status, "error")
        self.assertIn("503", yc.note)

    def test_other_years_data_not_counted(self):
        yc = self._one_year(summarized_nested(2022), year=2023)
        self.assertEqual(yc.status, "absent")

    def test_matrix_outputs(self):
        def serve(params, path_args):
            year = int(params["from"].split("-")[1])
            if year == 2021:
                return {"offenses": {"actuals": {}}}  # the NIBRS-transition hole
            return summarized_nested(year)

        client = FakeClient({"summarized": serve})
        rows = coverage_mod.build_matrix(client, [AGENCY], 2020, 2022)
        self.assertEqual([r.status for r in rows], ["reported", "absent", "reported"])

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            coverage_mod.write_outputs(rows, out, 2020, 2022)
            md = (out / "coverage.md").read_text()
            self.assertIn("| Alameda PD | █ | · | █ |", md)
            csv_text = (out / "coverage.csv").read_text()
            self.assertIn("CA0010100,Alameda PD,2021,0,absent,", csv_text)


if __name__ == "__main__":
    unittest.main()
