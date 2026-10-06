/**
 * Bukti BROWSER: node MCP dari backend benar-benar sampai ke UI.
 *
 * KENAPA SPEC INI ADA
 * -------------------
 * Verifikasi MCP 6 Okt 2026 menemukan: `POST /chat` bisa memulangkan workflow
 * ber-node `kind="mcp"`, tetapi TIDAK ADA bukti browser bahwa node itu dirender
 * dan bahwa tool MCP yang dipilih terbaca user. "Backend memulangkan JSON" dan
 * "user melihat node MCP di kanvas" adalah dua klaim berbeda.
 *
 * Rantai yang diuji di sini:
 *   POST /chat -> meta.workflow (2 node, 1 mcp)
 *   -> useChat menyimpannya -> thread.tsx merender <WorkflowDraftCard>
 *   -> kartu melaporkan "1 integrasi" (hitungan node kind=mcp)
 *   -> "Buka di Kanvas" memuat draf dari localStorage ke /builder
 *   -> kanvas menampilkan node MCP
 *
 * Yang di-stub HANYA jawaban backend (`page.route`), pola yang sama dengan
 * `approval-card.spec.ts`: tidak butuh database, backend, maupun akun asli.
 * Karena itu spec ini bisa menembak build lokal MAUPUN situs yang sudah
 * di-deploy (`E2E_BASE_URL`).
 */
import { test, expect, type Page, type Route, type Request } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const SHOTS = join(process.cwd(), "..", "docs", "marketing", "screenshots");
const SHOT = process.env.E2E_SHOT_PREFIX || "mcp-workflow";
const shot = (name: string) => join(SHOTS, `${SHOT}-${name}.png`);

const ONB_KEY = "katalir.onboarding.v1";
const LOCALE_KEY = "katalir.locale.v1";

/** Nama tool MCP NYATA dari katalog agentgateway (44 tool live). */
const MCP_TOOL = "everything_echo";
const WF_NAME = "MCP Echo Harian";

/**
 * Payload `meta.workflow` persis seperti yang dipulangkan backend.
 *
 * `config` hanya boleh string/number/boolean (`parseAgentWorkflow` membuang
 * objek bersarang), jadi argumen tool dikirim sebagai JSON STRING — sama
 * dengan yang dihasilkan `generate_workflow_json`.
 */
function mcpWorkflow() {
  return {
    name: WF_NAME,
    nodes: [
      {
        id: "trigger-1",
        type: "trigger",
        position: { x: 0, y: 0 },
        data: { kind: "trigger", label: "Manual Trigger", config: { type: "manual" } },
      },
      {
        id: "mcp-1",
        type: "mcp",
        position: { x: 280, y: 0 },
        data: {
          kind: "mcp",
          label: "MCP Echo",
          config: {
            provider: "gateway",
            tool: MCP_TOOL,
            arguments: JSON.stringify({ message: "hello dari workflow" }),
          },
        },
      },
    ],
    edges: [{ id: "e1", source: "trigger-1", target: "mcp-1" }],
  };
}

