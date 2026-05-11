# TODO

Tracking outstanding work that we want to address but haven't scheduled yet.

## Bug fixes

- **Delete account: friendly error when email does not match.** Submitting an email that is not the logged-in user's to the delete account form returns a raw JSON body in the browser instead of a formatted, useful error message. Render the error inline on the account page (or equivalent) the same way other validation errors are shown.
- **Cached query hits should not count against the daily search quota.** Serving a query from cache costs us nothing (no upstream search, no Claude call), so it shouldn't decrement the user's daily search allowance. Only count quota when we actually run a fresh search.
- **UptimeRobot health checks return 405.** UptimeRobot is reporting 405 Method Not Allowed against the health endpoint even though the site is up and `curl -I` (HEAD) succeeds locally. Investigate what UptimeRobot is actually sending (likely GET, or different path/User-Agent) and make the health endpoint accept it cleanly.
- **Dismissing the privacy policy banner mid-search restarts the search.** Clicking "Got it" on the privacy policy notice while a search is in progress causes the in-flight search to restart. The banner dismissal should be independent of the search lifecycle (no full page reload / form resubmit).

## Features

- **Recent successful searches on the home page.** Surface a list of recent user searches that succeeded on the home page, so visitors get a sense of what the tool can do and what others are finding. Decide on privacy/anonymization rules before implementing.
- **Print/export button on search results.** Add a button on the results page that produces a clean, shareable version of the answer and sources (print-friendly stylesheet at minimum; ideally also a downloadable export such as PDF or Markdown). Strip site chrome, keep citations linkable, and make sure it works without JavaScript where feasible.

## Tasks

- **Add a Google Search API key.** Provision a Google Search API key and wire it into the configuration (env var / Secrets Manager) so the Google backend can be enabled.
- **Add a Brave Search API key.** Provision a Brave Search API key and wire it into the configuration (env var / Secrets Manager) so the Brave backend can be enabled.
- **Apply the ECR lifecycle policy.** The `odin` ECR repository has no retention rules, so every deploy adds a new `:<sha>` tag that lives forever and storage cost grows monotonically. Follow `docs/aws-setup.md` § 1a to add the two-rule policy (expire untagged after 1 day, keep last 10 tagged).

## Safety / hardening

- **Constrain media types and sources sent to Claude API.** Add an allowlist for the kinds of content we'll fetch and forward to Claude (e.g., text/HTML only, size caps, drop binaries/executables, domain blocklist). Primary motivation is reducing prompt-injection surface from adversarial pages in search results; a secondary benefit is avoiding Claude refusals on clearly harmful content. Keep the list permissive enough that legitimate research queries still work.
- **Harden search-result reliability.** Reduce the rate at which searches and page loads fail end-to-end. Catalogue the failure modes we see (upstream search timeouts, fetch errors on individual result pages, Claude API hiccups, partial result sets), then add the right mix of retries with backoff, per-source timeouts, graceful degradation when one source is down, and clear user-facing messaging when a partial answer is the best we can do. Add metrics so we can track failure rates over time.

## Research

- **Evaluate additional public-data search sources.** Investigate which public platforms expose supported APIs we could query to supplement our current backends — Twitter/X, Reddit, Hacker News, Stack Exchange, Wikipedia, Mastodon, YouTube, GitHub, etc. For each, capture: API availability and stability, auth requirements, rate limits, pricing, terms-of-service constraints on resale/redistribution, and how well the content fits our answer-synthesis pipeline. Output a short ranked recommendation of which to integrate first.
