# plugin_system.py — Fitur #11: Plugin / Extension System (Okt 2026)
# ======================================================================
# SDK + registry + marketplace internal untuk plugin pihak ketiga: install/
# uninstall dari UI, sandbox ber-CAPABILITY (plugin hanya boleh memakai
# kemampuan yang dideklarasikan), versioning + resolusi dependensi, dan alur
# review/approval sebelum plugin dipublikasikan.
#
# RISET (Okt 2026): pola plugin Python = entry-points/pluggy untuk penemuan,
# tetapi untuk ISOLASI + MARKETPLACE perlu lapisan manifest + capability +
# review. KEPUTUSAN: manifest JSON + registry in-house (deterministik, dapat
# di-hard-test). Eksekusi handler disuntik sehingga tidak ada impor kode asing.
#
# KEAMANAN: plugin TIDAK PERNAH boleh mengakses `secrets`/`db`/`env`/`exec`.
# Capability berbahaya ditolak saat INSTALL (fail-closed).
# ======================================================================

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

#: Kemampuan yang BOLEH diminta plugin.
SAFE_CAPABILITIES = {
    "http", "kv", "log", "workflow.read", "workflow.write", "notify",
}

#: Kemampuan TERLARANG (langsung memblokir plugin).
FORBIDDEN_CAPABILITIES = {
    "secrets", "vault", "db", "database", "env", "exec", "eval", "shell",
    "filesystem", "admin",
}

#: Versi platform saat ini (untuk cek kompatibilitas).
KATALIR_VERSION = "1.6.0"

# Nama plugin: huruf kecil/angka, boleh `.` `_` `-` di tengah, 3-64 karakter,
# wajib diawali & diakhiri alfanumerik.
#
# CATATAN (bug ditemukan oleh hard test LIVE): pola lama
# `^[a-z0-9]([a-z0-9._-]{1,62}[a-z0-9])?$` TIDAK KOHEREN — grup opsionalnya
# membuat nama 1 karakter ("x") DITERIMA, sementara nama 2 karakter ("ok")
# DITOLAK. Kebijakan panjang yang tidak monoton seperti itu jelas keliru, jadi
# ambang minimum kini eksplisit: >= 3 karakter.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}[a-z0-9]$")


class PluginError(Exception):
    pass


class PluginBlocked(PluginError):
    """Plugin diblokir (capability terlarang / signature tak sah)."""


class CapabilityDenied(PluginError):
    """Plugin mencoba memakai capability yang tidak dideklarasikan."""


class DependencyError(PluginError):
    pass


class CompatibilityError(PluginError):
    pass


# ---------------------------------------------------------------------------
# Semver
# ---------------------------------------------------------------------------

def parse_semver(v: str) -> tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(v or "").strip())
    if not m:
        raise PluginError(f"versi semver tidak valid: {v!r}")
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def semver_gt(a: str, b: str) -> bool:
    return parse_semver(a) > parse_semver(b)


def semver_satisfies(version: str, spec: str) -> bool:
    """Dukung `>=x.y.z`, `>`, `<=`, `<`, `==`, dan `^x.y.z` (caret)."""
    spec = (spec or "").strip()
    if not spec or spec == "*":
        return True
    v = parse_semver(version)
    for bagian in [s.strip() for s in spec.split(",") if s.strip()]:
        m = re.match(r"^(\^|>=|<=|>|<|==)?\s*(\d+\.\d+\.\d+)", bagian)
        if not m:
            continue
        op = m.group(1) or "=="
        target = parse_semver(m.group(2))
        if op == ">=" and not v >= target:
            return False
        if op == ">" and not v > target:
            return False
        if op == "<=" and not v <= target:
            return False
        if op == "<" and not v < target:
            return False
        if op == "==" and not v == target:
            return False
        if op == "^":
            # kompatibel dalam major yang sama, >= target
            if not (v[0] == target[0] and v >= target):
                return False
    return True


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