function supabaseRef(): string {
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(
      /NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/,
    );
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

/** Sesi DUMMY (bukan kredensial asli): hanya memenuhi cek "ada sesi?" di klien. */
function dummySession() {
  const b64 = (o: unknown) =>
    Buffer.from(JSON.stringify(o)).toString("base64")
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const now = Math.floor(Date.now() / 1000);
  return {
    access_token: `${b64({ alg: "HS256", typ: "JWT" })}.${b64({
      sub: "00000000-0000-0000-0000-000000000001",
      aud: "authenticated", role: "authenticated",
      exp: now + 60 * 60 * 24 * 365, iat: now,
      email: "e2e-mcp@local.test", user_metadata: {},
    })}.local-tests-only`,
    token_type: "bearer",
    expires_in: 60 * 60 * 24 * 365,
    expires_at: now + 60 * 60 * 24 * 365,
    refresh_token: "local-tests-only",
    user: { id: "00000000-0000-0000-0000-000000000001", email: "e2e-mcp@local.test" },
  };
}

async function seed(page: Page) {
  const real = join(process.cwd(), "_e2e_session.refreshed.json");
  const sess = existsSync(real) ? JSON.parse(readFileSync(real, "utf-8")) : dummySession();
  const entries: [string, string][] = [
    [LOCALE_KEY, "id"],
    [ONB_KEY, "done"],
    [`sb-${supabaseRef()}-auth-token`, JSON.stringify(sess)],
  ];
  await page.addInitScript((kv: [string, string][]) => {
    for (const [k, v] of kv) { try { window.localStorage.setItem(k, v); } catch { /* abaikan */ } }
  }, entries);
}

function isApi(req: Request): boolean {
  return /^\/(chat|sessions|workflows|executions|preferences|api\/vault)/.test(
    new URL(req.url()).pathname,
  );
}

/** Stub backend: hanya jawaban yang dibutuhkan rantai render MCP. */
async function stubApi(page: Page) {
  await page.route("**/*", async (route: Route) => {
    const req = route.request();
    if (!isApi(req)) return route.continue();
    const path = new URL(req.url()).pathname;
    const json = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (path === "/sessions") return json(200, { sessions: [] });
    if (path === "/workflows" && req.method() === "GET") return json(200, { workflows: [] });
    if (path === "/executions") return json(200, { executions: [] });
    if (path === "/preferences") return json(200, { preferences: {} });

    if (path === "/chat" && req.method() === "POST") {
      return json(200, {
        status: "success",
        reply: `Workflow **${WF_NAME}** dibuat: trigger manual lalu node MCP \`${MCP_TOOL}\`.`,
        session_id: "sess-stub",
        meta: { model: "gemini-3.5-flash-lite", workflow: mcpWorkflow() },
      });
    }
    // WAJIB `continue`, bukan fulfill: `page.route("**/*")` juga menangkap
    // NAVIGASI DOKUMEN ke `/chat` (path-nya cocok dengan isApi). Mem-fulfill
    // dengan JSON membuat browser merender "{}" sebagai halaman — run pertama
    // gagal persis karena itu. Pola yang sama dipakai approval-card.spec.ts.
    return route.continue();
  });
}
test("node MCP dari backend dirender di UI dan termuat ke kanvas", async ({ page }) => {
  test.setTimeout(180000);
  mkdirSync(SHOTS, { recursive: true });
  await seed(page);
  await stubApi(page);

  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  // Tunggu elemen yang benar-benar dipakai, bukan penanda hidrasi di <html>:
  // `waitForSelector` default-nya menuntut elemen VISIBLE, dan <html> tidak
  // pernah memenuhi itu (run pertama gagal di sini).
  await page.getByTestId("composer-input").waitFor({ state: "visible", timeout: 60000 });
  await page.waitForTimeout(1500);

  await page.getByTestId("composer-input").fill(
    "Buat workflow: trigger manual lalu panggil MCP tool everything_echo",
  );
  await page.getByTestId("composer-send").click();

  // 1) Kartu draf muncul dengan hitungan node yang benar.
  const card = page.getByTestId("workflow-draft-card").last();
  await expect(card).toBeVisible({ timeout: 30000 });
  expect(await card.getAttribute("data-nodes")).toBe("2");
  expect(await card.getAttribute("data-edges")).toBe("1");
  await expect(card.getByTestId("draft-name")).toContainText(WF_NAME);

  // 2) Hitungan "integrasi" = jumlah node kind=mcp -> bukti node MCP terbaca.
  const counts = await card.getByTestId("draft-counts").innerText();
  console.log("DRAFT_COUNTS=" + counts);
  expect(counts).toMatch(/1 integrasi/);

  await page.screenshot({ path: shot("draft-card"), fullPage: true });

  // 3) "Buka di Kanvas" -> draf dimuat dari localStorage ke /builder.
  await card.getByTestId("draft-open-canvas").click();
  await page.waitForSelector(".react-flow", { timeout: 60000 });
  await page.waitForTimeout(4000);

  // 4) Kanvas benar-benar memuat node MCP (bukan kanvas kosong).
  const mcpNodes = page.locator('.react-flow__node[data-id="mcp-1"]');
  const anyNode = page.locator(".react-flow__node");
  console.log("CANVAS_NODES=" + (await anyNode.count()));
  await expect(anyNode.first()).toBeVisible({ timeout: 30000 });
  expect(await mcpNodes.count(), "node MCP tidak ada di kanvas").toBe(1);

  const canvasText = await page.locator(".react-flow").first().innerText();
  console.log("CANVAS_TEXT_HAS_TOOL=" + canvasText.includes(MCP_TOOL));
  expect(canvasText).toContain(MCP_TOOL);

  // Rapikan posisi node supaya screenshot menampilkan node MCP sepenuhnya
  // (tanpa ini node berada di luar area pandang dan screenshot hanya
  // memperlihatkan kanvas kosong).
  const autoLayout = page.getByRole("button", { name: /Auto\s*Layout/i }).first();
  if (await autoLayout.count()) {
    await autoLayout.click({ timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(2500);
  }

  await page.screenshot({ path: shot("canvas-node"), fullPage: true });
});
