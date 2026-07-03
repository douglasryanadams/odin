# Search Source Evaluation

This memo evaluates candidate public-data sources for a new `SearchBackend`.
See [`docs/search.md`](./search.md) for the protocol and the two backends
already shipped, Brave and Wikipedia. The goal, per
[`docs/vision.md`](./vision.md), is to feed more diverse, citable sources
into the cross-source connection pass. Two constraints bound that goal:
ODIN's cost-to-serve budget, and its promise that every fact traces back to
a source we are allowed to cache and show.

Eight sources were requested for evaluation: Twitter/X, Reddit, Hacker News,
Stack Exchange, Mastodon, YouTube, and GitHub. A ninth, Wikidata, is added
because it fits the connection pass better than most of the requested list
and costs nothing.

## Summary

| Source | Verdict | Reason |
| --- | --- | --- |
| Wikidata | **Build first** | Structured facts, CC0 license, no auth, near-zero engineering cost. Best fit for the connection pass of anything evaluated. |
| GitHub | **Build second** | Clean key-based auth like Brave's, generous free tier, permissive terms. Narrow but high-value for technical and organizational profiles. |
| Hacker News | Build (low priority) | Trivial integration, no auth, no cost. Coverage is narrow: startups, tech, and their people. |
| Stack Exchange | Hold | Cheap and simple, but CC BY-SA per-answer attribution adds real rendering work, and content outside technical topics is thin. |
| Reddit | Hold | Free tier exists, but terms restrict it to non-commercial use and require syncing deletions and edits. ODIN's future ad-funding plan (`docs/vision.md`) makes "non-commercial" a moving target. |
| YouTube | Hold | Official API is cheap, but the 30-day mandatory cache refresh and "no competing directory" clause need an expiry job we don't have, for thin per-result text (titles and descriptions, no transcripts). |
| Mastodon | Reject | No central index. Thousands of independently governed instances, each with its own auth, rate limit, and terms. No single endpoint gives useful coverage. |
| Twitter/X | Reject | No usable free read tier as of 2026 (pay-per-use, $0.005/read). Ongoing compliance burden (sync deletions, no bulk caching) independent of price. |

## Wikidata

**API availability.** Official, stable, maintained by the Wikimedia
Foundation. Two entry points suit ODIN: the `wbsearchentities` action on
`www.wikidata.org/w/api.php` for keyword lookup, and the SPARQL endpoint at
`query.wikidata.org` for structured queries once an entity ID is known.

**Auth.** None. Same policy as the existing Wikipedia backend: send a
descriptive `User-Agent` with a contact URL and email.

**Rate limits.** The SPARQL endpoint allows 60 seconds of query time per
minute per IP and user agent, bursting to 120. The search API has no
published hard cap; Wikimedia asks only for a compliant `User-Agent` and
reasonable request pacing. One or two calls per ODIN profile fits easily
inside either limit.

**Pricing.** Free. No tier, no key, no quota to buy.

**Terms of service.** All Wikidata content is CC0: public domain, no
attribution required, no resale or redistribution restriction. This is the
lowest-risk license of any source evaluated, lower even than Wikipedia's
CC BY-SA (which does require attribution).

**Fit with the synthesis pipeline.** Excellent. Wikidata stores atomic,
typed facts, not prose: birth date, occupation, employer, nationality,
family relations, external identifiers. That is the raw material the
cross-source connection pass needs. A fact from Wikidata can corroborate or
contradict a claim pulled from Brave or Wikipedia, and the connection can
cite both. Coverage also extends past Wikipedia's own reach, since many
minor entities carry a Wikidata item without a full article.

**Fit with `SearchBackend`.** Drop-in. It is an unauthenticated GET call
with JSON in and out, no session, no OAuth handshake. The implementation
looks like `WikipediaBackend` almost line for line: build a `User-Agent`
from settings, call `wbsearchentities`, and map each hit to a
`SearchResult`. One open question remains: whether search should return
entity summaries directly, or make a second SPARQL call to expand claims.
A first cut can ship with descriptions alone and add claim expansion later.

## GitHub

**API availability.** Official REST and GraphQL APIs, stable, heavily used,
well documented.

