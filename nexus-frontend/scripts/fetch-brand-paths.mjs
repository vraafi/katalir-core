// Bakes the brand paths for the MCP apps @lobehub/icons does not ship into
// src/lib/brand-paths.ts, so no logo is loaded from a third party at runtime.
//
// Slack is the one exception: it was removed from the current Simple Icons set,
// so it is pulled from simple-icons@13 (CC0-1.0) via jsDelivr, which still
// carries the 24x24 mark.
//
// Run: node scripts/fetch-brand-paths.mjs
import fs from "node:fs";
import path from "node:path";

const CDN = "https://cdn.simpleicons.org";
const FALLBACK = "https://cdn.jsdelivr.net/npm/simple-icons@13/icons";

const slugs = [
  "linear", "stripe", "supabase", "discord", "telegram", "docker", "gitlab",
  "postgresql", "redis", "mongodb", "airtable", "zoom", "shopify", "sentry",
  "slack",
];

function pick(svg, name) {
  const vb = svg.match(/viewBox="([^"]+)"/);
  const ds = [...svg.matchAll(/ d="([^"]+)"/g)].map((m) => m[1]);
  if (!vb || !ds.length) throw new Error(`could not parse ${name}`);
  return { viewBox: vb[1], d: ds.join(" ") };
}

const out = {};
for (const slug of slugs) {
  let svg = null;
  let from = "";
  const primary = await fetch(`${CDN}/${slug}/919191`);
  if (primary.ok) {
    svg = await primary.text();
    from = "simple-icons";
  } else {
    const alt = await fetch(`${FALLBACK}/${slug}.svg`);
    if (!alt.ok) throw new Error(`${slug}: ${primary.status} then ${alt.status}`);
    svg = await alt.text();
    from = "simple-icons@13";
  }
  out[slug] = pick(svg, slug);
  console.log(`ok ${slug.padEnd(12)} from=${from.padEnd(15)} viewBox=${out[slug].viewBox} len=${out[slug].d.length}`);
}

const header = `/**
 * Brand paths for the MCP apps that \`@lobehub/icons\` does not ship.
 *
 * Baked in rather than hot-linked from cdn.simpleicons.org because the
 * production Content-Security-Policy is \`img-src 'self' data: blob:\`, and
 * every remote logo was blocked at runtime. Inlining also removes a
 * third-party request per logo and lets the colour come from \`currentColor\`.
 *
 * Sources are CC0-1.0 (simple-icons.org); Slack comes from simple-icons@13
 * because it has since been removed from the current set.
 *
 * Do not hand-edit. Regenerate with: node scripts/fetch-brand-paths.mjs
 */
export const BRAND_PATHS: Record<string, { viewBox: string; d: string }> = `;

fs.mkdirSync(path.dirname("src/lib"), { recursive: true });
fs.writeFileSync("src/lib/brand-paths.ts", header + JSON.stringify(out, null, 2) + ";\n");
console.log(`\nwrote src/lib/brand-paths.ts with ${Object.keys(out).length} brands`);