@dataclass
class PluginManifest:
    name: str
    version: str = "1.0.0"
    entry: str = ""
    capabilities: list[str] = field(default_factory=list)
    dependencies: dict[str, str] = field(default_factory=dict)
    min_katalir_version: str = ""
    author: str = ""
    description: str = ""
    signature: str = ""

    def validate(self) -> list[str]:
        errs: list[str] = []
        if not _NAME_RE.match(self.name or ""):
            errs.append(f"nama plugin tidak valid: {self.name!r}")
        try:
            parse_semver(self.version)
        except PluginError as exc:
            errs.append(str(exc))
        if not self.entry:
            errs.append("entry wajib diisi")
        buruk = [c for c in self.capabilities if c in FORBIDDEN_CAPABILITIES]
        if buruk:
            errs.append(f"capability terlarang: {sorted(buruk)}")
        tak_dikenal = [c for c in self.capabilities if c not in SAFE_CAPABILITIES]
        if tak_dikenal:
            errs.append(f"capability tidak dikenal: {sorted(tak_dikenal)}")
        return errs

    @classmethod
    def from_dict(cls, d: dict) -> "PluginManifest":
        return cls(
            name=str(d.get("name", "")), version=str(d.get("version", "1.0.0")),
            entry=str(d.get("entry", "")),
            capabilities=list(d.get("capabilities") or []),
            dependencies=dict(d.get("dependencies") or {}),
            min_katalir_version=str(d.get("min_katalir_version", "")),
            author=str(d.get("author", "")),
            description=str(d.get("description", "")),
            signature=str(d.get("signature", "")))

    def to_dict(self) -> dict:
        return {"name": self.name, "version": self.version, "entry": self.entry,
                "capabilities": self.capabilities,
                "dependencies": self.dependencies,
                "min_katalir_version": self.min_katalir_version,
                "author": self.author, "description": self.description,
                "signature": bool(self.signature)}


# ---------------------------------------------------------------------------
# Sandbox ber-capability
# ---------------------------------------------------------------------------

class Sandbox:
    """Menjalankan handler plugin dengan pembatasan capability.

    Handler menerima `(capability, kwargs)`; sandbox menolak capability yang
    tidak dideklarasikan. Akses ke secrets/db/env MUSTAHIL dari sini.
    """

    def __init__(self, manifest: PluginManifest) -> None:
        self.manifest = manifest
        self.allowed = set(manifest.capabilities)

    def call(self, capability: str, handler: Callable, **kwargs) -> Any:
        cap = (capability or "").strip()
        if cap in FORBIDDEN_CAPABILITIES:
            raise CapabilityDenied(
                f"plugin {self.manifest.name} mencoba capability terlarang: {cap}")
        if cap not in self.allowed:
            raise CapabilityDenied(
                f"capability {cap!r} tidak dideklarasikan oleh "
                f"{self.manifest.name}")
        return handler(cap, kwargs)


# ---------------------------------------------------------------------------
# Registry + marketplace
# ---------------------------------------------------------------------------

class Plugin:
    def __init__(self, manifest: PluginManifest,
                 handler: Callable[[str, dict], Any]) -> None:
        self.manifest = manifest
        self.handler = handler
        self.enabled = True
        self.installed_at = time.time()
        self.sandbox = Sandbox(manifest)

    def call(self, capability: str, **kwargs) -> Any:
        if not self.enabled:
            raise PluginError(f"plugin {self.manifest.name} nonaktif")
        return self.sandbox.call(capability, self.handler, **kwargs)


