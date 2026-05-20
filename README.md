# rocketreach-autopilot

Fully automated RocketReach account creation and API recon toolkit. No browser required.

## What this does

1. **Solves reCAPTCHA v3** via pure HTTP requests (no Selenium, no headless browser)
2. **Creates RocketReach accounts** via their internal `/v1/signup` API
3. **Documents reverse-engineered API endpoints** extracted from their Angular SPA bundle

## How the reCAPTCHA v3 bypass works

reCAPTCHA v3 is "invisible" and score-based — Google assigns a score (0.0 = bot, 1.0 = human) and the site decides the threshold. The bypass exploits the fact that the reCAPTCHA JS widget internally hits two Google endpoints that are publicly accessible:

```
Step 1: GET  /recaptcha/api2/anchor?k={site_key}&co={origin}&size=invisible
        → Returns HTML with a hidden <input id="recaptcha-token" value="...">

Step 2: POST /recaptcha/api2/reload?k={site_key}
        Body: v={version}&reason=q&c={token_from_step_1}&k={site_key}&co={origin}
        → Returns a valid g-recaptcha-response token
```

When you call these endpoints with a plain HTTP client, Google has no behavioral signals (mouse movement, browsing history, etc.) to score against. Most sites set their v3 threshold low (0.3-0.5), so the token passes server-side verification.

**Credit**: Technique from [s0ftik3/recaptcha-bypass](https://github.com/s0ftik3/recaptcha-bypass) (Node.js), ported to Python.

## RocketReach internal API

Discovered by static analysis of `https://static.rocketreach.co/bundles/js/output.*.js`:

| Method | Endpoint                 | Auth              | Notes                                        |
| ------ | ------------------------ | ----------------- | -------------------------------------------- |
| POST   | `/v1/signup`             | CSRF cookie       | Account creation (form-urlencoded, NOT JSON) |
| POST   | `/login`                 | CSRF cookie       | Django form POST (sets session)              |
| GET    | `/v1/user`               | Session           | Returns user profile + credit balance        |
| POST   | `/v1/resendVerification` | Session           | Resend email verification                    |
| POST   | `/v1/profiles`           | Session + API key | Person lookup                                |
| POST   | `/v1/generateEmail`      | Session + API key | Email generation                             |
| POST   | `/v1/sendEmail`          | Session + API key | Send email                                   |
| POST   | `/v1/startTrial`         | Session           | Start free trial                             |
| POST   | `/api/account/key`       | Session           | Get/create API key                           |

### Signup form structure

The signup page (`/signup`) is an Angular SPA. Key details:

- **CSRF**: Cookie `validation_token` → sent as `X-CSRFToken` header + `csrfmiddlewaretoken` field
- **Content-Type**: `application/x-www-form-urlencoded` (serialized via Angular's `$httpParamSerializerJQLike`)
- **Captcha**: reCAPTCHA v3 invisible, site key `6Le8JXkUAAAAABWqhg7ud4UjL6yCBDirQhWh5CHD`, action `signup`
- **Response**: Returns JSON with `user_id` on success, or `error_code: 205` when phone verification is required

### Signup flow

```
GET /signup                     → sets validation_token cookie
POST /v1/signup                 → creates account, returns user_id
    → 200: success
    → 403 + error_code 205: account created but phone verification required
    → 422: validation error (bad captcha, duplicate email, etc.)
```

## Usage

### Solve reCAPTCHA v3 (standalone)

```bash
python recaptcha_v3.py --site-key 6Le8JXkUAAAAABWqhg7ud4UjL6yCBDirQhWh5CHD \
                       --url https://rocketreach.co/signup \
                       --action signup
```

### Auto-signup

```bash
# With auto-generated temp email
python signup.py --name "Jane Smith"

# With specific email
python signup.py --name "Jane Smith" --email you@example.com --password "YourPass123!"
```

### Person search (via browser session)

```bash
# Requires: Brave browser logged into RocketReach + browser-bridge extension
python search.py "Elon Musk"
python search.py "Jane Doe" --employer "Google"
python search.py "Elon Musk" --json
```

### API recon

```bash
python recon.py
```

## Dependencies

```bash
pip install requests
```

That's it for signup + captcha. The `search.py` module additionally requires the
[browser-bridge](https://github.com/anthropics/browser-bridge) MCP server running
with a logged-in Brave session.

## Architecture

```
                     +------------------+
                     |  recaptcha_v3.py |  Pure HTTP captcha solver
                     +--------+---------+
                              |
                     +--------v---------+
                     |    signup.py     |  Account creation
                     +--------+---------+
                              |
              +---------------v----------------+
              |  Browser (Brave + browser-bridge) |
              +---------------+----------------+
                              |
                     +--------v---------+
                     |    search.py     |  Person lookup via DOM scraping
                     +------------------+
```

## Key findings

### Why headless signup gets phone-verified

RocketReach's `/v1/signup` returns `error_code: 205` (phone verification required)
when the reCAPTCHA v3 score is too low. The pure HTTP captcha bypass generates a
valid token but with a low behavioral score. Browser signups with real user history
pass the score threshold and skip phone verification entirely.

### Why the search API rejects raw HTTP

The `/v2/services/customSearch` endpoint returns `400: "An update is necessary"`
for requests without proper Cloudflare/DataDome challenge cookies. These cookies
are set by client-side JavaScript challenges that only run in a real browser.
The workaround: use the browser-bridge to navigate and scrape results from the
rendered DOM.

## Current limitations

- **Phone verification**: RocketReach now requires phone verification (error_code 205) before accounts are fully activated. The account is created but locked until a phone number is verified via SMS.
- **reCAPTCHA version pinning**: The `RECAPTCHA_VERSION` constant may need updating if Google rotates it. Check the anchor page source for the current `v=` parameter.
- **Score threshold**: If RocketReach tightens their reCAPTCHA v3 score threshold, the pure HTTP bypass may stop working. A headless browser approach would be needed as fallback.

## Project structure

```
recaptcha_v3.py   — reCAPTCHA v3 solver (reusable for any site)
search.py         — Person search via browser-bridge DOM scraping
signup.py         — RocketReach account creation automation
recon.py          — Internal API endpoint documentation
requirements.txt  — Python dependencies
```

## Legal

For educational and authorized security research purposes only.
