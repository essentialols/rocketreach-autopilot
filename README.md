# rocketreach-autopilot

Fully automated RocketReach toolkit: account creation, reCAPTCHA v3 bypass, person search with Cloudflare bypass. No paid APIs needed.

## What this does

1. **Solves reCAPTCHA v3** via pure HTTP requests (no browser)
2. **Creates RocketReach accounts** via their internal `/v1/signup` API
3. **Searches for people** via FlareSolverr (headless Chrome, bypasses Cloudflare)
4. **Self-hosted proxy server** with FastAPI on your own infrastructure

## How the reCAPTCHA v3 bypass works

reCAPTCHA v3 is "invisible" and score-based. The bypass exploits two public Google endpoints:

```
Step 1: GET  /recaptcha/api2/anchor?k={site_key}&co={origin}&size=invisible
        -> Returns HTML with <input id="recaptcha-token" value="...">

Step 2: POST /recaptcha/api2/reload?k={site_key}
        Body: v={version}&reason=q&c={token}&k={site_key}&co={origin}
        -> Returns a valid g-recaptcha-response token
```

Most sites set their v3 threshold low (0.3-0.5), so the token passes.

**Credit**: [s0ftik3/recaptcha-bypass](https://github.com/s0ftik3/recaptcha-bypass) (Node.js), ported to Python.

## RocketReach internal API

Discovered via static analysis of their Angular JS bundle:

| Method | Endpoint                    | Notes                                 |
| ------ | --------------------------- | ------------------------------------- |
| POST   | `/v1/signup`                | Account creation (form-urlencoded)    |
| POST   | `/login`                    | Django form POST                      |
| GET    | `/v1/user`                  | Profile + credits                     |
| POST   | `/v2/services/customSearch` | Person search (blocked by Cloudflare) |
| POST   | `/v1/profiles`              | Person lookup (needs API key)         |
| POST   | `/v1/resendVerification`    | Resend email                          |
| POST   | `/api/account/key`          | API key management                    |

## Usage

### Solve reCAPTCHA v3 (standalone)

```bash
python recaptcha_v3.py --site-key 6Le8JXkUAAAAABWqhg7ud4UjL6yCBDirQhWh5CHD \
                       --url https://rocketreach.co/signup --action signup
```

### Auto-signup

```bash
python signup.py --name "Jane Smith"
python signup.py --name "Jane Smith" --email you@example.com --password "Pass123!"
```

### Person search (local, via browser-bridge)

```bash
python search.py "Elon Musk"
python search.py "Elon Musk" --employer "Tesla" --json
```

## Proxy server (self-hosted)

FastAPI proxy with FlareSolverr for Cloudflare bypass. Runs on your server.

### Setup

```bash
# 1. FlareSolverr (Docker)
docker run -d --name flaresolverr -p 8191:8191 --restart unless-stopped \
  ghcr.io/flaresolverr/flaresolverr:latest

# 2. Install + run proxy
python3 -m venv venv && source venv/bin/activate
pip install fastapi uvicorn requests
uvicorn proxy:app --host 0.0.0.0 --port 8420
```

### Systemd (auto-start on reboot)

```ini
# /etc/systemd/system/rocketreach-proxy.service
[Unit]
Description=RocketReach Proxy Server
After=network.target docker.service

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/rocketreach-proxy
ExecStart=/path/to/venv/bin/uvicorn proxy:app --host 0.0.0.0 --port 8420
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### Proxy API

```bash
# 1. Seed cookies (required first)
curl -X POST http://server:8420/cookies \
  -H 'Content-Type: application/json' \
  -d '{"cookies": {"validation_token": "...", "sessionid-20191028": "..."}}'

# 2. Search via FlareSolverr (~10s, bypasses Cloudflare)
curl -X POST http://server:8420/search/flare \
  -H 'Content-Type: application/json' \
  -d '{"name": "Elon Musk"}'

# 3. Solve reCAPTCHA v3 (instant)
curl -X POST http://server:8420/captcha \
  -H 'Content-Type: application/json' \
  -d '{"site_key": "...", "site_url": "...", "action": "signup"}'

# 4. Account info
curl http://server:8420/user

# 5. Refresh cookies from local browser
./push_cookies.sh http://server:8420
```

### Example response

```json
{
  "results": [
    {
      "id": 71298270,
      "name": "Elon Musk",
      "title": "Chief Executive Officer",
      "company": "Tesla",
      "company_url": "https://rocketreach.co/tesla-profile_b5db28f4f42e5131",
      "email_domain": "@spacex.com",
      "location": "California, United States"
    }
  ],
  "count": 10,
  "source": "flaresolverr"
}
```

## Architecture

```
  Local machine                          Server
  ============                          ======

  Browser (Brave)                    +------------------+
       |                             |   proxy.py       |  :8420
  push_cookies.sh ------------------>|   FastAPI        |
                                     +--------+---------+
  recaptcha_v3.py (standalone)               |
  signup.py       (standalone)       +-------v----------+
  search.py       (local alt)        |  FlareSolverr    |  :8191
                                     |  (headless Chrome)|
                                     +-------+----------+
                                             |
                                     +-------v----------+
                                     |  rocketreach.co  |
                                     |  (Cloudflare)    |
                                     +------------------+
```

## Key findings

- **reCAPTCHA v3**: Google's own `anchor`/`reload` endpoints return valid tokens without a browser
- **Phone verification**: Only triggered by low captcha scores (headless). Browser signups skip it.
- **Cloudflare**: Search API blocked for raw HTTP. FlareSolverr (headless Chrome) bypasses it.
- **HTML parsing**: Profile cards use `data-profile-card-id` containers with predictable structure

## Limitations

- **Credits**: Full contact info costs 1 lookup credit per person
- **Cookie expiry**: Session cookies expire ~48h. Use `push_cookies.sh` to refresh.
- **FlareSolverr latency**: ~10s per search (full page render)
- **reCAPTCHA version**: `RECAPTCHA_VERSION` may need updating if Google rotates it

## Project structure

```
recaptcha_v3.py    -- reCAPTCHA v3 solver (reusable, pure HTTP)
signup.py          -- Account creation automation
search.py          -- Person search via browser-bridge (local)
proxy.py           -- FastAPI proxy with FlareSolverr (server)
push_cookies.sh    -- Cookie refresh script
recon.py           -- Internal API documentation
requirements.txt   -- Dependencies
```

## Legal

For educational and authorized security research purposes only.
