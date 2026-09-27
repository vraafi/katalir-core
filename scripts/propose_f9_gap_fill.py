"""F9.2-F9.5 - propose catalogue entries for the n8n coverage gaps.

READ-ONLY BY DESIGN. This script never writes to `dedup_canonical.json`. It
emits a PROPOSAL that a human reviews, because a proposal that silently
merged would turn a 23,474-entry catalogue into an unreviewable diff.

Sources are the snapshots already committed in the repo:
  nango_providers.json, composio_toolkits.json, openapi_tools_manifest.json,
  glama_connectors.json.
No network calls and no API keys: a proposal that depends on a live key is
not reproducible, and F9's whole point is a checkable claim.

Usage:
    python scripts/propose_f9_gap_fill.py
Writes:
    docs/audit/f9-gap-fill-proposal.json
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAPS = ROOT / "docs" / "audit" / "n8n-gap-analysis.json"
OUT = ROOT / "docs" / "audit" / "f9-gap-fill-proposal.json"

SOURCES = {
    "nango": ROOT / "nango_providers.json",
    "composio": ROOT / "composio_toolkits.json",
    "openapi": ROOT / "openapi_tools_manifest.json",
    "glama": ROOT / "glama_connectors.json",
}

# --- Classification of n8n "gaps" -------------------------------------------
# The 181 raw gaps are NOT 181 missing integrations. They are mostly n8n's own
# core/utility surface plus a long tail of shared helper modules. Publishing
# "181 gaps" as a backlog size would be a marketing claim we cannot stand
# behind, so each gap is bucketed and only `integration` gaps count as real
# fillable work.

# n8n core / generic utility nodes. Not third-party services -- Katalir will
# never "integrate" with `If` or `SplitInBatches`.
CORE_NODES = re.compile(
    r"^(if|merge|set|switch|wait|cron|interval|function|functionitem|"
    r"genericfunction|flow|flowtrigger|webhook|respondtowebhook|"
    r"webhookmapping|scheduletrigger|ssetrigger|ssetrigger|"
    r"localfiletrigger|manualtrigger|errortrigger|nop|noop|"
    r"stopanderror|simulate|simulatetrigger|renamekeys|splitinbatches|"
    r"itemlists|validationerror|validation|javascriptsandbox|"
    r"jscodevalidator|jstaskrunnersandbox|pythontaskrunnersandbox|"
    r"executeCommand|html|htmlextract|markdown|xml|crypto|jwt|"
    r"readbinaryfile|readbinaryfiles|writebinaryfile|movebinarydata|"
    r"readpdf|spreadsheetfile|editimage|form|compression|comparedatasets|"
    r"executiondata|executionerror|dynamiccredentialcheck|"
    r"triggerplaceholders|workflowlocator|workflowtrigger|"
    r"emailreadimap|emailsend|mongodbproperties|stickynote|"
    r"httpRequest|postbin|peekalink|openthesaurus|"
    r"code|codejavascript|javascript|s3)$",
    re.I,
)

# Generic infrastructure Katalir covers differently (databases, transports,
# protocols) or deliberately does not expose as an "integration".
INFRA_NODES = re.compile(
    r"^(postgres|postgrestrigg|gres|mysql|mongodb|sqlite|redis|"
    r"elasticsearch|sftp|ftp|ssh|ldap|railway|airtable|github|gitlab|"
    r"googlesheets|slack|discord|notion|mailcheck|mailerlabs|"
    r"mailchimp|mailgun|mandrill|ses|smtp|imap)$",
    re.I,
)

# Shared helper / type modules that are not nodes at all.
HELPER_NODES = re.compile(
    r"(helper|interface|descriptions|desciption|descrition|descripion|"
    r"dtos?|types?|countries|currencies|cssvariables|randomdata|mock|"
    r"placeholder|utils|constants|queries|"
    r".*\.(operation|error)$)",
    re.I,
)


def classify(gap: str) -> str:
    g = gap.strip()
    if HELPER_NODES.search(g):
        return "helper_artifact"
    if CORE_NODES.match(g):
        return "n8n_core"
    if INFRA_NODES.match(g):
        return "infra"
    return "integration"


# Integration names that cannot work key-free: the caller must supply a
# credential we do not have. Proposing them would be proposing something we
# cannot verify, so they are reported separately rather than as fills.
NEEDS_CREDENTIAL = re.compile(
    r"^(aws|azure|gcp|google-cloud|slack|discord|notion|airtable|hubspot|"
    r"salesforce|shopify|stripe|github|gitlab|jira|confluence|zendesk|"
    r"intercom|microsoft-teams|ms-teams|openai|anthropic|datadog|"
    r"snowflake|databricks|sendgrid|twilio|mailchimp)$",
    re.I,
)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = s.encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def load_names(path: Path) -> dict[str, str]:
    """Return {normalised_name: display_name} from a source snapshot.

    Tolerates the several shapes these files use (list of dicts, dict of
    dicts, dict of lists) rather than assuming one, because guessing wrong
    would silently yield an empty proposal that still "succeeds".
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"  ! {path.name}: {exc}", file=sys.stderr)
        return {}

    out: dict[str, str] = {}

    def add(nm: str, label: str) -> None:
        n = norm(nm)
        if n:
            out.setdefault(n, label)

    def take(v: object) -> None:
        if isinstance(v, str) and v.strip():
            add(v, v.strip())
        elif isinstance(v, dict):
            for k in ("name", "title", "display_name", "slug", "key", "id"):
                if isinstance(v.get(k), str) and v[k].strip():
                    add(v[k], v[k].strip())
                    return

    if isinstance(data, dict):
        for k, v in data.items():
            # Keys are source-prefixed and slug-cased, e.g. `nango:1password-events`
            # or `composio:google_drive`. The PREFIX is an internal marker, not
            # part of the integration name, and the slug form is what actually
            # matches an n8n node. Indexing only the display `name` ("1Password
            # (Events API)") made 180 of 181 gaps miss.
            if isinstance(k, str) and ":" in k:
                slug = k.split(":", 1)[1].strip()
                if slug:
                    add(slug, slug)
            take(v)
            take(k)
    elif isinstance(data, list):
        for v in data:
            take(v)
    return out


