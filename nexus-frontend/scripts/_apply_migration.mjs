import { createClient } from "@supabase/supabase-js";
import { readFileSync } from "node:fs";

const env = readFileSync(new URL("../../.env", import.meta.url), "utf-8");
function get(k) {
  const m = env.split("\n").find((l) => l.trim().startsWith(k + "="));
  return m ? m.split("=").slice(1).join("=").trim() : "";
}
const URL0 = get("SUPABASE_URL");
const SR = get("SUPABASE_SERVICE_ROLE_KEY");
if (!URL0 || !SR) { console.log("ERR env"); process.exit(2); }
const admin = createClient(URL0, SR, { auth: { persistSession: false } });

// Cek apakah kolom client_request_id sudah ada (postgrest error PGRST204 bila tidak).
const { error } = await admin
  .from("chat_messages")
  .select("id,client_request_id")
  .limit(1);
console.log("COLUMN_PROBE_ERR=" + JSON.stringify(error?.message ?? "none"));
console.log("COLUMN_EXISTS=" + JSON.stringify(!error));
console.log("");
console.log("[!] exec_sql RPC tidak tersedia -> DDL tidak bisa dijalankan dari script ini.");
console.log("[!] Blokir dulu deploy: backend meng-insert client_request_id.");
console.log("[!] Jalankan migrations/2026_dedupe_chat_messages.sql manual di Supabase Dashboard > SQL Editor,");
console.log("[!] ATAU gunakan SUPABASE_ACCESS_TOKEN (management API) untuk query/ DDL via API.");
process.exit(error ? 5 : 0);