#!/usr/bin/env python3
"""
Infer full email addresses from RocketReach masked emails + teaser domains.

Combines:
- Masked email from public profile page (e.g., "w******@harvard.edu")
- Teaser email domains from plugin API (e.g., ["harvard.edu", "columbia.edu"])
- Name patterns (first, last, first.last, flast, firstlast)

Produces ranked candidates with confidence scores.
"""

import re
from typing import Optional


COMMON_PATTERNS = [
    ("first", lambda f, l: f),
    ("last", lambda f, l: l),
    ("first.last", lambda f, l: f"{f}.{l}"),
    ("flast", lambda f, l: f"{f[0]}{l}"),
    ("firstlast", lambda f, l: f"{f}{l}"),
    ("first_last", lambda f, l: f"{f}_{l}"),
    ("lastf", lambda f, l: f"{l}{f[0]}"),
    ("last.first", lambda f, l: f"{l}.{f}"),
    ("f.last", lambda f, l: f"{f[0]}.{l}"),
    ("firstl", lambda f, l: f"{f}{l[0]}"),
]


def infer_emails(
    first_name: str,
    last_name: str,
    masked_email: Optional[str] = None,
    teaser_domains: Optional[list] = None,
    professional_domains: Optional[list] = None,
    personal_domains: Optional[list] = None,
) -> list[dict]:
    """
    Infer email addresses from partial RocketReach data.

    Returns list of {email, confidence, pattern, source} dicts.
    """
    first = first_name.lower().strip()
    last = last_name.lower().strip()

    candidates = []

    # Parse masked email
    mask_first_char = None
    mask_length = None
    mask_domain = None
    if masked_email:
        parts = masked_email.split("@")
        if len(parts) == 2:
            mask_first_char = parts[0][0].lower()
            mask_length = len(parts[0])
            mask_domain = parts[1].lower()

    # All domains to try
    all_domains = set()
    if mask_domain:
        all_domains.add(mask_domain)
    for d in (teaser_domains or []):
        all_domains.add(d.lower())
    for d in (professional_domains or []):
        all_domains.add(d.lower())
    for d in (personal_domains or []):
        all_domains.add(d.lower())

    for pattern_name, pattern_fn in COMMON_PATTERNS:
        try:
            username = pattern_fn(first, last)
        except (IndexError, ValueError):
            continue

        for domain in all_domains:
            email = f"{username}@{domain}"
            confidence = 0.3  # base

            # Boost if matches masked email constraints
            if mask_domain and domain == mask_domain:
                confidence += 0.2
                if mask_first_char and username[0] == mask_first_char:
                    confidence += 0.2
                if mask_length and len(username) == mask_length:
                    confidence += 0.2

            # Boost professional domains
            if domain in (professional_domains or []):
                confidence += 0.1

            # Common academic patterns
            if domain.endswith(".edu") or domain.endswith(".edu.au"):
                if pattern_name in ("first.last", "flast", "last"):
                    confidence += 0.1

            # Cap at 0.95
            confidence = min(confidence, 0.95)

            candidates.append({
                "email": email,
                "confidence": round(confidence, 2),
                "pattern": pattern_name,
                "domain": domain,
                "source": "rocketreach_inference",
            })

    # Sort by confidence descending
    candidates.sort(key=lambda x: x["confidence"], reverse=True)

    # Deduplicate
    seen = set()
    unique = []
    for c in candidates:
        if c["email"] not in seen:
            seen.add(c["email"])
            unique.append(c)

    return unique[:10]


if __name__ == "__main__":
    # Example: Wolfram Schlenker
    results = infer_emails(
        first_name="Wolfram",
        last_name="Schlenker",
        masked_email="w******@harvard.edu",
        professional_domains=["harvard.edu"],
    )
    print("Wolfram Schlenker:")
    for r in results[:5]:
        print(f"  {r['confidence']:.2f}  {r['email']:40s}  ({r['pattern']})")

    print()
    results2 = infer_emails(
        first_name="Pippa",
        last_name="Norris",
        masked_email="p******@gmail.com",
        professional_domains=["bwh.harvard.edu", "harvard.edu"],
        personal_domains=["gmail.com"],
    )
    print("Pippa Norris:")
    for r in results2[:5]:
        print(f"  {r['confidence']:.2f}  {r['email']:40s}  ({r['pattern']})")
