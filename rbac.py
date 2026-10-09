"""rbac.py — Fitur #10: RBAC kustom dua tingkat (project + instance).

Padanan n8n "Custom roles" (Enterprise, docs Okt 2026). n8n punya **dua
tingkat peran**:

* **Instance role** — berlaku di seluruh instance (Owner/Admin/Member atau
  peran kustom). Menentukan kemampuan administratif.
* **Project role** — berlaku **hanya di dalam satu project**. Pengguna yang
  sama dapat memiliki peran berbeda di project berbeda.

Modul ini menyediakan kosakata scope **persis** seperti n8n (49 scope dalam
10 grup), peran bawaan (preset), peran kustom, penetapan peran, dan
pemeriksaan otorisasi — termasuk penolakan terhadap risiko **privilege
escalation** yang diperingatkan dokumentasi n8n.

Aturan yang dipertahankan (dari docs n8n):
  * `<resource>:read` otomatis memberi `<resource>:list`.
  * `workflow:publish` otomatis memberi `workflow:unpublish`.
  * `instanceRole:manageProjectRoles` otomatis termasuk dirinya; dan
    `roles:manageAll` otomatis termasuk `roles:manageProject`.
  * apiKeys "manage others" otomatis termasuk "manage own".
  * Peran kustom **hanya berlaku di project tempat ia ditetapkan**.
  * Peran yang masih dipakai TIDAK boleh dihapus (harus dipindahkan dulu).
  * `Roles: Manage all roles` + `Members: Manage` = risiko eskalasi.

Env:
    KATALIR_RBAC_STRICT   \"1\" (default) — tolak definisi peran yang
                          mengandung risiko privilege escalation
"""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from typing import Any, Callable, Iterable, Optional

__all__ = [
    "RBACError", "ScopeUnknown", "RoleNotFound", "RoleInUse",
    "RoleImmutable", "NotAuthorized", "PrivilegeEscalationRisk",
    "PROJECT_SCOPES", "SCOPE_GROUPS", "INSTANCE_SCOPES", "IMPLIED_SCOPES",
    "LISTABLE_RESOURCES",
    "PROJECT_PRESETS", "INSTANCE_PRESETS", "ESCALATION_FLAGS",
    "Role", "RoleRegistry", "Authorizer", "registry", "set_registry",
    "authorizer", "set_authorizer", "rbac_from_env", "describe",
    "expand_scopes", "scope_known", "validate_scopes", "implied_for",
]

# ---------------------------------------------------------------------------
# Kosakata scope — PERSIS n8n (docs Okt 2026)
# ---------------------------------------------------------------------------

#: Semua scope project n8n, dikelompokkan seperti di editor "Project roles".
SCOPE_GROUPS: dict[str, dict[str, str]] = {
    "Workflow": {
        "workflow:create": "Create new workflows",
        "workflow:read": "View workflow details",
        "workflow:update": "Edit workflows",
        "workflow:execute": "Execute workflows",
        "workflow:publish": "Publish workflows (also grants workflow:unpublish)",
        "workflow:delete": "Delete workflows",
        "workflow:move": "Transfer workflows between projects",
        "workflow:enableRedaction": "Turn on data redaction for a workflow",
        "workflow:disableRedaction": "Turn off data redaction for a workflow",
    },
    "Credential": {
        "credential:create": "Create new credentials",
        "credential:read": "View credential details",
        "credential:update": "Edit credentials",
        "credential:delete": "Delete credentials",
        "credential:move": "Transfer credentials between projects",
        "credential:share": "Share credentials with other users",
        "credential:unshare": "Remove credential sharing",
    },
    "Project": {
        "project:read": "View project details",
        "project:update": "Edit project settings",
        "project:delete": "Delete projects",
    },
    "Folder": {
        "folder:create": "Create new folders",
        "folder:read": "View folder contents",
        "folder:update": "Rename folders",
        "folder:delete": "Delete folders",
        "folder:move": "Transfer folders",
    },
    "Execution": {
        "execution:reveal": "Reveal redacted execution data",
    },
    "Secrets vaults": {
        "externalSecretsProvider:create": "Create new secret vaults in a project",
        "externalSecretsProvider:read": "View secret vaults in a project",
        "externalSecretsProvider:update": "Edit secret vault configuration",
        "externalSecretsProvider:delete": "Delete secret vaults from a project",
        "externalSecretsProvider:sync": "Reload a vault's secrets",
    },
    "Secrets": {
        "externalSecret:list": "Use secrets in credentials",
    },
    "Data table": {
        "dataTable:create": "Create new data tables",
        "dataTable:read": "View data table schema",
        "dataTable:update": "Edit data table schema",
        "dataTable:delete": "Delete data tables",
        "dataTable:readRow": "Read rows from data tables",
        "dataTable:writeRow": "Insert or update rows in data tables",
    },
    "Project variable": {
        "projectVariable:create": "Create new variables",
        "projectVariable:read": "View variable values",
        "projectVariable:update": "Edit variable values",
        "projectVariable:delete": "Delete variables",
    },
    "Source control": {
        "sourceControl:push": "Push changes to source control",
    },
}

