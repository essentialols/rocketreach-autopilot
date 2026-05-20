#!/usr/bin/env python3
"""
RocketReach person search via browser cookie session.

Extracts cookies from a logged-in Brave browser session and uses them
to query RocketReach's internal search API. Falls back to browser-bridge
scraping when the API rejects raw HTTP requests (anti-bot).

Usage:
    python search.py "Elon Musk"
    python search.py "Jane Doe" --employer "Google"
"""

import re
import sys
import json
import time
import argparse
import subprocess


def bridge_cmd(script: str, tab_id: int | None = None, timeout: int = 8) -> dict:
    """Send a command to the browser bridge and return parsed response."""
    payload = {"script": script, "timeout": timeout}
    if tab_id:
        payload["tab_id"] = tab_id
    import requests
    r = requests.post(
        "http://localhost:8787/execute_sync",
        json=payload,
        timeout=timeout + 5,
    )
    return r.json()


def find_tab(url_pattern: str) -> int | None:
    """Find a browser tab matching the URL pattern."""
    import requests
    try:
        # Try MCP tool via direct HTTP to bridge
        r = requests.post(
            "http://localhost:8787/execute_sync",
            json={"script": "page_info", "timeout": 5},
            timeout=10,
        )
        d = r.json()
        info = json.loads(d.get("html", "{}"))
        if url_pattern in info.get("url", ""):
            return None  # current tab matches
    except Exception:
        pass
    return None


def search_via_browser(name: str, employer: str = "", tab_id: int | None = None) -> list:
    """
    Search RocketReach by navigating the browser and scraping results.

    This bypasses anti-bot checks because the request originates from
    a real browser session with full Cloudflare/DataDome clearance.
    """
    # Build search URL
    params = f"name={name.replace(' ', '+')}&start=1&pageSize=10"
    if employer:
        params += f"&current_employer={employer.replace(' ', '+')}"
    url = f"https://rocketreach.co/person?{params}"

    print(f"[*] Navigating to: {url}")

    # Navigate using bridge
    import requests
    try:
        # Use the navigate builtin
        bridge_cmd(f"navigate {url}", tab_id)
    except Exception:
        # Fallback: use osascript
        subprocess.run([
            "osascript", "-e",
            f'tell application "Brave Browser" to set URL of active tab of front window to "{url}"'
        ], capture_output=True)

    # Wait for Angular to render results
    print("[*] Waiting for results to load...")
    time.sleep(6)

    # Scrape results
    resp = bridge_cmd(
        "query_all .result-items p, .result-items span, .result-items a",
        tab_id,
    )
    items = json.loads(resp.get("html", "[]"))

    # Parse into structured results
    results = []
    current = {}
    field_order = ["name", "title", "company"]
    field_idx = 0

    for item in items:
        text = item.get("text", "").strip()
        tag = item.get("tag", "")
        cls = item.get("classes", "")
        href = item.get("attrs", {}).get("href", "")

        if not text or text in ("Get Contact Info", "more"):
            continue

        if tag == "P" and field_idx == 0:
            # Start of a new result
            if current.get("name"):
                results.append(current)
                current = {}
                field_idx = 0
            current["name"] = text
            field_idx = 1
        elif tag == "P" and field_idx == 1:
            current["title"] = text
            field_idx = 2
        elif tag == "P" and field_idx == 2:
            current["company"] = text
            field_idx = 3
        elif "location" in cls.lower() or ("United States" in text or "," in text and len(text) < 80):
            if "location" not in current:
                current["location"] = text
        elif "@" in text and "." in text:
            current.setdefault("email_hint", text)
        elif text.startswith("+") or re.match(r"^\+?\d[\d\s-]{8,}", text):
            current.setdefault("phone_hint", text)
        elif href and "/profile" in href:
            current["profile_url"] = f"https://rocketreach.co{href}"

    if current.get("name"):
        results.append(current)

    return results


def main():
    parser = argparse.ArgumentParser(description="RocketReach person search")
    parser.add_argument("name", help="Person name to search for")
    parser.add_argument("--employer", default="", help="Current employer filter")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    results = search_via_browser(args.name, args.employer)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"\n{'='*60}")
        print(f" Results for: {args.name}")
        print(f"{'='*60}")
        for i, r in enumerate(results, 1):
            print(f"\n  [{i}] {r.get('name', '?')}")
            if r.get("title"):
                print(f"      Title:    {r['title']}")
            if r.get("company"):
                print(f"      Company:  {r['company']}")
            if r.get("location"):
                print(f"      Location: {r['location']}")
            if r.get("email_hint"):
                print(f"      Email:    {r['email_hint']}")
            if r.get("phone_hint"):
                print(f"      Phone:    {r['phone_hint']}")
            if r.get("profile_url"):
                print(f"      Profile:  {r['profile_url']}")
        if not results:
            print("\n  No results found.")
        print()


if __name__ == "__main__":
    main()
