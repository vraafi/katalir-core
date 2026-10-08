# environments.py — Fitur #4: Multi-Environment dev/staging/production (Okt 2026)
# ======================================================================
# Workflow hidup di beberapa environment terpisah; perubahan dipromosikan
# dev -> staging -> production dengan gerbang approval untuk production.
#
# RISET (Okt 2026): pola "environment promotion + approval gate + credential
# isolation + rollback" adalah standar SaaS (Vercel/Netlify envs, n8n envs).
# KEPUTUSAN: implementasi in-house di atas store yang dapat disuntik (memori
# untuk test, Supabase untuk produksi) — nol dependensi baru, dapat diuji
# deterministik, dan tidak mengunci ke vendor.
# ======================================================================

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Optional

#: Environment standar. `production` dilindungi approval.
ENVIRONMENTS: tuple[str, ...] = ("dev", "staging", "production")
PROTECTED: tuple[str, ...] = ("production",)

#: Urutan promosi yang diizinkan (hanya maju satu langkah).
PROMOTION_ORDER: dict[str, str] = {"dev": "staging", "staging": "production"}

#: Peran yang boleh mempromosikan ke environment tertentu.
ROLE_RIGHTS: dict[str, set[str]] = {
    "viewer": set(),
    "developer": {"dev", "staging"},
    "admin": {"dev", "staging", "production"},
    "owner": {"dev", "staging", "production"},
}


class EnvError(Exception):
    """Kesalahan pada lapisan multi-environment."""


class UnknownEnvironment(EnvError):
    pass


class ApprovalRequired(EnvError):
    """Promosi ke environment terlindungi butuh persetujuan."""

    def __init__(self, request_id: str):
        self.request_id = request_id
        super().__init__(
            f"promosi ke environment terlindungi butuh approval "
            f"(request={request_id})")


class Forbidden(EnvError):
    pass


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# Store (memori default; Supabase dapat disuntik)
# ---------------------------------------------------------------------------