#: Seluruh scope project (49 buah) dalam satu himpunan datar.
PROJECT_SCOPES: tuple[str, ...] = tuple(
    sorted(s for grp in SCOPE_GROUPS.values() for s in grp))

#: Scope tingkat instance (docs n8n 2.30.0, "Instance roles").
INSTANCE_SCOPES: dict[str, str] = {
    "instanceSettings:manage": "View and change instance-wide settings",
    "members:manage": "Invite, remove, and update users across the instance",
    "roles:manageProject": "Create, edit, and delete custom project roles only",
    "roles:manageAll": (
        "Create, edit, and delete all custom roles (instance and project)"),
    "apiKeys:manageOwn": "Create and delete the user's own API keys",
    "apiKeys:manageOthers": "View and delete other users' API keys",
    "tags:read": "View all tags",
    "tags:manage": "Create, edit, and delete tags",
    "projects:create": "Create new projects",
    "insights:read": "View instance-level insights and usage data",
}

#: Implikasi otomatis antar-scope (docs n8n "Automatically granted scopes").
IMPLIED_SCOPES: dict[str, tuple[str, ...]] = {
    "workflow:publish": ("workflow:unpublish",),
    "roles:manageAll": ("roles:manageProject",),
    "apiKeys:manageOthers": ("apiKeys:manageOwn",),
}


#: Resource yang benar-benar punya scope `:list` di n8n. Editor "Project
#: roles" tidak menampilkan `:list` sebagai *grantable* (karena selalu
#: diturunkan dari `:read`), tetapi scope-nya tetap ada dan dipakai
#: pemeriksaan otorisasi. Implikasi `read -> list` HANYA berlaku untuk
#: resource di himpunan ini; `project:read` misalnya tidak memberi
#: `project:list` karena n8n tidak mengenal scope itu.
LISTABLE_RESOURCES: frozenset[str] = frozenset({
    "workflow", "credential", "folder", "dataTable", "projectVariable",
    "externalSecretsProvider", "externalSecret", "tags", "execution",
})


def _read_implies_list(scope: str) -> tuple[str, ...]:
    """`<resource>:read` otomatis memberi `<resource>:list` (aturan n8n).

    Hanya berlaku bila `<resource>:list` memang resource yang punya
    daftar (lihat `LISTABLE_RESOURCES`).
    """
    if not scope.endswith(":read"):
        return ()
    res = scope[: -len(":read")]
    if res not in LISTABLE_RESOURCES:
        return ()
    return (res + ":list",)


def implied_for(scope: str) -> tuple[str, ...]:
    out = list(IMPLIED_SCOPES.get(scope, ()))
    out.extend(_read_implies_list(scope))
    return tuple(out)


def expand_scopes(scopes: Iterable[str]) -> set[str]:
    """Tutup transitif dari implikasi scope (mis. read -> list)."""
    out: set[str] = set()
    stack = [str(s) for s in scopes]
    while stack:
        s = stack.pop()
        if s in out:
            continue
        out.add(s)
        for extra in implied_for(s):
            if extra not in out:
                stack.append(extra)
    return out


