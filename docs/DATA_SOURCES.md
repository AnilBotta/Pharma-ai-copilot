# Data Sources

## Summary

| Provider | Required | Credentials | Without them |
|---|---|---|---|
| **PubMed** (NCBI E-utilities) | yes | optional key | Works at 3 req/s instead of 10 |
| **Europe PMC** | yes | none | Full function |
| **EPO OPS** | yes | key + secret | **No patent search.** Run continues on literature; report states patents were not searched |
| OpenAI | yes | API key | Nothing runs |
| Crossref | no | optional mailto | Not implemented |
| OpenAlex | no | optional key | Not implemented |
| USPTO | no | API key | Not implemented |

Crossref, OpenAlex and USPTO appear in configuration and on the integrations
page so their absence is visible, but no adapter exists yet.

---

## PubMed — NCBI E-utilities

**Endpoint** `https://eutils.ncbi.nlm.nih.gov/entrez/eutils`
**Credentials** `NCBI_API_KEY` (optional), `NCBI_EMAIL` (requested by NCBI policy)
**Key** https://account.ncbi.nlm.nih.gov → Account Settings → API Key Management

Two calls per search: `esearch` returns PMIDs, `efetch` returns records as XML.

Rate limits are NCBI's published figures: **3 requests/second without a key, 10
with one**. The adapter paces at 2.5 and 9 respectively to stay under.

The date filter is expressed in the query string (`(query) AND 2015:2026[dp]`)
rather than as `mindate`/`maxdate` parameters, so the exact string recorded in
`search_queries` is what was executed.

**Parsing notes.** Structured abstracts keep their section labels
(`OBJECTIVE: …`). Titles containing inline markup are flattened. Collective
author names are preserved. `ArticleDate` (electronic publication) is preferred
over the journal issue date, which is often year-only.

`efetch` never returns body text, so records are always `abstract_only`.
PubMed does not assert open access, so `is_open_access` stays false rather than
being guessed — Europe PMC supplies that.

**Verified live**: 15 records from 158 hits, with correct identifiers, dates,
authors and structured abstracts.

---

## Europe PMC

**Endpoint** `https://www.ebi.ac.uk/europepmc/webservices/rest`
**Credentials** none

Broader corpus than PubMed, including preprints. It is also the source that can
tell us whether open-access full text exists.

`resultType=core` is requested so abstracts and metadata arrive in the search
response, avoiding a round trip per record.

No published hard rate limit; the adapter paces at 5 req/s out of politeness.

**Important**: `isOpenAccess=Y` means full text is *available*, not that it was
*retrieved*. The search response carries no body text, so records remain
`abstract_only`. Marking them `full_text` would assert something untrue.

Preprints are detected from `source == "PPR"` or a preprint publication type
and labelled.

**Verified live**: 15 records from 7,454 hits, with open-access flags and PMCIDs.

---

## EPO Open Patent Services (OPS 3.2)

**Endpoints** `https://ops.epo.org/3.2/auth/accesstoken`, `.../rest-services`
**Credentials** `EPO_OPS_CONSUMER_KEY`, `EPO_OPS_CONSUMER_SECRET` — **both required**
**Register** https://developers.epo.org — free, 4 GB/month

OAuth2 client credentials. Tokens last ~20 minutes and are cached, refreshed 60
seconds before expiry.

A partial credential pair counts as unconfigured, so the failure message says
what is actually wrong rather than producing a confusing 401.

**Query format.** Plain text becomes `ti="..." or ab="..."`. Text already
containing a CQL operator is passed through. Date and jurisdiction clauses are
appended.

**Document types.** The kind code classifies each result: `B`/`C` prefixes
indicate a granted patent, everything else a published application. This
distinction is preserved in the database and displayed, because presenting an
application as a granted patent would materially mislead.

**Legal status is not inferred.** OPS exposes it through a separate register
service that costs extra quota. The field stays `None` rather than being guessed
from a kind code.

