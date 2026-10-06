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
 * 44 nama tool MCP hasil `GET /mcp/gateway/servers` di produksi.
 * Di-hardcode supaya spec deterministik (tidak bergantung gateway hidup) dan
 * sekaligus mengunci bahwa UI memang menampilkan katalog sebesar itu.
 */
const GATEWAY_TOOLS = [
  "everything_echo", "everything_get-annotated-message", "everything_get-env",
  "everything_get-resource-links", "everything_get-resource-reference",
  "everything_get-structured-content", "everything_get-sum",
  "everything_get-tiny-image", "everything_gzip-file-as-resource",
  "everything_toggle-simulated-logging", "everything_toggle-subscriber-updates",
  "everything_trigger-long-running-operation", "everything_simulate-research-query",
  "fetch_fetch", "memory_create_entities", "memory_create_relations",
  "memory_add_observations", "memory_delete_entities", "memory_delete_observations",
  "memory_delete_relations", "memory_read_graph", "memory_search_nodes",
  "memory_open_nodes", "filesystem_read_file", "filesystem_read_text_file",
  "filesystem_read_media_file", "filesystem_read_multiple_files",
  "filesystem_write_file", "filesystem_edit_file", "filesystem_create_directory",
  "filesystem_list_directory", "filesystem_list_directory_with_sizes",
  "filesystem_directory_tree", "filesystem_move_file", "filesystem_search_files",
  "filesystem_get_file_info", "filesystem_list_allowed_directories",
  "time_get_current_time", "time_convert_time", "openconnector_list_apps",
  "openconnector_list_connections", "openconnector_search_actions",
  "openconnector_get_action_guide", "openconnector_execute_action",
];

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
  // `/mcp/...` WAJIB ikut: endpoint katalog tool gateway ada di prefix itu.
  // Tanpa ini, fetch katalog lolos ke backend SUNGGUHAN
  // (`NEXT_PUBLIC_API_URL` di-bake saat build) dan dijawab 401 -> panel
  // menampilkan state error, bukan daftar tool (kegagalan run pertama).
  return /^\/(chat|sessions|workflows|executions|preferences|api\/vault|mcp)/.test(
    new URL(req.url()).pathname,
  );
}

/** Stub backend: hanya jawaban yang dibutuhkan rantai render MCP. */
type Captured = { savedFlow?: { nodes?: Array<{ id: string; data?: { config?: Record<string, string> } }> } };