#: Scope turunan yang tidak pernah ditampilkan sebagai kotak *grantable* di
#: editor n8n, tetapi tetap sah dan dihasilkan oleh aturan implikasi.
#: `workflow:unpublish` muncul dari `workflow:publish`; `<resource>:list`
#: muncul dari `<resource>:read` untuk resource berdaftar.
DERIVED_SCOPES: frozenset[str] = frozenset(
    {"workflow:unpublish"}
    | {res + ":list" for res in LISTABLE_RESOURCES})

ALL_SCOPES: frozenset[str] = frozenset(
    set(PROJECT_SCOPES) | set(INSTANCE_SCOPES) | DERIVED_SCOPES)


def scope_known(scope: str) -> bool:
    return str(scope) in ALL_SCOPES


def validate_scopes(scopes: Iterable[str]) -> list[str]:
    """Kembalikan scope yang TIDAK dikenal (kosong = semua sah)."""
    return [s for s in scopes if not scope_known(s)]


# ---------------------------------------------------------------------------
# Preset bawaan n8n
# ---------------------------------------------------------------------------

_VIEW_ONLY = ("project:read",)

#: Preset peran PROJECT (docs n8n "See available roles").
PROJECT_PRESETS: dict[str, tuple[str, ...]] = {
    # Project Admin: tertinggi
    "project:admin": (
        "project:read", "project:update", "project:delete",
        "workflow:create", "workflow:read", "workflow:update",
        "workflow:execute", "workflow:publish", "workflow:delete",
        "workflow:move", "workflow:enableRedaction",
        "workflow:disableRedaction",
        "credential:create", "credential:read", "credential:update",
        "credential:delete", "credential:move", "credential:share",
        "credential:unshare",
        "folder:create", "folder:read", "folder:update", "folder:delete",
        "folder:move",
        "execution:reveal",
        # external secrets: butuh gerbang instance "Enable external secrets
        # for project roles" (n8n 2.13+); di sini disertakan karena preset
        # admin memang mendapatkannya.
        "externalSecretsProvider:create", "externalSecretsProvider:read",
        "externalSecretsProvider:update", "externalSecretsProvider:delete",
        "externalSecretsProvider:sync",
        "externalSecret:list",
        "dataTable:create", "dataTable:read", "dataTable:update",
        "dataTable:delete", "dataTable:readRow", "dataTable:writeRow",
        "projectVariable:create", "projectVariable:read",
        "projectVariable:update", "projectVariable:delete",
        "sourceControl:push",
    ),
    # Project Editor: view+create+update+delete; TANPA kelola anggota/project
    "project:editor": (
        "project:read",
        "workflow:create", "workflow:read", "workflow:update",
        "workflow:execute", "workflow:delete",
        "credential:create", "credential:read", "credential:update",
        "credential:delete",
        "folder:create", "folder:read", "folder:update", "folder:delete",
    ),
    # Project Viewer: read-only; TIDAK boleh menjalankan workflow manual
    "project:viewer": _VIEW_ONLY + (
        "workflow:read", "credential:read", "folder:read",
    ),
}

#: Preset peran INSTANCE (Owner/Admin/Member, docs n8n).
INSTANCE_PRESETS: dict[str, tuple[str, ...]] = {
    "instance:owner": tuple(INSTANCE_SCOPES.keys()),
    "instance:admin": (
        "instanceSettings:manage", "members:manage",
        "roles:manageProject", "roles:manageAll",
        "apiKeys:manageOwn", "apiKeys:manageOthers",
        "tags:read", "tags:manage", "projects:create", "insights:read",
    ),
    # Member: hanya kelola dirinya + tag (tanpa delete tags) + workflow sendiri
    "instance:member": ("apiKeys:manageOwn", "tags:read", "tags:manage"),
}

