# FBI Crime Data Explorer ingester

Pulls agency-level UCR/NIBRS data for Alameda PD and peer-city agencies from the
FBI Crime Data Explorer API, writing immutable raw snapshots and a
**coverage matrix** — which agencies actually reported, for which years.

The coverage matrix is deliberately the first deliverable. UCR submission is
voluntary and most California agencies have a hole around the 2021–2022 NIBRS
transition; no chart gets built until we know where the holes are
(see `docs/data-acquisition-plan.md`).

## Setup

1. Get a free API key: https://api.data.gov/signup/ (instant, emailed).
2. `export CDE_API_KEY=...`

No third-party dependencies — Python 3.10+ stdlib only.

## Usage

```sh
# 1. Verify the API is up and our endpoint assumptions hold (run this first)
python -m sources.fbi_cde probe

# 2. Resolve ORIs for the peer agencies from the live agency directory
python -m sources.fbi_cde agencies

# 3. Build the coverage matrix (writes raw snapshots + CSV + markdown)
python -m sources.fbi_cde coverage --from-year 2015 --to-year 2025
```

Outputs land in:

- `raw/fbi_cde/<UTC timestamp>/` — verbatim API responses, append-only, never edited
- `out/fbi_cde/coverage.csv` and `out/fbi_cde/coverage.md` — the matrix

## Caveat: endpoint paths are assumptions until `probe` passes

This ingester was written in an environment where `api.usa.gov` was not
reachable, so the endpoint paths in `client.py` are documented best-effort and
**must be confirmed by running `probe` before anything else**. `probe` hits each
endpoint once with a known ORI and reports exactly which respond and what shape
came back. If the API has drifted, fix `ENDPOINTS` in `client.py` — everything
else is driven from there.

## Design notes

- Every HTTP response is snapshotted raw before parsing. Provenance is the product.
- ORIs are resolved from the live agency directory by name, not hardcoded —
  a wrong ORI silently yields another agency's data, which is the worst failure
  mode this pipeline can have. Resolved ORIs are cached in
  `sources/fbi_cde/ori_cache.json` (committed, reviewable) and re-verified on
  each `agencies` run.
- Rate limit: api.data.gov keys allow 1,000 req/hr by default; the client holds
  to 1 request/second regardless.
- "No data for year X" and "request for year X failed" are different facts and
  are recorded differently (`absent` vs `error`) in the matrix.
