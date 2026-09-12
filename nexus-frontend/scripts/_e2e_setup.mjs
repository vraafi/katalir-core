import { createClient } from "@supabase/supabase-js";
import { readFileSync, writeFileSync } from "node:fs";

// baca root .env (Proyek_AI/.env) — scripts/ berada dua level di bawah
const env = readFileSync(new URL("../../.env", import.meta.url), "utf-8");
function get(k) {
  const m = env.split("\n").find((l) => l.trim().startsWith(k + "="));
  return m ? m.split("=").slice(1).join("=").trim() : "";
}
const URL0 = get("SUPABASE_URL");
const SR = get("SUPABASE_SERVICE_ROLE_KEY");
const anon = get("SUPABASE_KEY");

if (!URL0 || !SR) {
  console.log("ERR env missing");
  process.exit(2);
}
const ref = URL0.replace("https://", "").replace(".supabase.co", "");
console.log("REF=" + ref);

const admin = createClient(URL0, SR, { auth: { persistSession: false } });
const email = `e2e.${Date.now()}@nexus-local.test`;
const password = "E2e!Xy9#Pass-" + Date.now();

const { data: created, error: cre } = await admin.auth.admin.createUser({
  email,
  password,
  email_confirm: true,
});
if (cre) {
  console.log("CREATE_ERR=" + cre.message);
  process.exit(3);
}
console.log("CREATED user=" + email);

// signIn untuk dapat access_token asli
const cli = createClient(URL0, anon || SR, { auth: { persistSession: false } });
const { data, error } = await cli.auth.signInWithPassword({ email, password });
if (error) {
  console.log("SIGNIN_ERR=" + error.message);
  process.exit(4);
}
const s = data.session;
const sess = {
  access_token: s.access_token,
  refresh_token: s.refresh_token,
  expires_in: s.expires_in,
  expires_at: s.expires_at,
  token_type: s.token_type,
  user: s.user,
};
// session json disimpan di nexus-frontend/_e2e_session.json (cwd playwright)
writeFileSync(
  new URL("../_e2e_session.json", import.meta.url),
  JSON.stringify(sess, null, 0)
);
console.log("SESSION_SAVED access_token_len=" + s.access_token.length);
console.log("DONE " + email + " " + password);