PROJECT_PRESET_NAMES = tuple(PROJECT_PRESETS.keys())
INSTANCE_PRESET_NAMES = tuple(INSTANCE_PRESETS.keys())

#: Kombinasi yang berisiko privilege escalation (peringatan dokumentasi n8n).
ESCALATION_FLAGS: tuple[str, ...] = (
    "roles:manageAll", "roles:manageProject", "members:manage",
)


class RBACError(Exception):
    """Kesalahan umum RBAC."""


class ScopeUnknown(RBACError, ValueError):
    """Scope tidak ada dalam kosakata n8n."""


class RoleNotFound(RBACError):
    """Peran tidak ditemukan."""


class RoleInUse(RBACError):
    """Peran masih dipakai -> tidak boleh dihapus (perilaku n8n)."""


class RoleImmutable(RBACError):
    """Peran bawaan tidak boleh diubah/dihapus."""


class NotAuthorized(RBACError):
    """Aktor tidak punya scope yang dibutuhkan."""


class PrivilegeEscalationRisk(RBACError):
    """Definisi peran mengandung kombinasi berisiko (mode strict)."""


# ---------------------------------------------------------------------------
# Peran
# ---------------------------------------------------------------------------

_SLUG_RX = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class Role:
    """Sebuah peran (project ATAU instance).

    `builtin=True` berarti peran bawaan: tidak dapat diubah/dihapus.
    """

    def __init__(self, name: str, *, level: str = "project",
                 scopes: Optional[Iterable[str]] = None,
                 description: str = "", builtin: bool = False,
                 preset_of: str = "", created_by: str = "",
                 created_at: Optional[float] = None,
                 updated_at: Optional[float] = None) -> None:
        lvl = str(level).strip().lower()
        if lvl not in ("project", "instance"):
            raise RBACError(f"level harus 'project' atau 'instance', "
                            f"dapat {level!r}")
        n = str(name).strip()
        if not n:
            raise RBACError("nama peran wajib diisi")
        if not builtin and not _SLUG_RX.match(n):
            raise RBACError(
                f"nama peran harus slug huruf kecil (a-z0-9._-), dapat {n!r}")
        self.name = n
        self.level = lvl
        self.builtin = bool(builtin)
        self.description = description
        self.preset_of = preset_of
        self.created_by = created_by
        self._raw_scopes = tuple(dict.fromkeys(str(s) for s in (scopes or ())))
        bad = validate_scopes(self._raw_scopes)
        if bad:
            raise ScopeUnknown(f"scope tidak dikenal: {', '.join(bad)}")
        #: scopes = himpunan EFEKTIF (sudah termasuk implikasi otomatis).
        self.scopes: frozenset[str] = frozenset(expand_scopes(self._raw_scopes))
        self.created_at = float(created_at if created_at is not None
                                else time.time())
        self.updated_at = float(updated_at if updated_at is not None
                                else self.created_at)

    # -- bantuan ----------------------------------------------------------
    @property
    def granted(self) -> tuple[str, ...]:
        """Scope yang eksplisit diberikan (tanpa implikasi)."""
        return self._raw_scopes

    def has(self, scope: str) -> bool:
        return str(scope) in self.scopes

    def escalation_risks(self) -> list[str]:
        """Kombinasi berisiko yang dimiliki peran ini (peringatan n8n)."""
        risks: list[str] = []
        if "roles:manageAll" in self.scopes:
            risks.append(
                "roles:manageAll: dapat mengubah peran sendiri untuk "
                "menambah izin yang tidak diberikan semula")
        if "roles:manageProject" in self.scopes:
            risks.append(
                "roles:manageProject: dapat mengubah peran project yang "
                "dipegang sendiri untuk menambah izin")
        if "members:manage" in self.scopes:
            risks.append(
                "members:manage: dapat mengundang akun yang dikendalikan "
                "lalu memberinya akses tingkat Admin")
        return risks

    def to_dict(self) -> dict:
        return {
            "name": self.name, "level": self.level,
            "builtin": self.builtin, "description": self.description,
            "preset_of": self.preset_of, "created_by": self.created_by,
            "scopes": sorted(self.scopes), "granted": list(self._raw_scopes),
            "implied": sorted(self.scopes - set(self._raw_scopes)),
            "scope_count": len(self.scopes),
            "escalation_risks": self.escalation_risks(),
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# Registry peran + penetapan
# ---------------------------------------------------------------------------

class RoleRegistry:
    """Menyimpan peran kustom + penetapan peran ke pengguna dalam project."""

    def __init__(self, *, strict: bool = True,
                 clock: Callable[[], float] | None = None) -> None:
        self.strict = bool(strict)
        self._clock = clock or time.time
        self._lock = threading.RLock()
        #: name -> Role (peran kustom, project & instance)
        self.roles: dict[str, Role] = {}
        #: (project_id, user_id) -> role_name
        self.assignments: dict[tuple[str, str], str] = {}
        #: user_id -> instance role name
        self.instance_assignments: dict[str, str] = {}
        self.audit: list[dict] = []
        self._install_builtins()

    # -- bawaan -----------------------------------------------------------
    def _install_builtins(self) -> None:
        for name, scopes in PROJECT_PRESETS.items():
            self.roles[name] = Role(name, level="project", scopes=scopes,
                                    builtin=True, preset_of=name,
                                    description=f"bawaan n8n: {name}")
        for name, scopes in INSTANCE_PRESETS.items():
            self.roles[name] = Role(name, level="instance", scopes=scopes,
                                    builtin=True, preset_of=name,
                                    description=f"bawaan n8n: {name}")

    def builtin_names(self) -> list[str]:
        return sorted(n for n, r in self.roles.items() if r.builtin)

    # -- CRUD peran --------------------------------------------------------
    @staticmethod
    def _merge_preset(level: str, preset: str,
                      scopes: Optional[Iterable[str]]) -> tuple[str, ...]:
        """Gabungkan basis preset dengan scope eksplisit (dedup, urut stabil).

        `scopes=None` berarti "biarkan basis preset apa adanya".
        Ini dipakai bersama oleh `create_role` dan `update_role` supaya
        semantik keduanya identik — di UI n8n, mengedit peran yang berasal
        dari preset menampilkan kotak preset SUDAH tercentang, sehingga
        scope preset tidak hilang saat peran disimpan.
        """
        base: tuple[str, ...] = ()
        if preset:
            src = (PROJECT_PRESETS.get(preset) if level == "project"
                   else INSTANCE_PRESETS.get(preset))
            if src is None:
                raise RoleNotFound(f"preset tidak dikenal: {preset}")
            base = tuple(src)
        if scopes is None:
            return base
        return tuple(dict.fromkeys(list(base) + [str(s) for s in scopes]))

    def create_role(self, name: str, scopes: Iterable[str], *,
                    level: str = "project", description: str = "",
                    preset: str = "", created_by: str = "",
                    allow_escalation: bool = False) -> Role:
        """Buat peran kustom. `preset` mengisi scope awal dari peran bawaan."""
        lvl = str(level).strip().lower()
        merged = list(self._merge_preset(lvl, preset, scopes))
        with self._lock:
            if name in self.roles:
                raise RBACError(f"peran sudah ada: {name}")
            role = Role(name, level=lvl, scopes=merged, description=description,
                        preset_of=preset, created_by=created_by,
                        created_at=self._clock())
            risks = role.escalation_risks()
            if self.strict and risks and not allow_escalation:
                raise PrivilegeEscalationRisk(
                    "kombinasi izin berisiko terdeteksi: " + "; ".join(risks))
            self.roles[name] = role
            self._log("role_created", role=name, level=lvl,
                      scopes=sorted(role.scopes), risks=risks)
            return role

    def update_role(self, name: str, *, scopes: Optional[Iterable[str]] = None,
                    description: Optional[str] = None,
                    allow_escalation: bool = False) -> Role:
        """Ubah peran kustom.

        `scopes` MENGGANTIKAN scope eksplisit, tetapi basis preset
        (`preset_of`) selalu dipertahankan — lihat `_merge_preset`.
        Passing `scopes=None` mempertahankan scope eksplisit yang ada.
        """
        with self._lock:
            role = self.get_role(name)
            if role.builtin:
                raise RoleImmutable(f"peran bawaan tidak dapat diubah: {name}")
            effective_scopes = (role.granted if scopes is None
                                else self._merge_preset(role.level,
                                                        role.preset_of, scopes))
            candidate = Role(role.name, level=role.level,
                             scopes=effective_scopes,
                             description=(role.description if description
                                          is None else description),
                             preset_of=role.preset_of,
                             created_by=role.created_by,
                             created_at=role.created_at,
                             updated_at=self._clock())
            risks = candidate.escalation_risks()
            if self.strict and risks and not allow_escalation:
                raise PrivilegeEscalationRisk(
                    "kombinasi izin berisiko terdeteksi: " + "; ".join(risks))
            self.roles[name] = candidate
            self._log("role_updated", role=name, scopes=sorted(candidate.scopes))
            return candidate

    def duplicate_role(self, name: str, new_name: str, *,
                       created_by: str = "") -> Role:
        """Salin peran. Himpunan EFEKTIF disalin apa adanya.

        Penting: `preset_of` sengaja dikosongkan. Bila preset ikut diteruskan,
        `create_role` akan menambahkan basis preset **lagi** di atas scope
        yang sudah memuatnya -> duplikat jadi lebih luas dari aslinya.
        """
        with self._lock:
            src = self.get_role(name)
            if str(new_name) in self.roles:
                raise RBACError(f"peran sudah ada: {new_name}")
            role = Role(new_name, level=src.level, scopes=src.granted,
                        description=src.description, preset_of="",
                        created_by=created_by, created_at=self._clock())
            risks = role.escalation_risks()
            if self.strict and risks:
                raise PrivilegeEscalationRisk(
                    "kombinasi izin berisiko terdeteksi: " + "; ".join(risks))
            self.roles[role.name] = role
            self._log("role_duplicated", role=role.name, source=src.name,
                      level=src.level, scopes=sorted(role.scopes))
            return role

    def delete_role(self, name: str) -> dict:
        """Hapus peran. Peran yang masih dipakai DITOLAK (perilaku n8n)."""
        with self._lock:
            role = self.get_role(name)
            if role.builtin:
                raise RoleImmutable(f"peran bawaan tidak dapat dihapus: {name}")
            in_proj = [k for k, v in self.assignments.items() if v == name]
            in_inst = [u for u, v in self.instance_assignments.items() if v == name]
            total = len(in_proj) + len(in_inst)
            if total:
                raise RoleInUse(
                    f"peran masih dipakai oleh {total} penetapan; "
                    "pindahkan pengguna terlebih dahulu")
            del self.roles[name]
            self._log("role_deleted", role=name)
            return {"role": name, "deleted": True, "reassigned": 0}

    def get_role(self, name: str) -> Role:
        r = self.roles.get(str(name))
        if r is None:
            raise RoleNotFound(f"peran tidak ditemukan: {name}")
        return r

    def list_roles(self, *, level: str = "") -> list[dict]:
        lvl = str(level).strip().lower()
        return [r.to_dict() for r in self.roles.values()
                if not lvl or r.level == lvl]

    # -- penetapan ---------------------------------------------------------
    def assign(self, project_id: str, user_id: str, role_name: str) -> dict:
        """Tetapkan peran project. Peran project hanya berlaku di project itu."""
        with self._lock:
            role = self.get_role(role_name)
            if role.level != "project":
                raise RBACError(
                    f"{role_name!r} adalah peran instance; pakai "
                    "assign_instance()")
            key = (str(project_id), str(user_id))
            self.assignments[key] = role.name
            self._log("role_assigned", project_id=str(project_id),
                      user_id=str(user_id), role=role.name)
            return {"project_id": str(project_id), "user_id": str(user_id),
                    "role": role.name, "scopes": sorted(role.scopes)}

    def unassign(self, project_id: str, user_id: str) -> bool:
        with self._lock:
            key = (str(project_id), str(user_id))
            if key not in self.assignments:
                return False
            self.assignments.pop(key)
            self._log("role_unassigned", project_id=str(project_id),
                      user_id=str(user_id))
            return True

    def assign_instance(self, user_id: str, role_name: str) -> dict:
        """Tetapkan peran instance (satu per pengguna)."""
        with self._lock:
            role = self.get_role(role_name)
            if role.level != "instance":
                raise RBACError(
                    f"{role_name!r} adalah peran project; pakai assign()")
            self.instance_assignments[str(user_id)] = role.name
            self._log("instance_role_assigned", user_id=str(user_id),
                      role=role.name)
            return {"user_id": str(user_id), "role": role.name,
                    "scopes": sorted(role.scopes)}

    # -- pembacaan ---------------------------------------------------------
    def roles_for(self, user_id: str, project_id: str = "") -> list[Role]:
        """Peran EFEKTIF pengguna: instance + (opsional) di project itu."""
        out: list[Role] = []
        inst = self.instance_assignments.get(str(user_id))
        if inst:
            r = self.roles.get(inst)
            if r is not None:
                out.append(r)
        if project_id:
            pname = self.assignments.get((str(project_id), str(user_id)))
            if pname:
                r = self.roles.get(pname)
                if r is not None:
                    out.append(r)
        return out

    def effective_scopes(self, user_id: str, project_id: str = "") -> set[str]:
        out: set[str] = set()
        for r in self.roles_for(user_id, project_id):
            out |= set(r.scopes)
        return out

    def members_of(self, project_id: str) -> list[dict]:
        return [{"project_id": p, "user_id": u, "role": v}
                for (p, u), v in sorted(self.assignments.items())
                if p == str(project_id)]

    def projects_of(self, user_id: str) -> list[str]:
        return sorted({p for (p, u) in self.assignments
                       if u == str(user_id)})

    # -- audit -------------------------------------------------------------
    def _log(self, event: str, **kw: Any) -> None:
        row = {"event": event, "at": self._clock(), **kw}
        self.audit.append(row)

    def stats(self) -> dict:
        with self._lock:
            custom = [r for r in self.roles.values() if not r.builtin]
            return {
                "roles_total": len(self.roles),
                "roles_builtin": len(self.roles) - len(custom),
                "roles_custom": len(custom),
                "project_assignments": len(self.assignments),
                "instance_assignments": len(self.instance_assignments),
                "audit_events": len(self.audit),
                "strict": self.strict,
                "enforce_escalation_guard": self.strict,
            }


# ---------------------------------------------------------------------------
# Authorizer
# ---------------------------------------------------------------------------

class Authorizer:
    """Pemeriksa otorisasi: `allow(user, scope, project)`."""

    def __init__(self, reg: RoleRegistry | None = None, *,
                 enforce: bool = True) -> None:
        self.registry = reg or RoleRegistry()
        self.enforce = bool(enforce)
        self.checks = 0
        self.denials: list[dict] = []
        self._lock = threading.RLock()

    def scopes(self, user_id: str, project_id: str = "") -> set[str]:
        return self.registry.effective_scopes(user_id, project_id)

    def allow(self, user_id: str, scope: str, *, project_id: str = "") -> bool:
        need = expand_scopes([scope])
        with self._lock:
            self.checks += 1
        have = self.scopes(user_id, project_id)
        ok = need <= have
        if not ok:
            with self._lock:
                self.denials.append({
                    "user_id": str(user_id), "scope": str(scope),
                    "project_id": str(project_id),
                    "missing": sorted(need - have)})
        return ok

    def allows_any(self, user_id: str, scopes: Iterable[str], *,
                   project_id: str = "") -> bool:
        """True bila pengguna memiliki SETIDAKNYA SATU dari scope diminta.

        Fail-closed: permintaan kosong -> False (tidak ada yang boleh).
        """
        need = expand_scopes(scopes)
        if not need:
            return False
        return bool(need & self.scopes(user_id, project_id))

    def require(self, user_id: str, scope: str, *, project_id: str = "") -> None:
        """Lempar NotAuthorized bila scope tidak dimiliki."""
        if not self.allow(user_id, scope, project_id=project_id):
            raise NotAuthorized(
                f"pengguna {user_id} tidak memiliki scope {scope!r}"
                + (f" di project {project_id}" if project_id else ""))

    def require_all(self, user_id: str, scopes: Iterable[str], *,
                    project_id: str = "") -> None:
        for s in scopes:
            self.require(user_id, s, project_id=project_id)

    def assert_can_grant(self, actor_id: str, target_scopes: Iterable[str], *,
                         project_id: str = "") -> None:
        """Cegah pemberian izin melebihi milik aktor (anti-escalation).

        Aturan n8n: hanya pengguna dengan `roles:manageProject` boleh
        membuat/mengubah peran project; dan peran yang dibuat tidak boleh
        memuat scope yang tidak dimiliki aktor.
        """
        target = expand_scopes(target_scopes)
        have = self.scopes(actor_id, project_id)
        extra = target - have
        if extra:
            raise PrivilegeEscalationRisk(
                "aktor tidak boleh memberikan scope yang tidak dimilikinya: "
                + ", ".join(sorted(extra)))

    def describe_request(self, user_id: str, scope: str, *,
                         project_id: str = "") -> str:
        have = self.scopes(user_id, project_id)
        return (f"{scope}: {'ALLOW' if expand_scopes([scope]) <= have else 'DENY'}"
                f" | user={user_id} project={project_id or '-'}"
                f" | scopes={len(have)}")

    def stats(self) -> dict:
        with self._lock:
            return {"checks": self.checks, "denials": len(self.denials),
                    "enforce": self.enforce,
                    "recent_denials": self.denials[-10:]}


# ---------------------------------------------------------------------------
# Registry proses + factory
# ---------------------------------------------------------------------------

_REGISTRY: RoleRegistry | None = None
_AUTHORIZER: Authorizer | None = None


def registry() -> RoleRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = rbac_from_env()[0]
    return _REGISTRY


def set_registry(new: RoleRegistry | None) -> None:
    global _REGISTRY, _AUTHORIZER
    _REGISTRY = new
    _AUTHORIZER = None


def authorizer() -> Authorizer:
    global _AUTHORIZER
    if _AUTHORIZER is None:
        _AUTHORIZER = Authorizer(registry())
    return _AUTHORIZER


def set_authorizer(new: Authorizer | None) -> None:
    global _AUTHORIZER
    _AUTHORIZER = new


def _env_flag(env: dict, name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on", "ya")


def rbac_from_env(env: dict | None = None) -> tuple[RoleRegistry, Authorizer]:
    e = env if env is not None else os.environ
    reg = RoleRegistry(strict=_env_flag(e, "KATALIR_RBAC_STRICT", True))
    return reg, Authorizer(reg)


def describe(env: dict | None = None) -> dict:
    e = env if env is not None else os.environ
    reg = RoleRegistry(strict=_env_flag(e, "KATALIR_RBAC_STRICT", True))
    return {
        "levels": ["instance", "project"],
        "project_scope_groups": {k: sorted(v) for k, v in SCOPE_GROUPS.items()},
        "project_scope_count": len(PROJECT_SCOPES),
        "instance_scopes": sorted(INSTANCE_SCOPES),
        "instance_scope_count": len(INSTANCE_SCOPES),
        "project_presets": list(PROJECT_PRESET_NAMES),
        "instance_presets": list(INSTANCE_PRESET_NAMES),
        "implied_scopes": {k: list(v) for k, v in IMPLIED_SCOPES.items()},
        "read_implies_list": True,
        "listable_resources": sorted(LISTABLE_RESOURCES),
        "derived_scopes": sorted(DERIVED_SCOPES),
        "all_scopes_count": len(ALL_SCOPES),
        "escalation_flags": list(ESCALATION_FLAGS),
        "strict": reg.strict,
        "builtin_roles": reg.builtin_names(),
    }
