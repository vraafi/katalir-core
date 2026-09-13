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

// Ambil 60 sesi terbaru, lalu periksa chat_messages untuk duplikat role=user
// dalam satu sesi (indikator bug DB = double-insert).
const { data: sessions, error: se } = await admin
  .from("chat_sessions")
  .select("id, title, created_at")
  .order("created_at", { ascending: false })
  .limit(60);
if (se) { console.log("SESS_ERR=" + se.message); process.exit(3); }

let checked = 0;
let dups = 0;
let dupExamples = [];
for (const s of sessions || []) {
  const { data: msgs, error } = await admin
    .from("chat_messages")
    .select("role, content")
    .eq("session_id", s.id)
    .order("created_at", { ascending: true });
  if (error) continue;
  const users = (msgs || []).filter((m) => m.role === "user");
  const count = {};
  for (const m of users) {
    const k = m.content;
    count[k] = (count[k] || 0) + 1;
  }
  const dup = Object.entries(count).filter(([, n]) => n > 1);
  checked++;
  if (dup.length) {
    dups++;
    if (dupExamples.length < 5) {
      dupExamples.push({ session: s.id.slice(0, 12), title: (s.title || "").slice(0, 30), dup });
    }
  }
}
console.log("SESSIONS_SCANNED=" + checked);
console.log("SESSIONS_WITH_DUP_USER_MSG=" + dups);
console.log("EXAMPLES=" + JSON.stringify(dupExamples));