**Auth.** A personal access token or a registered GitHub App. Read-only
access to public data needs no user OAuth flow. A single token scoped to
public repos is enough. That is much closer to Brave's static-key model
than to a full OAuth dance.

**Rate limits.** 5,000 requests/hour authenticated (60/hour unauthenticated,
too low to use). The Search endpoints specifically (`/search/users`,
`/search/repositories`, `/search/issues`) are capped tighter, at 30
requests/minute per token. That still covers thousands of ODIN profile
lookups a day.

**Pricing.** Free for read access to public data at this volume. No paid
tier is needed unless usage grows past the free rate limit, and GitHub does
not charge per-request even then — it just throttles harder.

**Terms of service.** GitHub's API terms permit caching search results and
metadata for normal application use; there is no resale-specific
prohibition on read-only public data comparable to Twitter's or Reddit's.
Displaying a user's public profile, bio, or repository description with a
link back is standard practice for GitHub-integrated tools.

**Fit with the synthesis pipeline.** Good but narrow. Structured JSON
data — bio, company, location, public repositories, contribution activity
— is strong signal for software engineers, open-source maintainers, and
companies with an engineering presence. That is a real subset of ODIN's
queries, not the general case. A public figure with no GitHub footprint
simply gets nothing back from this backend, and the aggregator already
handles that gracefully.

**Fit with `SearchBackend`.** Clean. Same shape as `BraveBackend`: static
token in a header, one GET call, JSON mapped directly to `SearchResult`.

## Hacker News

**API availability.** Two APIs exist. The official Firebase-backed API
(`hacker-news.firebaseio.com`) mirrors live site state (item by item); the
community-maintained Algolia Search API (`hn.algolia.com/api/v1/search`)
indexes full history and is the one that matters for search-style queries.
Both are stable and have run largely unchanged for years.

**Auth.** None for either API.

**Rate limits.** Algolia's HN Search API allows roughly 10,000 requests per
hour per IP. The Firebase API publishes no formal limit but expects
reasonable, cached use. Either comfortably covers ODIN's expected volume.

**Pricing.** Free, no tier.

**Terms of service.** No published restriction on caching or displaying
search results; the API exists specifically to let third parties build
search and analysis tools on top of Hacker News content. Attribution is a
link back to the discussion thread, which ODIN already does for every
source.

**Fit with the synthesis pipeline.** Narrow but clean where it applies.
Coverage is startups, engineers, tech companies, and product launches. A
comment thread can surface a founder's own words, or a detail no press
source carries. But the same thread can just as easily be off-topic noise
for a query outside tech. Signal quality varies post to post. The pipeline
should treat Hacker News results as corroborating color, not a primary
fact source.

**Fit with `SearchBackend`.** Best of the set for integration cost. One
unauthenticated GET, JSON response, no header ceremony beyond a
`User-Agent`. This is the same shape as `WikipediaBackend` with a smaller
domain.

## Stack Exchange

**API availability.** Official REST API (v2.3), stable, documented, spans
the whole network (Stack Overflow plus 170+ other Q&A communities:
Skeptics, Law, Judaism, Academia, and more).

**Auth.** A free registered "app key" raises the daily quota; no user OAuth
is needed for reading public questions and answers.

**Rate limits.** 300 requests/day per IP without a key, 10,000/day with a
registered key (per key-and-IP pair). A hard ceiling of 30 requests/second
applies regardless. 10,000/day is enough for steady ODIN traffic at today's
scale.

**Pricing.** Free at this volume.

**Terms of service.** All user-contributed content is CC BY-SA 4.0. Legal
reuse requires attribution: the author's name, a link to their profile,
and a link to the original question. That attribution has to show up per
result, not once per page. This is a real, if small, rendering change:
today's citation format shows a URL and a title, not a per-answer byline.

**Fit with the synthesis pipeline.** Mixed. Q&A content is more structured
than typical social chatter. Answers on non-programming sites can surface
biographical or factual detail — a Skeptics.SE thread scrutinizing a
public claim, for instance. But most of the network's volume is
programming Q&A, which rarely matters to a person, place, or event
profile.