def main() -> int:
    if not GAPS.exists():
        print("run scripts/audit_n8n_gap.py first", file=sys.stderr)
        return 1
    gap_doc = json.loads(GAPS.read_text(encoding="utf-8"))
    gaps: list[str] = gap_doc.get("gaps", [])
    matched_slugs = {m["slug"] for m in gap_doc.get("matched", [])}

    sources = {name: load_names(p) for name, p in SOURCES.items()}
    for name, idx in sources.items():
        print(f"{name}: {len(idx)} names")

    entries: list[dict] = []
    per_source = {"nango": 0, "composio": 0, "openapi": 0, "glama": 0}
    skipped: list[dict] = []
    unresolved: list[str] = []
    buckets: dict[str, int] = {
        "integration": 0,
        "n8n_core": 0,
        "infra": 0,
        "helper_artifact": 0,
    }

    for gap in gaps:
        kind = classify(gap)
        buckets[kind] += 1
        if kind != "integration":
            # Not a fillable integration. Recording it as a proposal entry
            # would inflate the backlog with work that does not exist.
            continue
        k = norm(gap)
        # Source priority mirrors catalogue richness: curated Nango/Composio
        # entries beat machine-generated OpenAPI rows.
        hit = None
        for name in ("nango", "composio", "openapi", "glama"):
            if k in sources[name]:
                hit = (name, sources[name][k])
                break
        if not hit:
            unresolved.append(gap)
            continue
        name, display = hit
        if NEEDS_CREDENTIAL.match(display):
            skipped.append(
                {"name": display, "source": name, "reason": "needs caller API key"}
            )
            continue
        per_source[name] += 1
        entries.append(
            {
                "name": display,
                "n8n_node": gap,
                "source": name,
                "slug": norm(display),
                "reason": f"exact normalised name match in {name} snapshot",
            }
        )

    payload = {
        "generated_by": "scripts/propose_f9_gap_fill.py",
        "status": "PROPOSAL_ONLY_NOT_APPLIED",
        "policy": {
            "applied_to_canonical": False,
            "network_calls": 0,
            "api_keys_used": 0,
            "note": (
                "Nothing here is written to dedup_canonical.json. These are "
                "candidates for human review, keyed off the local provider "
                "snapshots so the result is reproducible offline."
            ),
        },
        "input": {
            "gaps_considered": len(gaps),
            "n8n_nodes": gap_doc.get("summary", {}).get("n8n_node_count"),
            "catalogue_entries": gap_doc.get("summary", {}).get("catalogue_entries"),
            "already_matched": len(matched_slugs),
        },
        "gap_classification": {
            **buckets,
            "note": (
                "The raw gap count is NOT a backlog of missing integrations. "
                "Most gaps are n8n's own core nodes (If/Merge/Webhook), generic "
                "infrastructure (databases/transports), or shared helper modules "
                "that are not nodes at all. Only 'integration' gaps are real "
                "fillable work."
            ),
        },
        "total_proposed": len(entries),
        "from_nango": per_source["nango"],
        "from_composio": per_source["composio"],
        "from_openapi": per_source["openapi"],
        "from_glama": per_source["glama"],
        "skipped_need_apikey": len(skipped),
        "unresolved_no_source": len(unresolved),
        "entries": entries,
        "skipped": skipped,
        "unresolved": unresolved,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"proposed {len(entries)} / {len(gaps)} gaps")
    print(
        f"  nango={per_source['nango']} composio={per_source['composio']} "
        f"openapi={per_source['openapi']} glama={per_source['glama']}"
    )
    print(f"  skipped(need apikey)={len(skipped)} unresolved={len(unresolved)}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

