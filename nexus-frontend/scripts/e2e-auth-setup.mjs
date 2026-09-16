/**
 * GLOBAL SETUP Playwright — menyiapkan fixture auth E2E yang SAH, bukan sekadar
 * "belum kedaluwarsa".
 *
 * MASALAH YANG DIPERBAIKI — 2026-09-16 (dibuktikan dari payload, bukan dugaan):
 *   Tiga tes produksi gagal dengan `/models` & `/chat` menjawab 503
 *   `{"detail":"Verifikasi token sementara tidak tersedia ...; JWKS: ConnectTimeout"}`.
 *   Penelusuran memisahkan DUA sebab yang sebelumnya tercampur:
 *     1. Pesan 503 itu menyesatkan UNTUK KASUS INI: tokennya memang tidak sah.
 *        Verifikasi terhadap JWKS proyek (id `kid` identik; cache disk dan
 *        unduhan segar dibandingkan satu per satu) menghasilkan
 *        `InvalidSignatureError` untuk `_e2e_session.refreshed.json` &
 *        `_e2e_session.extended.json`, sementara token asli
 *        (`_e2e_session.json`) hanya `ExpiredSignatureError`. Backend menolak
 *        dengan BENAR; yang salah adalah fixture-nya.
 *     2. Sumber token palsu ada di repo: `_e2e_extend.py` menyunting klaim
 *        `exp` TANPA menandatangani ulang. Setup versi lama memilih fixture
 *        HANYA dari TTL (`expires_in: 604800` >> 60s), sehingga token palsu itu
 *        disebarkan ke `_e2e_session.refreshed.json` + `_e2e_storage.json` dan
 *        dipakai SEMUA spec ber-auth. Gejalanya terbaca sebagai "bug produk"
 *        padahal cacat harness.
 *
 * KEBIJAKAN BARU (menutup kelas bug ini, bukan gejalanya):
 *   - Fixture TIDAK PERNAH dipakai ulang tanpa VERIFIKASI SIGNATURE terhadap
 *     JWKS proyek (env `SUPABASE_JWKS` -> `.jwks_cache.json` -> unduhan).
 *     Fixture yang gagal verifikasi DITOLAK dan dilaporkan sebabnya.
 *   - `_e2e_session.extended.json` dikeluarkan dari daftar kandidat; bila
 *     ditemukan di disk ia di-rename ke `*.FORGED.json` supaya sesi berikutnya
 *     tidak bisa tertipu lagi.
 *   - Bila tidak ada fixture yang sah, sesi DIMINT dari GoTrue secara sah:
 *     (a) tukar `refresh_token`, (b) `grant_type=password` memakai user E2E
 *     tetap, (c) admin API (service role) membuat user E2E lalu password grant.
 *     Kredensial user tetap disimpan di `_e2e_user.json` (gitignored) agar
 *     tidak membuat user baru setiap run.
 *
 * YANG DITULIS: `_e2e_session.refreshed.json` (dibaca `model-filter.spec.ts`)
 * dan `_e2e_storage.json` (storageState). SENGAJA TIDAK PERNAH GAGAL TOTAL:
 * bila tidak ada sesi sah, setup hanya memberi peringatan — spec tetap gagal
 * di guard TTL-nya sendiri (tempat yang tepat), bukan crash setup yang
 * menyembunyikan sebab.
 */