**Fit with `SearchBackend`.** Simple call shape, comparable to Brave. The
added attribution requirement is a display-layer cost, not a backend-layer
one, but it is not free.

## Reddit

**API availability.** Official Data API, stable, actively maintained,
following a major terms and pricing overhaul in mid-2023.

**Auth.** OAuth2 app registration (script-app credentials are enough for
read-only, no per-user login needed).

**Rate limits.** Free tier: 100 requests/minute authenticated (10/minute
unauthenticated). That is generous in isolation.

**Pricing.** The free tier is explicitly scoped to "personal projects,
academic research, and non-commercial applications." Commercial use starts
at roughly $12,000/year for the lowest paid tier, scaling with rate limit.

**Terms of service.** This is the real blocker, not the rate limit. Two
clauses matter for ODIN specifically:

1. The free tier's non-commercial restriction. ODIN is non-commercial
   today, but `docs/vision.md` names advertising as a future sustainability
   path "at critical mass." Reddit could plausibly reclassify an
   ad-supported ODIN as commercial. That would cut off free access, or
   force the $12,000/year tier.
2. Content lifecycle obligations. Reddit's terms require any cached copy
   to reflect upstream deletions and edits. ODIN would need a sync or
   expiry job just for Reddit results, not the generic cache timeout every
   other backend uses today.

**Fit with the synthesis pipeline.** Mixed to poor for grounding. Reddit is
the "noisy social chatter" that `docs/vision.md` implicitly contrasts with
cited fact-finding: opinion, sarcasm, and unverifiable anecdote dominate.
It can add useful color about a subject's public reception. But the
connection pass exists to assert corroboration or contradiction between
sources, and an unverified Reddit comment is a weak anchor for either.

**Fit with `SearchBackend`.** Moderate lift. OAuth2 app credentials and
token refresh add more moving parts than a static API key, though still
far short of a full user-auth flow. The bigger gap is the deletion-sync
obligation. The current registry pattern does not anticipate it at all:
every other backend treats a cached result as valid until its own TTL
expires.

