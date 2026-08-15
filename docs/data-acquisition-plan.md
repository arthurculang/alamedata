# Data Acquisition Plan

Companion to [`legal-assessment.md`](./legal-assessment.md). The assessment concludes scraping is *probably* lawful; this document argues it shouldn't be our first move, and lays out what to do instead.

## The case against leading with the scraper

`alameda.citizenrims.com` is a **thin, lossy, transient view** of the underlying RIMS records:

- Arrest logs are typically retained ~30 days; the map covers a limited window. We want years.
- Fields are dropped for public display. The record system has disposition, clearance, unit, response time, call source — the map has a pin and a category.
- HTML/JS output breaks on every vendor release. A CSV export does not.
- We inherit whatever geocoding and category-rollup decisions the vendor made, with no way to audit them.

The CPRA route gets richer data, longer history, and a stable format — and eliminates the one live legal theory (contract) entirely. It's slower to start and strictly better thereafter.

**Recommendation: pursue tiers 1–3 in parallel now; hold the scraper as tier 4.**

---

## Tier 1 — Direct request to Alameda PD (primary)

The records are public. Under the CPRA (Gov. Code § 7922.570 / § 7922.575) an agency must produce records in an electronic format it uses, and duplication cost is limited to the **direct cost of producing the electronic copy**. The agency *may* shift cost to us where the request requires data compilation, extraction, or programming — so the request should ask for an **existing standard report/export** first, which sidesteps that.

**Contacts:**
- `APDRecords@alamedaca.gov` · 510-337-8411
- Formal portal: https://cityofalamedaca.nextrequest.com/requests/new

**Two-step approach:**
1. **Informal email first** — describe the project, ask what standard exports exist and whether a recurring feed is possible. Agencies frequently just say yes, and it costs nothing.
2. **Formal CPRA request** if the informal ask stalls. Draft ready at [`cpra-request-draft.md`](./cpra-request-draft.md).

Ask specifically for a **recurring monthly export**, not a one-shot — that turns a records request into a data pipeline.

## Tier 2 — Existing official aggregates (immediate, zero friction)

Use these now for the historical baseline and to sanity-check anything we scrape later.

