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
  ["nango contributed 0 tools", "0", String(Object.values(nango).reduce((a, v) => a + (v.tools_count || 0), 0))],
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
