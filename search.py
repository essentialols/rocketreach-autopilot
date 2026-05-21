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


def _navigate_rr_tab(url: str):
    """Navigate a RocketReach tab via AppleScript (doesn't steal focus)."""
    # Find existing RR tab and navigate it, or open in current tab
    script = f'''
    tell application "Brave Browser"
        repeat with w in windows
            repeat with t in tabs of w
                if URL of t contains "rocketreach.co" then
                    set URL of t to "{url}"
                    return "ok"
                end if
            end repeat
        end repeat
        set URL of active tab of front window to "{url}"
        return "new"
    end tell'''
    subprocess.run(["osascript", "-e", script], capture_output=True)


def search_via_browser(name: str, employer: str = "", tab_id: int | None = None) -> list:
    """
    Search RocketReach by navigating the browser and scraping results.

    Uses AppleScript for navigation (reliable, no MAIN world issues)
    and browser-bridge query_all for DOM scraping (ISOLATED world).
    Requires a logged-in RocketReach session in Brave.
    """
    params = f"name={name.replace(' ', '+')}&start=1&pageSize=10"
    if employer:
        params += f"&current_employer={employer.replace(' ', '+')}"
    url = f"https://rocketreach.co/person?{params}"

    print(f"[*] Navigating to: {url}")
    _navigate_rr_tab(url)

    # Wait for Angular to render results
    print("[*] Waiting for results to load...")
    for attempt in range(4):
        time.sleep(5 + attempt * 2)
        resp = bridge_cmd(
            "query_all [data-profile-card-id]", tab_id, timeout=10,
        )
        items = json.loads(resp.get("html", "[]"))
        if items:
            break

    if not items:
        print("[!] No profile cards found")
        return []

    # Get detailed data from each card
    resp2 = bridge_cmd(
        "query_all [data-profile-card-id] #profile-name, "
        "[data-profile-card-id] p, "
        "[data-profile-card-id] span, "
        "[data-profile-card-id] a",
        tab_id, timeout=10,
    )
    elements = json.loads(resp2.get("html", "[]"))

    # Parse using profile-name as card delimiter
    results = []
    current = {}
    for el in elements:
        text = el.get("text", "").strip()
        tag = el.get("tag", "")
        attrs = el.get("attrs", {})
        iid = attrs.get("id", "")
        href = attrs.get("href", "")

        if iid == "profile-name":
            if current.get("name"):
                results.append(current)
            current = {"name": text}
        elif not current.get("name"):
            continue
        elif tag == "P" and text and len(text) > 2:
            if text == "Get contact info to view data":
                continue
            if "title" not in current:
                current["title"] = text
            elif "company" not in current:
                current["company"] = text
        elif "@" in text and "." in text and len(text) < 40:
            current.setdefault("email_hint", text)
        elif text.startswith("+") and any(c.isdigit() for c in text):
            current.setdefault("phone_hint", text)
        elif href and "-profile_" in href:
            current["company_url"] = f"https://rocketreach.co{href}"

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