| Source | What it gives | Notes |
|---|---|---|
| [City of Alameda — Police & Crime Data (OpenGov)](https://stories.opengov.com/alamedaca/published/ohnjJFMdY) | APD's own published crime series, drillable by month and type | The city's official numbers — our figures should reconcile to these |
| [City of Alameda — Arrest Stats](https://stories.opengov.com/alamedaca/published/LUk-OKaZ1) | Arrest counts | |
| [City of Alameda — Crime Activity](https://www.alamedaca.gov/Departments/Police-Department/Crime-Activity) | Crime mapping + daily activity log, ~6 months | Entry point that links to the CitizenRIMS portal |
| [Alameda County Open Data Hub](https://data.acgov.org/) | County datasets incl. [Crime Reports](https://data.acgov.org/datasets/9e459776d4c3463cad52fe6003ffc668) | ArcGIS Hub — CSV/GeoJSON/KML downloads plus GeoServices/WMS/WFS APIs. Confirm coverage: some datasets are Sheriff-only, not APD |

## Tier 3 — Regional and state comparison data (this is the actual product differentiator)

The WhatsApp thread asked two questions the CitizenRIMS map **structurally cannot answer**, and both are answerable from open federal/state sources:

**"Is the grass greener elsewhere?"** — requires comparable, normalized, per-capita series across peer cities. A single-agency map can never show this.
- [FBI Crime Data Explorer](https://cde.ucr.cjis.gov/) — agency-level UCR/NIBRS for Alameda, Berkeley, San Leandro, Oakland, Lafayette, Piedmont, Albany. Bulk CSV plus a REST API at `https://api.usa.gov/crime/fbi/sapi` (free key from https://api.data.gov/signup/).
- Caveat to surface in the UI: UCR submission is voluntary and the NIBRS transition broke comparability for some agencies in some years. Don't silently paper over gaps.

### Federal data is not a substitute for Alameda's

Worth stating plainly, because it's a tempting shortcut: **FBI CDE cannot replace the APD data.** The gaps run both ways.

| | APD (CitizenRIMS / CPRA) | FBI CDE (UCR / NIBRS) |
|---|---|---|
| Mappable location | Address / block / coordinates | **Location *type* only** (coded category, e.g. "Residence/Home"). No map is possible from federal data. |
| Calls for service | Yes | **Not collected** |
| Recency | Near-real-time (24h, active calls) | Monthly publication; agencies submit on an April 1 deadline for the prior year |
| RIPA stop data | Yes | **No** — CA DOJ only |
| Offense classification | APD internal codes — **not comparable across cities** | Standardized NIBRS/UCR — the whole point |
| Victim/offender demographics, weapon, relationship | Limited / redacted | Richer (NIBRS segments) |
| History | ~30-day public window | 1991–present |
| Coverage guarantee | It's their own data | **Voluntary.** California cumulative NIBRS participation ≈ 48%, ~30 points below the national rate (up from <2% in 2021) |

**Before promising a peer-comparison feature, verify per-agency, per-year submission coverage** for Alameda and every comparison city on the CDE agency pages. Most California agencies have a 2021–2022 hole from the NIBRS transition. A reporting gap rendered as a line going down is a fabricated crime drop — precisely the artifact this project exists to expose. Gaps render as gaps.

**"DUIs are up, but is that just more traffic stops?"** — this is a **denominator problem**, and it's the sharpest insight in the thread. A count is meaningless without the enforcement volume behind it.
- **RIPA stop data** (Racial and Identity Profiling Act) is exactly that denominator: every stop, with outcome. CitizenRIMS itself publishes RIPA stop data, and [CA DOJ OpenJustice](https://openjustice.doj.ca.gov/) publishes statewide downloads.
- Shipping *DUI arrests per 1,000 traffic stops* alongside the raw count would, on its own, make our interface more useful than the source.

## Tier 4 — Scraping (supplement / fallback)

Justified only for **near-real-time** incidents (the 24-hour and active-calls views), which no batch export will match, or if tiers 1–3 fail.

Gated on: V1–V3 in the legal assessment verified clean, and every operating rule in §4 enforced in code. Design notes deferred until the site can actually be inspected — **do not guess at endpoints**; open DevTools, watch the map's network calls, and write the ingester against what's really there.

---

## Architecture sketch

Deliberately boring, so the data outlives the code:

```
sources/          one adapter per source; each writes immutable raw snapshots
  apd_cpra/       CSV/XLSX exports from records requests
  fbi_cde/        API client, keyed, cached
  doj_ripa/       bulk download + parse
  citizenrims/    (tier 4, gated)
raw/              append-only, timestamped, never edited — provenance lives here
normalize/        raw -> canonical incident schema; category crosswalk lives here
db/               Postgres + PostGIS (or SQLite+spatialite to start)
api/              read-only JSON
web/              map + trend + comparison views
```

Two principles worth committing to early:

1. **Raw is immutable and separate from normalized.** Every published figure must be traceable to a timestamped source snapshot. For a civic crime-data project, provenance *is* the credibility.
2. **The category crosswalk is the hard part.** APD categories, UCR/NIBRS codes, and county schemas don't align. That mapping is a reviewable data file with documented decisions — not logic buried in a transform.

## What "superior interface" should mean here

The source map shows *where pins are*. The gap the thread exposed is that residents can't get from pins to judgment. Concretely:

- **Rates, not counts** — per-capita, per-stop, seasonally aware.
- **Peer comparison as a first-class view**, not an afterthought.
- **Denominator-aware enforcement metrics** (the DUI-per-stop insight above).
- **Trend honesty** — confidence bands, explicit annotations where reporting methodology changed, visible gaps instead of interpolated ones.
- **Multi-year history** the 30-day source window can't provide.
- **Every number links back to its source snapshot.**

## Immediate next steps

1. Verify V1–V4 from a normal browser on the real site; commit evidence to `docs/evidence/`.
2. Send the informal email to `APDRecords@alamedaca.gov` (Tier 1, step 1).
3. Get an api.data.gov key and pull FBI CDE agency data for Alameda + peer cities — this is unblocked today and answers the thread's loudest question.
4. Pull the OpenGov and county datasets for the historical baseline.
5. Decide free/non-commercial (keeps the Delete Act out of scope) before any person-level data is displayed.
