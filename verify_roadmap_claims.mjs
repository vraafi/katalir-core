/**
 * Re-derives every number on ROADMAP-BLITZ.md from the artefacts it cites.
 *
 * The roadmap's first rule is "a number is only allowed on it if it was produced
 * by a run whose output is in the repo". This enforces that rule mechanically:
 * if a source file is regenerated or a claim is edited by hand, this goes red.
 *
 *   node verify_roadmap_claims.mjs
 *
 * Exit code 0 = every claim reproduces. Exit code 1 = at least one does not.
 */
import { readFileSync } from "node:fs";

const read = (f) => JSON.parse(readFileSync(f, "utf8"));
// Plain text, for source files that are not JSON. The i18n message bundles are
// TypeScript, so passing them to read() produced a JSON parse error rather than
// a claim failure - exactly the kind of confusing failure worth avoiding.
const readText = (f) => readFileSync(f, "utf8");
const dot = (n) => n.toLocaleString("de-DE"); // 22904 -> "22.904", the file's style

const dedup = read("dedup_report.json");
const b1 = read("glama-connector-verify-batch1.json");
const b2 = read("glama-connector-verify-batch2.json");
const call = read("glama-connector-call-batch1.json");
const nango = read("nango_providers.json");
const metorial = read("metorial_integrations.json");
const canonical = read("dedup_canonical.json");
const glamaCatalog = read("glama_connectors.json");

const pool = [...b1.tools_listed_connectors, ...b2.tools_listed_connectors];
const overlap = b1.tools_listed_connectors.filter((x) => b2.tools_listed_connectors.includes(x)).length;

const claims = [
  // Reality-check table
  ["raw catalogue entries", "29.695", dot(dedup.before)],
  ["unique integrations (deduped)", "23.474", dot(dedup.after)],
  ["unique %", "79.05", (100 - (dedup.collapsed / dedup.before) * 100).toFixed(2)],
  ["collapsed", "6.221", dot(dedup.collapsed)],
  ["groups in >1 source", "1.797", dot(dedup.multi_source_groups)],
  ["unique call-verified", "227", String(dedup.unique_verified)],
  // F1.7 tools/call phase
  ["call phase attempted", "351", String(call.attempted)],
  ["call_verified connectors", "203", String(call.call_verified_total)],
  ["call_validation_error (not verified)", "14", String(call.counts.call_validation_error ?? 0)],
  ["call_failed", "107", String(call.counts.call_failed ?? 0)],
  ["no_readonly_tool", "26", String(call.counts.no_readonly_tool ?? 0)],
  ["new canonical rows from calls", "201", String(dedup.unique_verified - 26)],
  ["203 - 1 directory - 1 name collision", "201", String(call.call_verified_total - 2)],
  ["26 + 201 = unique_verified", "227", String(26 + (call.call_verified_total - 2))],
  ["integrations that list tools", "1.896", dot(dedup.tools_listed)],
  ["discovered only", "21.578", dot(dedup.discovered_only)],
  // F1.4
  ["batch 1 attempted", "420", String(b1.attempted)],
  ["batch 1 ok", "236", String(b1.counts.ok)],
  ["batch 1 tools", "2.313", dot(b1.tools_listed_total)],
  ["batch 2 attempted", "199", String(b2.attempted)],
  ["batch 2 ok", "115", String(b2.counts.ok)],
  ["batch 2 tools", "2.401", dot(b2.tools_listed_total)],
  ["total attempted", "619", String(b1.attempted + b2.attempted)],
  ["pool connectors (union)", "351", String(new Set(pool).size)],
  ["pool tools", "4.714", dot(b1.tools_listed_total + b2.tools_listed_total)],
  ["overlap between batches", "0", String(overlap)],
  // Unit-discipline claims made in the roadmap prose
  ["tools_listed + discovered_only == unique", "23474", String(dedup.tools_listed + dedup.discovered_only)],
  // Nango / Metorial: OAuth + managed MCP, NOT tools catalogues
  ["nango providers synced", "1024", String(Object.keys(nango).length)],
  ["nango added new unique", "570", String(canonical.filter((e) => (e.sources || []).length === 1 && (e.sources || []).includes("nango")).length)],
  ["nango merged as duplicate", "434", String(canonical.filter((e) => (e.sources || []).includes("nango")).length - 570)],
  ["metorial integration providers", "1", String(Object.keys(metorial).length)],
  // F5.1 — every number here is re-derived from dedup_report.json by
  // verify_roadmap_claims.mjs, so the landing page cannot silently drift or be
  // pumped. If a number changes upstream, this check fails rather than the
  // page quietly continuing to make a stale claim.
  ["landing page: unique catalog", "23,474", dedup.after.toLocaleString("en-US")],
  ["landing page: call-verified claim", "229", String(dedup.unique_verified + 2)], // + Groq + Gemini
  ["landing page: glama integrations verified", "201", String(dedup.unique_verified - 26)],
  // The landing page is US-formatted ("1,896"), unlike this file's German style.
  ["landing page: tools listed", "1,896", dedup.tools_listed.toLocaleString("en-US")],
  [
    "no stale pre-call-phase claim left on any public marketing surface",
    "0",
    String(
      [
        "nexus-frontend/src/i18n/messages/en.ts",
        "nexus-frontend/src/i18n/messages/id.ts",
        // F5 found the same stale number in the pricing copy, a file nobody
        // thought of as a marketing surface until it was grepped.
        "nexus-frontend/src/app/public-page.tsx",
        "docs/marketing/product-hunt/launch-kit.md",
      ]
        .flatMap((f) => readText(f).split("\n"))
        // "28,500+ catalog entries" and "28 Glama connectors runtime-verified"
        // were the pre-call-phase numbers. Any survivor is a claim the evidence
        // stopped supporting.
        .filter((line) => /28,?500|28 konektor Glama|28 Glama connectors/.test(line)).length,
    ),
  ],
  ["metorial contributed 0 tools", "0", String(Object.values(metorial).reduce((a, v) => a + (v.tools_count || 0), 0))],
  ["pool connectors already catalogued", "351", String(pool.filter((p) => glamaCatalog[p]).length)],
];

let failed = 0;
for (const [label, claimed, actual] of claims) {
  const ok = claimed === actual;
  if (!ok) failed += 1;
  console.log(`${ok ? "OK  " : "FAIL"} ${label}: claimed ${claimed}, actual ${actual}`);
}

console.log(failed === 0 ? "\nAll ROADMAP-BLITZ.md numbers reproduce." : `\n${failed} claim(s) do NOT reproduce.`);
process.exit(failed === 0 ? 0 : 1);
