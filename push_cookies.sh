#!/bin/bash
# Push fresh RocketReach cookies from Brave browser to the proxy server.
# Run this periodically (e.g. every 30 min) to keep the session alive.
#
# Usage: ./push_cookies.sh [proxy_url]
#   proxy_url defaults to http://homeserver:8420

PROXY="${1:-http://homeserver:8420}"

# Extract cookies via browser-bridge MCP
COOKIES=$(curl -s -X POST http://localhost:8787/execute_sync \
  -H 'Content-Type: application/json' \
  -d '{"script": "get_cookies .rocketreach.co", "timeout": 5}' 2>/dev/null)

if echo "$COOKIES" | grep -q '"error"' && ! echo "$COOKIES" | grep -q '"error": ""'; then
  echo "[!] Browser bridge error: $COOKIES"
  exit 1
fi

# Parse cookies into a JSON dict for the proxy
COOKIE_JSON=$(echo "$COOKIES" | python3 -c "
import sys, json
raw = json.loads(sys.stdin.read())
html = raw.get('html', '[]')
cookies = json.loads(html) if isinstance(html, str) else html
result = {}
for c in cookies:
    if isinstance(c, dict):
        result[c['name']] = c['value']
print(json.dumps({'cookies': result}))
" 2>/dev/null)

if [ -z "$COOKIE_JSON" ] || [ "$COOKIE_JSON" = '{"cookies": {}}' ]; then
  echo "[!] No cookies extracted"
  exit 1
fi

echo "[*] Pushing cookies to $PROXY..."
RESP=$(curl -s -X POST "$PROXY/cookies/refresh" \
  -H 'Content-Type: application/json' \
  -d "$COOKIE_JSON")
echo "[+] $RESP"
