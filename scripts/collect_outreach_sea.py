"""Collect a public-profile outreach shortlist for Katalir (F7.1).

SCOPE - DELIBERATE AND NARROW
-----------------------------
Collects ONLY data a GitHub user has chosen to publish on their profile:
login, profile URL, display name, self-declared bio, self-declared
location, public repo count / followers, and the public names + URLs +
descriptions of their top repositories.

It NEVER stores an email address or any scraped contact detail - not even
if the API hands one back. `email` is explicitly popped from every payload
before it reaches the output file. The output is a shortlist a human then
contacts at their own discretion (GitHub DM, Twitter, launch cross-promo);
it is not a mailing list.

Why this exists: the raw `location:Indonesia language:TypeScript` search
returns an unranked, heavily duplicated set (bots, mirror accounts, single
-person token dumps). Filtering on signals of *actual maintained work* is
what makes the shortlist worth a human's time.

Usage:
    python scripts/collect_outreach_sea.py
Writes:
    docs/community/outreach-sea.json
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "community" / "outreach-sea.json"
TARGET = 100

# NOTE ON QUALIFIERS: GitHub's *user* search endpoint does not support
# `stars:` - that is a repository qualifier. Using it here made every query
# match literally zero users and the first "successful" run collected 0
# profiles. `followers:` and `repos:` ARE valid for user search, so those are
# the traction filters here. Language is split per query so we do not only
# surface one ecosystem.
QUERIES = [
    "location:Indonesia language:TypeScript followers:>10",
    "location:Indonesia language:JavaScript followers:>10",
    "location:Indonesia language:Python followers:>5",
    "location:Indonesia followers:>25",
    "location:Singapore language:TypeScript followers:>15",
    "location:Singapore language:Python followers:>10",
    "location:Malaysia language:TypeScript followers:>10",
    "location:Malaysia language:JavaScript followers:>10",
    # Lower traction bars for the thinner markets. `followers:>10` matches
    # almost nobody in the Philippines / Thailand / Vietnam, so the strict
    # threshold silently produced 0 rows for them. These stay positive (a real
    # public account) while widening the pool enough to be reviewable.
    "location:Philippines language:TypeScript followers:>5",
    "location:Philippines language:JavaScript followers:>5",
    "location:Thailand language:TypeScript followers:>5",
    "location:Thailand language:JavaScript followers:>5",
    "location:Vietnam language:TypeScript followers:>5",
    "location:Vietnam language:JavaScript followers:>5",
    "location:Vietnam language:Python followers:>5",
    "location:Malaysia language:Python followers:>5",
    "location:Thailand language:Python followers:>3",
    "location:Indonesia repos:>20",
]

# Per-country cap, so the shortlist is actually regional.
#
# REGRESSION THIS FIXES: the enrichment loop below stops as soon as it has
# TARGET rows. Because the Indonesia queries come first, the first run filled
# all 100 slots before Singapore/Malaysia/Philippines/Thailand/Vietnam were
# ever enriched -- the output was 100% Indonesian despite being called
# "SEA". Tagging each candidate with its country and skipping a country once
# it hits its quota keeps the file honest about its own name.
COUNTRY_QUOTA = 20
COUNTRIES = [
    "Indonesia",
    "Singapore",
    "Malaysia",
    "Philippines",
    "Thailand",
    "Vietnam",
]
# The country a query targets, derived from its `location:` qualifier. Anything
# we cannot attribute is still eligible, but does not consume a quota.
COUNTRY_ORDER = {c: i for i, c in enumerate(COUNTRIES)}


def country_of(query: str) -> str | None:
    m = re.search(r"location:([A-Za-z]+)", query)
    if not m:
        return None
    name = m.group(1)
    for c in COUNTRIES:
        if c.lower() == name.lower():
            return c
    return None

# Agents that are not people we want in a human-reviewed shortlist.
JUNK = re.compile(
    r"bot|dependabot|renovate|github-actions|awesome-|"
    r"^\d+-?fork|freecodecamp|codecov|travis|circleci",
    re.I,
)

# Copied from a profile. An allow-list, not a deny-list, so a new API field
# can never leak into the output by default.
PROFILE_FIELDS = ("login", "html_url", "name", "bio", "company")

# A profile's own `bio` frequently volunteers an address ("Email: foo@bar.com").
# That is public, but collecting it would make the file a mailing list and would
# falsify the `emails_collected: 0` claim in the output. One real profile in the
# first run had exactly this, so bios are scrubbed before they are stored.
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Also drop "DM me"/"contact" style handles: this list is identity only.
CONTACT_RE = re.compile(r"\b(dm|contact|email|reach me|ping me)\b[:\s].*", re.I)


def scrub(text: str | None) -> str | None:
    """Remove email addresses and contact instructions from free-text fields."""
    if not text:
        return text
    out = EMAIL_RE.sub("[redacted]", text)
    out = CONTACT_RE.sub("", out)
    return re.sub(r"\s{2,}", " ", out).strip() or None


def dominant_language(repos: list[dict]) -> str | None:
    """Most common language across the top repos.

    The /users endpoint does not return a `language` field, so the first run
    emitted `null` for every profile. Repo languages are the real signal.
    """
    counts: dict[str, int] = {}
    for r in repos:
        lang = r.get("language")
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


# A single keep-alive opener for the whole run. Re-dialling TLS for every one
# of the ~200 requests was what made this flaky: the first run lost every
# search to "remote end closed connection" / getaddrinfo timeouts even though
# the same endpoint answered on the retry below.
_OPENER = urllib.request.build_opener()


def api(path: str, token: str, params: dict | None = None, retries: int = 6):
    """GET a GitHub API path. Returns None on 404 or exhausted retries."""
    url = "https://api.github.com" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "katalir-outreach",
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Connection": "keep-alive",
            },
        )
        try:
            with _OPENER.open(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            if exc.code in (403, 429) and attempt < retries - 1:
                time.sleep(min(5 * (attempt + 1), 30))  # secondary limit: back off
                continue
            if exc.code == 404:
                return None
            break
        except Exception as exc:  # noqa: BLE001 - network flake
            last = str(exc)
            # Exponential-ish backoff; the first run failed purely on this.
            time.sleep(min(2 * (attempt + 1), 20))
    print(f"  ! {path} -> {last}", file=sys.stderr)
    return None


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("GITHUB_TOKEN is not set", file=sys.stderr)
        return 1

    seen: dict[str, dict] = {}
    for query in QUERIES:
        # NO early exit. The previous `len(seen) >= TARGET * 2` break meant the
        # Indonesia queries alone filled the candidate pool, so the Malaysia /
        # Philippines / Thailand / Vietnam queries never ran and the "SEA"
        # file came out two countries wide. A regional shortlist is only
        # useful if the region is actually represented, so every query runs and
        # the per-country quota below shapes the output instead.
        print(f"search: {query}")
        data = api("/search/users", token, {"q": query, "sort": "followers", "per_page": 50})
        for user in (data or {}).get("items", []):
            login = user.get("login")
            if not login or login in seen:
                continue
            if user.get("type") != "User" or JUNK.search(login):
                continue
            seen[login] = {
                "search_language": user.get("language") or "unspecified",
                "discovered_via": query,
                "country": country_of(query),
            }
        time.sleep(2)  # be a good API citizen between searches

    print(f"candidates: {len(seen)}")
    rows: list[dict] = []
    per_country: dict[str, int] = {c: 0 for c in COUNTRIES}
    # Round-robin over countries so a thin country (fewer than 20 matching
    # users) cannot starve the others and leave the file half-empty.
    by_country: dict[str | None, list[tuple[str, dict]]] = {c: [] for c in COUNTRIES}
    for login, stub in seen.items():
        by_country.setdefault(stub["country"], []).append((login, stub))
    unattributed = by_country.pop(None, [])
    # Big countries first, then interleave round-robin taking at most one per
    # country per pass so no single country monopolises the shortlist.
    pools = [by_country[c] for c in COUNTRIES if by_country.get(c)]
    round_robin: list[tuple[str, dict]] = []
    idx_per_pool = 0
    while any(idx_per_pool < len(p) for p in pools):
        for p in pools:
            if idx_per_pool < len(p):
                round_robin.append(p[idx_per_pool])
        idx_per_pool += 1
    round_robin.extend(unattributed)

    for idx, (login, stub) in enumerate(round_robin, start=1):
        if len(rows) >= TARGET:
            break
        country = stub.get("country")
        if country and per_country[country] >= COUNTRY_QUOTA:
            continue
        profile = api(f"/users/{login}", token)
        if not profile:
            continue

        # Explicitly discard every contact field the API may include. `blog`
        # and `twitter_username` are dropped too: those are contact channels,
        # and this list is meant to hold public *identity* only.
        for key in ("email", "blog", "hireable", "twitter_username"):
            profile.pop(key, None)

        public = {k: profile.get(k) for k in PROFILE_FIELDS}
        # Scrub free-text fields: bios and company strings are where a profile
        # volunteers its own email address.
        public["bio"] = scrub(public.get("bio"))
        public["company"] = scrub(public.get("company"))
        if not public.get("name") and not public.get("bio"):
            continue  # no public signal at all
        if JUNK.search(profile.get("name") or ""):
            continue

        repos = api(f"/users/{login}/repos", token, {"sort": "updated", "per_page": 5}) or []
        top_repos = [
            {
                "name": r.get("name"),
                "url": r.get("html_url"),
                "description": r.get("description"),
                "language": r.get("language"),
                "stars": r.get("stargazers_count", 0),
                "updated_at": r.get("updated_at"),
            }
            for r in repos
            if r.get("fork") is False
        ][:5]

        rows.append(
            {
                **public,
                "location": profile.get("location"),
                "primary_language": dominant_language(top_repos) or stub["search_language"],
                "public_repos_count": profile.get("public_repos", 0),
                "followers": profile.get("followers", 0),
                "account_created_at": profile.get("created_at"),
                "public_repos": top_repos,
                "discovered_via": stub["discovered_via"],
                "search_language": stub["search_language"],
                "country": stub.get("country"),
            }
        )
        if country:
            per_country[country] += 1
        if idx % 20 == 0:
            print(
                f"  enriched {idx} -> kept {len(rows)} "
                f"({', '.join(f'{c}={per_country[c]}' for c in COUNTRIES)})"
            )
        time.sleep(0.4)

    # Rank: real shipped work first, then audience size.
    rows.sort(key=lambda r: (-len(r["public_repos"]), -r["followers"]))

    payload = {
        "generated_by": "scripts/collect_outreach_sea.py",
        "data_policy": {
            "public_profile_data_only": True,
            "emails_collected": 0,
            "private_data_collected": 0,
            "note": (
                "Public GitHub profile fields only. No email addresses, no "
                "scraped contact details. A human decides who to contact and "
                "how; this file is a shortlist, not a mailing list."
            ),
        },
        "count": len(rows),
        "country_breakdown": {
            c: sum(1 for r in rows if r.get("country") == c) for c in COUNTRIES
        },
        "profiles": rows,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT} with {len(rows)} profiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