async function stubApi(page: Page, captured: Captured = {}) {
  await page.route("**/*", async (route: Route) => {
    const req = route.request();
    if (!isApi(req)) return route.continue();
    const path = new URL(req.url()).pathname;
    const json = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (path === "/sessions") return json(200, { sessions: [] });
    if (path === "/workflows" && req.method() === "GET") return json(200, { workflows: [] });
    if (path === "/workflows" && req.method() === "POST") {
      // Simpan payload apa adanya supaya test bisa MEMBUKTIKAN config yang
      // benar-benar dikirim klien (bukan sekadar teks di layar).
      const body = JSON.parse(req.postData() || "{}") as { flow_data?: Captured["savedFlow"] };
      captured.savedFlow = body.flow_data ?? {};
      return json(201, { workflow: { id: "wf-stub" }, updated: false });
    }
    if (path === "/executions") return json(200, { executions: [] });
    if (path === "/preferences") return json(200, { preferences: {} });

    // Katalog tool MCP gateway — endpoint NYATA (bukan /mcp/gateway/tools).
    if (path === "/mcp/gateway/servers" && req.method() === "GET") {
      return json(200, {
        tools: GATEWAY_TOOLS.map((name) => ({
          name,
          title: name,
          description: `Tool MCP ${name}`,
          inputSchema: { type: "object", properties: {} },
        })),
      });
    }

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

/**
 * Pemilih tool MCP: katalog gateway harus muncul di ConfigPanel dan memilih
 * sebuah tool harus MENGARAHKAN node ke jalur gateway (`provider=gateway`).
 *
 * Sebelum perbaikan, `<select>` di ConfigPanel hanya berisi DUA opsi hardcoded
 * (`web_search`, `http_request`) sehingga 44 tool MCP yang benar-benar hidup di
 * produksi tidak bisa dipilih user sama sekali.
 */
test("pemilih tool MCP menampilkan katalog gateway dan menyetel provider=gateway", async ({ page }) => {
  test.setTimeout(180000);
  mkdirSync(SHOTS, { recursive: true });

  // Draf dimuat langsung dari localStorage supaya test ini tidak bergantung
  // pada alur /chat (fokusnya panel konfigurasi).
  await page.addInitScript(
    (kv: { onb: string; locale: string; pending: string }) => {
      try {
        window.localStorage.setItem("katalir.onboarding.v1", kv.onb);
        window.localStorage.setItem("katalir.locale.v1", kv.locale);
        window.localStorage.setItem("katalir.workflow.pending.v1", kv.pending);
      } catch { /* abaikan */ }
    },
    { onb: "done", locale: "id", pending: JSON.stringify(mcpWorkflow()) },
  );
  await seed(page);
  await stubApi(page);

  await page.goto("/builder", { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".react-flow", { timeout: 60000 });
  await page.waitForTimeout(4000);

  // Pilih node MCP -> ConfigPanel terbuka.
  await page.locator('.react-flow__node[data-id="mcp-1"]').first().click();

  // ConfigPanel dirender DUA kali (aside desktop `lg:flex` + Sheet mobile),
  // jadi semua pencarian di-scope ke aside supaya tidak kena strict mode.
  const panel = page.getByTestId("config-aside");
  await expect(panel).toBeVisible({ timeout: 30000 });
  const select = panel.getByTestId("mcp-tool-select");
  await expect(select).toBeVisible({ timeout: 30000 });

  // 1) Katalog dimuat dari endpoint gateway (bukan daftar hardcoded).
  await expect(select).toHaveAttribute("data-gateway-tools", String(GATEWAY_TOOLS.length));
  const gatewayOptions = select.locator('option[data-tool-source="gateway"]');
  const optionCount = await gatewayOptions.count();
  console.log("GATEWAY_OPTIONS=" + optionCount);
  expect(optionCount).toBe(GATEWAY_TOOLS.length);

  // 2) Tool MCP nyata ada di daftar.
  const values = await gatewayOptions.evaluateAll((os) =>
    os.map((o) => (o as HTMLOptionElement).value));
  expect(values).toContain(MCP_TOOL);
  console.log("SELECT_FIRST_5=" + JSON.stringify(values.slice(0, 5)));

  // 3) Memilih tool MCP mengarahkan node ke jalur gateway.
  await select.selectOption(MCP_TOOL);
  await page.waitForTimeout(600);
  await expect(select).toHaveValue(MCP_TOOL);

  await page.screenshot({ path: shot("tool-selector"), fullPage: true });

  // 4) BUKTI TERKUAT: payload yang benar-benar disimpan ke backend memuat
  //    provider=gateway + tool=everything_echo (dibaca dari POST /workflows).
  const captured: Captured = {};
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await stubApi(page, captured);
  await page.getByRole("button", { name: /Simpan Alur/i }).first().click();
  await page.waitForTimeout(3500);

  const mcpNode = (captured.savedFlow?.nodes ?? []).find((n) => n.id === "mcp-1");
  console.log("SAVED_MCP_CONFIG=" + JSON.stringify(mcpNode?.data?.config ?? null));
  expect(mcpNode, "node mcp tidak ada di payload simpan").toBeTruthy();
  expect(mcpNode!.data!.config!.provider).toBe("gateway");
  expect(mcpNode!.data!.config!.tool).toBe(MCP_TOOL);
});

