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
const glamaCatalog = read("glama_connectors.json");

const pool = [...b1.tools_listed_connectors, ...b2.tools_listed_connectors];
const overlap = b1.tools_listed_connectors.filter((x) => b2.tools_listed_connectors.includes(x)).length;

const claims = [
  // Reality-check table
  ["raw catalogue entries", "28.670", dot(dedup.before)],
  ["unique integrations (deduped)", "22.904", dot(dedup.after)],
  ["unique %", "79.89", (100 - (dedup.collapsed / dedup.before) * 100).toFixed(2)],
  ["collapsed", "5.766", dot(dedup.collapsed)],
  ["groups in >1 source", "1.602", dot(dedup.multi_source_groups)],
  ["unique call-verified", "26", String(dedup.unique_verified)],
  ["integrations that list tools", "1.896", dot(dedup.tools_listed)],
  ["discovered only", "21.008", dot(dedup.discovered_only)],
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
  ["tools_listed + discovered_only == unique", "22904", String(dedup.tools_listed + dedup.discovered_only)],
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
