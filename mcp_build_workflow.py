"""MCP Build Workflow (fitur #2) — membangun workflow lewat MCP, ala n8n.

Konteks
-------
n8n menyediakan **instance-level MCP server** yang membolehkan aplikasi AI
(Claude, ChatGPT, Cursor, IDE) membangun dan memperbaiki workflow langsung di
dalam instance, tanpa copy-paste JSON. Yang membuatnya bekerja bukan sekadar
"ada MCP", melainkan **loop build** yang bisa diperiksa:

    get_workflow_sdk_reference  -> baca kontrak SDK
    search_nodes                -> temukan node
    get_node_types              -> ambil tipe persis node itu
    validate_workflow           -> WAJIB lulus sebelum menulis
    create_workflow_from_code   -> simpan
    test_workflow / execute     -> jalankan
    (gagal) -> baca error -> update_workflow -> ulangi

Modul ini memodelkan taksonomi + loop tersebut, plus gerbang protokol MCP
**2026-07-28** (stateless per-request envelope, `server/discover`,
`ttlMs`/`cacheScope`, header `Mcp-Method`/`Mcp-Name`).

Sumber kebenaran (dibaca dari docs resmi, bukan karangan):
  * https://docs.n8n.io/connect/connect-to-n8n-mcp-server/mcp-server-tools-reference
    — 53 tool dalam 7 kategori, masing-masing dengan gerbang versi n8n.
  * https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger
    — MCP Server Trigger: transport SSE + streamable HTTP, auth none/bearer/header.
  * https://modelcontextprotocol.io/specification/2026-07-28/changelog
    — revisi 2026-07-28: hapus `initialize` + `Mcp-Session-Id`, `server/discover`
    WAJIB, MRTR, `resultType`, caching list, header routing.
  * https://py.sdk.modelcontextprotocol.io/v2/migration/ — panduan migrasi SDK
    Python v1 -> v2 (FastMCP -> MCPServer).

Catatan desain penting
----------------------
Modul ini **TIDAK** memanggil jaringan dan tidak menyimpan workflow. Ia adalah
lapisan kebijakan/validasi yang menentukan: tool apa yang ada, versi n8n mana
yang mendukungnya, apakah suatu urutan panggilan sah, dan apakah sebuah
pesan/envelope sesuai revisi protokol yang diklaim klien.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

__all__ = [
    "PROTOCOL_REVISIONS", "MODERN_REVISIONS", "HANDSHAKE_REVISIONS",
    "LATEST_REVISION", "LATEST_MODERN_REVISION",
    "MODERN_REQUIRED_HEADERS", "ROUTING_HEADERS",
    "TOOL_CATEGORIES", "TOOLS", "TOOL_NAMES", "CATEGORY_OF",
    "BUILD_LOOP", "CREATE_GATE_TOOLS", "READ_ONLY_TOOLS",
    "SDK_SECTIONS", "REQUIRED_SDK_SECTION",
    "McpBuildError", "UnknownTool", "VersionTooOld", "ProtocolMismatch",
    "DiscoveryMissing", "BuildLoopViolation", "SessionHeaderForbidden",
    "BuildSession", "ToolCall", "tool_by_name", "tools_in_category",
    "tools_for_version", "require_tool", "parse_version",
    "tool_catalog", "build_reference", "check_envelope", "discover_payload",
    "reference_payload", "validate_discovery", "describe",
    "policy_from_env", "loop_state",
]


# ---------------------------------------------------------------------------
# 1. Revisi protokol MCP
# ---------------------------------------------------------------------------
# Urutan ini diambil dari registry SDK resmi (`mcp.types.version`), bukan
# ditebak: revisi berbentuk tanggal memang urut secara leksikografis, tetapi
# spesifikasi melarang memperlakukannya sebagai skalar yang bisa dibandingkan
# bebas.
PROTOCOL_REVISIONS: tuple[str, ...] = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
    "2026-07-28",
)

#: Revisi yang memakai amplop stateless per-request (tanpa `initialize`).
MODERN_REVISIONS: tuple[str, ...] = ("2026-07-28",)

#: Revisi yang masih memakai handshake `initialize`/`initialized`.
HANDSHAKE_REVISIONS: tuple[str, ...] = tuple(
    r for r in PROTOCOL_REVISIONS if r not in MODERN_REVISIONS)

LATEST_REVISION: str = PROTOCOL_REVISIONS[-1]
LATEST_MODERN_REVISION: str = MODERN_REVISIONS[-1]

#: Header routing WAJIB pada Streamable HTTP menurut revisi 2026-07-28.
#: Gunanya: gateway/WAF/limiter bisa merutekan tanpa mengurai badan JSON.
MODERN_REQUIRED_HEADERS: tuple[str, ...] = ("Mcp-Method", "Mcp-Name")

#: Semua header yang dikenali di jalur routing/negosiasi.
ROUTING_HEADERS: tuple[str, ...] = (
    "Mcp-Method", "Mcp-Name",
    "MCP-Protocol-Version",
)

#: Header sesi lama. Revisi 2026-07-28 MENGHAPUSNYA; menerimanya kembali
#: sebagai "berhasil" akan menyembunyikan ketidakcocokan.
REVOKED_SESSION_HEADER = "Mcp-Session-Id"

#: Kunci `_meta` pada amplop modern.
META_PREFIX = "io.modelcontextprotocol/"
META_PROTOCOL_VERSION = META_PREFIX + "protocolVersion"
META_CLIENT_INFO = META_PREFIX + "clientInfo"
META_CLIENT_CAPABILITIES = META_PREFIX + "clientCapabilities"
META_SERVER_INFO = META_PREFIX + "serverInfo"
META_LOG_LEVEL = META_PREFIX + "logLevel"

#: Metode yang WAJIB disediakan server modern (MUST, bukan opsional).
DISCOVER_METHOD = "server/discover"

#: `resultType` yang sah pada revisi 2026-07-28.
RESULT_TYPES: tuple[str, ...] = ("complete", "input_required")

#: Field freshness cache pada hasil list (SEP-2549).
CACHE_FIELDS: tuple[str, ...] = ("ttlMs", "cacheScope")
CACHE_SCOPES: tuple[str, ...] = ("public", "private")

#: Metode list yang hasilnya WAJIB membawa field cache.
CACHEABLE_LIST_METHODS: tuple[str, ...] = (
    "tools/list", "prompts/list", "resources/list",
    "resources/read", "resources/templates/list",
)

#: Kode galat yang dinomori ulang pada 2026-07-28.
RENUMBERED_ERRORS: dict[str, int] = {
    "HeaderMismatch": -32020,
    "MissingRequiredClientCapability": -32021,
    "UnsupportedProtocolVersion": -32022,
}

#: Rentang kode galat menurut revisi terbaru.
ERROR_RANGES: dict[str, tuple[int, int]] = {
    "implementation": (-32019, -32000),   # grandfathered
    "specification": (-32099, -32020),
}


# ---------------------------------------------------------------------------
# 2. Taksonomi tool n8n MCP
# ---------------------------------------------------------------------------
# `since` = versi n8n minimum yang menyediakan tool, dikutip langsung dari
# blok "Feature availability" di docs. Tidak ada tebakan: tool yang docs-nya
# tidak menyebut versi minimum tercatat `since=""` dan diperlakukan sebagai
# selalu-tersedia (n8n 2.12.0 adalah basis catatan ini).
@dataclass(frozen=True)
class ToolSpec:
    """Satu tool MCP yang diekspos server instance-level n8n."""

    name: str
    category: str
    since: str = ""                 # versi n8n minimum ("" = tanpa gerbang)
    mutating: bool = False          # mengubah state?
    requires_validation: bool = False  # butuh validate_workflow lebih dulu
    purpose: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "since": self.since,
            "mutating": self.mutating,
            "requires_validation": self.requires_validation,
            "purpose": self.purpose,
            "notes": self.notes,
        }


#: 7 kategori, persis seperti daftar isi docs.
TOOL_CATEGORIES: tuple[str, ...] = (
    "Workflow management",
    "Execution management",
    "Credential management",
    "Instance context",
    "Workflow builder",
    "Agent management",
    "Data tables",
)


def _specs() -> tuple[ToolSpec, ...]:
    """Bangun katalog 53 tool. Dipisah agar mudah diaudit per kategori."""
    out: list[ToolSpec] = []

    def add(name: str, category: str, since: str = "", mutating: bool = False,
            requires_validation: bool = False, purpose: str = "",
            notes: str = "") -> None:
        out.append(ToolSpec(name, category, since, mutating,
                            requires_validation, purpose, notes))

    WM = "Workflow management"
    # -- Workflow management (13) ------------------------------------------
    add("search_workflows", WM, since="2.12.0",
        purpose="cari workflow dengan filter",
        notes="filter tags sejak 2.27.0; folderId sejak 2.37.0")
    add("get_workflow_details", WM, since="2.12.0",
        purpose="detail satu workflow",
        notes="detailLevel sejak 2.35.0")
    add("execute_workflow", WM, since="2.12.0", mutating=True,
        purpose="jalankan workflow",
        notes="triggerNodeName sejak 2.36.0")
    add("test_workflow", WM, since="2.15.0", mutating=True,
        purpose="uji jalan tanpa produksi",
        notes="timeout sejak 2.33.0")
    add("prepare_workflow_pin_data", WM, since="2.15.0", mutating=True,
        purpose="siapkan data pin untuk uji")
    add("publish_workflow", WM, since="2.12.0", mutating=True,
        purpose="aktifkan versi produksi")
    add("unpublish_workflow", WM, since="2.12.0", mutating=True,
        purpose="matikan versi produksi")
    add("get_workflow_history", WM, since="2.29.0",
        purpose="riwayat versi workflow")
    add("get_workflow_version", WM, since="2.29.0",
        purpose="ambil satu versi",
        notes="kredensial ikut sejak 2.34.0")
    add("get_workflow_versions_diff", WM, since="2.36.0",
        purpose="diff antar versi")
    add("search_projects", WM, since="2.14.0",
        purpose="cari project (resolusi projectId)")
    add("search_folders", WM, since="2.14.0",
        purpose="cari folder (resolusi folderId)")
    add("list_workflow_tags", WM, since="2.27.0",
        purpose="daftar nama tag")

    EM = "Execution management"
    add("get_workflow_execution", EM, since="2.12.0",
        purpose="baca satu eksekusi + log")
    add("search_workflow_executions", EM, since="2.20.0",
        purpose="cari eksekusi")

    CM = "Credential management"
    add("list_credentials", CM, since="2.21.0",
        purpose="daftar kredensial yang bisa diakses",
        notes="data[].description sejak 2.41.0")

    IC = "Instance context"
    add("get_instance_context", IC, since="2.12.0",
        purpose="konteks instance (resource)")
    add("get_instance_activity", IC, since="2.12.0",
        purpose="aktivitas instance")
    add("expand_instance_activity", IC, since="2.12.0",
        purpose="perluas satu aktivitas")
    add("get_node_usage", IC, since="2.12.0",
        purpose="statistik pemakaian node")

    WB = "Workflow builder"
    # -- Workflow builder (11) ---------------------------------------------
    add("get_workflow_sdk_reference", WB, since="2.12.0",
        purpose="kontrak SDK workflow (panggil PERTAMA)",
        notes="bernama get_sdk_reference sebelum 2.34.0; "
              "section 'groups' sejak 2.41.0")
    add("search_nodes", WB, since="2.12.0",
        purpose="cari node berdasarkan layanan/trigger/util",
        notes="usage sejak 2.34.0")
    add("get_node_types", WB, since="2.12.0",
        purpose="definisi tipe TypeScript node",
        notes="nodeIds wajib objek sejak 2.27.0")
    add("get_workflow_best_practices", WB, since="2.26.0",
        purpose="praktik terbaik penyusunan")
    add("explore_node_resources", WB, since="2.27.0",
        purpose="telusuri resource node")
    add("validate_workflow", WB, since="2.12.0",
        purpose="validasi kode SDK — WAJIB sebelum tulis",
        notes="cek node groups sejak 2.41.0")
    add("validate_node_config", WB, since="2.25.1",
        purpose="validasi konfigurasi node tunggal")
    add("create_workflow_from_code", WB, since="2.12.0", mutating=True,
        requires_validation=True,
        purpose="simpan workflow dari kode SDK tervalidasi",
        notes="node groups disimpan sejak 2.41.0")
    add("update_workflow", WB, since="2.12.0", mutating=True,
        requires_validation=True,
        purpose="ubah workflow dari kode SDK",
        notes="sejak 2.20.0 memakai partial update")
    add("archive_workflow", WB, since="2.12.0", mutating=True,
        purpose="arsipkan workflow")
    add("restore_workflow_version", WB, since="2.29.0", mutating=True,
        purpose="pulihkan versi lama",
        notes="entri riwayat dinamai otomatis sejak 2.31.0")

    AM = "Agent management"
    # -- Agent management (15) --------------------------------------------
    # Seluruh kategori muncul sejak 2.34.0 (butuh workflow builder + modul
    # agents aktif) dan berstatus Preview.
    _AGENT_SINCE = "2.34.0"
    add("search_agents", AM, since=_AGENT_SINCE,
        purpose="cari agent (termasuk yang MCP-nya mati)")
    add("get_agent", AM, since=_AGENT_SINCE,
        purpose="detail satu agent")
    add("get_agent_builder_reference", AM, since=_AGENT_SINCE,
        purpose="kontrak penyusunan agent")
    add("discover_agent_assets", AM, since=_AGENT_SINCE,
        purpose="temukan aset agent",
        notes="setupGuidance Slack sejak 2.43.0")
    add("create_agent", AM, since=_AGENT_SINCE, mutating=True,
        purpose="buat agent")
    add("mutate_agent", AM, since=_AGENT_SINCE, mutating=True,
        purpose="ubah agent (config.replace/patch)")
    add("validate_agent", AM, since=_AGENT_SINCE,
        purpose="validasi definisi agent")
    add("call_agent", AM, since="2.35.0", mutating=True,
        purpose="panggil agent (berjalan)")
    add("verify_agent_mcp_server", AM, since=_AGENT_SINCE,
        purpose="verifikasi MCP server milik agent")
    add("publish_agent", AM, since=_AGENT_SINCE, mutating=True,
        purpose="publikasikan agent")
    add("unpublish_agent", AM, since=_AGENT_SINCE, mutating=True,
        purpose="tarik agent dari publikasi")
    add("revert_agent", AM, since=_AGENT_SINCE, mutating=True,
        purpose="kembalikan agent ke versi lama")
    add("list_agent_versions", AM, since=_AGENT_SINCE,
        purpose="riwayat publikasi agent")
    add("update_agent_integration", AM, since=_AGENT_SINCE, mutating=True,
        purpose="sambung/putus integrasi Slack/Telegram/Linear",
        notes="setup terkelola Slack sejak 2.43.0")
    add("delete_agent", AM, since=_AGENT_SINCE, mutating=True,
        purpose="hapus agent")

    DT = "Data tables"
    add("search_data_tables", DT, since="2.16.0", purpose="cari data table")
    add("create_data_table", DT, since="2.16.0", mutating=True,
        purpose="buat data table")
    add("add_data_table_column", DT, since="2.16.0", mutating=True,
        purpose="tambah kolom")
    add("rename_data_table_column", DT, since="2.16.0", mutating=True,
        purpose="ganti nama kolom")
    add("delete_data_table_column", DT, since="2.16.0", mutating=True,
        purpose="hapus kolom")
    add("rename_data_table", DT, since="2.16.0", mutating=True,
        purpose="ganti nama data table")
    add("add_data_table_rows", DT, since="2.16.0", mutating=True,
        purpose="tambah baris")

    return tuple(out)


TOOLS: tuple[ToolSpec, ...] = _specs()
TOOL_NAMES: tuple[str, ...] = tuple(t.name for t in TOOLS)
CATEGORY_OF: dict[str, str] = {t.name: t.category for t in TOOLS}
_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOLS}

#: Tool yang menulis dan karena itu WAJIB didahului `validate_workflow`.
CREATE_GATE_TOOLS: frozenset[str] = frozenset(
    t.name for t in TOOLS if t.requires_validation)

#: Tool yang tidak mengubah apa pun (aman dipanggil bebas).
READ_ONLY_TOOLS: frozenset[str] = frozenset(
    t.name for t in TOOLS if not t.mutating)

#: Urutan loop build kanonik, seperti dijelaskan docs n8n ("Here's what a
#: common flow looks like") dan diperkuat catatan tiap tool
#: ("Should be called first", "Must be called before ...").
BUILD_LOOP: tuple[str, ...] = (
    "get_workflow_sdk_reference",
    "search_nodes",
    "get_node_types",
    "validate_node_config",     # opsional: validasi per-node sebelum rakit
    "validate_workflow",
    "create_workflow_from_code",
    "test_workflow",
    "execute_workflow",
)

#: Bagian dokumen SDK yang bisa diminta.
SDK_SECTIONS: tuple[str, ...] = (
    "patterns", "patterns_detailed", "expressions", "functions", "rules",
    "import", "guidelines", "design", "groups", "all",
)

#: Bagian yang WAJIB dibaca sebelum menulis kode workflow.
REQUIRED_SDK_SECTION = "rules"


# ---------------------------------------------------------------------------
# 3. Galat
# ---------------------------------------------------------------------------
class McpBuildError(Exception):
    """Induk semua galat di modul ini."""


class UnknownTool(McpBuildError):
    """Nama tool tidak ada di katalog."""


class VersionTooOld(McpBuildError):
    """Instance n8n lebih tua dari versi minimum tool."""


class ProtocolMismatch(McpBuildError):
    """Amplop tidak sesuai revisi protokol yang diklaim."""


class DiscoveryMissing(McpBuildError):
    """`server/discover` tidak disediakan padahal revisi modern.MUST."""


class BuildLoopViolation(McpBuildError):
    """Urutan panggilan melanggar gate (mis. menulis tanpa validasi)."""


class SessionHeaderForbidden(ProtocolMismatch):
    """Header sesi lama dipakai pada revisi yang sudah menghapusnya."""


# ---------------------------------------------------------------------------
# 4. Utilitas versi
# ---------------------------------------------------------------------------
_VER_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?\s*$")


def parse_version(text: str) -> tuple[int, int, int]:
    """Ubah "2.41.0" -> (2, 41, 0). Melempar ValueError bila tidak sah.

    Versi non-numerik (mis. "latest", "beta") sengaja ditolak: menerimanya
    sebagai "cukup baru" akan membuat gerbang versi kehilangan gigi.
    """
    m = _VER_RE.match(str(text))
    if not m:
        raise ValueError(f"versi tidak sah: {text!r} (harap format x.y.z)")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def at_least(have: str, need: str) -> bool:
    """True bila `have` >= `need`, keduanya x.y.z."""
    if not need:
        return True
    return parse_version(have) >= parse_version(need)


# ---------------------------------------------------------------------------
# 5. Akses katalog
# ---------------------------------------------------------------------------
def tool_by_name(name: str) -> ToolSpec:
    spec = _BY_NAME.get(str(name))
    if spec is None:
        raise UnknownTool(
            f"tool {name!r} tidak dikenal "
            f"({len(TOOLS)} tool tersedia; contoh: "
            f"{', '.join(TOOL_NAMES[:4])}...)")
    return spec


def tools_in_category(category: str) -> tuple[ToolSpec, ...]:
    want = str(category).strip().lower()
    return tuple(t for t in TOOLS if t.category.lower() == want)


def tools_for_version(version: str) -> tuple[ToolSpec, ...]:
    """Tool yang tersedia pada versi n8n tertentu (gerbang versi dihormati)."""
    have = parse_version(version)
    out = []
    for t in TOOLS:
        if not t.since or parse_version(t.since) <= have:
            out.append(t)
    return tuple(out)


def require_tool(name: str, version: str) -> ToolSpec:
    """Pastikan `name` ada DAN tersedia pada `version`.

    `version=""` berarti "versi instance tidak diketahui". Dalam keadaan itu
    gerbang versi TIDAK dapat ditegakkan dan sengaja dilewati — bukan
    diperlakukan sebagai kegagalan. (Memanggil `at_least("", need)` akan
    melempar ValueError, jadi versi kosong harus ditangani lebih dulu.)
    """
    spec = tool_by_name(name)
    if not version:
        return spec
    if spec.since and not at_least(version, spec.since):
        raise VersionTooOld(
            f"tool {name!r} butuh n8n >= {spec.since}, instance memakai "
            f"{version}")
    return spec


def tool_catalog(version: str = "") -> dict:
    """Katalog lengkap; bila `version` diberi, tandai tool yang belum ada."""
    rows = []
    for t in TOOLS:
        row = t.to_dict()
        if version:
            try:
                row["available"] = at_least(version, t.since) if t.since else True
            except ValueError:
                row["available"] = t.since == ""
        rows.append(row)
    by_cat: dict[str, int] = {}
    for t in TOOLS:
        by_cat[t.category] = by_cat.get(t.category, 0) + 1
    return {
        "total": len(TOOLS),
        "categories": list(TOOL_CATEGORIES),
        "per_category": by_cat,
        "tools": rows,
        "build_loop": list(BUILD_LOOP),
        "create_gate_tools": sorted(CREATE_GATE_TOOLS),
        "read_only_count": len(READ_ONLY_TOOLS),
    }


# ---------------------------------------------------------------------------
# 6. Gate loop build
# ---------------------------------------------------------------------------
@dataclass
class ToolCall:
    """Satu pemanggilan tool yang tercatat di sesi build."""

    name: str
    at: float
    ok: bool = True
    note: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "at": self.at, "ok": self.ok,
                "note": self.note}


@dataclass
class BuildSession:
    """Melacak urutan panggilan dan menegakkan gate loop build.

    Gate yang ditegakkan:
      G1  `get_workflow_sdk_reference` harus dipanggil lebih dulu, dan
          menyertakan bagian ``rules`` — tanpa itu kode ditulis dari hafalan.
      G2  Nama tool harus ada di katalog (tidak ada tool karangan).
      G3  `validate_workflow` harus LULUS sebelum tool tulis dijalankan.
      G4  `test_workflow`/`execute_workflow` hanya setelah workflow ada.
    """

    version: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock,
                                   repr=False)
    _clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    _sdk_sections: set[str] = field(default_factory=set, repr=False)
    _validated: bool = field(default=False, repr=False)
    _workflow_exists: bool = field(default=False, repr=False)
    _reference_ok: bool = field(default=False, repr=False)

    # -- pencatatan --------------------------------------------------------
    def call(self, name: str, *, ok: bool = True, section: str = "",
             workflow_created: bool = False, note: str = "") -> ToolCall:
        """Catat panggilan; melempar bila melanggar gate."""
        if self.version:
            require_tool(name, self.version)   # G2 + gerbang versi
        else:
            tool_by_name(name)                 # G2 saja

        if name == "get_workflow_sdk_reference":
            self._sdk_sections.add(str(section or "all"))

        # G1: tool tulis/susun butuh referensi SDK (bagian rules) lebih dulu.
        if name in ("create_workflow_from_code",):
            if not self._reference_ok:
                raise BuildLoopViolation(
                    "get_workflow_sdk_reference (bagian 'rules') harus "
                    "dipanggil sebelum menulis workflow")

        # G3: validasi wajib lulus sebelum menulis.
        if tool_by_name(name).requires_validation and not self._validated:
            raise BuildLoopViolation(
                f"{name} memerlukan validate_workflow yang LULUS lebih dulu")

        # G4: menjalankan butuh workflow yang sudah ada.
        if name in ("test_workflow", "execute_workflow") \
                and not self._workflow_exists:
            raise BuildLoopViolation(
                f"{name} memerlukan workflow yang sudah dibuat/dimuat")

        # Efek samping pencatatan.
        if name == "validate_workflow" and ok:
            self._validated = True
        if name == "update_workflow" and ok:
            self._validated = False     # update berikutnya harus validasi lagi
        if name in ("create_workflow_from_code", "update_workflow") and ok:
            self._workflow_exists = True
        if workflow_created:
            self._workflow_exists = True
        if name == "get_workflow_sdk_reference":
            self._reference_ok = self._reference_ok or (
                ok and (section in ("rules", "all", "")))

        rec = ToolCall(name=name, at=self._clock(), ok=bool(ok), note=note)
        with self._lock:
            self.calls.append(rec)
        return rec

    # -- keadaan -----------------------------------------------------------
    @property
    def sdk_reference_loaded(self) -> bool:
        return self._reference_ok

    @property
    def validated(self) -> bool:
        return self._validated

    @property
    def workflow_exists(self) -> bool:
        return self._workflow_exists

    def next_step(self) -> str:
        """Langkah berikutnya menurut BUILD_LOOP, atau "" bila selesai."""
        if not self._reference_ok:
            return "get_workflow_sdk_reference"
        if not self._workflow_exists:
            if not self._validated:
                return "validate_workflow"
            return "create_workflow_from_code"
        return ""

    def missing_prerequisites(self, name: str) -> list[str]:
        """Syarat yang belum terpenuhi untuk memanggil `name`."""
        need: list[str] = []
        spec = tool_by_name(name)
        if self.version and spec.since and not at_least(self.version, spec.since):
            need.append(f"n8n >= {spec.since} (punya {self.version})")
        if name == "create_workflow_from_code" and not self._reference_ok:
            need.append("get_workflow_sdk_reference(rules)")
        if spec.requires_validation and not self._validated:
            need.append("validate_workflow(lulus)")
        if name in ("test_workflow", "execute_workflow") \
                and not self._workflow_exists:
            need.append("workflow dibuat dimuat dulu")
        return need

    def history(self) -> list[dict]:
        return [c.to_dict() for c in self.calls]

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "calls": len(self.calls),
            "sdk_reference_loaded": self._reference_ok,
            "sdk_sections": sorted(self._sdk_sections),
            "validated": self._validated,
            "workflow_exists": self._workflow_exists,
            "next_step": self.next_step(),
            "tools_used": [c.name for c in self.calls],
        }


# ---------------------------------------------------------------------------
# 7. Referensi SDK + payload protokol
# ---------------------------------------------------------------------------
def build_reference(version: str = "", sections: Iterable[str] = ()
                    ) -> dict:
    """Kontrak loop build untuk sebuah versi n8n.

    Menjawab: tool apa yang ada, urutan apa yang sah, dan bagian dokumen SDK
    mana yang wajib dibaca. Berguna sebagai "peta" yang diberikan ke model
    sebelum ia menulis kode workflow.
    """
    avail = tools_for_version(version) if version else TOOLS
    names = {t.name for t in avail}
    steps = [s for s in BUILD_LOOP if s in names]
    skipped = [s for s in BUILD_LOOP if s not in names]
    want = tuple(sections) if sections else SDK_SECTIONS
    unknown = [s for s in want if s not in SDK_SECTIONS]
    return {
        "n8n_version": version or "",
        "protocol_revision": LATEST_MODERN_REVISION,
        "required_sdk_section": REQUIRED_SDK_SECTION,
        "sections": list(want),
        "unknown_sections": unknown,
        "steps": steps,
        "unavailable_steps": skipped,
        "create_gate": sorted(CREATE_GATE_TOOLS & names),
        "tool_count": len(avail),
        "rules": [
            "panggil get_workflow_sdk_reference dulu (bagian 'rules')",
            "selalu validate_workflow sebelum create/update",
            "satu node di satu waktu: validate_node_config untuk rakit aman",
            "publish_workflow hanya setelah test_workflow lulus",
            "agent tidak boleh diandalkan di produksi (status: Preview)",
        ],
    }


def discover_payload(version: str = "", server_info: Optional[dict] = None
                     ) -> dict:
    """Bangun balasan `server/discover` (WAJIB pada revisi 2026-07-28).

    Tidak ada handshake di revisi modern: inilah satu-satunya cara klien
    memilih versi dan mengetahui kemampuan server sebelum mengirim request
    bisnis.
    """
    si = dict(server_info or {})
    si.setdefault("name", "katalir-mcp")
    si.setdefault("version", "1.0.0")
    result = {
        "protocolVersions": list(PROTOCOL_REVISIONS),
        "latest": LATEST_REVISION,
        "modern": list(MODERN_REVISIONS),
        "handshake": list(HANDSHAKE_REVISIONS),
        "serverInfo": si,
        "capabilities": {
            "tools": {"listChanged": True},
            "resources": {"listChanged": True},
        },
        "requiredHeaders": list(MODERN_REQUIRED_HEADERS),
        "cacheFields": list(CACHE_FIELDS),
        "resultTypes": list(RESULT_TYPES),
    }
    if version:
        result["toolsForVersion"] = [t.name for t in tools_for_version(version)]
    return result


def check_envelope(method: str, *, revision: str = LATEST_MODERN_REVISION,
                   headers: Optional[dict] = None,
                   meta: Optional[dict] = None,
                   result: Optional[dict] = None,
                   tool_name: str = "") -> dict:
    """Periksa satu pertukaran MCP terhadap revisi 2026-07-28.

    Mengembalikan `{ok, revision, errors[], warnings[]}`. Tidak melempar,
    supaya bisa dipakai sebagai pemeriksa batch maupun gerbang.
    """
    errs: list[str] = []
    warns: list[str] = []
    hdrs = {str(k).lower(): v for k, v in (headers or {}).items()}
    m = dict(meta or {})

    if revision not in PROTOCOL_REVISIONS:
        errs.append(f"revisi tidak dikenal: {revision!r}")

    modern = revision in MODERN_REVISIONS
    if modern:
        # Header routing wajib.
        for h in MODERN_REQUIRED_HEADERS:
            if h.lower() not in hdrs:
                errs.append(f"header wajib hilang: {h}")
        # `Mcp-Name` harus cocok dengan nama tool yang dipanggil.
        got_name = str(hdrs.get("mcp-name", "") or "")
        if tool_name and got_name and got_name != tool_name:
            errs.append(
                f"HeaderMismatch: Mcp-Name={got_name!r} "
                f"!= tool={tool_name!r}")
        if tool_name and not got_name:
            errs.append("Mcp-Name kosong untuk pemanggilan tool")
        # Header sesi lama dilarang.
        if REVOKED_SESSION_HEADER.lower() in hdrs:
            errs.append(
                f"{REVOKED_SESSION_HEADER} dihapus pada {LATEST_MODERN_REVISION}")
        # Amplop self-describing.
        if m.get(META_PROTOCOL_VERSION) != revision:
            errs.append(
                f"_meta.{META_PROTOCOL_VERSION} harus {revision!r}, "
                f"dapat {m.get(META_PROTOCOL_VERSION)!r}")
        if META_CLIENT_INFO not in m:
            warns.append(f"_meta.{META_CLIENT_INFO} disarankan")
        if META_CLIENT_CAPABILITIES not in m:
            warns.append(f"_meta.{META_CLIENT_CAPABILITIES} disarankan")
    else:
        # Revisi handshake: header routing justru fitur modern.
        if "mcp-method" in hdrs:
            warns.append("Mcp-Method tidak dikenal pada revisi handshake")

    # Cache field pada hasil list.
    if result is not None and method in CACHEABLE_LIST_METHODS:
        for f in CACHE_FIELDS:
            if f not in result:
                errs.append(f"hasil {method} wajib memuat {f}")
        scope = result.get("cacheScope")
        if scope is not None and scope not in CACHE_SCOPES:
            errs.append(f"cacheScope tidak sah: {scope!r}")

    # `resultType` wajib pada semua hasil revisi modern.
    if modern and result is not None:
        rt = result.get("resultType")
        if rt is None:
            errs.append("resultType wajib ada pada hasil modern")
        elif rt not in RESULT_TYPES:
            errs.append(f"resultType tidak sah: {rt!r}")
        elif rt == "input_required":
            if "inputRequests" not in result:
                errs.append("input_required tanpa inputRequests")
            if "requestState" not in result:
                warns.append(
                    "input_required sebaiknya menyertakan requestState "
                    "(dilindungi HMAC/AEAD) untuk anti-replay")

    return {"ok": not errs, "revision": revision, "method": method,
            "errors": errs, "warnings": warns,
            "modern": modern}


def reference_payload(version: str = "", *, section: str = "all",
                      result: Optional[dict] = None) -> dict:
    """Hasil `get_workflow_sdk_reference` dengan field cache modern.

    Dipakai untuk membuktikan bahwa jalur jawaban sudah memenuhi SEP-2549
    (`ttlMs` + `cacheScope`), bukan hanya daftar teks.
    """
    if section not in SDK_SECTIONS:
        raise McpBuildError(
            f"section tidak dikenal: {section!r} "
            f"(pilih: {', '.join(SDK_SECTIONS)})")
    body = dict(result or {})
    body.setdefault("reference", f"[{section}]")
    body.setdefault("section", section)
    body.setdefault("resultType", "complete")
    body.setdefault("ttlMs", 300_000)
    body.setdefault("cacheScope", "public")
    body["toolForVersion"] = version or ""
    return body


def validate_discovery(payload: Optional[dict]) -> dict:
    """`server/discover` WAJIB ada pada revisi 2026-07-28.

    Ini gerbang yang paling mudah dilupakan: server v1 yang tidak menyediakan
    discovery tetap "jalan" untuk klien lama, tetapi klien modern akan
    melaporkan permintaan `server/discover` yang tidak terduga dan jatuh ke
    fallback handshake.
    """
    errs: list[str] = []
    if not payload:
        errs.append("server/discover tidak disediakan (MUST pada 2026-07-28)")
        return {"ok": False, "errors": errs}
    vers = payload.get("protocolVersions")
    if not vers:
        errs.append("protocolVersions kosong")
    else:
        if LATEST_REVISION not in vers:
            errs.append(f"protocolVersions tidak memuat {LATEST_REVISION}")
        unknown = [v for v in vers if v not in PROTOCOL_REVISIONS]
        if unknown:
            errs.append(f"revisi tak dikenal dilaporkan: {unknown}")
    if not payload.get("serverInfo"):
        errs.append("serverInfo kosong")
    if not payload.get("capabilities"):
        errs.append("capabilities kosong")
    return {"ok": not errs, "errors": errs, "latest": payload.get("latest")}


# ---------------------------------------------------------------------------
# 8. Kebijakan dari env + deskripsi
# ---------------------------------------------------------------------------
def _flag(env: dict, name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def policy_from_env(env: Optional[dict] = None) -> dict:
    """Kebijakan gerbang fitur #2. Membaca dari DICT yang di-inject.

    Membaca `os.environ` di sini akan membuat nilai yang di-override saat uji
    tidak berpengaruh — bug yang sudah dua kali tertangkap di modul lain.
    """
    e = dict(env or {})
    version = str(e.get("KATALIR_MCP_N8N_VERSION", "") or "").strip()
    if version:
        try:
            parse_version(version)
        except ValueError as exc:
            raise McpBuildError(str(exc))
    return {
        "n8n_version": version,
        "require_validation": _flag(e, "KATALIR_MCP_REQUIRE_VALIDATION", True),
        "require_discovery": _flag(e, "KATALIR_MCP_REQUIRE_DISCOVERY", True),
        "enforce_routing_headers": _flag(
            e, "KATALIR_MCP_ENFORCE_ROUTING_HEADERS", True),
        "strict_tool_names": _flag(e, "KATALIR_MCP_STRICT_TOOL_NAMES", True),
        "protocol_revision": str(
            e.get("KATALIR_MCP_PROTOCOL_REVISION", "") or LATEST_MODERN_REVISION),
        "max_sdk_section_ttl_ms": int(
            e.get("KATALIR_MCP_SDK_TTL_MS", "300000") or 300000),
    }


def loop_state(session: Optional[BuildSession] = None) -> dict:
    """Ringkas keadaan loop build + langkah berikutnya."""
    s = session or BuildSession()
    return {
        "state": s.to_dict(),
        "loop": list(BUILD_LOOP),
        "next_step": s.next_step(),
        "blocked_create_reasons": s.missing_prerequisites(
            "create_workflow_from_code"),
    }


def describe() -> dict:
    """Katalog lengkap untuk `/mcp/build/overview` dan UI."""
    return {
        "feature": "mcp_build_workflow",
        "protocol": {
            "revisions": list(PROTOCOL_REVISIONS),
            "latest": LATEST_REVISION,
            "modern": list(MODERN_REVISIONS),
            "handshake": list(HANDSHAKE_REVISIONS),
            "discover_method": DISCOVER_METHOD,
            "required_headers": list(MODERN_REQUIRED_HEADERS),
            "cache_fields": list(CACHE_FIELDS),
            "result_types": list(RESULT_TYPES),
            "renumbered_errors": dict(RENUMBERED_ERRORS),
            "revoked_session_header": REVOKED_SESSION_HEADER,
        },
        "categories": list(TOOL_CATEGORIES),
        "tool_count": len(TOOLS),
        "tools_by_category": {
            c: [t.name for t in TOOLS if t.category == c]
            for c in TOOL_CATEGORIES
        },
        "build_loop": list(BUILD_LOOP),
        "sdk_sections": list(SDK_SECTIONS),
        "create_gate_tools": sorted(CREATE_GATE_TOOLS),
    }