class PluginRegistry:
    """Marketplace internal: daftar + cari plugin."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    def register(self, manifest: PluginManifest, handler: Callable) -> Plugin:
        p = Plugin(manifest, handler)
        self._plugins[manifest.name] = p
        return p

    def get(self, name: str) -> Optional[Plugin]:
        return self._plugins.get(name)

    def remove(self, name: str) -> bool:
        return self._plugins.pop(name, None) is not None

    def list(self) -> list[dict]:
        return [{"name": p.manifest.name, "version": p.manifest.version,
                 "enabled": p.enabled, "author": p.manifest.author,
                 "description": p.manifest.description,
                 "capabilities": p.manifest.capabilities}
                for p in self._plugins.values()]

    def search(self, q: str = "") -> list[dict]:
        q = (q or "").lower().strip()
        hasil = []
        for p in self._plugins.values():
            blob = f"{p.manifest.name} {p.manifest.description} " \
                   f"{p.manifest.author}".lower()
            if not q or q in blob:
                hasil.append({"name": p.manifest.name,
                              "version": p.manifest.version,
                              "description": p.manifest.description})
        return hasil


# ---------------------------------------------------------------------------
# Manajer: install/uninstall, dependensi, review
# ---------------------------------------------------------------------------

class PluginManager:
    def __init__(self, registry: Optional[PluginRegistry] = None,
                 katalir_version: str = KATALIR_VERSION,
                 require_signature: bool = False,
                 store: Optional[PluginStore] = None,
                 owner: str = "") -> None:
        self.registry = registry or PluginRegistry()
        self.katalir_version = katalir_version
        self.require_signature = require_signature
        # `store`/`owner` OPSIONAL: bila None, perilaku tetap murni in-memory
        # (unit test tak butuh jaringan). Bila diisi, setiap mutasi dicerminkan
        # ke store sehingga registry bertahan lintas restart.
        self.store = store
        self.owner = owner
        self._reviews: dict[str, dict] = {}
        self._audit: list[dict] = []
        self._calls = 0

    # -- durability --------------------------------------------------------
    def hydrate(self, handler: Optional[Callable] = None) -> list[str]:
        """Muat ulang plugin dari store ke registry (dipanggil saat startup).

        Hanya manifest yang dipulihkan; handler tetap kode server (handler
        default = no-op yang aman). Manifest yang kini tidak valid (mis. versi
        platform naik) DILEWATI, bukan mematikan startup.
        """
        if not self.store:
            return []
        h = handler or (lambda cap, kwargs: {"capability": cap, "args": kwargs})
        dimuat: list[str] = []
        for rec in self.store.list(self.owner):
            try:
                man = PluginManifest.from_dict(rec.get("manifest") or {})
                if man.validate():
                    continue
                self.check_compatibility(man)
            except Exception:  # noqa: BLE001
                continue
            p = self.registry.register(man, h)
            p.enabled = bool(rec.get("enabled", True))
            dimuat.append(man.name)
        if dimuat:
            self._log("hydrate", "*", count=len(dimuat))
        return dimuat

    # -- audit -------------------------------------------------------------
    def _log(self, action: str, name: str, **extra) -> None:
        self._audit.append({"action": action, "plugin": name,
                            "at": time.time(), **extra})

    def audit(self) -> list[dict]:
        return list(self._audit)

    # -- kompatibilitas ----------------------------------------------------
    def check_compatibility(self, manifest: PluginManifest) -> None:
        if manifest.min_katalir_version:
            if parse_semver(manifest.min_katalir_version) > parse_semver(
                    self.katalir_version):
                raise CompatibilityError(
                    f"butuh Katalir >= {manifest.min_katalir_version}, "
                    f"platform {self.katalir_version}")

    # -- instalasi ---------------------------------------------------------
    def install(self, manifest: PluginManifest, handler: Callable,
                allow_unsigned: bool = True) -> dict:
        """Validasi -> cek kompatibilitas -> daftar. Fail-closed pada bahaya."""
        errs = manifest.validate()
        if errs:
            # capability terlarang => PluginBlocked (bukan sekadar error)
            if any("terlarang" in e for e in errs):
                self._log("install_blocked", manifest.name, errors=errs)
                raise PluginBlocked("; ".join(errs))
            raise PluginError("; ".join(errs))
        self.check_compatibility(manifest)
        if self.require_signature and not manifest.signature and not allow_unsigned:
            raise PluginBlocked("signature wajib untuk plugin ini")
        # dependensi harus tersedia
        self.resolve_dependencies(manifest)
        lama = self.registry.get(manifest.name)
        if lama and semver_gt(lama.manifest.version, manifest.version):
            raise PluginError(
                f"versi {manifest.version} lebih lama dari terpasang "
                f"{lama.manifest.version}")
        p = self.registry.register(manifest, handler)
        if self.store:
            self.store.save(self.owner, manifest, p.enabled)
        self._log("install", manifest.name, version=manifest.version,
                  updated=bool(lama))
        return {"name": manifest.name, "version": manifest.version,
                "updated": bool(lama), "enabled": p.enabled}

    def uninstall(self, name: str) -> bool:
        ok = self.registry.remove(name)
        if self.store:
            self.store.delete(self.owner, name)
        self._log("uninstall", name, removed=ok)
        return ok

    def set_enabled(self, name: str, enabled: bool) -> bool:
        p = self.registry.get(name)
        if not p:
            return False
        p.enabled = bool(enabled)
        if self.store:
            self.store.set_enabled(self.owner, name, p.enabled)
        self._log("enable" if enabled else "disable", name)
        return True

    def call(self, name: str, capability: str, **kwargs) -> Any:
        p = self.registry.get(name)
        if not p:
            raise PluginError(f"plugin tidak terpasang: {name}")
        self._calls += 1
        return p.call(capability, **kwargs)

    # -- dependensi --------------------------------------------------------
    def resolve_dependencies(self, manifest: PluginManifest) -> list[str]:
        """Urutan instalasi (dependency dulu). Deteksi hilang/versi/cycle."""
        urutan: list[str] = []
        sedang: set[str] = set()
        selesai: set[str] = set()

        def kunjungi(m: PluginManifest, rantai: list[str]) -> None:
            if m.name in selesai:
                return
            if m.name in sedang:
                raise DependencyError(
                    f"siklus dependensi: {' -> '.join(rantai + [m.name])}")
            sedang.add(m.name)
            for dep, spec in (m.dependencies or {}).items():
                terpasang = self.registry.get(dep)
                if not terpasang:
                    raise DependencyError(
                        f"dependensi hilang: {dep} (dibutuhkan {m.name})")
                if not semver_satisfies(terpasang.manifest.version, spec):
                    raise DependencyError(
                        f"versi {dep} {terpasang.manifest.version} tidak "
                        f"memenuhi {spec!r} (dibutuhkan {m.name})")
                kunjungi(terpasang.manifest, rantai + [m.name])
            sedang.discard(m.name)
            selesai.add(m.name)
            urutan.append(m.name)

        kunjungi(manifest, [])
        return urutan

    # -- review / marketplace ---------------------------------------------
    def submit_for_review(self, manifest: PluginManifest) -> dict:
        errs = manifest.validate()
        rid = f"rev-{manifest.name}-{int(time.time() * 1000)}"
        rec = {"request_id": rid, "name": manifest.name,
               "version": manifest.version, "errors": errs,
               "status": "pending", "at": time.time()}
        self._reviews[rid] = rec
        self._log("review_submitted", manifest.name, request_id=rid)
        return dict(rec)

    def approve(self, request_id: str, reviewer: str = "") -> dict:
        rec = self._reviews.get(request_id)
        if not rec:
            raise PluginError(f"review tidak ditemukan: {request_id}")
        if rec["errors"]:
            raise PluginBlocked(f"plugin punya pelanggaran: {rec['errors']}")
        rec["status"] = "approved"
        rec["reviewer"] = reviewer
        self._log("review_approved", rec["name"], request_id=request_id)
        return dict(rec)

    def reject(self, request_id: str, reason: str = "") -> dict:
        rec = self._reviews.get(request_id)
        if not rec:
            raise PluginError(f"review tidak ditemukan: {request_id}")
        rec["status"] = "rejected"
        rec["reason"] = reason
        self._log("review_rejected", rec["name"], request_id=request_id)
        return dict(rec)

    def reviews(self) -> list[dict]:
        return [dict(r) for r in self._reviews.values()]

    def stats(self) -> dict:
        return {"installed": len(self.registry.list()),
                "calls": self._calls,
                "reviews": len(self._reviews)}


# ---------------------------------------------------------------------------
# Persistensi registry (durability)
# ---------------------------------------------------------------------------
# Registry in-memory hilang saat proses restart. Untuk produksi, manifest
# disimpan di tabel `plugin_registry` (Supabase) sehingga plugin yang dipasang
# bertahan lintas deploy. Pola sama dengan fitur #4/#5/#7: base store memori +
# subclass Supabase dengan antarmuka identik, sehingga unit test tetap murni
# tanpa jaringan.
#
# Plugin TIDAK menyimpan kode di DB — hanya manifest (deklaratif). Handler tetap
# kode server; `entry` adalah penunjuk, bukan kode yang dieksekusi dari DB.

class PluginStore:
    """Store default (memori) — dipakai unit test & bila DB tak tersedia."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], dict] = {}

    def save(self, owner: str, manifest: "PluginManifest",
             enabled: bool = True) -> dict:
        rec = {"owner": owner, "name": manifest.name,
               "version": manifest.version, "manifest": manifest.to_dict(),
               "enabled": bool(enabled), "installed_at": time.time()}
        self._rows[(owner, manifest.name)] = rec
        return dict(rec)

    def delete(self, owner: str, name: str) -> bool:
        return self._rows.pop((owner, name), None) is not None

    def set_enabled(self, owner: str, name: str, enabled: bool) -> bool:
        rec = self._rows.get((owner, name))
        if rec is None:
            return False
        rec["enabled"] = bool(enabled)
        return True

    def list(self, owner: str) -> list[dict]:
        return [dict(r) for (o, _), r in self._rows.items() if o == owner]


