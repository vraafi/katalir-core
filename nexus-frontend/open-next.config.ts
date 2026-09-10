import { defineCloudflareConfig } from "@opennextjs/cloudflare";
import incrementalCache from "@opennextjs/cloudflare/overrides/incremental-cache/kv-incremental-cache";

// OpenNext Cloudflare config — RSC, Server Actions, streaming aktif.
// Dev: `opennextjs-cloudflare build && opennextjs-cloudflare preview`.
// Prod: `opennextjs-cloudflare deploy` (via wrangler | OpenNext Dashboard).
export default defineCloudflareConfig({
  incrementalCache,
});