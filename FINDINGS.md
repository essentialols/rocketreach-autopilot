# RocketReach Reverse Engineering Findings

## Anti-bot layers (in order of depth)

### 1. reCAPTCHA v3 (BYPASSED)

- Score-based, invisible
- Bypass: hit Google's `api2/anchor` + `api2/reload` endpoints directly
- Works because most sites set threshold low (0.3-0.5)
- Our tokens pass for account creation

### 2. Phone verification (PARTIALLY BYPASSED)

- Triggered when reCAPTCHA v3 score is low (our pure HTTP tokens)
- NOT triggered for browser signups with real behavioral signals
- The check is on the `POST /v1/signup` response: `error_code: 205`
- Account IS created (gets user_id) but session stays `state: anonymous`

### 3. Cloudflare (BYPASSED via FlareSolverr)

- Standard CF challenge on all pages
- `_cfuvid` cookie issued after challenge
- FlareSolverr's headless Chrome passes this automatically
- `curl_cffi` with Chrome impersonation also passes (gets `_cfuvid`)

### 4. Backend session validation on search API (NOT BYPASSED)

- `POST /v2/services/customSearch` returns `400: "An update is necessary"`
- Rejects all non-browser requests regardless of:
  - Valid session cookies
  - Valid CSRF token
  - Chrome TLS fingerprint (curl_cffi)
  - Cloudflare cookies
  - Feature flags (ff3p)
- Extensively investigated and ruled out: X-RR-For header (null in Brave),
  X-SOURCE-PAGE, Sec-Fetch headers, HTTP version, \_\_cf_bm cookie, RR_SA token
  (just UI prefs, XOR key 0x72), RR_INIT_STORE (empty), full Angular init
  sequence, curl_cffi Chrome TLS impersonation
- Remaining hypothesis: server-side session flag set during JS page load
  that can't be replicated via raw HTTP

### 5. Email verification on official API (NOT BYPASSED)

- `api.rocketreach.co/api/v2/*` requires `is_verified: True`
- Account gets an `api_key` immediately, but it's locked until email is verified
- Temp email domains can receive the verification email IF the signup didn't
  hit the phone verification wall (which blocks email sending too)
- Catch-22: headless signup -> phone verify -> no email sent -> can't verify

### 6. Plugin API /v1/pluginProfileMatch (BYPASSED - THE KEY DISCOVERY)

- Chrome extension API that returns structured profile data
- **Works WITHOUT email or phone verification**
- Returns: name, title, company, location, LinkedIn, social links, education,
  job history, teaser email domains (personal + professional), partial phones
- Accepts batch requests (multiple profiles at once)
- Works from raw HTTP with just session cookies (no browser needed)
- This is the production-ready search endpoint

### 7. Public profile pages (PARTIALLY USEFUL)

- URL format: `/firstname-lastname-email_HASH` (hash from plugin API `url` field)
- Shows **masked emails**: `w******@harvard.edu` (first char + asterisks + domain)
- Shows **partial phones**: `+1 352-872-....`
- Combined with name pattern inference, can reconstruct full email addresses

## What works

| Method                       | Works?  | Notes                                                  |
| ---------------------------- | ------- | ------------------------------------------------------ |
| reCAPTCHA v3 solve           | Yes     | Pure HTTP, instant, any site                           |
| Account creation             | Yes     | Gets user_id, but phone-verified on headless           |
| Login via POST               | Yes     | Sets valid session cookies                             |
| `/v1/user` (account info)    | Yes     | Returns full profile + API key                         |
| **`/v1/pluginProfileMatch`** | **Yes** | **THE KEY: structured search, no verification needed** |
| Public profile page scraping | Yes     | Masked emails, needs profile hash from plugin API      |
| Email inference              | Yes     | From masked + teaser domains + name patterns           |
| Browser-bridge search        | Yes     | Local only, reads DOM from Brave                       |
| FlareSolverr HTML parse      | Flaky   | Works on warm session, breaks after reset              |
| Direct search API            | No      | "Update is necessary" for unverified accounts          |
| Official API                 | No      | Requires email verification                            |

## Key architectural insights

1. **Angular SPA**: All data fetched client-side via XHR. No server-side rendering.
2. **CSRF**: `validation_token` cookie -> `X-CSRFToken` header + `csrfmiddlewaretoken` form field
3. **Session**: `sessionid-20191028` cookie (Django session)
4. **Plugin API**: `/v1/pluginProfileMatch` is the Chrome extension's search API.
   Different auth requirements than the main search. Accepts `{profiles: [{name, current_employer}]}`.
5. **Teaser data**: Plugin API returns email domains split into personal vs professional,
   plus partial phone numbers with last 4 digits masked
6. **Public profile pages**: Show masked emails (`w******@domain.com`) and partial phones
   in meta description and page content. URL hash comes from plugin API response.
7. **Email inference**: First char of masked email + mask length + teaser domains + name
   patterns = reconstructed email at 0.5-0.95 confidence
8. **Free tier**: 5 lookup credits (for full reveal), unlimited plugin API searches

## Definitive root cause (discovered via Selenium Chrome on server)

### The "update is necessary" error = email verification check

When `is_verified: False`, the search page shows a verification banner INSTEAD
of results. The `/v2/services/customSearch` API returns 400 for unverified accounts.
This was confirmed by loading the search page in Selenium Chrome (Docker on
homeserver) — the page literally says "A verification email has been sent...
Please click the link to activate your account."

### Phone verification gates ALL new signups

Creating accounts from a real Selenium Chrome browser (not curl_cffi) STILL
triggers phone verification. This is not a reCAPTCHA score issue — it's a
universal policy for new RocketReach accounts as of 2026.

### Why the user's browser worked

The user's existing browser session has an account that either:

1. Was created before the phone verification policy
2. Completed phone verification at some point
3. Was created via Google/Microsoft OAuth (which may bypass phone verify)

### Server infrastructure deployed

- Selenium Chrome: `docker run selenium/standalone-chrome` on port 4444
- Could be used for automated searches IF a verified account is available

## API endpoint notes

### Batch vs non-batch plugin API

- **Non-batch** (`POST /search/plugin`): `{name, employer}` -> `{results: [...]}`
- **Batch** (`POST /search/plugin/batch`): `{profiles: [{name, current_employer}]}` -> `{profiles: [...]}` (NOT `results`!)

The batch endpoint returns data under the `profiles` key, not `results`. Using the
wrong key silently returns empty arrays. The non-batch endpoint is more reliable for
single lookups and returns richer results for ambiguous names.

### Plugin API with generic employer

Using "researcher" as a generic employer for contacts without known affiliations
yields ~60% hit rate via non-batch endpoint. The batch endpoint returns 0 results
for the same queries -- likely due to stricter matching logic server-side.

## Scale test results (plugin API)

Total: 2,670 lookups over multiple batches, zero errors, zero rate limiting.

- Initial batch: 1,507 lookups in ~4 min, 894 found (59%)
- Domain-based batch: 971 lookups, 730 found (75%)
- High-value batch: 192 lookups via non-batch, 116 found (60%)
- Final: 1,740 unique persons enriched, 1,702 LinkedIn URLs, ~1,100 email inferences
