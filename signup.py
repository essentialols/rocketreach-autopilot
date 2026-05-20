#!/usr/bin/env python3
"""
RocketReach account signup -- fully automated, no browser.

Creates a RocketReach account using:
  - A disposable temp email (etempmail.com)
  - reCAPTCHA v3 bypass via pure HTTP (see recaptcha_v3.py)
  - Direct POST to RocketReach's internal /v1/signup API

Usage:
    python signup.py
    python signup.py --email foo@tempmail.com --name "John Doe" --password "Pass123!"
"""

import re
import sys
import time
import json
import argparse
import requests

from recaptcha_v3 import solve_recaptcha_v3

# RocketReach config
SITE_KEY = "6Le8JXkUAAAAABWqhg7ud4UjL6yCBDirQhWh5CHD"
SIGNUP_URL = "https://rocketreach.co/signup"
SIGNUP_API = "https://rocketreach.co/v1/signup"

# Temp email config
TEMP_EMAIL_API = "https://etempmail.com"


def get_temp_email() -> str:
    """Generate a fresh disposable email address."""
    print("[*] Generating temp email...")
    r = requests.post(f"{TEMP_EMAIL_API}/getEmailAddress", timeout=15)
    r.raise_for_status()
    data = r.json()
    email = data if isinstance(data, str) else data.get("emailAddress", "")
    print(f"[+] Temp email: {email}")
    return email


def signup(name: str, email: str, password: str) -> dict:
    """
    Create a RocketReach account.

    Returns the JSON response from RocketReach's /v1/signup endpoint.
    """
    # 1) Solve reCAPTCHA v3
    print("[*] Solving reCAPTCHA v3...")
    captcha_token = solve_recaptcha_v3(
        site_key=SITE_KEY, site_url=SIGNUP_URL, action="signup"
    )
    print(f"[+] Captcha token: {captcha_token[:50]}... ({len(captcha_token)} chars)")

    # 2) Create session and fetch CSRF cookie
    print("[*] Fetching CSRF token...")
    s = requests.Session()
    s.headers["User-Agent"] = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
    s.get(SIGNUP_URL)
    csrf = s.cookies.get("validation_token", "")
    if not csrf:
        raise RuntimeError("No validation_token cookie received")
    print(f"[+] CSRF: {csrf[:20]}...")

    # 3) POST to /v1/signup
    # RocketReach's Angular frontend serializes form data with
    # $httpParamSerializerJQLike and sends it as x-www-form-urlencoded.
    # The endpoint also accepts multipart, but NOT JSON.
    print("[*] Submitting signup...")
    resp = s.post(
        SIGNUP_API,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": SIGNUP_URL,
            "Origin": "https://rocketreach.co",
            "X-CSRFToken": csrf,
            "X-Requested-With": "XMLHttpRequest",
        },
        data={
            "csrfmiddlewaretoken": csrf,
            "name": name,
            "login": email,
            "password": password,
            "agreeTerms": "true",
            "force_phone": "false",
            "g-recaptcha-response": captcha_token,
        },
    )

    print(f"[+] Response {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def poll_inbox(email: str, attempts: int = 30, interval: int = 10):
    """Poll etempmail.com inbox for a verification email."""
    print(f"\n[*] Polling inbox for {email}...")
    for i in range(1, attempts + 1):
        print(f"    {i}/{attempts}...")
        try:
            r = requests.post(
                f"{TEMP_EMAIL_API}/getInbox",
                json={"emailAddress": email},
                timeout=15,
            )
            if r.text.strip():
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    print(f"[+] {len(data)} email(s) received!")
                    for m in data:
                        print(f"    From: {m.get('from', '?')}")
                        print(f"    Subject: {m.get('subject', '?')}")
                        body = m.get("body", "") or m.get("html", "")
                        links = re.findall(
                            r"https://rocketreach\.co[^\s\"<>']+", body
                        )
                        if links:
                            print(f"[+] Verification link: {links[0]}")
                            return links[0]
                        print(f"    Preview: {body[:200]}")
                    return data
        except Exception as e:
            print(f"    Error: {e}")
        time.sleep(interval)
    print("[!] No verification email received.")
    return None


def main():
    parser = argparse.ArgumentParser(description="RocketReach auto-signup")
    parser.add_argument("--name", default="John Doe", help="Full name")
    parser.add_argument("--email", default=None, help="Email (auto-generated if omitted)")
    parser.add_argument("--password", default="Changeme123!", help="Password (min 8 chars)")
    parser.add_argument("--skip-inbox", action="store_true", help="Skip inbox polling")
    args = parser.parse_args()

    email = args.email or get_temp_email()

    print("=" * 55)
    print(f"  RocketReach Auto-Signup")
    print(f"  Name:     {args.name}")
    print(f"  Email:    {email}")
    print(f"  Password: {'*' * len(args.password)}")
    print("=" * 55)

    result = signup(args.name, email, args.password)

    # Interpret response
    error_code = result.get("error_code")
    user_id = result.get("user_id")

    if user_id:
        print(f"\n[+] Account created! User ID: {user_id}")
        if error_code == 205:
            print("[!] Phone verification required (error_code 205)")
            print("    Account exists but needs phone verify to fully activate.")
    elif "already" in str(result.get("message", "")).lower():
        print("\n[!] Account already exists for this email.")
    else:
        print(f"\n[!] Signup result: {json.dumps(result, indent=2)}")

    if not args.skip_inbox:
        poll_inbox(email)


if __name__ == "__main__":
    main()
