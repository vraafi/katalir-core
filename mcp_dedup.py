"""Deduplicate the Katalir integration catalogue.

Why this exists: a name like "Slack" or "Gmail" legitimately appears in several
upstream catalogues (ToolSDK, Composio, Glama, OpenConnector). Counting each
occurrence inflates every headline number, so nothing may be counted until it
has been collapsed to one canonical entry.

Design rules:

* the canonical key is a *normalised name*, not the source id, because ids are
  source-specific (``composio/slack`` vs ``@modelcontextprotocol/server-slack``);
* merging never downgrades evidence: the strongest verification flag wins and
  every contributing source is preserved, so provenance stays auditable;
* a group is only ``unique_verified`` if some member earned that by actually
  being called - being *listed* is not verification;
* nothing is deleted: every collapsed member is kept under ``member_ids``.
"""
from __future__ import annotations

import json
import pathlib
import re
import unicodedata
from collections import Counter, defaultdict

REGISTRY_FILES = {
    "toolsdk": "mcp_registry_cache.json",
    "composio": "composio_toolkits.json",
    "openconnector": "openconnector_actions.json",
    "glama": "glama_servers.json",
    "glama-connector": "glama_connectors.json",
    "openapi-generated": "openapi_apis.json",
}

# Generator/branding words that carry no identity information.
# Word-boundary matched on purpose: without \b the word "api" was being carved
# out of "openapi", turning that name into "open" and letting real duplicates
# slip past the dedup.
_NOISE = re.compile(
    r"\b(?:mcp|mcps|server|servers|api|apis|sdk|client|clients|tool|tools|"
    r"integration|integrations|node|nodes|generated|openapi|wrapper|official)\b",
    re.IGNORECASE,
)


def normalize_name(name: str) -> str:
    """Fold a display name into a comparable key.

    ``"@modelcontextprotocol/server-memory"``, ``"Memory MCP Server"`` and
    ``"memory"`` all collapse to ``memory``.
    """
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.casefold()
    text = re.sub(r"^@?[\w.\-]+/[\w.\-]+$", text.split("/")[-1], text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = _NOISE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip() or text.strip()


def load_registry() -> dict[str, dict]:
    """Load every source file into one dict.

    Keys are namespaced per source on purpose. Several catalogues use bare
    service names ("github"), so a plain key would let one file silently
    overwrite another and lose entries before dedup even starts - which is
    exactly the kind of silent inflation this module exists to stop.
    """
    out: dict[str, dict] = {}
    for source, filename in REGISTRY_FILES.items():
        path = pathlib.Path(filename)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            if isinstance(value, dict):
                out[f"{source}:{key}"] = {**value, "source": value.get("source") or source}
    return out


def evidence_of(entry: dict) -> dict:
    ver = entry.get("verification") or {}
    return {
        "call_verified": bool(ver.get("call_verified") or entry.get("runtime_verified")),
        "tools_listed": bool(ver.get("tools_listed")),
        "discovered": bool(ver.get("discovered", True)),
        "tools": len(entry.get("tools") or []) or int(entry.get("tools_count") or 0),
    }


def priority_of(entry: dict) -> tuple:
    """Sort key: real execution beats listing beats mere presence."""
    ev = evidence_of(entry)
    return (ev["call_verified"], ev["tools_listed"], ev["tools"], ev["discovered"])


def dedup_catalog(entries: dict[str, dict]) -> tuple[list[dict], dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for key, entry in entries.items():
        name = entry.get("name") or key
        groups[normalize_name(name)].append({**entry, "_id": key})

    canonical: list[dict] = []
    for norm, members in groups.items():
        ranked = sorted(members, key=priority_of, reverse=True)
        winner = dict(ranked[0])
        # evidence is merged across the group: a verification earned anywhere
        # in the group survives the collapse
        merged_call = any(evidence_of(m)["call_verified"] for m in members)
        winner["canonical_key"] = norm
        winner["sources"] = sorted({str(m.get("source")) for m in members})
        winner["source_count"] = len(winner["sources"])
        winner["member_ids"] = sorted(m["_id"] for m in members)
        winner["verification"] = {
            "discovered": any(evidence_of(m)["discovered"] for m in members),
            "tools_listed": any(evidence_of(m)["tools_listed"] for m in members),
            "call_verified": merged_call,
        }
        winner["runtime_verified"] = merged_call
        winner["unique_verified"] = merged_call
        winner.pop("_id", None)
        canonical.append(winner)

    canonical.sort(key=lambda e: (not e["unique_verified"], str(e.get("name") or "").casefold()))
    stats = {
        "before": len(entries),
        "after": len(canonical),
        "collapsed": len(entries) - len(canonical),
        "unique_percent": round(100.0 * len(canonical) / len(entries), 2) if entries else 0.0,
        "multi_source_groups": sum(1 for e in canonical if e["source_count"] > 1),
        "unique_verified": sum(1 for e in canonical if e["unique_verified"]),
        "tools_listed": sum(1 for e in canonical if e["verification"]["tools_listed"]),
        "discovered_only": sum(1 for e in canonical if not e["verification"]["tools_listed"]),
        "by_source_membership": dict(
            Counter(s for e in canonical for s in e["sources"]).most_common()
        ),
    }
    return canonical, stats


def duplicates_report(canonical: list[dict], limit: int = 25) -> list[dict]:
    worst = sorted((e for e in canonical if e["source_count"] > 1), key=lambda e: -e["source_count"])
    return [
        {
            "name": e.get("name"),
            "canonical_key": e["canonical_key"],
            "sources": e["sources"],
            "collapsed_ids": e["member_ids"],
        }
        for e in worst[:limit]
    ]


if __name__ == "__main__":
    reg = load_registry()
    canon, stats = dedup_catalog(reg)
    pathlib.Path("dedup_report.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    pathlib.Path("dedup_canonical.json").write_text(
        json.dumps(canon, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    pathlib.Path("dedup_duplicates.json").write_text(
        json.dumps(duplicates_report(canon), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\nTop duplicate groups:")
    for d in duplicates_report(canon, 12):
        print(f"  {d['name']!r} <- {d['sources']}")