import { createPublicKey, verify as verifyRaw } from "node:crypto";
import { existsSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const ROOT = process.cwd();
const FRONTEND_PORT = Number(process.env.E2E_PORT || 3000);
const ORIGIN = `http://localhost:${FRONTEND_PORT}`;
/** Token dipakai ulang hanya bila sisa umurnya di atas ambang ini (detik). */
const MIN_TTL_S = 60;
/** Batas waktu panggilan GoTrue (ms). */
const AUTH_TIMEOUT_MS = 20000;

/** Baca env dari .env.local lalu ../.env (konvensi repo ini). */
function envValue(...names) {
  for (const file of [".env.local", "../.env", ".env"]) {
    const p = join(ROOT, file);
    if (!existsSync(p)) continue;
    const text = readFileSync(p, "utf-8");
    for (const name of names) {
      const m = text.match(new RegExp(`^\\s*${name}\\s*=\\s*(.+)\\s*$`, "m"));
      if (m) return m[1].replace(/^["']|["']$/g, "").trim();
    }
  }
  return process.env[names[0]] ?? "";
}

const SUPABASE_URL = envValue("NEXT_PUBLIC_SUPABASE_URL", "SUPABASE_URL").replace(/\/+$/, "");
const ANON_KEY = envValue(
  "NEXT_PUBLIC_SUPABASE_ANON_KEY",
  "NEXT_PUBLIC_SUPABASE_KEY",
  "SUPABASE_ANON_KEY",
  "SUPABASE_PUBLISHABLE_KEY",
  "SUPABASE_KEY"
);
const SERVICE_ROLE = envValue("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_KEY");
/** User E2E tetap (opsional). Dikosongkan -> `_e2e_user.json` yang dipakai. */
const E2E_EMAIL = envValue("E2E_USER_EMAIL");
const E2E_PASS = envValue("E2E_USER_PASSWORD");

const REF = SUPABASE_URL.match(/https?:\/\/([a-z0-9]+)\.supabase/)?.[1];
const LS_KEY = `sb-${REF ?? "unknown"}-auth-token`;

/** Kredensial user E2E tetap hasil pembuatan (gitignored, TIDAK di-commit). */
const USER_FILE = "_e2e_user.json";
/**
 * Kandidat fixture yang boleh dipakai ulang — dari paling baru ke paling lama.
 * `_e2e_session.extended.json` SENGAJA TIDAK ADA di sini: isinya token yang
 * klaim `exp`-nya disunting tanpa tanda tangan baru (lihat docstring).
 */
const CANDIDATES = ["_e2e_session.refreshed.json", "_e2e_session.json"];
/** Fixture token palsu yang dikenal — di-rename agar tidak menyusup lagi. */
const FORGED_FILES = ["_e2e_session.extended.json"];
/** Cache JWKS lokal (ditanam `security.py`); cwd = nexus-frontend. */
const JWKS_PATHS = [".jwks_cache.json", "../.jwks_cache.json"];

/** Dekode segmen JWT base64url -> objek (null bila rusak). */
function b64urlJson(seg) {
  try {
    return JSON.parse(Buffer.from(seg, "base64url").toString("utf-8"));
  } catch {
    return null;
  }
}

/** Sisa umur token dari klaim `exp` (detik); -1 bila token tidak terbaca. */
function ttl(token) {
  const p = b64urlJson(String(token || "").split(".")[1] ?? "");
  return typeof p?.exp === "number" ? p.exp - Math.floor(Date.now() / 1000) : -1;
}

/** Baca sesi fixture; null bila hilang/rusak/tanpa `access_token`. */
function readSession(file) {
  const p = join(ROOT, file);
  if (!existsSync(p)) return null;
  try {
    const s = JSON.parse(readFileSync(p, "utf-8"));
    return s?.access_token ? s : null;
  } catch {
    return null;
  }
}
/**
 * Sumber kunci publik proyek, dari yang paling murah: env `SUPABASE_JWKS`
 * (ditanam `security.py`), cache disk, lalu unduhan jaringan. Beberapa sumber
 * dikumpulkan sekaligus supaya token hasil rotasi kunci tetap bisa diverifikasi
 * walau salah satu sumber basi.
 */
async function jwksSources() {
  const out = [];
  const fromEnv = (envValue("SUPABASE_JWKS") || "").trim();
  if (fromEnv) {
    try {
      out.push({ src: "env SUPABASE_JWKS", doc: JSON.parse(fromEnv) });
    } catch {
      console.log("[e2e-auth] SUPABASE_JWKS di env bukan JSON valid -> diabaikan");
    }
  }
  for (const rel of JWKS_PATHS) {
    const p = join(ROOT, rel);
    if (!existsSync(p)) continue;
    try {
      out.push({ src: rel, doc: JSON.parse(readFileSync(p, "utf-8")) });
    } catch {
      /* cache rusak -> diabaikan */
    }
  }
  if (SUPABASE_URL) {
    try {
      const r = await fetch(`${SUPABASE_URL}/auth/v1/.well-known/jwks.json`, {
        signal: AbortSignal.timeout(15000),
      });
      if (r.ok) out.push({ src: "https /auth/v1/.well-known/jwks.json", doc: await r.json() });
      else console.log(`[e2e-auth] unduh JWKS HTTP ${r.status}`);
    } catch (e) {
      console.log(`[e2e-auth] unduh JWKS gagal: ${String(e)}`);
    }
  }
  return out;
}

/** Digest SHA per algoritma JWS yang didukung. */
const DIGEST = {
  ES256: "sha256",
  ES384: "sha384",
  ES512: "sha512",
  RS256: "sha256",
  RS384: "sha384",
  RS512: "sha512",
};

/**
 * Verifikasi SIGNATURE token terhadap JWKS proyek — inti perbaikan ini.
 *
 * Dulu fixture hanya diperiksa UMURNYA, sehingga token yang klaim `exp`-nya
 * disunting (`_e2e_extend.py`) lolos dan dipakai seluruh spec; backend menolak
 * token itu dan gejalanya terbaca sebagai bug produk.
 *
 * Return `{ ok, reason }`. Bila `ok:false` dengan reason menyebut "tidak
 * tersedia" artinya TIDAK BISA dibuktikan (bukan berarti sah): pemakaian ulang
 * fixture tetap DITOLAK, sedangkan token hasil mint GoTrue boleh dilanjutkan.
 */
async function checkSignature(token, sources) {
  const parts = String(token || "").split(".");
  if (parts.length !== 3) return { ok: false, reason: "bukan JWT 3-segmen" };
  const header = b64urlJson(parts[0]) ?? {};
  const alg = String(header.alg || "");
  const kid = header.kid;
  const all = sources.flatMap((s) => (s.doc?.keys ?? []).map((k) => ({ ...k, _src: s.src })));
  if (!all.length) return { ok: false, reason: "tidak tersedia (JWKS tidak ada di env/cache/jaringan)" };
  const pool = kid ? all.filter((k) => k.kid === kid) : all;
  if (!pool.length) return { ok: false, reason: `JWKS tidak memuat kid ${kid}` };
  const digest = DIGEST[alg];
  if (!digest) return { ok: false, reason: `algoritma ${alg || "(kosong)"} tidak didukung` };
  const data = Buffer.from(`${parts[0]}.${parts[1]}`);
  const sig = Buffer.from(parts[2], "base64url");
  for (const jwk of pool) {
    try {
      const key = createPublicKey({ key: jwk, format: "jwk" });
      // ES* memakai signature JWS mentah (R||S), bukan DER -> ieee-p1363.
      const params = alg.startsWith("ES") ? { key, dsaEncoding: "ieee-p1363" } : key;
      if (verifyRaw(digest, data, params, sig)) return { ok: true, reason: `${alg} cocok (${jwk._src})` };
    } catch {
      /* bentuk kunci tak terduga -> coba kandidat berikutnya */
    }
  }
  return { ok: false, reason: `signature TIDAK cocok dengan kunci kid ${kid ?? "(kosong)"}` };
}
/** Panggilan POST ke GoTrue. `bearer` diisi service role untuk endpoint admin. */
async function postAuth(path, body, bearer) {
  if (!SUPABASE_URL) return { status: 0, json: null };
  const key = bearer || ANON_KEY || SERVICE_ROLE;
  try {
    const r = await fetch(`${SUPABASE_URL}${path}`, {
      method: "POST",
      headers: { apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(AUTH_TIMEOUT_MS),
    });
    const json = await r.json().catch(() => null);
    return { status: r.status, json };
  } catch (e) {
    return { status: 0, json: null, err: String(e) };
  }
}

/** Normalisasi sesi GoTrue -> bentuk yang dibaca auth-js. */
function normalizeSession(json) {
  const s = { ...json };
  // GoTrue mengirim `expires_in` (detik); auth-js memerlukan `expires_at`
  // (epoch) agar `_isValidSession()` menganggap sesi hidup.
  if (!s.expires_at && s.expires_in) s.expires_at = Math.floor(Date.now() / 1000) + Number(s.expires_in);
  return s;
}

/** Tukar `refresh_token` -> sesi baru; tanda tangan datang dari Supabase. */
async function mintViaRefresh(refreshToken) {
  if (!refreshToken || !SUPABASE_URL || !ANON_KEY) return null;
  const { status, json, err } = await postAuth("/auth/v1/token?grant_type=refresh_token", {
    refresh_token: refreshToken,
  });
  if (status !== 200 || !json?.access_token) {
    console.log(`[e2e-auth] refresh ditolak HTTP ${status}${err ? ` (${err})` : ""}`);
    return null;
  }
  return normalizeSession(json);
}

/** Login email/password (grant_type=password) -> access_token asli. */
async function mintViaPassword(email, password) {
  if (!email || !password || !SUPABASE_URL || !ANON_KEY) return null;
  const { status, json, err } = await postAuth("/auth/v1/token?grant_type=password", { email, password });
  if (status !== 200 || !json?.access_token) {
    console.log(`[e2e-auth] signIn ${email} gagal HTTP ${status}${err ? ` (${err})` : ""}`);
    return null;
  }
  return normalizeSession(json);
}

/** Buat user E2E lewat admin API (butuh service role key). */
async function adminCreateUser(email, password) {
  if (!SERVICE_ROLE || !SUPABASE_URL) return false;
  const { status, json } = await postAuth(
    "/auth/v1/admin/users",
    { email, password, email_confirm: true },
    SERVICE_ROLE
  );
  if (status === 200) return true;
  // Sudah terdaftar -> pakai user yang ada (422 "User already registered").
  if (/already|exist/i.test(JSON.stringify(json ?? {}))) return true;
  console.log(`[e2e-auth] admin createUser HTTP ${status}: ${JSON.stringify(json ?? {}).slice(0, 160)}`);
  return false;
}

/** Kredensial user E2E tetap yang tersimpan lokal (gitignored). */
function savedUser() {
  const p = join(ROOT, USER_FILE);
  if (!existsSync(p)) return null;
  try {
    const u = JSON.parse(readFileSync(p, "utf-8"));
    return u?.email && u?.password ? u : null;
  } catch {
    return null;
  }
}

/** Tulis fixture yang dibaca spec + storageState untuk spec lain. */
function writeOutputs(session) {
  writeFileSync(join(ROOT, "_e2e_session.refreshed.json"), JSON.stringify(session, null, 2));
  writeFileSync(
    join(ROOT, "_e2e_storage.json"),
    JSON.stringify(
      {
        cookies: [],
        origins: [{ origin: ORIGIN, localStorage: [{ name: LS_KEY, value: JSON.stringify(session) }] }],
      },
      null,
      2
    )
  );
}
export default async function globalSetup() {
  console.log(`[e2e-auth] ref=${REF ?? "?"} key=${LS_KEY} origin=${ORIGIN}`);

  // 0) Buang fixture token palsu yang dikenal (klaim `exp` disunting tanpa
  //    tanda tangan baru). Di-rename, bukan dihapus, agar jejaknya tetap
  //    terlihat dan tidak menyusup ke sesi berikutnya.
  for (const f of FORGED_FILES) {
    const p = join(ROOT, f);
    if (!existsSync(p)) continue;
    const renamed = f.replace(/\.json$/, ".FORGED.json");
    try {
      renameSync(p, join(ROOT, renamed));
      console.log(`[e2e-auth] DIBUANG ${f} -> ${renamed} (token palsu: exp disunting tanpa tanda tangan baru)`);
    } catch (e) {
      console.log(`[e2e-auth] gagal membuang ${f}: ${String(e)}`);
    }
  }

  const sources = await jwksSources();
  console.log(`[e2e-auth] sumber JWKS: ${sources.map((s) => s.src).join(" | ") || "(tidak ada)"}`);

  let chosen = null;
  let source = null;
  let minted = false;

  // 1) Fixture yang SAH = signature terverifikasi + sisa umur cukup. Ini jalur
  //    termurah dan menghindari pemakaian refresh token (rotasi di Supabase).
  const refreshable = [];
  for (const f of CANDIDATES) {
    const s = readSession(f);
    if (!s) continue;
    if (s.refresh_token) refreshable.push({ f, s });
    const v = await checkSignature(s.access_token, sources);
    if (!v.ok) {
      console.log(`[e2e-auth] TOLAK ${f}: ${v.reason}`);
      continue;
    }
    const t = ttl(s.access_token);
    if (t > MIN_TTL_S) {
      chosen = s;
      source = `${f} (terverifikasi: ${v.reason}; ttl=${t}s)`;
      break;
    }
    console.log(`[e2e-auth] ${f} terverifikasi tapi kedaluwarsa (ttl=${t}s)`);
  }

  // 2) Tukar refresh_token. `refresh_token` GoTrue bersifat opaque dan
  //    diverifikasi di sisi server, jadi tetap boleh dipakai walau
  //    access_token-nya terbukti tidak sah (fixture hasil sunting).
  if (!chosen) {
    for (const { f, s } of refreshable) {
      const fresh = await mintViaRefresh(s.refresh_token);
      if (fresh) {
        chosen = fresh;
        minted = true;
        source = `${f} (hasil refresh; ttl=${ttl(fresh.access_token)}s)`;
        break;
      }
    }
  }

  // 3) Login user E2E tetap (dari env atau `_e2e_user.json`).
  if (!chosen) {
    const u = savedUser();
    const email = E2E_EMAIL || u?.email || "";
    const pass = E2E_PASS || u?.password || "";
    const sess = await mintViaPassword(email, pass);
    if (sess) {
      chosen = sess;
      minted = true;
      source = `signInWithPassword ${email} (ttl=${ttl(sess.access_token)}s)`;
    }
  }

  // 4) Belum ada juga -> buat user E2E lewat admin API (service role) lalu login.
  if (!chosen && SERVICE_ROLE) {
    const u = savedUser();
    const email = E2E_EMAIL || u?.email || `e2e.${Date.now()}@nexus-local.test`;
    const pass = E2E_PASS || u?.password || `E2e!Xy9#Pass-${Date.now()}`;
    if (await adminCreateUser(email, pass)) {
      const sess = await mintViaPassword(email, pass);
      if (sess) {
        chosen = sess;
        minted = true;
        source = `admin.createUser + signInWithPassword ${email} (ttl=${ttl(sess.access_token)}s)`;
        if (!u || u.email !== email || u.password !== pass) {
          writeFileSync(join(ROOT, USER_FILE), JSON.stringify({ email, password: pass }, null, 2));
        }
      }
    }
  }

  if (!chosen) {
    console.log(
      "[e2e-auth] PERINGATAN: tidak ada sesi E2E yang sah. Spec yang butuh auth akan gagal pada guard TTL-nya " +
        "(bukan crash di sini). Isi E2E_USER_EMAIL/E2E_USER_PASSWORD atau SUPABASE_SERVICE_ROLE_KEY di .env."
    );
    return;
  }

  // Guard terakhir: token hasil mint GoTrue WAJIB terverifikasi. Bila signature
  // TIDAK cocok, fixture TIDAK ditulis — menulisnya persis kesalahan yang
  // diperbaiki di sesi ini (spec gagal dengan sebab yang menyesatkan).
  const v = await checkSignature(chosen.access_token, sources);
  if (!v.ok) {
    if (minted && /tidak tersedia/.test(v.reason)) {
      console.log(
        `[e2e-auth] PERINGATAN: signature tidak dapat dibuktikan sekarang (${v.reason}); token berasal langsung dari GoTrue, dilanjutkan.`
      );
    } else {
      console.log(`[e2e-auth] GAGAL: ${v.reason} -> fixture TIDAK ditulis.`);
      return;
    }
  } else {
    console.log(`[e2e-auth] verifikasi akhir OK: ${v.reason}`);
  }

  writeOutputs(chosen);
  console.log(`[e2e-auth] siap: ${source}`);
  console.log(
    `[e2e-auth] email=${chosen.user?.email ?? "?"} -> _e2e_session.refreshed.json + _e2e_storage.json`
  );
}
