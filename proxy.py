#!/usr/bin/env python3
"""
RocketReach proxy server.

Maintains an authenticated session with RocketReach and exposes
a simple JSON API for person search and lookup. Cookies are refreshed
automatically from an initial seed.

Endpoints:
    GET  /health              — health check
    POST /search              — person search
    POST /lookup              — lookup a specific profile (costs 1 credit)
    GET  /user                — current account info + credit balance
    POST /captcha             — solve a reCAPTCHA v3 token
    POST /cookies             — update session cookies
"""

import re
import json
import base64
import time
import logging
from typing import Optional
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("rr-proxy")

app = FastAPI(title="RocketReach Proxy", version="0.1.0")

# --------------------------------------------------------------------------- #
# Session state
# --------------------------------------------------------------------------- #
SESSION = requests.Session()
SESSION.verify = False
SESSION.headers["User-Agent"] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

import urllib3
urllib3.disable_warnings()

CSRF_TOKEN = ""
COOKIES_LOADED = False


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class CookieSet(BaseModel):
    cookies: dict[str, str]


class SearchRequest(BaseModel):
    name: str
    employer: Optional[str] = None
    title: Optional[str] = None
    location: Optional[str] = None
    page: int = 1
    page_size: int = 10


class LookupRequest(BaseModel):
    profile_id: int | None = None
    linkedin_url: str | None = None
    name: str | None = None
    employer: str | None = None


class CaptchaRequest(BaseModel):
    site_key: str
    site_url: str
    action: str = "submit"


# --------------------------------------------------------------------------- #
# reCAPTCHA v3 solver
# --------------------------------------------------------------------------- #
RECAPTCHA_VERSION = "Ai7lOI0zKMDPHxlv62g7oMoA"


def solve_recaptcha_v3(site_key: str, site_url: str, action: str = "submit") -> str:
    parsed = urlparse(site_url)
    origin = f"{parsed.scheme}://{parsed.hostname}:{443 if parsed.scheme == 'https' else 80}"
    co = base64.b64encode(origin.encode()).decode().rstrip("=")

    s = requests.Session()
    s.verify = False
    s.headers["User-Agent"] = SESSION.headers["User-Agent"]

    resp = s.get(
        f"https://www.google.com/recaptcha/api2/anchor"
        f"?ar=1&k={site_key}&co={co}&hl=en&v={RECAPTCHA_VERSION}&size=invisible&cb=1"
    )
    match = re.search(r'id="recaptcha-token"\s+value="([^"]+)"', resp.text)
    if not match:
        raise RuntimeError("Failed to get anchor token")

    resp2 = s.post(
        f"https://www.google.com/recaptcha/api2/reload?k={site_key}",
        data=f"v={RECAPTCHA_VERSION}&reason=q&c={match.group(1)}&k={site_key}&co={co}&hl=en&size=invisible",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    data = json.loads(resp2.text.replace(")]}'", "").strip())
    return data[1]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _csrf() -> str:
    global CSRF_TOKEN
    for c in SESSION.cookies:
        if c.name == "validation_token":
            CSRF_TOKEN = c.value
            return c.value
    return CSRF_TOKEN


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "X-CSRFToken": _csrf(),
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://rocketreach.co/person",
        "Accept": "application/json, text/plain, */*",
    }


def _ensure_cookies():
    if not COOKIES_LOADED:
        raise HTTPException(
            status_code=503,
            detail="No cookies loaded. POST /cookies first with a valid session.",
        )


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {
        "status": "ok",
        "cookies_loaded": COOKIES_LOADED,
        "csrf": _csrf()[:10] + "..." if _csrf() else None,
    }


@app.post("/cookies")
def set_cookies(req: CookieSet):
    """Load session cookies from a browser session."""
    global COOKIES_LOADED
    for name, value in req.cookies.items():
        domain = ".rocketreach.co" if name.startswith("_") else "rocketreach.co"
        SESSION.cookies.set(name, value, domain=domain)
        if name == "sessionid-20191028":
            SESSION.cookies.set(name, value, domain=".rocketreach.co")
    COOKIES_LOADED = True
    log.info(f"Loaded {len(req.cookies)} cookies")

    # Verify session
    r = SESSION.get("https://rocketreach.co/v1/user", headers=_headers())
    try:
        d = r.json()
        return {
            "status": "ok",
            "user": d.get("first_name", "") + " " + d.get("last_name", ""),
            "state": d.get("state"),
            "credits": d.get("lookup_credit_balance"),
        }
    except Exception:
        return {"status": "cookies_set", "user_check": "failed"}


