"""
reCAPTCHA v3 solver -- pure HTTP, no browser needed.

Exploits Google's own anchor/reload API endpoints to generate valid
g-recaptcha-response tokens without any browser, JS execution, or
behavioral signals.

Based on the technique from https://github.com/s0ftik3/recaptcha-bypass
Ported to Python with no dependencies beyond `requests`.
"""

import re
import json
import base64
import requests
from urllib.parse import urlparse


RECAPTCHA_VERSION = "Ai7lOI0zKMDPHxlv62g7oMoA"


def solve_recaptcha_v3(
    site_key: str,
    site_url: str,
    action: str = "submit",
    session: requests.Session | None = None,
) -> str:
    """
    Solve a reCAPTCHA v3 challenge and return a valid token.

    Args:
        site_key: The reCAPTCHA site key (public, found in page source).
        site_url: The URL of the page hosting the captcha.
        action:   The reCAPTCHA action string (e.g. "signup", "login").
        session:  Optional requests.Session for connection reuse.

    Returns:
        A valid g-recaptcha-response token string.

    Raises:
        RuntimeError: If token extraction fails at any stage.

    How it works
    ------------
    1. GET the anchor endpoint -- Google returns an HTML page with a
       hidden <input id="recaptcha-token" value="..."> containing
       an initial challenge token.
    2. POST that token to the reload endpoint -- Google validates it
       and returns a fresh g-recaptcha-response token, identical to
       what the JS widget would produce in a real browser.
    3. The token is accepted by the target site's backend because
       reCAPTCHA v3 is score-based, and many sites set their
       threshold low enough that a raw HTTP request passes.
    """
    s = session or requests.Session()
    s.headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36",
    )

    # Encode the origin for Google's co parameter (base64 of origin:port)
    parsed = urlparse(site_url)
    origin = f"{parsed.scheme}://{parsed.hostname}:{443 if parsed.scheme == 'https' else 80}"
    co = base64.b64encode(origin.encode()).decode().rstrip("=")

    # Step 1: Fetch anchor page to get initial challenge token
    anchor_url = (
        f"https://www.google.com/recaptcha/api2/anchor"
        f"?ar=1&k={site_key}&co={co}&hl=en"
        f"&v={RECAPTCHA_VERSION}&size=invisible&cb=1"
    )
    resp = s.get(anchor_url)
    resp.raise_for_status()

    token_match = re.search(r'id="recaptcha-token"\s+value="([^"]+)"', resp.text)
    if not token_match:
        raise RuntimeError(f"No recaptcha-token in anchor response: {resp.text[:300]}")
    initial_token = token_match.group(1)

    # Step 2: POST to reload endpoint to get final token
    reload_url = f"https://www.google.com/recaptcha/api2/reload?k={site_key}"
    reload_data = (
        f"v={RECAPTCHA_VERSION}&reason=q&c={initial_token}"
        f"&k={site_key}&co={co}&hl=en&size=invisible"
    )
    resp2 = s.post(
        reload_url,
        data=reload_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp2.raise_for_status()

    # Response: )]}'\n["rresp","TOKEN",...]
    cleaned = resp2.text.replace(")]}'", "").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        raise RuntimeError(f"Failed to parse reload response: {cleaned[:300]}")

    if not isinstance(data, list) or len(data) < 2:
        raise RuntimeError(f"Unexpected response shape: {cleaned[:300]}")

    token = data[1]
    if not token or len(token) < 100:
        raise RuntimeError(f"Token looks invalid (len={len(token) if token else 0})")
    return token


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Solve reCAPTCHA v3 via pure HTTP")
    p.add_argument("--site-key", required=True, help="reCAPTCHA site key")
    p.add_argument("--url", required=True, help="Page URL hosting the captcha")
    p.add_argument("--action", default="submit", help="reCAPTCHA action")
    args = p.parse_args()
    print(solve_recaptcha_v3(args.site_key, args.url, args.action))