**Recommendation.** Hold. Revisit only if the non-commercial question is
resolved (ODIN commits to staying ad-free, or Reddit's terms change) and if
the deletion-sync work is scoped as its own item.

## YouTube

**API availability.** Official Data API v3, stable, run by Google.

**Auth.** API key, same shape as Brave's.

**Rate limits.** Quota-based, not request-count-based: 10,000 units/day
free. A search call costs 100 units, so roughly 100 searches/day before
hitting the ceiling; a details lookup costs 1 unit. Raising the quota
requires a compliance audit and Google's manual approval.

**Pricing.** No per-call charge; the constraint is the quota, not money. A
paid path to raise it does not exist in the way it does for Brave — you
request more free quota and wait for review.

**Terms of service.** The YouTube API Services Developer Policies require
any client that stores API data to delete or refresh it within 30 calendar
days. ODIN's caching model has no source-specific expiry logic today; it
treats a cached result as valid until a single generic TTL runs out.
YouTube would need a new refresh-or-delete job, similar in shape to the
Reddit obligation above. The terms also block building a directory or
dataset that competes with YouTube's own service, a fuzzy line that calls
for caution around any bulk indexing.

**Fit with the synthesis pipeline.** Weak. The v3 API returns titles,
descriptions, and metadata, not transcripts. A transcript needs a separate,
less-supported API surface with its own terms questions. Titles and
descriptions also read like marketing copy more often than not, not the
factual density the connection pass wants. Where YouTube helps is
confirming that a subject has a public voice or presence, through
interviews or talks. That is real value, but a secondary one.

**Fit with `SearchBackend`.** Structurally simple (key-based, JSON), but
the 30-day refresh obligation is real recurring engineering weight for
comparatively thin content.

**Recommendation.** Hold. Revisit if a future need specifically wants
video/media presence signals, and budget for the refresh job at that point.

## Mastodon

**API availability.** Each Mastodon server runs its own instance of the
same open API; there is no single "Mastodon API" endpoint the way there is
a single Reddit or Twitter API. The protocol connecting instances
(ActivityPub) is federation, not search.

**Auth.** Varies per instance. Some instances serve public search
unauthenticated. A growing number restrict search and public timelines to
logged-in users only, a trend driven by instance-operator privacy concerns
(discussed openly in Mastodon's own GitHub issue tracker).

**Rate limits.** Set independently by each instance's operator; no network-
wide number exists.

**Pricing.** Free, but meaningless as a comparison point given the
structural problem below.

**Terms of service.** Set independently per instance, with no network-wide
terms to evaluate once.

**Fit with the synthesis pipeline.** The deciding problem is coverage, not
content quality. Querying one instance's search endpoint only searches
posts that instance has federated into its own view. That view is a
subset of the fediverse, decided by which other instances it follows.
There is no canonical "search all of Mastodon," the way
`api.wikimedia.org` searches all of Wikipedia. Building broad coverage
would mean integrating with many independently governed instances at
once, and trusting each one's uptime, terms, and rate limit.

**Fit with `SearchBackend`.** Poor. The registry pattern assumes one
backend equals one upstream service with one contract. Mastodon would need
either a fixed list of hand-picked instances (fragile, arbitrary coverage)
or a third-party fediverse-wide search aggregator (an extra dependency with
its own reliability and terms to vet). Neither is a clean fit.

**Recommendation.** Reject. Revisit only if a well-supported, terms-clear,
network-wide fediverse search service emerges.

## Twitter/X

**API availability.** Official API, but its terms and pricing have changed
repeatedly since 2023 and again in February 2026, when X moved new
developers to pay-per-use by default with no viable free read tier.

**Auth.** OAuth2 app registration, developer account approval.

**Rate limits.** The nominal free tier allows about 500 posts/month and one
request per 24 hours on most read endpoints — not usable for live search at
any real volume.

**Pricing.** Pay-per-use as of 2026: $0.005 per post read, capped at 2
million reads/month. Legacy Basic ($200/month) and Pro ($5,000/month)
tiers remain, but only for existing subscribers. At ODIN's query volume,
this is real recurring cost for a single backend, well outside a "cheap
tier" by any reading. It also costs far more per read than Brave's roughly
$3–5 per 1,000 queries.

**Terms of service.** Historically among the strictest of any source
evaluated. Display requirements have required syncing deletions in near
real time, capped how many posts can be stored offline, and restricted
bulk export and republishing at every tier. Even setting price aside, the
compliance burden of keeping cached tweets in sync with live deletions and
edits outweighs anything else considered here.

**Fit with the synthesis pipeline.** Would be genuinely useful in
principle — real-time public statements from a subject are strong,
citable, first-person material. The cost and compliance burden are what
rule it out, not the content.

**Fit with `SearchBackend`.** Not evaluated in depth given the pricing and
terms verdict above; OAuth2 app registration alone would already be a
bigger lift than Brave's static key.

**Recommendation.** Reject at current pricing. Revisit only if X
reintroduces a usable free or low-cost read tier.

## Recommendation

Build **Wikidata** first. It costs nothing, carries no licensing risk
(CC0), and needs no auth. Its structured facts are the best input to the
cross-source connection pass of anything evaluated: an atomic claim from
Wikidata is easier to corroborate or contradict against Brave or Wikipedia
prose than a comment, a post, or a video description. The implementation
is close to a copy of `WikipediaBackend`, which keeps the lift small.

Build **GitHub** second. Its free tier easily covers ODIN's volume, its
terms are permissive for read-only public data, and its key-based auth
matches Brave's existing pattern rather than adding a new one. Its value
is narrower, strongest for technical and organizational profiles. But
where it applies, the structured data — bio, company, location, activity —
is a clean, low-noise addition.

Hacker News is a reasonable third pick, if a low-cost, low-risk source is
wanted beyond the first two. It needs zero auth and costs nothing, but its
coverage is narrower than either recommendation above, so it does not
outrank them.

Reddit, YouTube, and Stack Exchange are worth revisiting later, each for
the specific reason noted in its section above: non-commercial terms, the
30-day refresh obligation, and per-answer attribution. None is ready to
build today without resolving that blocker first. Mastodon and Twitter/X
should not be pursued under current terms. Mastodon has no coverage story,
and Twitter/X has no affordable one.