@app.get("/user")
def get_user():
    _ensure_cookies()
    r = SESSION.get("https://rocketreach.co/v1/user", headers=_headers())
    return r.json()


@app.post("/search")
def search(req: SearchRequest):
    """Search for people on RocketReach."""
    _ensure_cookies()

    terms = []
    if req.name:
        terms.append({"keyword": req.name, "incexc": "include", "type": "name"})
    if req.employer:
        terms.append({"keyword": req.employer, "incexc": "include", "type": "current_employer"})
    if req.title:
        terms.append({"keyword": req.title, "incexc": "include", "type": "current_title"})
    if req.location:
        terms.append({"keyword": req.location, "incexc": "include", "type": "location"})

    r = SESSION.post(
        "https://rocketreach.co/v2/services/customSearch",
        headers=_headers(),
        json={
            "mode": "person",
            "start": req.page,
            "pageSize": req.page_size,
            "terms": terms,
        },
    )

    if r.status_code == 400 and "update is necessary" in r.text:
        # Anti-bot block — session may need refreshing
        return {
            "error": "anti_bot_block",
            "detail": "Session blocked by Cloudflare/DataDome. Refresh cookies from browser.",
            "status": r.status_code,
        }

    try:
        return r.json()
    except Exception:
        raise HTTPException(status_code=r.status_code, detail=r.text[:500])


@app.post("/lookup")
def lookup(req: LookupRequest):
    """Lookup a specific profile. Costs 1 credit."""
    _ensure_cookies()

    if req.profile_id:
        r = SESSION.post(
            "https://rocketreach.co/v2/services/search/person",
            headers=_headers(),
            json={"id": [req.profile_id]},
        )
    elif req.linkedin_url:
        r = SESSION.get(
            f"https://rocketreach.co/person?start=1&pageSize=10&link={req.linkedin_url}",
            headers=_headers(),
        )
    elif req.name:
        params = {"name": req.name}
        if req.employer:
            params["current_employer"] = req.employer
        r = SESSION.post(
            "https://rocketreach.co/v2/services/search/person",
            headers=_headers(),
            json={"query": params},
        )
    else:
        raise HTTPException(400, "Provide profile_id, linkedin_url, or name")

    try:
        return r.json()
    except Exception:
        raise HTTPException(status_code=r.status_code, detail=r.text[:500])


class PluginSearchRequest(BaseModel):
    profiles: list[dict]


@app.post("/search/plugin")
def search_plugin(req: SearchRequest):
    """
    Search via /v1/pluginProfileMatch (Chrome extension API).
    WORKS without email verification! Returns structured profile data.
    """
    _ensure_cookies()
    profile = {"name": req.name}
    if req.employer:
        profile["current_employer"] = req.employer
    if req.title:
        profile["current_title"] = req.title

    r = SESSION.post(
        "https://rocketreach.co/v1/pluginProfileMatch",
        headers=_headers(),
        json={"profiles": [profile]},
    )
    if r.status_code in (200, 201):
        data = r.json()
        profiles = data.get("profiles", [])
        return {
            "results": profiles,
            "count": len(profiles),
            "source": "pluginProfileMatch",
        }
    raise HTTPException(status_code=r.status_code, detail=r.text[:500])


@app.post("/search/plugin/batch")
def search_plugin_batch(req: PluginSearchRequest):
    """Batch search via plugin API. Pass list of {name, current_employer} dicts."""
    _ensure_cookies()
    r = SESSION.post(
        "https://rocketreach.co/v1/pluginProfileMatch",
        headers=_headers(),
        json={"profiles": req.profiles},
    )
    if r.status_code in (200, 201):
        return r.json()
    raise HTTPException(status_code=r.status_code, detail=r.text[:500])


@app.post("/captcha")
def captcha(req: CaptchaRequest):
    """Solve a reCAPTCHA v3 challenge."""
    try:
        token = solve_recaptcha_v3(req.site_key, req.site_url, req.action)
        return {"token": token, "length": len(token)}
    except Exception as e:
        raise HTTPException(500, str(e))


