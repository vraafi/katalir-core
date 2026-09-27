"""F9.1 — gap analysis: n8n nodes vs the Katalir catalogue.

Compares the public n8n node list against Katalir's canonical catalogue
(`dedup_canonical.json`, 23,474 entries) and writes the gaps.

Sources are EXISTING, PUBLIC, KEY-FREE only. This script never needs an API
key and never writes to the catalogue - it is read-only analysis. Anything
requiring a credential (regional payment rails, healthcare, logistics) is
explicitly out of scope per the F8 deferral.

Writes:
    docs/audit/n8n-gap-analysis.json

Usage:
    python scripts/audit_n8n_gap.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import tarfile
import time
import urllib.request
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "dedup_canonical.json"
OUT = ROOT / "docs" / "audit" / "n8n-gap-analysis.json"

NPM_LATEST = "https://registry.npmjs.org/n8n-nodes-base/latest"


def norm(value: str) -> str:
    """`GitHub`, `Http Request`, `http-request` all normalise to the same key."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def load_catalog() -> list[dict]:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else list(data.values())


def extract_node_names(tarball_url: str, token: str | None = None) -> tuple[list[str], int]:
    """Stream the npm tarball and derive node names from its build output.

    Returns (node names, tarball bytes downloaded).

    Two things this had to get right, both found by inspecting the real
    archive rather than assuming:

    1. The published tarball ships ONLY build output. There is no
       `package/nodes/**` and no `*.node.ts` source - the tree is
       `package/dist/nodes/**` plus `package/dist/node-definitions/**`. An
       earlier version of this function looked for the source layout and
       matched 0 of 26,578 files.
    2. A node's identity lives in its `node-definitions/<Name>.js` companion,
       which carries `name`/`displayName`/`group`. Directory names under
       `dist/nodes` are folders of implementation files, not node names, so
       we read the definitions and fall back to the file stem.
    """
    headers = {"User-Agent": "katalir-audit"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # The 9MB tarball download reset mid-transfer on a first attempt. Retry
    # the whole fetch rather than letting a flaky socket fail the audit.
    blob = b""
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(tarball_url, headers=headers)
            with urllib.request.urlopen(req, timeout=180) as resp:
                blob = resp.read()
            break
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"  ! tarball download attempt {attempt + 1} failed: {exc}", file=sys.stderr)
            time.sleep(4 * (attempt + 1))
    if not blob:
        raise RuntimeError(f"could not download tarball: {last}")

    names: set[str] = set()

    def add(candidate: str | None) -> None:
        if candidate and re.match(r"^[A-Za-z][A-Za-z0-9 _.-]{1,60}$", candidate.strip()):
            names.add(candidate.strip())

    with tarfile.open(fileobj=BytesIO(blob), mode="r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            # Primary: the built node definition, e.g.
            # package/dist/node-definitions/Slack.node.js
            m = re.match(r"package/dist/node-definitions/([^/]+)\.js$", member.name)
            if m:
                stem = re.sub(r"\.(node|action|trigger|credentials)$", "", m.group(1))
                add(stem)
                try:
                    text = tar.extractfile(member).read().decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    continue
                # `name:"Slack"` / `displayName:"Slack"` in the built definition.
                for field in ("displayName", "name"):
                    fm = re.search(rf'{field}\s*:\s*["\']([^"\']{{1,60}})["\']', text)
                    if fm:
                        add(fm.group(1))
                continue
            # Secondary: directory-style nodes shipped without a definition file.
            m = re.match(r"package/dist/nodes/([^/]+)/([^/]+)\.js$", member.name)
            if m and m.group(1) not in {"core", "utils"}:
                add(re.sub(r"\.(node|action|trigger)$", "", m.group(2)))

    return sorted(names), len(blob)


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    req = urllib.request.Request(NPM_LATEST, headers={"User-Agent": "katalir-audit"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        meta = json.loads(resp.read().decode("utf-8"))

    pkg, version = meta.get("name"), meta.get("version")
    tarball = meta.get("dist", {}).get("tarball")
    print(f"n8n-nodes-base {version}")
    print(f"tarball: {tarball}")

    catalog = load_catalog()
    print(f"catalogue entries: {len(catalog)}")

    # Index every plausible identifier per catalogue row so a node matches
    # whether it is stored as a slug, a display name, or an external id.
    index: dict[str, dict] = {}
    for row in catalog:
        for key in (row.get("slug"), row.get("name"), row.get("id"), row.get("namespace")):
            k = norm(str(key)) if key else ""
            if k and k not in index:
                index[k] = row
    print(f"catalogue keys indexed: {len(index)}")

    try:
        node_names, blob_bytes = extract_node_names(tarball, token)
    except Exception as exc:  # noqa: BLE001
        print(f"FATAL: could not read n8n tarball: {exc}", file=sys.stderr)
        return 2
    print(f"n8n node dirs: {len(node_names)} (tarball {blob_bytes:,} bytes)")

    matched, gaps = [], []
    # Non-node artefacts that share the node-definitions directory. Without
    # this filter the "gaps" list fills with GraphQL helper types
    # (`*Description`, `*Interface`, `*Type`, `*Filter`) that are not
    # integrations and would send contributors chasing things that do not
    # exist as nodes.
    ARTIFACT_SUFFIX = (
        "description",
        "descriptions",
        "desciption",
        "interface",
        "inteface",
        "type",
        "types",
        "filter",
        "filters",
        "query",
        "mutation",
        "connection",
        "input",
        "args",
        "options",
        "constants",
        "dtos",
        "dto",
        "functions",
        "templates",
    )

    def is_artifact(name: str) -> bool:
        n = name.strip().lower()
        return n.endswith(ARTIFACT_SUFFIX)

    for node in node_names:
        if is_artifact(node):
            continue
        k = norm(node)
        hit = index.get(k)
        # n8n exposes many nodes under a "trigger"/"action" sub-folder; try the
        # bare service name too (`SlackTrigger` -> `slack`) so a present
        # service is not reported as a gap.
        if not hit:
            trimmed = re.sub(r"(trigger|action|credentials)$", "", k, flags=re.I)
            hit = index.get(trimmed)
        if hit:
            matched.append({"node": node, "slug": hit.get("slug")})
        else:
            gaps.append(node)

    overlap_pct = round(100 * len(matched) / len(node_names), 2) if node_names else 0.0
    print(f"matched {len(matched)} / gaps {len(gaps)} ({overlap_pct}% covered)")

    payload = {
        "generated_by": "scripts/audit_n8n_gap.py",
        "sources": {
            "n8n_package": {"name": pkg, "version": version, "tarball": tarball},
            "katalir_catalog": {"file": CATALOG.name, "entries": len(catalog)},
        },
        "summary": {
            "n8n_node_count": len(node_names),
            "catalogue_entries": len(catalog),
            "matched": len(matched),
            "gaps": len(gaps),
            "overlap_percent": overlap_pct,
        },
        "policy": {
            "existing_public_sources_only": True,
            "api_keys_required": 0,
            "catalogue_mutated": False,
            "note": (
                "Read-only analysis over public data. No catalogue entries were "
                "created. F9.2 generation is a separate, credentialed step and is "
                "NOT covered by this file."
            ),
        },
        "matched": matched,
        "gaps": gaps,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