class EnvStore:
    """Penyimpanan versi workflow per-environment.

    Kunci: (owner, env, workflow_id) -> daftar versi (append-only).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[tuple[str, str, str], list[dict]] = {}
        self._audit: list[dict] = []
        self._pending: dict[str, dict] = {}

    def put(self, owner: str, env: str, workflow_id: str, flow_data: dict,
            config: Optional[dict] = None, note: str = "") -> dict:
        with self._lock:
            kunci = (owner, env, workflow_id)
            versi = len(self._data.get(kunci, [])) + 1
            rec = {
                "owner": owner, "env": env, "workflow_id": workflow_id,
                "version": versi, "flow_data": flow_data,
                "config": config or {}, "note": note, "updated_at": _now(),
            }
            self._data.setdefault(kunci, []).append(rec)
            return dict(rec)

    def latest(self, owner: str, env: str, workflow_id: str) -> Optional[dict]:
        with self._lock:
            rows = self._data.get((owner, env, workflow_id))
            return dict(rows[-1]) if rows else None

    def history(self, owner: str, env: str, workflow_id: str) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._data.get((owner, env, workflow_id), [])]

    def get_version(self, owner: str, env: str, workflow_id: str,
                    version: int) -> Optional[dict]:
        with self._lock:
            for r in self._data.get((owner, env, workflow_id), []):
                if r["version"] == version:
                    return dict(r)
            return None

    def list_workflows(self, owner: str, env: str) -> list[str]:
        with self._lock:
            return sorted({k[2] for k in self._data
                           if k[0] == owner and k[1] == env})

    def audit(self, entry: dict) -> None:
        with self._lock:
            self._audit.append(dict(entry))

    def audit_trail(self, owner: str = "") -> list[dict]:
        with self._lock:
            return [dict(e) for e in self._audit
                    if not owner or e.get("owner") == owner]

    # pending approvals
    def add_pending(self, rec: dict) -> None:
        with self._lock:
            self._pending[rec["request_id"]] = rec

    def pop_pending(self, request_id: str) -> Optional[dict]:
        with self._lock:
            return self._pending.pop(request_id, None)

    def get_pending(self, request_id: str) -> Optional[dict]:
        with self._lock:
            r = self._pending.get(request_id)
            return dict(r) if r else None

    def list_pending(self, owner: str = "") -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._pending.values()
                    if not owner or r.get("owner") == owner]


# ---------------------------------------------------------------------------
# Diff struktural
# ---------------------------------------------------------------------------

def _nodes(flow_data: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for n in (flow_data or {}).get("nodes", []) or []:
        nid = str(n.get("id") or n.get("node_id") or "")
        if nid:
            out[nid] = n
    return out


def _edges(flow_data: dict) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for e in (flow_data or {}).get("edges", []) or []:
        a = str(e.get("source") or e.get("from") or "")
        b = str(e.get("target") or e.get("to") or "")
        if a or b:
            out.add((a, b))
    return out


def diff_flow(a: dict, b: dict) -> dict:
    """Diff struktural dua `flow_data`. Return ringkasan perubahan."""
    na, nb = _nodes(a), _nodes(b)
    ea, eb = _edges(a), _edges(b)
    ditambah = sorted(set(nb) - set(na))
    dihapus = sorted(set(na) - set(nb))
    diubah = sorted(
        nid for nid in set(na) & set(nb)
        if na[nid] != nb[nid])
    return {
        "nodes_added": ditambah,
        "nodes_removed": dihapus,
        "nodes_changed": diubah,
        "edges_added": sorted(f"{x}->{y}" for x, y in (eb - ea)),
        "edges_removed": sorted(f"{x}->{y}" for x, y in (ea - eb)),
        "changed": bool(ditambah or dihapus or diubah or (ea ^ eb)),
    }


# ---------------------------------------------------------------------------
# Isolasi credential per environment
# ---------------------------------------------------------------------------

def credential_key(owner: str, env: str, provider: str) -> str:
    """Kunci credential terisolasi per environment.

    Bentuk: `env:<env>:<provider>`. Dipakai sebagai namespace vault sehingga
    credential dev tidak pernah terpakai di production.
    """
    if env not in ENVIRONMENTS:
        raise UnknownEnvironment(env)
    return f"env:{env}:{provider}"


def resolve_credential_ref(owner: str, env: str, provider: str,
                           field: str = "") -> str:
    """Bangun referensi `secret://` untuk credential env tertentu."""
    kunci = credential_key(owner, env, provider)
    return f"secret://{kunci}/{field}" if field else f"secret://{kunci}"


# ---------------------------------------------------------------------------
# Mesin environment
# ---------------------------------------------------------------------------

class Environments:
    """Operasi environment: create/promote/diff/rollback + approval + audit."""

    def __init__(self, store: Optional[EnvStore] = None) -> None:
        self.store = store or EnvStore()

    # -- create / import ---------------------------------------------------
    def create(self, owner: str, env: str, workflow_id: str, flow_data: dict,
               config: Optional[dict] = None, role: str = "owner") -> dict:
        if env not in ENVIRONMENTS:
            raise UnknownEnvironment(env)
        if env not in ROLE_RIGHTS.get(role, set()):
            raise Forbidden(f"peran {role!r} tidak boleh menulis ke {env}")
        rec = self.store.put(owner, env, workflow_id, flow_data, config,
                             note="create")
        self.store.audit({"owner": owner, "action": "create", "env": env,
                          "workflow_id": workflow_id, "version": rec["version"],
                          "role": role, "at": _now()})
        return rec

    def import_existing(self, owner: str, workflow_id: str, flow_data: dict,
                        env: str = "dev", role: str = "owner") -> dict:
        """Migrasi workflow lama ke sebuah environment (default dev)."""
        return self.create(owner, env, workflow_id, flow_data, role=role)

    # -- promote -----------------------------------------------------------
    def promote(self, owner: str, workflow_id: str, src: str, dst: str,
                role: str = "owner", approver: str = "",
                require_approval: bool = True) -> dict:
        """Promosikan versi terbaru dari `src` ke `dst`.

        - Hanya boleh maju satu langkah (dev->staging->production).
        - Ke environment terlindungi: membuat permintaan approval, kecuali
          `approver` diisi (menyetujui sekaligus).
        """
        if src not in ENVIRONMENTS or dst not in ENVIRONMENTS:
            raise UnknownEnvironment(f"{src}/{dst}")
        if PROMOTION_ORDER.get(src) != dst:
            raise EnvError(f"promosi {src}->{dst} tidak diizinkan "
                           f"(hanya {PROMOTION_ORDER})")
        if dst not in ROLE_RIGHTS.get(role, set()):
            raise Forbidden(f"peran {role!r} tidak boleh promosi ke {dst}")
        sumber = self.store.latest(owner, src, workflow_id)
        if not sumber:
            raise EnvError(f"workflow {workflow_id} tidak ada di {src}")

        if dst in PROTECTED and require_approval and not approver:
            rid = uuid.uuid4().hex[:16]
            rec = {"request_id": rid, "owner": owner, "workflow_id": workflow_id,
                   "src": src, "dst": dst, "source_version": sumber["version"],
                   "requested_by": role, "at": _now()}
            self.store.add_pending(rec)
            self.store.audit({"owner": owner, "action": "promote_request",
                              "env": dst, "workflow_id": workflow_id,
                              "request_id": rid, "at": _now()})
            raise ApprovalRequired(rid)

        target = self.store.put(
            owner, dst, workflow_id, sumber["flow_data"], sumber["config"],
            note=f"promote {src}->{dst}")
        self.store.audit({"owner": owner, "action": "promote", "from": src,
                          "env": dst, "workflow_id": workflow_id,
                          "version": target["version"], "approver": approver,
                          "at": _now()})
        return {"status": "promoted", "from": src, "to": dst,
                "version": target["version"], "record": target}

    def approve(self, request_id: str, approver: str,
                role: str = "admin") -> dict:
        """Setujui permintaan promosi yang tertunda lalu jalankan."""
        req = self.store.pop_pending(request_id)
        if not req:
            raise EnvError(f"permintaan approval tidak ditemukan: {request_id}")
        if req["dst"] not in ROLE_RIGHTS.get(role, set()):
            # kembalikan ke pending supaya bisa disetujui peran yang tepat
            self.store.add_pending(req)
            raise Forbidden(f"peran {approver!r} tidak boleh menyetujui {req['dst']}")
        sumber = self.store.latest(req["owner"], req["src"], req["workflow_id"])
        if not sumber:
            raise EnvError("sumber promosi hilang")
        target = self.store.put(
            req["owner"], req["dst"], req["workflow_id"], sumber["flow_data"],
            sumber["config"], note=f"approved {request_id}")
        self.store.audit({"owner": req["owner"], "action": "promote_approved",
                          "env": req["dst"], "workflow_id": req["workflow_id"],
                          "request_id": request_id, "approver": approver,
                          "version": target["version"], "at": _now()})
        return {"status": "promoted", "from": req["src"], "to": req["dst"],
                "version": target["version"], "approver": approver,
                "record": target}

    # -- diff / rollback ---------------------------------------------------
    def diff(self, owner: str, workflow_id: str, env_a: str,
             env_b: str) -> dict:
        a = self.store.latest(owner, env_a, workflow_id)
        b = self.store.latest(owner, env_b, workflow_id)
        if not a or not b:
            raise EnvError("salah satu environment tidak punya workflow ini")
        d = diff_flow(a["flow_data"], b["flow_data"])
        d.update({"env_a": env_a, "env_b": env_b,
                  "version_a": a["version"], "version_b": b["version"]})
        return d

    def rollback(self, owner: str, workflow_id: str, env: str,
                 version: int, role: str = "owner") -> dict:
        """Kembalikan environment ke versi sebelumnya (append versi baru)."""
        if env not in ROLE_RIGHTS.get(role, set()):
            raise Forbidden(f"peran {role!r} tidak boleh rollback {env}")
        rec = self.store.get_version(owner, env, workflow_id, version)
        if not rec:
            raise EnvError(f"versi {version} tidak ada di {env}")
        baru = self.store.put(owner, env, workflow_id, rec["flow_data"],
                              rec["config"], note=f"rollback->v{version}")
        self.store.audit({"owner": owner, "action": "rollback", "env": env,
                          "workflow_id": workflow_id, "to_version": version,
                          "new_version": baru["version"], "at": _now()})
        return {"status": "rolled_back", "env": env, "to_version": version,
                "new_version": baru["version"], "record": baru}

    # -- query -------------------------------------------------------------
    def list(self, owner: str, env: str) -> list[str]:
        if env not in ENVIRONMENTS:
            raise UnknownEnvironment(env)
        return self.store.list_workflows(owner, env)

    def audit_trail(self, owner: str = "") -> list[dict]:
        return self.store.audit_trail(owner)

    def pending(self, owner: str = "") -> list[dict]:
        return self.store.list_pending(owner)

    def compare_environments(self, owner: str, workflow_id: str) -> dict:
        """Ringkas versi workflow ini di tiap environment."""
        out: dict[str, Any] = {}
        for env in ENVIRONMENTS:
            rec = self.store.latest(owner, env, workflow_id)
            out[env] = None if not rec else {
                "version": rec["version"], "updated_at": rec["updated_at"]}
        return out


# ---------------------------------------------------------------------------
# Store Supabase (opsional) — antarmuka sama dengan EnvStore
# ---------------------------------------------------------------------------

class SupabaseEnvStore(EnvStore):
    """Store environment di tabel `workflow_environments` (Supabase).

    Memakai `database.get_write_client()` (service_role). Bila tabel belum
    ada / DB tak tersedia, operasi baca mengembalikan kosong dan tulis
    melempar EnvError — pemanggil dapat jatuh ke store memori.
    """

    def _svc(self):
        import database as db
        return db.get_write_client()

    def put(self, owner: str, env: str, workflow_id: str, flow_data: dict,
            config: Optional[dict] = None, note: str = "") -> dict:
        svc = self._svc()
        hist = self.history(owner, env, workflow_id)
        versi = len(hist) + 1
        rec = {"owner": owner, "env": env, "workflow_id": workflow_id,
               "version": versi, "flow_data": flow_data,
               "config": config or {}, "note": note}
        try:
            svc.table("workflow_environments").insert(rec).execute()
        except Exception as exc:  # noqa: BLE001
            raise EnvError(f"gagal menyimpan versi: {type(exc).__name__}") from exc
        out = dict(rec)
        out["updated_at"] = _now()
        return out

    def latest(self, owner: str, env: str, workflow_id: str) -> Optional[dict]:
        try:
            res = (self._svc().table("workflow_environments").select("*")
                   .eq("owner", owner).eq("env", env)
                   .eq("workflow_id", workflow_id)
                   .order("version", desc=True).limit(1).execute())
            rows = res.data or []
            return dict(rows[0]) if rows else None
        except Exception:  # noqa: BLE001
            return None

    def history(self, owner: str, env: str, workflow_id: str) -> list[dict]:
        try:
            res = (self._svc().table("workflow_environments").select("*")
                   .eq("owner", owner).eq("env", env)
                   .eq("workflow_id", workflow_id)
                   .order("version", desc=False).execute())
            return [dict(r) for r in (res.data or [])]
        except Exception:  # noqa: BLE001
            return []

    def list_workflows(self, owner: str, env: str) -> list[str]:
        try:
            res = (self._svc().table("workflow_environments")
                   .select("workflow_id").eq("owner", owner).eq("env", env)
                   .execute())
            return sorted({r["workflow_id"] for r in (res.data or [])})
        except Exception:  # noqa: BLE001
            return []

    def audit(self, entry: dict) -> None:
        try:
            self._svc().table("environment_audit").insert(entry).execute()
        except Exception:  # noqa: BLE001 - audit gagal tidak mematikan aksi
            pass

    def audit_trail(self, owner: str = "") -> list[dict]:
        try:
            q = self._svc().table("environment_audit").select("*")
            if owner:
                q = q.eq("owner", owner)
            res = q.order("at", desc=True).limit(500).execute()
            return [dict(r) for r in (res.data or [])]
        except Exception:  # noqa: BLE001
            return []


def default_store() -> EnvStore:
    """Store default: Supabase bila tersedia, jika tidak -> memori."""
    try:
        import database  # noqa: F401
        s = SupabaseEnvStore()
        s._svc().table("workflow_environments").select("id").limit(1).execute()
        return s
    except Exception:  # noqa: BLE001
        return EnvStore()