# --------------------------------------------------------------------------- #
# FlareSolverr integration (Cloudflare bypass via headless Chrome)
# --------------------------------------------------------------------------- #
FLARESOLVERR_URL = "http://localhost:8191/v1"
FLARE_SESSION = "rocketreach"
_flare_initialized = False

PROFILE_LINK_RE = re.compile(r'href="(/[^"]*-profile_[^"]+)"')
PERSON_NAME_RE = re.compile(r'>([A-Z][a-z]+ [A-Z][a-z]+(?:\s[A-Z][a-z]+)?)</(?:p|span|h[1-6]|a|div)')
TITLE_RE = re.compile(
    r'>((?:Chief|CEO|CTO|CFO|COO|VP|Vice President|Director|Manager|'
    r'Engineer|President|Owner|Founder|Head of|Senior|Lead|Principal)[^<]{0,80})<'
)
EMAIL_DOMAIN_RE = re.compile(r'@([a-zA-Z0-9.-]+\.[a-z]{2,})')
PHONE_RE = re.compile(r'\+1[\s-]?\d{3}[\s-]?\d{3}[\s-]?\w{4}')
SKIP_NAMES = frozenset({
    "Getting Started", "My Contacts", "My Companies", "Upload List",
    "Browser Extension", "View Usage", "All Results", "Net New",
    "Learn More", "Contact Details", "Get Contacts", "Sign Up",
    "Log In", "Search Results", "Find Email", "Account Settings",
    "Search Filters", "Community Program Terms", "View Privacy Policy",
    "Keyword Search", "Performance Cookies", "Strictly Necessary Cookies",
    "Always Active", "Targeting Cookies", "Functional Cookies",
    "Cookie List", "Back To Top", "Sales Engagement", "Chrome Extension",
    "Privacy Policy", "Terms Of Service", "Contact Us", "Help Center",
    "About Us", "Saved Lists", "Team Management", "Phone Numbers",
    "Email Addresses", "Social Links", "Company Info",
})


def _init_flaresolverr():
    global _flare_initialized
    if _flare_initialized:
        return
    try:
        requests.post(FLARESOLVERR_URL, json={
            "cmd": "sessions.create", "session": FLARE_SESSION,
        }, timeout=10, verify=False)
    except Exception:
        pass
    cookie_list = [
        {"name": c.name, "value": c.value, "domain": c.domain or "rocketreach.co"}
        for c in SESSION.cookies
    ]
    if cookie_list:
        requests.post(FLARESOLVERR_URL, json={
            "cmd": "request.get",
            "url": "https://rocketreach.co/login",
            "session": FLARE_SESSION,
            "maxTimeout": 30000,
            "cookies": cookie_list,
        }, timeout=35, verify=False)
    # Warm up: visit dashboard then a search page to prime Angular SPA cache
    log.info("Warming up FlareSolverr: visiting dashboard...")
    requests.post(FLARESOLVERR_URL, json={
        "cmd": "request.get",
        "url": "https://rocketreach.co/dashboard",
        "session": FLARE_SESSION,
        "maxTimeout": 20000,
    }, timeout=25, verify=False)
    log.info("Warming up FlareSolverr: visiting search page...")
    requests.post(FLARESOLVERR_URL, json={
        "cmd": "request.get",
        "url": "https://rocketreach.co/person?name=test&start=1&pageSize=1",
        "session": FLARE_SESSION,
        "maxTimeout": 20000,
    }, timeout=25, verify=False)
    _flare_initialized = True
    log.info("FlareSolverr session initialized and warmed up")


@app.post("/flare/warmup")
def warmup_flare():
    """Manually re-initialize and warm up the FlareSolverr session."""
    global _flare_initialized
    _flare_initialized = False
    _init_flaresolverr()
    return {"status": "ok", "warmed_up": True}