**Quota.** 4 GB/month on the free tier. Exhaustion surfaces as a rate-limit
error and zero results, never as degraded output.

> ⚠️ **Not verified live.** The OAuth2 endpoint and flow were confirmed correct
> (invalid credentials return 401, not 404), but the response parser has never
> seen a real OPS payload. Field paths, single-vs-list collapsing, party
> de-duplication and classification parsing are written against documented
> shapes and fixture data. Expect to fix parsing on first live use.

---

## OpenAI

**Credentials** `OPENAI_API_KEY` — required; nothing runs without it.

Uses the **Responses API** (`client.responses.parse`) with Pydantic-typed
structured output. The deprecated Assistants API is not used.

Five configurable model roles:

```env
OPENAI_MODEL_SUPERVISOR=      # planning and synthesis
OPENAI_MODEL_RESEARCH=        # background
OPENAI_MODEL_EXTRACTION=      # per-record extraction — the cheap one
OPENAI_MODEL_SYNTHESIS=       # report writing
OPENAI_MODEL_VERIFICATION=    # evidence review
OPENAI_EMBEDDING_MODEL=       # document RAG (not yet implemented)
```

Extraction runs once per retrieved record and dominates call volume, so it is
the slot worth pointing at a cheaper model.

`ModelProvider.health_check()` lists available models and reports any configured
name the key cannot access, so a typo in `OPENAI_MODEL_SYNTHESIS` fails at
startup rather than mid-run after money has been spent.

---

## Shared provider behaviour

### The contract

```
succeeded     → records
found nothing → zero records, ok=True
failed        → zero records, ok=False, error explains why
```

No fourth branch. No adapter substitutes, approximates or synthesises.

The distinction between "found nothing" and "failed" matters downstream: the
first supports "no reliable evidence found"; the second does not.

### Rate limiting and retries

Minimum-interval pacing per provider. Bounded exponential backoff capped at 8s
(0.5, 1, 2, 4, 8). `Retry-After` is honoured on 429. 4xx other than 429 is not
retried — it will fail identically and only waste quota.

### Caching

Responses are cached in `provider_cache`, keyed by a hash of provider, operation
and sorted parameters. Default TTL 24 hours (`PROVIDER_CACHE_TTL_SECONDS`).

The cache is shared across users because PubMed, Europe PMC and EPO responses
are public data and sharing them reduces quota consumption. **No user content is
ever written there.** RLS is enabled with no policy, so the anon key cannot read
it.

A cache failure degrades to an uncached call rather than failing the run.

### Deduplication

Literature: DOI → PMID → PMCID → normalised title, strongest first, with
transitive grouping. Records are merged rather than discarded, so the survivor
keeps the union of identifiers and the most complete metadata. Full text wins
over provider preference, since having the text determines whether the evidence
may be described as full text.

Titles under 20 characters are excluded as identity keys, so "Erratum" does not
collapse unrelated records.

Patents: by family. Granted beats application, then earliest priority, then
lowest publication number. Absorbed members remain visible in `family_members`.

### Query logging

Every query against every provider is written to `search_queries` with its
result count, cache status, duration and error. The run page displays them, so
the user sees exactly what was searched rather than a claim that searching
occurred.

### Identifier integrity

A record with no resolvable identifier is dropped — enforced both in the
adapter and by the `literature_has_identifier` database constraint.

Identifiers are normalised, never coerced. A regression fixed during
development: an early validator prefixed `PMC` onto any long numeric value,
turning PMID `26414409` into the non-existent `PMC26414409`. PMIDs and PMCIDs
now have separate validators that reject rather than reshape, because a mangled
identifier resolves to the wrong paper or to nothing.

URLs are derived from verified identifiers (`https://doi.org/{doi}`,
`https://pubmed.ncbi.nlm.nih.gov/{pmid}/`), never invented.
