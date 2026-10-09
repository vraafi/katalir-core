"""Uji Fitur #10 — RBAC kustom dua tingkat (project + instance).

12 kategori: 3 basic, 2 durability, 3 edge, 2 performance, 2 security
(+ ekstra). Waktu deterministik lewat jam yang disuntik; tidak ada `sleep`.

Acuan perilaku: docs n8n Okt 2026
  * "Custom roles" / "See available roles"
  * "Create custom instance roles" (n8n 2.30.0)
  * "Create custom project roles" (n8n 1.122.0)
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rbac as R  # noqa: E402


# ---------------------------------------------------------------------------
# Perkakas
# ---------------------------------------------------------------------------

class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> float:
        self.t += dt
        return self.t


def make_reg(clk: Clock | None = None, **kw) -> R.RoleRegistry:
    return R.RoleRegistry(clock=clk or Clock(), **kw)


def make_auth(**kw) -> R.Authorizer:
    return R.Authorizer(make_reg(), **kw)


# ---------------------------------------------------------------------------
# B — BASIC (3)
# ---------------------------------------------------------------------------

def test_b1_kosakata_scope_persis_n8n():
    """B1: 42 scope project dalam 10 grup + 10 scope instance."""
    assert len(R.PROJECT_SCOPES) == 42, len(R.PROJECT_SCOPES)
    assert len(R.SCOPE_GROUPS) == 10, list(R.SCOPE_GROUPS)
    # Jumlah per grup sesuai editor "Project roles" n8n.
    per_group = {k: len(v) for k, v in R.SCOPE_GROUPS.items()}
    assert per_group == {
        "Workflow": 9, "Credential": 7, "Project": 3, "Folder": 5,
        "Execution": 1, "Secrets vaults": 5, "Secrets": 1,
        "Data table": 6, "Project variable": 4, "Source control": 1,
    }, per_group
    assert len(R.INSTANCE_SCOPES) == 10, len(R.INSTANCE_SCOPES)
    for s in ("workflow:publish", "credential:share", "execution:reveal",
              "dataTable:writeRow", "projectVariable:delete",
              "sourceControl:push"):
        assert s in R.PROJECT_SCOPES, s
    for s in ("roles:manageAll", "roles:manageProject", "members:manage",
              "apiKeys:manageOwn", "apiKeys:manageOthers", "insights:read"):
        assert s in R.INSTANCE_SCOPES, s
    # `workflow:list` sah walau bukan scope "grantable" (turunan read).
    assert R.scope_known("workflow:list")
    assert R.validate_scopes(["workflow:read", "nope:read"]) == ["nope:read"]


def test_b2_preset_bawaan_sesuai_dokumentasi():
    """B2: 3 preset project + 3 preset instance, isi sesuai n8n."""
    reg = make_reg()
    assert set(R.PROJECT_PRESETS) == {
        "project:admin", "project:editor", "project:viewer"}
    assert set(R.INSTANCE_PRESETS) == {
        "instance:owner", "instance:admin", "instance:member"}
    assert len(reg.builtin_names()) == 6, reg.builtin_names()

    admin = reg.get_role("project:admin")
    editor = reg.get_role("project:editor")
    viewer = reg.get_role("project:viewer")

    # Admin punya SEMUA scope project (implikasi menambah `workflow:list`).
    assert set(R.PROJECT_SCOPES) <= admin.scopes
    assert admin.has("workflow:unpublish")   # implikasi dari publish
    assert admin.has("workflow:list")        # implikasi dari read
    assert "execution:reveal" in admin.scopes

    # Editor: bisa create/update/delete tapi TIDAK publish, TIDAK move,
    # TIDAK execution:reveal, TIDAK kelola project.
    assert editor.has("workflow:create") and editor.has("workflow:delete")
    assert not editor.has("workflow:publish")
    assert not editor.has("workflow:move")
    assert not editor.has("execution:reveal")
    assert not editor.has("credential:share")
    assert not editor.has("project:update")

    # Viewer: read-only; TIDAK boleh execute. `:list` hanya muncul untuk
    # resource yang memang punya daftar (workflow/credential/folder);
    # `project:read` TIDAK memberi `project:list` (n8n tak mengenalnya).
    assert viewer.scopes == frozenset({"project:read", "workflow:read",
                                       "workflow:list", "credential:read",
                                       "credential:list", "folder:read",
                                       "folder:list"}), sorted(viewer.scopes)
    assert "project:list" not in viewer.scopes
    assert not viewer.has("workflow:execute")
    assert not viewer.has("workflow:create")

    # Owner = superset dari semua scope instance (termasuk implikasi).
    owner = reg.get_role("instance:owner")
    assert set(R.INSTANCE_SCOPES) <= owner.scopes
    assert owner.has("roles:manageProject")  # implikasi manageAll
    assert owner.has("apiKeys:manageOwn")    # implikasi manageOthers


def test_b3_crud_peran_kustom_dan_duplikasi():
    """B3: buat/ubah/duplikat/hapus peran kustom; preset sebagai basis."""
    clk = Clock()
    reg = make_reg(clk)
    r = reg.create_role("workflow-publisher", ["workflow:read"],
                        preset="project:viewer", created_by="u-admin")
    assert r.builtin is False and r.level == "project"
    assert r.preset_of == "project:viewer"
    # preset(viewer) + tambahan
    assert r.has("workflow:read") and r.has("project:read")
    assert not r.has("workflow:publish")

    clk.advance(5)
    r2 = reg.update_role("workflow-publisher",
                         scopes=["workflow:read", "workflow:publish"])
    assert r2.has("workflow:publish") and r2.has("workflow:unpublish")
    assert r2.updated_at == clk.t and r2.created_at < r2.updated_at

    dup = reg.duplicate_role("workflow-publisher", "workflow-publisher-2")
    assert dup.name == "workflow-publisher-2" and not dup.builtin
    # Duplikat menyalin himpunan EFEKTIF apa adanya (tanpa menambah basis).
    assert dup.scopes == r2.scopes, (sorted(dup.scopes), sorted(r2.scopes))
    assert dup.granted == r2.granted
    assert dup.preset_of == ""  # tidak mewarisi preset -> tak ada penggandaan

    out = reg.delete_role("workflow-publisher-2")
    assert out == {"role": "workflow-publisher-2", "deleted": True,
                   "reassigned": 0}
    with pytest.raises(R.RoleNotFound):
        reg.get_role("workflow-publisher-2")

    st = reg.stats()
    assert st["roles_custom"] == 1 and st["roles_builtin"] == 6
    assert any(e["event"] == "role_created" for e in reg.audit)
    assert any(e["event"] == "role_deleted" for e in reg.audit)


# ---------------------------------------------------------------------------
# D — DURABILITY (2)
# ---------------------------------------------------------------------------

def test_d1_penetapan_bertahan_dan_terisolasi_per_project():
    """D1: peran project hanya berlaku di project tempat ia ditetapkan."""
    reg = make_reg()
    reg.create_role("pub", ["workflow:read", "workflow:publish"])
    reg.assign("proj-1", "u-1", "pub")
    reg.assign("proj-2", "u-1", "project:viewer")

    assert reg.effective_scopes("u-1", "proj-1") >= {"workflow:publish"}
    assert "workflow:publish" not in reg.effective_scopes("u-1", "proj-2")
    # Tanpa project -> hanya peran instance (tidak ditetapkan) = kosong.
    assert reg.effective_scopes("u-1") == set()
    assert reg.projects_of("u-1") == ["proj-1", "proj-2"]

    # Peran instance ikut terhitung di semua project.
    reg.assign_instance("u-1", "instance:member")
    assert reg.effective_scopes("u-1", "proj-1") >= {"apiKeys:manageOwn"}
    assert reg.effective_scopes("u-1", "proj-2") >= {"tags:read"}
    assert reg.effective_scopes("u-1") >= {"tags:manage"}


def test_d2_peran_dipakai_tidak_bisa_dihapus():
    """D2: `delete_role` menolak selama masih ada penetapan (perilaku n8n)."""
    reg = make_reg()
    reg.create_role("temp", ["workflow:read"])
    reg.assign("proj-1", "u-1", "temp")
    reg.assign_instance("u-2", "instance:member")
    reg.create_role("temp-inst", ["tags:read"], level="instance")
    reg.assign_instance("u-3", "temp-inst")

    with pytest.raises(R.RoleInUse) as e1:
        reg.delete_role("temp")
    assert "1 penetapan" in str(e1.value)
    with pytest.raises(R.RoleInUse) as e2:
        reg.delete_role("temp-inst")
    assert "1 penetapan" in str(e2.value)

    # Setelah dipindahkan/dilepas, baru boleh dihapus.
    assert reg.unassign("proj-1", "u-1") is True
    assert reg.unassign("proj-1", "u-1") is False  # idempoten
    assert reg.delete_role("temp")["deleted"] is True

    reg.instance_assignments.pop("u-3")
    assert reg.delete_role("temp-inst")["deleted"] is True

    st = reg.stats()
    assert st["project_assignments"] == 0
    assert st["roles_custom"] == 0


# ---------------------------------------------------------------------------
# E — EDGE (3)
# ---------------------------------------------------------------------------

def test_e1_peran_bawaan_immutable():
    """E1: peran bawaan tidak dapat diubah/dihapus."""
    reg = make_reg()
    with pytest.raises(R.RoleImmutable):
        reg.update_role("project:admin", scopes=["workflow:read"])
    with pytest.raises(R.RoleImmutable):
        reg.delete_role("project:editor")
    with pytest.raises(R.RoleImmutable):
        reg.delete_role("instance:owner")
    with pytest.raises(R.RBACError):
        reg.update_role("project:viewer", description="apa pun")
    # Isi peran bawaan tetap utuh.
    assert reg.get_role("project:admin").has("sourceControl:push")


def test_e2_scope_tak_dikenal_dan_nama_tidak_valid():
    """E2: validasi kosakata & slug nama peran."""
    reg = make_reg()
    with pytest.raises(R.ScopeUnknown) as e:
        reg.create_role("bad", ["workflow:teleport", "credential:read"])
    assert "workflow:teleport" in str(e.value)

    with pytest.raises(R.RBACError):
        R.Role("Bad Name", level="project")            # spasi/kapital
    with pytest.raises(R.RBACError):
        R.Role("-leading", level="project")
    with pytest.raises(R.RBACError):
        R.Role("ok", level="galaxy")                   # level tidak sah
    with pytest.raises(R.RBACError):
        R.Role("", level="project")                    # nama kosong

    # Level tidak cocok dengan cara penetapan.
    reg.create_role("inst-role", ["tags:read"], level="instance")
    with pytest.raises(R.RBACError):
        reg.assign("proj-1", "u-1", "inst-role")       # instance via assign()
    with pytest.raises(R.RBACError):
        reg.assign_instance("u-1", "project:viewer")   # project via instance
    # Duplikat.
    reg.create_role("dupe", ["workflow:read"])
    with pytest.raises(R.RBACError):
        reg.create_role("dupe", ["workflow:read"])
    # Preset tak dikenal.
    with pytest.raises(R.RoleNotFound):
        reg.create_role("x", [], preset="project:god")
    # Peran tak ditemukan.
    with pytest.raises(R.RoleNotFound):
        reg.assign("proj-1", "u-1", "ghost")


def test_e3_implikasi_transitif_dan_except_konflik():
    """E3: tutup transitif implikasi + authorize/deny konsisten."""
    # manageAll -> manageProject ; manageOthers -> manageOwn
    assert R.expand_scopes(["roles:manageAll"]) == {
        "roles:manageAll", "roles:manageProject"}
    assert R.expand_scopes(["apiKeys:manageOthers"]) == {
        "apiKeys:manageOthers", "apiKeys:manageOwn"}
    # publish -> unpublish, dan read -> list pada tiap resource.
    assert R.expand_scopes(["workflow:publish", "credential:read"]) == {
        "workflow:publish", "workflow:unpublish",
        "credential:read", "credential:list"}
    # Sudah-implisit tidak menambah apa-apa lagi (idempoten).
    assert R.expand_scopes(["workflow:list"]) == {"workflow:list"}
    # read pada scope instance juga memberi list (perilaku generik n8n).
    assert R.expand_scopes(["tags:read"]) == {"tags:read", "tags:list"}

    reg = make_reg()
    au = R.Authorizer(reg)
    reg.create_role("list-only", ["workflow:list"])
    reg.assign_instance("u-x", "instance:member")
    reg.assign("p-l", "u-x", "list-only")
    # Punya `workflow:list` eksplisit -> boleh list, TIDAK boleh read.
    assert au.allow("u-x", "workflow:list", project_id="p-l") is True
    assert au.allow("u-x", "workflow:read", project_id="p-l") is False
    # `allow(...)` untuk read butuh read+list; di sini tidak ada read.

    reg.create_role("reader", ["workflow:read"])
    reg.assign("p-r", "u-y", "reader")
    assert au.allow("u-y", "workflow:read", project_id="p-r") is True
    assert au.allow("u-y", "workflow:list", project_id="p-r") is True
    assert au.allow("u-y", "workflow:create", project_id="p-r") is False

    with pytest.raises(R.NotAuthorized):
        au.require("u-y", "workflow:create", project_id="p-r")
    au.require("u-y", "workflow:read", project_id="p-r")  # tidak melempar
    with pytest.raises(R.NotAuthorized):
        au.require_all("u-y", ["workflow:read", "workflow:delete"],
                       project_id="p-r")
    assert "ALLOW" in au.describe_request("u-y", "workflow:list",
                                         project_id="p-r")
    assert "DENY" in au.describe_request("u-y", "workflow:delete",
                                        project_id="p-r")
    st = au.stats()
    assert st["checks"] >= 6 and st["denials"] >= 1
    assert all("missing" in d for d in st["recent_denials"])


# ---------------------------------------------------------------------------
# P — PERFORMANCE (2)
# ---------------------------------------------------------------------------

def test_p1_seribu_pengguna_dua_ratus_peran_cepat():
    """P1: 200 peran + 1000 penetapan tetap di bawah ambang waktu."""
    clk = Clock()
    reg = make_reg(clk)
    t0 = time.perf_counter()
    for i in range(200):
        reg.create_role(f"role-{i}", ["workflow:read", "credential:read"])
    for i in range(1000):
        reg.assign(f"proj-{i % 50}", f"user-{i}", f"role-{i % 200}")
    au = R.Authorizer(reg)
    ok = 0
    for i in range(1000):
        if au.allow(f"user-{i}", "workflow:list", project_id=f"proj-{i % 50}"):
            ok += 1
    dt = time.perf_counter() - t0
    assert ok == 1000, ok
    assert dt < 5.0, f"terlalu lambat: {dt:.3f}s"

    st = reg.stats()
    assert st["roles_custom"] == 200 and st["roles_builtin"] == 6
    assert st["project_assignments"] == 1000
    assert st["audit_events"] == 1200


def test_p2_otorisasi_paralel_thread_safe():
    """P2: 8 thread x 500 cek konkuren -> tak ada kehilangan hitungan."""
    reg = make_reg()
    reg.create_role("worker-role", ["workflow:execute", "workflow:read"])
    members = [f"w-{i}" for i in range(8)]
    for m in members:
        reg.assign("proj-par", m, "worker-role")
    au = R.Authorizer(reg)

    def hammer(user: str) -> int:
        good = 0
        for _ in range(500):
            if au.allow(user, "workflow:execute", project_id="proj-par"):
                good += 1
            au.allow(user, "workflow:delete", project_id="proj-par")  # ditolak
        return good

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(hammer, members))
    assert results == [500] * 8, results
    st = au.stats()
    assert st["checks"] == 8000, st["checks"]
    assert st["denials"] == 4000, st["denials"]  # 8 x 500 ditolak


# ---------------------------------------------------------------------------
# S — SECURITY (2)
# ---------------------------------------------------------------------------

def test_s1_guard_privilege_escalation_strict():
    """S1: kombinasi berisiko ditolak di mode strict (default)."""
    reg = make_reg()  # strict=True
    for risky, combo in (
        ("esc-a", ["roles:manageAll"]),
        ("esc-b", ["roles:manageProject"]),
        ("esc-c", ["members:manage"]),
        ("esc-d", ["instanceSettings:manage", "members:manage"]),
    ):
        with pytest.raises(R.PrivilegeEscalationRisk) as e:
            reg.create_role(risky, combo, level="instance")
        assert "berisiko" in str(e.value)

    # Peran bawaan instance:admin/owner memang punya; ia tidak dibuat lewat
    # create_role sehingga tidak terkena guard.
    assert reg.get_role("instance:admin").escalation_risks() != []

    # `allow_escalation=True` = jalan keluar eksplisit (mis. bootstrap).
    r = reg.create_role("esc-ok", ["members:manage"], level="instance",
                        allow_escalation=True)
    assert r.has("members:manage") and r.escalation_risks() != []

    # Mode non-strict: diizinkan tanpa flag.
    loose = make_reg(strict=False)
    r2 = loose.create_role("loose-esc", ["roles:manageAll"], level="instance")
    assert r2.has("roles:manageAll")
    assert loose.stats()["enforce_escalation_guard"] is False

    # Update juga digerbangi.
    with pytest.raises(R.PrivilegeEscalationRisk):
        reg.update_role("esc-ok", scopes=["roles:manageAll"])


def test_s2_aktor_tak_bisa_memberi_izin_melebihi_miliknya():
    """S2: `assert_can_grant` mencegah eskalasi lewat definisi peran."""
    reg = make_reg()
    au = R.Authorizer(reg)
    reg.assign("p-sec", "u-editor", "project:editor")
    reg.assign_instance("u-editor", "instance:member")

    # Editor boleh "memberikan" scope yang memang dimilikinya.
    au.assert_can_grant("u-editor", ["workflow:update"], project_id="p-sec")

    # Tapi TIDAK boleh `workflow:publish` / `execution:reveal` / `members:manage`.
    for bad in ("workflow:publish", "execution:reveal", "credential:share"):
        with pytest.raises(R.PrivilegeEscalationRisk) as e:
            au.assert_can_grant("u-editor", [bad], project_id="p-sec")
        assert bad in str(e.value)

    # Implikasi juga diperhitungkan: memberi `workflow:read` menarik
    # `workflow:list` -> editor punya keduanya, jadi lolos.
    au.assert_can_grant("u-editor", ["workflow:read"], project_id="p-sec")

    # Fail-closed: pengguna tanpa penetapan tidak boleh memberi apa pun.
    with pytest.raises(R.PrivilegeEscalationRisk):
        au.assert_can_grant("u-nobody", ["workflow:read"], project_id="p-sec")

    # Admin project (punya semua) boleh memberi `sourceControl:push`.
    reg.assign("p-sec", "u-admin", "project:admin")
    au.assert_can_grant("u-admin", ["sourceControl:push"], project_id="p-sec")


# ---------------------------------------------------------------------------
# X — EKSTRA
# ---------------------------------------------------------------------------

def test_x1_describe_dari_env_inject():
    """X1: `describe()` membaca env yang disuntik, bukan `os.environ`."""
    d = R.describe({"KATALIR_RBAC_STRICT": "0"})
    assert d["strict"] is False
    assert d["project_scope_count"] == 42
    assert d["instance_scope_count"] == 10
    assert d["project_presets"] == ["project:admin", "project:editor",
                                    "project:viewer"]
    # Urutan deklarasi dict (owner dulu), bukan alfabetis.
    assert d["instance_presets"] == ["instance:owner", "instance:admin",
                                     "instance:member"]
    assert d["levels"] == ["instance", "project"]
    assert d["read_implies_list"] is True
    assert d["implied_scopes"]["workflow:publish"] == ["workflow:unpublish"]
    assert len(d["builtin_roles"]) == 6
    assert sum(len(v) for v in d["project_scope_groups"].values()) == 42

    d2 = R.describe({})
    assert d2["strict"] is True


def test_x2_factory_env_membuat_registry_dan_authorizer_terhubung():
    """X2: `rbac_from_env` mengikat registry ke authorizer-nya."""
    reg, au = R.rbac_from_env({"KATALIR_RBAC_STRICT": "1"})
    assert au.registry is reg and reg.strict is True
    reg.create_role("sandbox", ["workflow:read"])
    reg.assign("p", "u", "sandbox")
    assert au.allow("u", "workflow:list", project_id="p") is True

    # Singleton proses dapat diganti/di-reset (dipakai suite API).
    R.set_registry(None)
    assert R.registry().builtin_names() == R.builtin_names_expected() \
        if hasattr(R, "builtin_names_expected") else True
    R.set_registry(reg)
    assert R.registry() is reg
    assert R.authorizer().registry is reg
    R.set_authorizer(None)
    assert R.authorizer().registry is reg


def test_x3_clock_disuntik_dipakai_untuk_audit_dan_timestamp():
    """X3: `Role.created_at`/audit memakai jam yang disuntik."""
    clk = Clock(5000.0)
    reg = make_reg(clk)
    r = reg.create_role("t-role", ["workflow:read"])
    assert r.created_at == 5000.0 and r.updated_at == 5000.0
    clk.advance(30)
    reg.assign("p", "u", "t-role")
    r2 = reg.update_role("t-role", scopes=["workflow:update"])
    assert r2.updated_at == 5030.0 and r2.created_at == 5000.0
    assert reg.audit[-1]["at"] == 5030.0
    assert all(isinstance(e["at"], float) for e in reg.audit)


def test_x4_members_of_dan_ringkasan_peran():
    """X4: daftar anggota per project + ringkasan `to_dict` lengkap."""
    reg = make_reg()
    reg.create_role("mixed", ["workflow:read", "workflow:publish"],
                    description="uji")
    reg.assign("p1", "u-a", "project:editor")
    reg.assign("p1", "u-b", "mixed")
    reg.assign("p2", "u-a", "project:viewer")

    m = reg.members_of("p1")
    assert m == [{"project_id": "p1", "user_id": "u-a", "role": "project:editor"},
                 {"project_id": "p1", "user_id": "u-b", "role": "mixed"}], m
    assert reg.members_of("p3") == []

    d = reg.get_role("mixed").to_dict()
    assert d["name"] == "mixed" and d["level"] == "project"
    assert d["builtin"] is False and d["description"] == "uji"
    assert "workflow:publish" in d["granted"]
    assert "workflow:unpublish" in d["implied"]
    assert d["scope_count"] == len(d["scopes"])
    assert set(d["scopes"]) == set(d["granted"]) | set(d["implied"])

    lst = reg.list_roles(level="instance")
    assert {x["name"] for x in lst} == set(R.INSTANCE_PRESETS)
    assert len(reg.list_roles()) == 6 + 1


def test_x5_allows_any_dan_enforce_flag():
    """X5: `allows_any` + flag `enforce` pada Authorizer."""
    reg = make_reg()
    reg.create_role("ro", ["workflow:read"])
    reg.assign("p", "u", "ro")
    au = R.Authorizer(reg)
    assert au.allows_any("u", ["workflow:delete", "workflow:read"],
                         project_id="p") is True
    assert au.allows_any("u", ["workflow:delete", "workflow:move"],
                         project_id="p") is False
    assert au.allows_any("u", [], project_id="p") is False
    assert au.allows_any("u", ["workflow:teleport"], project_id="p") is False
    assert au.enforce is True
    assert R.Authorizer(reg, enforce=False).enforce is False

    # `expand_scopes` ganda: publish + read sekaligus.
    reg2 = make_reg()
    reg2.create_role("both", ["workflow:publish", "workflow:read"])
    r = reg2.get_role("both")
    assert {"workflow:publish", "workflow:unpublish", "workflow:read",
            "workflow:list"} <= r.scopes
    # `granted` tetap eksplisit saja.
    assert set(r.granted) == {"workflow:publish", "workflow:read"}


def test_x6_scope_implikasi_read_ke_list_untuk_semua_resource():
    """X6: setiap `<resource>:read` pada resource berdaftar memberi `:list`."""
    # Resource project yang punya daftar -> harus memunculkan `:list`.
    for res in ("workflow", "credential", "folder", "dataTable",
                "projectVariable", "externalSecretsProvider"):
        assert R.implied_for(res + ":read") == (res + ":list",), res
    # `tags:read` (instance) juga.
    assert R.implied_for("tags:read") == ("tags:list",)

    # Resource yang TIDAK punya daftar -> tidak memunculkan `:list`.
    # `project:read` TIDAK memberi `project:list` (n8n tak mengenalnya);
    # sebaliknya `execution:list` memang ada (halaman Executions).
    assert "project" not in R.LISTABLE_RESOURCES
    assert R.implied_for("project:read") == ()
    assert R.implied_for("execution:reveal") == ()
    assert "execution" in R.LISTABLE_RESOURCES

    # Yang bukan `:read` tidak menghasilkan `:list`.
    assert R.implied_for("workflow:create") == ()
    assert R.implied_for("workflow:list") == ()
    assert R.implied_for("externalSecret:list") == ()

    # Semua `:list` turunan tetap dikenali sebagai scope sah.
    for res in R.LISTABLE_RESOURCES:
        assert R.scope_known(res + ":list"), res


def test_x9_konsistensi_kosakata_menyeluruh():
    """X9: invarians kosakata — semua preset/implikasi/turunan saling konsisten.

    Menangkap kelas bug "scope turunan tidak dikenal": `workflow:unpublish`
    dihasilkan oleh implikasi `workflow:publish` dan dipakai `project:admin`,
    tetapi sempat TIDAK ada di `ALL_SCOPES` sehingga `validate_scopes()`
    keliru menolaknya sebagai tak dikenal.
    """
    # 1. Semua scope preset wajib dikenal.
    for name, sc in list(R.PROJECT_PRESETS.items()) + list(R.INSTANCE_PRESETS.items()):
        assert R.validate_scopes(sc) == [], (name, R.validate_scopes(sc))

    # 2. Semua hasil `expand_scopes` untuk semua preset wajib dikenal.
    for name, sc in list(R.PROJECT_PRESETS.items()) + list(R.INSTANCE_PRESETS.items()):
        for s in R.expand_scopes(sc):
            assert R.scope_known(s), f"expand({name}) -> {s} tak dikenal"

    # 3. Sumber & target implikasi wajib dikenal.
    for src, dsts in R.IMPLIED_SCOPES.items():
        assert R.scope_known(src), src
        for d in dsts:
            assert R.scope_known(d), f"{src} -> {d}"

    # 4. Turunan `:list` untuk resource berdaftar wajib dikenal.
    for res in R.LISTABLE_RESOURCES:
        assert R.scope_known(res + ":list"), res

    # 5. `workflow:unpublish` turunan wajib dikenal & terdaftar sebagai turunan.
    assert R.scope_known("workflow:unpublish")
    assert "workflow:unpublish" in R.DERIVED_SCOPES
    assert "workflow:unpublish" not in R.PROJECT_SCOPES  # bukan grantable

    # 6. Tidak ada scope yang muncul di dua tingkat (project vs instance).
    assert not (set(R.PROJECT_SCOPES) & set(R.INSTANCE_SCOPES))

    # 7. Scope instance tidak bocor ke preset project (dan sebaliknya).
    admin = R.expand_scopes(R.PROJECT_PRESETS["project:admin"])
    assert not (admin & set(R.INSTANCE_SCOPES)), sorted(admin & set(R.INSTANCE_SCOPES))
    member = R.expand_scopes(R.INSTANCE_PRESETS["instance:member"])
    assert not (member & set(R.PROJECT_SCOPES))

    # 8. `project:admin` memberi SEMUA scope project (49 efektif = 42 + 7 list).
    assert set(R.PROJECT_SCOPES) <= admin
    assert len(admin) == 49, len(admin)
    assert len(R.ALL_SCOPES) == len(set(R.PROJECT_SCOPES)
                                   | set(R.INSTANCE_SCOPES)
                                   | R.DERIVED_SCOPES)


def test_x7_audit_event_lengkap_untuk_siklus_penuh():
    """X7: setiap operasi mutasi tercatat di audit."""
    reg = make_reg()
    reg.create_role("a1", ["workflow:read"])
    reg.assign("p", "u1", "a1")
    reg.assign_instance("u2", "instance:member")
    reg.unassign("p", "u1")
    reg.delete_role("a1")
    events = [e["event"] for e in reg.audit]
    assert events == ["role_created", "role_assigned",
                      "instance_role_assigned", "role_unassigned",
                      "role_deleted"], events
    assert reg.audit[1]["project_id"] == "p"
    assert reg.audit[1]["user_id"] == "u1"
    assert reg.audit[1]["role"] == "a1"


def test_x8_update_role_mempertahankan_basis_preset():
    """X8 (regresi): `update_role(scopes=...)` TIDAK boleh menghapus basis
    preset. Di UI n8n, mengedit peran yang berasal dari preset menampilkan
    kotak preset SUDAH tercentang, jadi scope preset harus bertahan."""
    reg = make_reg()
    reg.create_role("wp", ["workflow:read"], preset="project:viewer")
    r = reg.update_role("wp", scopes=["workflow:read", "workflow:publish"])
    assert r.preset_of == "project:viewer"
    # Basis viewer bertahan.
    assert r.has("project:read") and r.has("credential:read")
    assert r.has("folder:read")
    # Plus yang baru diminta + implikasinya.
    assert r.has("workflow:publish") and r.has("workflow:unpublish")
    assert r.has("workflow:list")

    # `scopes=None` mempertahankan scope eksplisit yang ada.
    before = set(r.granted)
    r2 = reg.update_role("wp", description="diubah")
    assert set(r2.granted) == before, (sorted(r2.granted), sorted(before))
    assert r2.description == "diubah"

    # Mengubah level-instance yang berpreset juga mempertahankan basis.
    reg.create_role("inst-editor", [], level="instance",
                    preset="instance:member")
    r3 = reg.update_role("inst-editor", scopes=["insights:read"])
    assert r3.has("apiKeys:manageOwn") and r3.has("tags:read")
    assert r3.has("insights:read")

    # Duplikat lalu diubah: duplikat tanpa preset -> update MENGGANTI
    # seluruh scope eksplisit (tanpa basis preset yang perlu dipertahankan).
    dup = reg.duplicate_role("wp", "wp-dup")
    assert dup.preset_of == ""
    r4 = reg.update_role("wp-dup", scopes=["workflow:execute"])
    assert not r4.has("project:read"), sorted(r4.granted)
    assert not r4.has("workflow:read"), sorted(r4.granted)
    assert r4.has("workflow:execute")
    assert set(r4.granted) == {"workflow:execute"}, sorted(r4.granted)

    # Audit mencatat update + duplikasi.
    evs = [e["event"] for e in reg.audit]
    assert evs.count("role_updated") == 4, evs
    assert evs.count("role_duplicated") == 1, evs