def _flare_get(url: str, timeout: int = 30000, retries: int = 2) -> str:
    """Fetch URL via FlareSolverr. Retries if SPA hasn't rendered yet."""
    _init_flaresolverr()
    for attempt in range(retries + 1):
        r = requests.post(FLARESOLVERR_URL, json={
            "cmd": "request.get",
            "url": url,
            "session": FLARE_SESSION,
            "maxTimeout": timeout,
        }, timeout=timeout // 1000 + 10, verify=False)
        d = r.json()
        if d.get("status") != "ok":
            raise RuntimeError(f"FlareSolverr: {d.get('message', 'unknown')}")
        html = d["solution"]["response"]
        # Check if SPA rendered (profile cards present)
        if "data-profile-card-id" in html or attempt == retries:
            return html
        log.info(f"SPA not rendered yet, retry {attempt + 1}/{retries}")
        time.sleep(2)
    return html


CARD_RE = re.compile(
    r'data-profile-card-id="(\d+)"(.*?)(?=data-profile-card-id=|</body>)',
    re.DOTALL,
)
CARD_NAME_RE = re.compile(r'id="profile-name"[^>]*>\s*([^<]+)')
CARD_TEXT_RE = re.compile(r'<p[^>]*>\s*([^<]+?)\s*</p>')
CARD_COMPANY_RE = re.compile(
    r'href="(/[^"]*-profile_[^"]+)"[^>]*>\s*<span[^>]*>\s*([^<]+)'
)
CARD_LOCATION_RE = re.compile(
    r'(?:Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|'
    r'Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|'
    r'Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|'
    r'Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|'
    r'New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|'
    r'Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|'
    r'Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming|'
    r'United States|United Kingdom|Canada|India|Germany|France|Australia'
    r')[^<]{0,60}'
)


def _parse_search_results(html: str) -> list:
    """Parse structured results from profile cards in rendered HTML."""
    cards = CARD_RE.findall(html)
    results = []

    for profile_id, card_html in cards:
        entry = {"id": int(profile_id)}

        # Name
        name_match = CARD_NAME_RE.search(card_html)
        if name_match:
            entry["name"] = name_match.group(1).strip()

        # Title + company from sequential <p> tags
        texts = [t.strip() for t in CARD_TEXT_RE.findall(card_html)
                 if t.strip() and len(t.strip()) > 2
                 and t.strip() not in ("Get contact info to view data",)]
        if len(texts) >= 2:
            entry["title"] = texts[1]  # first is name, second is title
        if len(texts) >= 3:
            entry["company"] = texts[2]

        # Company link
        company_match = CARD_COMPANY_RE.search(card_html)
        if company_match:
            entry["company_url"] = f"https://rocketreach.co{company_match.group(1)}"
            if "company" not in entry:
                entry["company"] = company_match.group(2).strip()

        # Email hints
        emails = EMAIL_DOMAIN_RE.findall(card_html)
        emails = [e for e in emails if not any(
            x in e for x in ("rocketreach", "sentry", "google", "datadoghq")
        )]
        if emails:
            entry["email_domain"] = f"@{emails[0]}"

        # Phone hints
        phones = PHONE_RE.findall(card_html)
        if phones:
            entry["phone_hint"] = phones[0]

        # Location
        loc_match = CARD_LOCATION_RE.search(card_html)
        if loc_match:
            entry["location"] = loc_match.group(0).strip().rstrip(",")

        if entry.get("name"):
            results.append(entry)

    return results


@app.post("/search/flare")
def search_flare(req: SearchRequest):
    """Search for people via FlareSolverr (bypasses Cloudflare)."""
    _ensure_cookies()
    params = f"name={req.name.replace(' ', '+')}&start={req.page}&pageSize={req.page_size}"
    if req.employer:
        params += f"&current_employer={req.employer.replace(' ', '+')}"
    if req.title:
        params += f"&current_title={req.title.replace(' ', '+')}"
    if req.location:
        params += f"&location={req.location.replace(' ', '+')}"
    url = f"https://rocketreach.co/person?{params}"
    log.info(f"FlareSolverr search: {url}")
    try:
        html = _flare_get(url)
        results = _parse_search_results(html)
        return {"results": results, "count": len(results), "url": url, "source": "flaresolverr"}
    except Exception as e:
        raise HTTPException(500, f"FlareSolverr error: {e}")


@app.post("/cookies/refresh")
def refresh_cookies(req: CookieSet):
    """Update cookies and reset FlareSolverr session."""
    global _flare_initialized
    result = set_cookies(req)
    _flare_initialized = False
    log.info(f"Cookie refresh: user={result.get('user')}, credits={result.get('credits')}")
    return {**result, "refreshed_at": time.time()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8420)
