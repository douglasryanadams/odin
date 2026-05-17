# TODO

Tracking outstanding work that we want to address but haven't scheduled yet. Items are ordered by priority and magnitude of impact within each tier; revisit the ordering whenever a new TODO is added or scope changes.

## High priority

Security exposure, broken operational visibility, accumulating cost, and user-fairness bugs. Most are small changes with disproportionate impact.

1. **Constrain media types and sources sent to Claude API.** Add an allowlist for the kinds of content we'll fetch and forward to Claude (e.g., text/HTML only, size caps, drop binaries/executables, domain blocklist). Primary motivation is reducing prompt-injection surface from adversarial pages in search results; a secondary benefit is avoiding Claude refusals on clearly harmful content. Keep the list permissive enough that legitimate research queries still work.
2. **UptimeRobot health checks return 405.** UptimeRobot is reporting 405 Method Not Allowed against the health endpoint even though the site is up and `curl -I` (HEAD) succeeds locally. Investigate what UptimeRobot is actually sending (likely GET, or different path/User-Agent) and make the health endpoint accept it cleanly.
3. **CloudFront usage approaching free-tier limit.** AWS notified us we've consumed 50% of the CloudFront free tier this billing period, so at the current trajectory we'll start incurring real CDN cost soon. Start by opening the CloudFront usage report to see whether request count or egress bytes is the dominant driver, since the right fix differs. Likely levers, in rough order of expected impact:
   1. Configure Custom Error Responses so 404/403/5xx responses are cached at the edge for several minutes — bot probes for paths like `/wp-admin` or `.php` otherwise hit origin on every request.
   2. Audit `Cache-Control` headers from the Flask app so hashed static assets are `public, max-age=31536000, immutable`, semi-static pages (home, about, terms) get a short edge cache, and authenticated or search responses remain no-cache.
   3. Add a `robots.txt` and consider a CloudFront Function or WAF rule that turns away the noisiest scrapers and known-bad user agents before they reach origin.

   Decide the strategy after reading the usage report — don't guess which lever matters most.
4. **Apply the ECR lifecycle policy.** The `odin` ECR repository has no retention rules, so every deploy adds a new `:<sha>` tag that lives forever and storage cost grows monotonically. Follow `docs/aws-setup.md` § 1a to add the two-rule policy (expire untagged after 1 day, keep last 10 tagged).
5. **Cached query hits should not count against the daily search quota.** Serving a query from cache costs us nothing (no upstream search, no Claude call), so it shouldn't decrement the user's daily search allowance. Only count quota when we actually run a fresh search.

## Medium priority

Reliability work, UX bugs in normal flows, and provisioning that unblocks new search backends.

1. **Harden search-result reliability.** Reduce the rate at which searches and page loads fail end-to-end. Catalogue the failure modes we see (upstream search timeouts, fetch errors on individual result pages, Claude API hiccups, partial result sets), then add the right mix of retries with backoff, per-source timeouts, graceful degradation when one source is down, and clear user-facing messaging when a partial answer is the best we can do. Add metrics so we can track failure rates over time.
2. **SEO baseline: About page and crawlable metadata.** Outside the home page the site exposes very little indexable content, which makes us hard to find for relevant queries. Add a small amount of static content and SEO hygiene so search engines have something to chew on — without turning the site into a content-marketing surface. Suggested minimum scope:
   1. Write a concise About page (what the tool does, what it doesn't, why this approach) — no marketing fluff.
   2. Add per-route `<title>` and `<meta name="description">` to home, about, and the results page.
   3. Add Open Graph and Twitter Card tags so shared links unfurl with a sensible title, description, and image.
   4. Add a `robots.txt` and a basic `sitemap.xml` listing the public pages.
   5. Confirm each public page has a single `<h1>` and clear semantic structure for crawlers.

   Defer blog or content-marketing additions — keep the surface area small and the focus on search.
3. **Dismissing the privacy policy banner mid-search restarts the search.** Clicking "Got it" on the privacy policy notice while a search is in progress causes the in-flight search to restart. The banner dismissal should be independent of the search lifecycle (no full page reload / form resubmit).
4. **Add a Google Search API key.** Provision a Google Search API key and wire it into the configuration (env var / Secrets Manager) so the Google backend can be enabled.
5. **Add a Brave Search API key.** Provision a Brave Search API key and wire it into the configuration (env var / Secrets Manager) so the Brave backend can be enabled.
6. **Delete account: friendly error when email does not match.** Submitting an email that is not the logged-in user's to the delete account form returns a raw JSON body in the browser instead of a formatted, useful error message. Render the error inline on the account page (or equivalent) the same way other validation errors are shown.

## Low priority / backlog

Discretionary features and exploratory research; pick these up when higher tiers are clear or when one becomes strategically interesting.

1. **GitHub source link on the results page.** Restore a visible link to the project's GitHub repo so users browsing search results can find the source, read the README, or open issues — a trust signal and a discoverability path for contributors. Place it somewhere unobtrusive (results-page header corner or footer) — not the home page. Use the standard GitHub Octocat mark, styled to match the existing theme (current accent color, spacing, and corner radius) and small enough that it doesn't compete with the answer for attention.
2. **Recent successful searches on the home page.** Surface a list of recent user searches that succeeded on the home page, so visitors get a sense of what the tool can do and what others are finding. Decide on privacy/anonymization rules before implementing.
3. **Print/export button on search results.** Add a button on the results page that produces a clean, shareable version of the answer and sources (print-friendly stylesheet at minimum; ideally also a downloadable export such as PDF or Markdown). Strip site chrome, keep citations linkable, and make sure it works without JavaScript where feasible.
4. **Map of key event locations in the overview.** When the overview describes events tied to specific places, render a map alongside the summary that pins those locations. Have Claude emit structured place data (name + coordinates, or names we geocode server-side) so the map is driven by the answer rather than guessed from prose. Decide on a map provider (tile source, licensing, offline/static vs interactive) before implementing.
5. **Popularity / trends graph on results.** Show a time-series "popularity" chart for the search topic (Google Trends or an equivalent source) so users can see how interest in the subject has changed over time. Evaluate available APIs for licensing, rate limits, and historical depth; cache results to stay within quota and keep the page fast.
6. **Evaluate additional public-data search sources.** Investigate which public platforms expose supported APIs we could query to supplement our current backends — Twitter/X, Reddit, Hacker News, Stack Exchange, Wikipedia, Mastodon, YouTube, GitHub, etc. For each, capture: API availability and stability, auth requirements, rate limits, pricing, terms-of-service constraints on resale/redistribution, and how well the content fits our answer-synthesis pipeline. Output a short ranked recommendation of which to integrate first.
