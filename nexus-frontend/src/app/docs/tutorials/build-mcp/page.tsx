/**
 * Tutorial: "Build an MCP tool for Katalir".
 *
 * Every code block below is transcribed from the real `mcp_gateway/` package
 * rather than written from imagination — the snippets came from
 * mcp_gateway/katalir_server.py. That file is the source of truth; if it
 * changes and this page does not, the page is wrong, so it is deliberately
 * short and points back at the source.
 *
 * Bilingual ID/EN per the project rule: the Indonesian text is written as
 * natural Indonesian, not a literal translation of the English.
 */

const FILES = [
  { path: "mcp_gateway/katalir_server.py", note: "MCP server (stdio). Tools: list_workflows, run_workflow." },
  { path: "mcp_gateway/client.py", note: "Typed client for the Katalir HTTP API." },
  { path: "mcp_gateway/policy.py", note: "Policy checks applied before a tool may run." },
  { path: "tests/test_mcp_gateway/", note: "test_client.py + test_policy.py — required for a submission." },
];

const SHAPE = `from mcp.server.fastmcp import FastMCP
import api_server

mcp = FastMCP("katalir-workflows")

def _auth() -> str:
    token = os.environ.get("KATALIR_JWT", "").strip()
    if not token:
        raise RuntimeError("KATALIR_JWT wajib untuk workflow owner-scoped")
    return f"Bearer {token}"

@mcp.tool()
def list_workflows() -> list[dict[str, Any]]:
    user = api_server.security.get_current_user(_auth())
    return api_server._mcp_workflow_tools(str(user["id"]))`;

const RUN = `@mcp.tool()
def run_workflow(tool: str) -> dict[str, Any]:
    user = api_server.security.get_current_user(_auth())
    row = next((r for r in (api_server.db.list_workflows(str(user["id"])) or [])
                if api_server._mcp_workflow_tool_name(r.get("name"), str(r.get("id"))) == tool), None)
    if row is None:
        raise ValueError("workflow not found")
    detail = api_server.db.get_workflow(str(row["id"]), str(user["id"]))
    if not detail:
        raise ValueError("workflow not found")
    execution_id = api_server.engine.launch_execution(
        str(row["id"]), detail.get("flow_data") or {},
        owner_email=str(user.get("email") or ""))
    return {"execution_id": execution_id, "workflow_id": str(row["id"]), "status": "pending"}`;

const STEPS = [
  {
    n: "1",
    id: "Pahami bentuk sebuah tool",
    en: "Understand the tool shape",
    body: "Sebuah tool Katalir adalah fungsi Python biasa dengan dekorator @mcp.tool(). Nama fungsi MENJADI nama tool yang dilihat agent, jadi beri nama sesuai apa yang dikerjakan, bukan cara kerjanya.",
  },
  {
    n: "2",
    id: "Selalu ambil owner dari token",
    en: "Always resolve the owner from the token",
    body: "Jangan pernah menerima user id, email, atau workflow id sebagai parameter lalu mempercayanya. Panggil get_current_user(_auth()) dan batasi semua query ke id itu. Aturan inilah yang membuat workflow satu user tidak terlihat oleh user lain.",
  },
  {
    n: "3",
    id: "Kembalikan nilai yang sederhana",
    en: "Return something small and predictable",
    body: "Kembalikan dict biasa atau list of dict. Untuk aksi yang berjalan lama, kembalikan execution id dan status:'pending' alih-alih memblokir — agent tidak bisa menahan panggilan tool selamanya.",
  },
  {
    n: "4",
    id: "Uji sebelum submit",
    en: "Test before submitting",
    body: "Tambahkan test di tests/test_mcp_gateway/ bersama test yang sudah ada. Tool tanpa test tidak akan di-merge, dan perbaikan bug tanpa test gagal yang membuktikan bug itu juga tidak akan di-merge.",
  },
];

export default function BuildMcpTutorialPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-12">
      <h1 className="text-title1">Build an MCP tool for Katalir</h1>
      <p className="mt-2 text-body text-fg-muted">
        <strong>EN</strong> — A short, practical guide to adding a tool to the Katalir
        MCP server. <strong>ID</strong> — Panduan singkat dan praktis untuk menambahkan
        tool ke MCP server Katalir.
      </p>

      <h2 className="mt-10 text-title3">1. The shape of a tool / Bentuk sebuah tool</h2>
      <p className="mt-2 text-callout text-fg-muted">
        <strong>EN</strong> — Transcribed from <code>mcp_gateway/katalir_server.py</code>.{" "}
        <strong>ID</strong> — Disalin dari <code>mcp_gateway/katalir_server.py</code>.
      </p>
      <pre className="mt-3 overflow-x-auto rounded-lg border border-border bg-bg-subtle p-4 text-footnote">
        <code>{SHAPE}</code>
      </pre>

      <h2 className="mt-10 text-title3">2. Running a workflow / Menjalankan workflow</h2>
      <p className="mt-2 text-callout text-fg-muted">
        <strong>EN</strong> — Note the scoping: the row is found by matching the tool name,
        then re-fetched through <code>get_workflow(id, owner)</code>. The name match alone is
        never treated as proof of ownership.{" "}
        <strong>ID</strong> — Perhatikan scoping-nya: baris dicari berdasarkan nama tool,
        lalu diambil ulang lewat <code>get_workflow(id, owner)</code>. Kecocokan nama saja
        tidak pernah dianggap sebagai bukti kepemilikan.
      </p>
      <pre className="mt-3 overflow-x-auto rounded-lg border border-border bg-bg-subtle p-4 text-footnote">
        <code>{RUN}</code>
      </pre>

      <h2 className="mt-10 text-title3">3. Steps / Langkah</h2>
      <ol className="mt-3 grid gap-4">
        {STEPS.map((s) => (
          <li key={s.n} className="rounded-lg border border-border p-4">
            <p className="font-medium text-subhead">
              {s.n}. {s.id}
            </p>
            <p className="text-footnote text-fg-muted">{s.en}</p>
            <p className="mt-2 text-callout">{s.body}</p>
          </li>
        ))}
      </ol>

      <h2 className="mt-10 text-title3">4. Where things live / Letak berkas</h2>
      <ul className="mt-3 grid gap-2">
        {FILES.map((f) => (
          <li key={f.path} className="text-callout">
            <code className="font-mono">{f.path}</code>
            <span className="text-fg-muted"> — {f.note}</span>
          </li>
        ))}
      </ul>

      <h2 className="mt-10 text-title3">5. Submitting / Mengirim</h2>
      <p className="mt-2 text-callout text-fg-muted">
        <strong>EN</strong> — Open a PR with the tool, its tests, and a short note on what
        it does. Original work only. Scope agreed before you start.{" "}
        <strong>ID</strong> — Buka PR berisi tool, test-nya, dan catatan singkat tentang
        apa yang dikerjakannya. Karya orisinal saja. Scope disepakati sebelum mulai.
      </p>
    </main>
  );
}
