# alamedata

A civic data project: make Alameda, CA crime and public-safety data actually analyzable — trends over time, per-capita rates, denominator-aware enforcement metrics, and comparison against neighboring cities.

The city already publishes incident data through a vendor crime map. That map shows *where the pins are*. It can't tell you whether crime is up or down in any meaningful sense, whether Alameda is safer than its neighbors, or whether a jump in DUI arrests reflects more drunk driving or simply more traffic stops. That gap is the project.

## Status

Pre-implementation. Legal and sourcing groundwork is done; no data has been acquired yet.

## Documents

| Doc | What it covers |
|---|---|
| [`docs/legal-assessment.md`](docs/legal-assessment.md) | Whether scraping the city's CitizenRIMS portal is lawful — CFAA, contract, CDAFA, copyright, trespass to chattels, and downstream privacy exposure. Includes the operating rules that bind this project. |
| [`docs/data-acquisition-plan.md`](docs/data-acquisition-plan.md) | Where the data actually comes from. Four tiers, with scraping as the last one. |
| [`docs/cpra-request-draft.md`](docs/cpra-request-draft.md) | Ready-to-send informal email and formal California Public Records Act request to Alameda PD. |

## Position in one paragraph

Scraping the public map is very likely lawful in the Ninth Circuit — but it's the *worst* of the available paths. The underlying records are California public records, which means we can request them directly, in bulk, in machine-readable form, with more fields and more history than the map exposes and no contractual risk at all. So: file the records request, build the historical baseline from official federal, state, and county sources that are open today, and treat scraping as a supplement for near-real-time data if we need it. See the legal assessment for the full reasoning and the conditions attached.

## Principles

- **Free and non-commercial.** Selling person-level data pulls the project into California's data-broker regime.
- **Provenance over convenience.** Raw source snapshots are immutable and every published figure traces back to one.
- **Aggregate by default.** No booking photos, no victim details, no exact addresses for sensitive incident types.
- **Arrests are allegations.** Anything person-level carries that framing, is `noindex`ed, and has a takedown path.
- **Honest gaps.** Show missing and methodologically-broken data as missing, not interpolated.
- **Not an official record** of the Alameda Police Department, and labeled as such everywhere.
