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
- The Angular SPA has something the raw HTTP client doesn't
- Likely candidates: a JavaScript-generated request header, a browser fingerprint in cookies,
  or a WebSocket session token that's validated server-side

### 5. Email verification on official API (NOT BYPASSED)

- `api.rocketreach.co/api/v2/*` requires `is_verified: True`
- Account gets an `api_key` immediately, but it's locked until email is verified
- Temp email domains can receive the verification email IF the signup didn't
  hit the phone verification wall (which blocks email sending too)
- Catch-22: headless signup -> phone verify -> no email sent -> can't verify

## What works

| Method                    | Works? | Notes                                             |
| ------------------------- | ------ | ------------------------------------------------- |
| reCAPTCHA v3 solve        | Yes    | Pure HTTP, instant, any site                      |
| Account creation          | Yes    | Gets user_id, but phone-verified on headless      |
| Login via POST            | Yes    | Sets valid session cookies                        |
| `/v1/user` (account info) | Yes    | Returns full profile + API key                    |
| Browser-bridge search     | Yes    | Local only, reads DOM from Brave                  |
| FlareSolverr HTML parse   | Flaky  | Works on warm session, breaks after reset         |
| Direct search API         | No     | "Update is necessary" for all non-browser clients |
| Official API              | No     | Requires email verification                       |

## Key architectural insights

1. **Angular SPA**: All data fetched client-side via XHR. No server-side rendering.
2. **CSRF**: `validation_token` cookie -> `X-CSRFToken` header + `csrfmiddlewaretoken` form field
3. **Session**: `sessionid-20191028` cookie (Django session)
4. **Search query format**: `{mode, start, pageSize, terms: [{keyword, incexc, type}]}`
5. **HTML structure**: Profile cards use `data-profile-card-id` with predictable child elements
6. **Feature flags**: `ff3p` field is XOR-encoded (`rrff3p` key), GET-only
7. **Free tier**: 5 lookup credits, unlimited search (but search blocked headless)

## Recommended next steps

1. **Intercept the actual browser XHR** to find what header/token the Angular app sends
   that the backend validates (use browser DevTools Network tab)
2. **Sign up through the browser** with a real email to get a verified API key
3. **Use Playwright/Puppeteer** with `waitForSelector` instead of FlareSolverr for
   reliable SPA rendering