class SupabasePluginStore(PluginStore):
    """Store `plugin_registry` (Supabase). Baca gagal -> kosong, tulis -> error."""

    def _svc(self):
        import database as db
        return db.get_write_client()

    def save(self, owner: str, manifest: "PluginManifest",
             enabled: bool = True) -> dict:
        rec = {"owner": owner, "name": manifest.name,
               "version": manifest.version, "manifest": manifest.to_dict(),
               "enabled": bool(enabled)}
        try:
            self._svc().table("plugin_registry").upsert(
                rec, on_conflict="owner,name").execute()
        except Exception as exc:  # noqa: BLE001
            raise PluginError(
                f"gagal menyimpan plugin: {type(exc).__name__}") from exc
        return dict(rec)

    def delete(self, owner: str, name: str) -> bool:
        try:
            self._svc().table("plugin_registry").delete().eq(
                "owner", owner).eq("name", name).execute()
            return True
        except Exception as exc:  # noqa: BLE001
            raise PluginError(
                f"gagal menghapus plugin: {type(exc).__name__}") from exc

    def set_enabled(self, owner: str, name: str, enabled: bool) -> bool:
        try:
            self._svc().table("plugin_registry").update(
                {"enabled": bool(enabled)}).eq("owner", owner).eq(
                "name", name).execute()
            return True
        except Exception as exc:  # noqa: BLE001
            raise PluginError(
                f"gagal mengubah status plugin: {type(exc).__name__}") from exc

    def list(self, owner: str) -> list[dict]:
        try:
            res = (self._svc().table("plugin_registry").select("*")
                   .eq("owner", owner).order("name").execute())
            return [dict(r) for r in (res.data or [])]
        except Exception:  # noqa: BLE001
            return []


def default_store() -> PluginStore:
    """Store default: Supabase bila tabel hidup, jika tidak -> memori."""
    try:
        import database  # noqa: F401
        s = SupabasePluginStore()
        s._svc().table("plugin_registry").select("id").limit(1).execute()
        return s
    except Exception:  # noqa: BLE001
        return PluginStore()
