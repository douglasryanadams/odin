# TODO

Tracking outstanding work that we want to address but haven't scheduled yet.

## Bug fixes

- **Delete account: friendly error when email does not match.** Submitting an email that is not the logged-in user's to the delete account form returns a raw JSON body in the browser instead of a formatted, useful error message. Render the error inline on the account page (or equivalent) the same way other validation errors are shown.
- **Cached query hits should not count against the daily search quota.** Serving a query from cache costs us nothing (no upstream search, no Claude call), so it shouldn't decrement the user's daily search allowance. Only count quota when we actually run a fresh search.
- **UptimeRobot health checks return 405.** UptimeRobot is reporting 405 Method Not Allowed against the health endpoint even though the site is up and `curl -I` (HEAD) succeeds locally. Investigate what UptimeRobot is actually sending (likely GET, or different path/User-Agent) and make the health endpoint accept it cleanly.
- **Dismissing the privacy policy banner mid-search restarts the search.** Clicking "Got it" on the privacy policy notice while a search is in progress causes the in-flight search to restart. The banner dismissal should be independent of the search lifecycle (no full page reload / form resubmit).

## Features

- **Recent successful searches on the home page.** Surface a list of recent user searches that succeeded on the home page, so visitors get a sense of what the tool can do and what others are finding. Decide on privacy/anonymization rules before implementing.

## Tasks

- **Add a Google Search API key.** Provision a Google Search API key and wire it into the configuration (env var / Secrets Manager) so the Google backend can be enabled.
- **Add a Brave Search API key.** Provision a Brave Search API key and wire it into the configuration (env var / Secrets Manager) so the Brave backend can be enabled.

## Safety / hardening

- **Constrain media types and sources sent to Claude API.** Add an allowlist for the kinds of content we'll fetch and forward to Claude (e.g., text/HTML only, size caps, drop binaries/executables, domain blocklist). Primary motivation is reducing prompt-injection surface from adversarial pages in search results; a secondary benefit is avoiding Claude refusals on clearly harmful content. Keep the list permissive enough that legitimate research queries still work.
