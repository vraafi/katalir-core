import { createClient } from "@supabase/supabase-js";
import { readFileSync, rmSync } from "node:fs";

const env = readFileSync(new URL("../../.env", import.meta.url), "utf-8");
const get = (k) => {
  const m = env.split("\n").find((l) => l.trim().startsWith(k + "="));
  return m ? m.split("=").slice(1).join("=").trim() : "";
};
const URL0 = get("SUPABASE_URL");
const SR = get("SUPABASE_SERVICE_ROLE_KEY");
if (URL0 && SR) {
  try {
    const sess = JSON.parse(readFileSync(new URL("../_e2e_session.json", import.meta.url), "utf-8"));
    const admin = createClient(URL0, SR, { auth: { persistSession: false } });
    const { error } = await admin.auth.admin.deleteUser(sess.user.id);
    console.log("DELETED user=", sess.user.email, "err=", error?.message ?? "none");
  } catch (e) {
    console.log("CLEANUP_ERR", String(e).slice(0, 120));
  }
}
rmSync(new URL("../_e2e_session.json", import.meta.url), { force: true });
console.log("session file removed ok");