# TODO

Tracking outstanding work that we want to address but haven't scheduled yet. Items are ordered by priority and magnitude of impact within each tier; revisit the ordering whenever a new TODO is added or scope changes.

## High priority

Security exposure, broken operational visibility, accumulating cost, and user-fairness bugs. Most are small changes with disproportionate impact.

1. **Cached query hits should not count against the daily search quota.** Serving a query from cache costs us nothing (no upstream search, no Claude call), so it shouldn't decrement the user's daily search allowance. Only count quota when we actually run a fresh search.

## Medium priority

Reliability work, UX bugs in normal flows, and provisioning that unblocks new search backends.

1. **Harden search-result reliability.** Reduce the rate at which searches and page loads fail end-to-end. Catalogue the failure modes we see (upstream search timeouts, fetch errors on individual result pages, Claude API hiccups, partial result sets), then add the right mix of retries with backoff, per-source timeouts, graceful degradation when one source is down, and clear user-facing messaging when a partial answer is the best we can do. Add metrics so we can track failure rates over time.
2. **Dismissing the privacy policy banner mid-search restarts the search.** Clicking "Got it" on the privacy policy notice while a search is in progress causes the in-flight search to restart. The banner dismissal should be independent of the search lifecycle (no full page reload / form resubmit).
3. **Add a Google Search API key.** Provision a Google Search API key and wire it into the configuration (env var / Secrets Manager) so the Google backend can be enabled.
4. **Add a Brave Search API key.** Provision a Brave Search API key and wire it into the configuration (env var / Secrets Manager) so the Brave backend can be enabled.
5. **Generate an Open Graph share image.** The SEO baseline shipped text-only social unfurls. Add a 1200x630 PNG (`static/og-image.png`) with the ODIN wordmark on the existing dark background, reference it as `og:image` / `twitter:image` in the `social_meta` block of `_base.html`, and switch `twitter:card` to `summary_large_image`. Social platforms (LinkedIn, X, Slack, Discord) typically triple CTR with a real card image.
6. **Wire Google Search Console and Bing Webmaster verification meta tags.** Once `odinseye.info` is registered in both consoles, drive the verification tokens off optional env vars (`GOOGLE_SITE_VERIFICATION`, `BING_SITE_VERIFICATION`) so the values stay out of the repo, render them in `_base.html` only when present, and submit `sitemap.xml` from each console. Bing Webmaster can import the GSC verification directly.
7. **Delete account: friendly error when email does not match.** Submitting an email that is not the logged-in user's to the delete account form returns a raw JSON body in the browser instead of a formatted, useful error message. Render the error inline on the account page (or equivalent) the same way other validation errors are shown.
8. **Replace the removed `detect-secrets` lint step.** We pulled `detect-secrets` out of `make lint` because it shells out to `git` from inside the container, and a worktree's `.git` pointer escapes the bind mount, so the step fails any time someone lints from a worktree. We still want a pre-merge secret-scan signal — evaluate alternatives that don't depend on container-internal git: a GitHub Actions job using `trufflehog` or `gitleaks` over the PR diff, `git-secrets` pre-commit, or a host-side wrapper that runs detect-secrets outside Docker. Pick one, wire it into CI, document the audit workflow in `docs/configuration.md`.

## Low priority / backlog

Discretionary features and exploratory research; pick these up when higher tiers are clear or when one becomes strategically interesting.

1. **GitHub source link on the results page.** Restore a visible link to the project's GitHub repo so users browsing search results can find the source, read the README, or open issues — a trust signal and a discoverability path for contributors. Place it somewhere unobtrusive (results-page header corner or footer) — not the home page. Use the standard GitHub Octocat mark, styled to match the existing theme (current accent color, spacing, and corner radius) and small enough that it doesn't compete with the answer for attention.
2. **Recent successful searches on the home page.** Surface a list of recent user searches that succeeded on the home page, so visitors get a sense of what the tool can do and what others are finding. Decide on privacy/anonymization rules before implementing.
3. **Print/export button on search results.** Add a button on the results page that produces a clean, shareable version of the answer and sources (print-friendly stylesheet at minimum; ideally also a downloadable export such as PDF or Markdown). Strip site chrome, keep citations linkable, and make sure it works without JavaScript where feasible.
4. **Map of key event locations in the overview.** When the overview describes events tied to specific places, render a map alongside the summary that pins those locations. Have Claude emit structured place data (name + coordinates, or names we geocode server-side) so the map is driven by the answer rather than guessed from prose. Decide on a map provider (tile source, licensing, offline/static vs interactive) before implementing.
5. **Popularity / trends graph on results.** Show a time-series "popularity" chart for the search topic (Google Trends or an equivalent source) so users can see how interest in the subject has changed over time. Evaluate available APIs for licensing, rate limits, and historical depth; cache results to stay within quota and keep the page fast.
6. **Evaluate additional public-data search sources.** Investigate which public platforms expose supported APIs we could query to supplement our current backends — Twitter/X, Reddit, Hacker News, Stack Exchange, Wikipedia, Mastodon, YouTube, GitHub, etc. For each, capture: API availability and stability, auth requirements, rate limits, pricing, terms-of-service constraints on resale/redistribution, and how well the content fits our answer-synthesis pipeline. Output a short ranked recommendation of which to integrate first.
7. **IndexNow ping on publish.** Add a tiny background task that posts canonical URLs to the IndexNow endpoint whenever a sitemap-listed page changes (or on deploy). Near-zero effort to gain Bing and Yandex near-instant indexing; Google has not adopted IndexNow so this complements, rather than replaces, sitemap submission.
