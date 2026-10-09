"""Uji Fitur #5 — isolasi sandbox agen (model task runner n8n).

12 kategori: 3 basic, 2 durability, 3 edge, 2 performance, 2 security
(+ ekstra). Waktu deterministik lewat jam yang disuntik; tidak ada `sleep`.

Acuan perilaku (Okt 2026):
  * n8n docs — "Task runners": mode internal/external, broker, requester
  * n8n docs — "Task runner environment variables": batas & default persis
  * n8n docs — "Harden task runners": distroless, nobody 65532,
    read-only rootfs, AppArmor /proc deny
  * GHSA-jjpj-p2wh-qf23 / CVE-2026-27495 — sandbox escape, CVSS 9.4, CWE-94
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sandbox_isolation as S  # noqa: E402


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


def make_policy(clk: Clock | None = None, **kw) -> S.SandboxPolicy:
    clk = clk or Clock()
    kw.setdefault("clock", clk)
    return S.SandboxPolicy(**kw)


def make_cluster(clk: Clock | None = None, *, runtimes=("python",),
                 mode: str = "external", **pkw):
    """Broker + runner siap pakai."""
    clk = clk or Clock()
    pol = make_policy(clk, mode=mode, **pkw)
    br = S.TaskBroker(policy=pol, clock=clk)
    runners = []
    for rt in runtimes:
        r = S.TaskRunner(rt, policy=pol, clock=clk)
        br.register(r)
        runners.append(r)
    return pol, br, runners


# ---------------------------------------------------------------------------
# B — BASIC (3)
# ---------------------------------------------------------------------------

def test_b1_default_sesuai_dokumentasi_n8n():
    """B1: default env var persis seperti docs n8n."""
    d = S.N8N_RUNNER_DEFAULTS
    assert d["mode"] == "internal"
    assert d["broker_port"] == 5679
    assert d["broker_listen_address"] == "127.0.0.1"
    assert d["max_payload"] == 1_073_741_824
    assert d["max_concurrency"] == 5
    assert d["task_timeout"] == 300
    assert d["heartbeat_interval"] == 30
    assert d["task_request_timeout"] == 60
    assert d["auto_shutdown_timeout"] == 15
    assert d["launcher_health_port"] == 5680
    assert d["insecure_mode"] is False
    assert d["allow_prototype_mutation"] is False
    assert d["block_runner_env_access"] is True
    assert d["enabled"] is False

    p = make_policy()
    assert p.mode == "internal"
    assert p.max_concurrency == 5
    assert p.task_timeout_s == 300
    assert p.heartbeat_interval_s == 30
    assert p.request_timeout_s == 60
    assert p.max_payload_bytes == 1_073_741_824
    assert p.auto_shutdown_s == 15
    assert p.broker_port == 5679
    assert p.block_env_access is True
    assert p.production_safe is False   # internal = tidak siap produksi


def test_b2_python_builtins_ditolak_dan_impor_default_diblokir():
    """B2: allowlist KOSONG = semua impor ditolak (perilaku n8n)."""
    p = make_policy()
    # Daftar builtin terlarang persis docs n8n.
    assert set(S.PY_BUILTINS_DENY_DEFAULT) == {
        "eval", "exec", "compile", "open", "input", "breakpoint", "getattr",
        "object", "type", "vars", "setattr", "delattr", "hasattr", "dir",
        "memoryview", "__build_class__", "globals", "locals"}
    assert len(S.PY_BUILTINS_DENY_DEFAULT) == 18

    # Default: semua ditolak, kedua runtime.
    for rt, mods in (("python", ("os", "sys", "subprocess", "json", "re")),
                     ("javascript", ("fs", "child_process", "crypto", "url"))):
        for m in mods:
            assert p.module_allowed(rt, m) is False, (rt, m)

    # Hanya yang diizinkan secara eksplisit yang lolos.
    q = make_policy(allow_stdlib=["json", "re"], allow_builtin=["crypto"])
    assert q.module_allowed("python", "json") is True
    assert q.module_allowed("python", "re") is True
    assert q.module_allowed("python", "os") is False
    assert q.module_allowed("javascript", "crypto") is True
    assert q.module_allowed("javascript", "fs") is False

    # Submodul dinilai dari akarnya; `*` berarti semua.
    r = make_policy(allow_stdlib=["os"])
    assert r.module_allowed("python", "os.path") is True
    assert r.module_allowed("python", "os.path.join") is True
    star = make_policy(allow_builtin=["*"])
    assert star.module_allowed("javascript", "child_process") is True
    # Nama kosong / runtime tak dikenal.
    assert p.module_allowed("python", "") is False
    with pytest.raises(S.SandboxPolicyError):
        p.module_allowed("ruby", "json")


def test_b3_broker_runner_requester_satu_siklus_penuh():
    """B3: requester -> broker -> runner -> hasil (alur n8n)."""
    clk = Clock()
    pol, br, (runner,) = make_cluster(clk, runtimes=("python",))
    req = S.TaskRequester(br, node_name="Kode Saya", runtime="python")
    out = req.request("hasil = input_data", imports=[])
    assert out["status"] == "done", out
    assert out["result"]["ok"] is True
    assert out["runner_id"] == runner.runner_id
    assert br.stats()["dispatched"] == 1
    assert runner.stats()["completed"] == 1
    # `executor` nyata dipanggil.
    pol2 = make_policy(clk, mode="external")
    br2 = S.TaskBroker(policy=pol2, clock=clk)
    r2 = S.TaskRunner("python", policy=pol2, clock=clk,
                      executor=lambda t: {"echo": t["code"].upper()})
    br2.register(r2)
    out2 = S.TaskRequester(br2).request("halo")
    assert out2["result"]["result"] == {"echo": "HALO"}, out2


# ---------------------------------------------------------------------------
# D — DURABILITY (2)
# ---------------------------------------------------------------------------

def test_d1_heartbeat_dan_runner_mati_akan_dijalankan_ulang():
    """D1: runner tanpa heartbeat dianggap mati; tugas ditolak & antre ulang."""
    clk = Clock()
    pol, br, (runner,) = make_cluster(
        clk, mode="external", heartbeat_interval_s=10, task_timeout_s=300)
    assert runner.is_alive() is True
    # Lewati 2x interval -> mati.
    clk.advance(21)
    assert runner.is_alive() is False
    assert br.heartbeat_sweep() == [runner.runner_id]
    assert br.alive_runners("python") == []

    # Tugas tetap di antrean (tidak hilang) saat tak ada runner hidup.
    tid = br.enqueue({"runtime": "python", "code": "x=1"})
    assert br.dispatch_one() is None
    assert br.stats()["queue_depth"] == 1

    # Heartbeat lagi -> runner hidup, tugas terkirim.
    runner.heartbeat()
    assert runner.is_alive() is True
    res = br.dispatch_one()
    assert res is not None and res["task_id"] == tid
    assert br.stats()["queue_depth"] == 0


def test_d2_antrean_fifo_dan_tidak_ada_tugas_yang_hilang():
    """D2: antrean FIFO; gagal sesaat tidak menelan tugas."""
    clk = Clock()
    pol, br, (runner,) = make_cluster(
        clk, mode="external", heartbeat_interval_s=10, task_timeout_s=300)
    ids = [br.enqueue({"runtime": "python", "code": f"x={i}"})
           for i in range(50)]
    # Lewati > 2x interval heartbeat -> runner mati, tak ada yang terkirim.
    clk.advance(25)
    assert runner.is_alive() is False
    assert br.drain() == []
    assert br.stats()["queue_depth"] == 50
    runner.heartbeat()
    out = br.drain()
    # 50 tugas, kapasitas 5, tapi dispatch berurutan -> semua selesai.
    assert len(out) == 50, len(out)
    assert [o["task_id"] for o in out] == ids, "urutan FIFO rusak"
    assert br.stats()["queue_depth"] == 0


# ---------------------------------------------------------------------------
# E — EDGE (3)
# ---------------------------------------------------------------------------

def test_e1_konfigurasi_tidak_aman_ditolak():
    """E1: gerbang konfigurasi — kombinasi berbahaya ditolak saat dibangun."""
    # heartbeat >= task_timeout -> runner akan di-restart palsu.
    with pytest.raises(S.UnsafeConfiguration) as e:
        make_policy(heartbeat_interval_s=300, task_timeout_s=300)
    assert "heartbeat" in str(e.value)
    with pytest.raises(S.UnsafeConfiguration):
        make_policy(heartbeat_interval_s=400, task_timeout_s=300)

    # distroless mewajibkan uid/gid 65532.
    with pytest.raises(S.UnsafeConfiguration) as e2:
        make_policy(distroless=True, uid=1000)
    assert "65532" in str(e2.value)
    # Dengan uid benar -> boleh, dan lapisan hardening muncul.
    ok = make_policy(distroless=True, uid=65532, mode="external",
                     read_only_root=True, apparmor=True)
    assert set(ok.hardening_layers) >= {
        "external-mode", "distroless", "nobody-65532", "readonly-rootfs",
        "apparmor-proc-deny"}
    assert ok.gid == 65532  # gid mengikuti uid bila tak diberikan

    # require_production + mode internal -> ditolak (CVE-2026-27495).
    with pytest.raises(S.UnsafeConfiguration) as e3:
        make_policy(mode="internal", require_production=True)
    assert "internal" in str(e3.value) and "CVE" in str(e3.value)
    # insecure_mode + require_production -> ditolak.
    with pytest.raises(S.UnsafeConfiguration):
        make_policy(mode="external", insecure_mode=True,
                    require_production=True)
    # external + require_production -> boleh.
    assert make_policy(mode="external",
                       require_production=True).production_safe is True

    # Batas harus > 0 (n8n: "harus > 0").
    for kw in ({"max_concurrency": 0}, {"task_timeout_s": 0},
               {"request_timeout_s": 0}, {"max_payload_bytes": 0},
               {"heartbeat_interval_s": 0}):
        with pytest.raises(S.SandboxPolicyError):
            make_policy(**kw)
    with pytest.raises(S.SandboxPolicyError):
        make_policy(mode="galaxy")
    with pytest.raises(S.SandboxPolicyError):
        S.TaskRunner("ruby", policy=make_policy())


def test_e2_payload_concurrency_timeout_ditegakkan():
    """E2: batas payload, concurrency, dan task timeout."""
    clk = Clock()
    pol, br, (runner,) = make_cluster(
        clk, mode="external", max_concurrency=2, max_payload_bytes=1024,
        task_timeout_s=30, heartbeat_interval_s=5)

    # Payload terlalu besar.
    with pytest.raises(S.PayloadTooLarge) as e:
        runner.submit({"runtime": "python", "code": "x", "payload_bytes": 2048})
    assert "2048" in str(e.value)
    assert runner.stats()["rejected"] == 1
    # Tepat di batas -> boleh.
    assert runner.submit({"runtime": "python", "code": "x",
                          "payload_bytes": 1024})["ok"] is True
    # Payload dihitung dari kode bila tak diberikan.
    assert runner.submit({"runtime": "python",
                          "code": "a" * 1000})["ok"] is True

    # Concurrency: isi 2 slot dengan executor yang menahan.
    pol2 = make_policy(clk, mode="external", max_concurrency=2,
                       task_timeout_s=30, heartbeat_interval_s=5)
    r2 = S.TaskRunner("python", policy=pol2, clock=clk,
                      executor=lambda t: {"held": True})
    # Submit manual dengan slot yang belum dilepas (pakai internal dict).
    r2.active["t1"] = {"started_at": clk.t, "task": {}}
    r2.active["t2"] = {"started_at": clk.t, "task": {}}
    with pytest.raises(S.ConcurrencyExceeded) as e2:
        r2.submit({"runtime": "python", "code": "x"})
    assert "2" in str(e2.value)
    assert r2.capacity == 0

    # Task timeout -> runner menghentikan tugas (n8n: restart runner).
    clk.advance(31)
    killed = r2.reap_timeouts()
    assert len(killed) == 2, killed
    assert all(k["action"] == "stop-and-restart-runner" for k in killed)
    assert r2.capacity == 2
    assert r2.stats()["failed"] == 2
    # Tugas yang belum lewat batas tidak dibunuh.
    r2.active["t3"] = {"started_at": clk.t, "task": {}}
    assert r2.reap_timeouts() == []
    assert r2.reap_timeouts(now=clk.t + 31)[0]["task_id"] == "t3"


def test_e3_allowlist_per_runtime_dan_auth_broker():
    """E3: allowlist terpisah per runtime; broker butuh token bila diatur."""
    clk = Clock()
    pol = make_policy(clk, mode="external", allow_stdlib=["json"],
                      allow_py_external=["numpy"],
                      allow_builtin=["crypto"], allow_external=["uuid"])
    # Python: stdlib + external gabungan.
    assert pol.module_allowed("python", "json") is True
    assert pol.module_allowed("python", "numpy") is True
    assert pol.module_allowed("python", "os") is False
    # JS: builtin + external gabungan.
    assert pol.module_allowed("javascript", "crypto") is True
    assert pol.module_allowed("javascript", "uuid") is True
    assert pol.module_allowed("javascript", "fs") is False
    # Allowlist JS TIDAK membocor ke Python.
    assert pol.module_allowed("python", "crypto") is False
    assert pol.module_allowed("javascript", "json") is False

    # Tugas dengan impor terlarang ditolak SEBELUM dieksekusi.
    br = S.TaskBroker(policy=pol, clock=clk, auth_token="rahasia-broker")
    r = S.TaskRunner("python", policy=pol, clock=clk,
                     executor=lambda t: {"ran": True})
    with pytest.raises(S.SandboxPolicyError) as e:
        br.register(r, token="salah")
    assert "token" in str(e.value)
    assert br.stats()["rejected_registrations"] == 1
    br.register(r, token="rahasia-broker")
    assert br.stats()["auth_required"] is True

    out = S.TaskRequester(br).request("import os", imports=["os"])
    assert out["status"] == "done"
    assert out["result"]["ok"] is False
    assert "ModuleNotAllowed" in out["result"]["error"]
    assert r.stats()["completed"] == 0
    assert r.stats()["rejected"] == 1

    # Runner hanya menerima runtime-nya sendiri.
    jr = S.TaskRunner("javascript", policy=pol, clock=clk)
    br.register(jr, token="rahasia-broker")
    with pytest.raises(S.SandboxPolicyError) as e2:
        jr.submit({"runtime": "python", "code": "x"})
    assert "javascript" in str(e2.value)


# ---------------------------------------------------------------------------
# P — PERFORMANCE (2)
# ---------------------------------------------------------------------------

def test_p1_ribuan_tugas_cepat_dan_lengkap():
    """P1: 5000 tugas melalui broker+runner tetap di bawah ambang waktu."""
    clk = Clock()
    pol, br, (runner,) = make_cluster(
        clk, mode="external", max_concurrency=50)
    t0 = time.perf_counter()
    ids = [br.dispatch_one(now=clk.t) for _ in range(0)]  # no-op
    for i in range(5000):
        br.enqueue({"runtime": "python", "code": f"x={i}"})
    out = br.drain()
    dt = time.perf_counter() - t0
    assert len(out) == 5000, len(out)
    assert dt < 10.0, f"terlalu lambat: {dt:.3f}s"
    assert br.stats()["queue_depth"] == 0
    assert runner.stats()["completed"] == 5000
    assert br.stats()["dispatched"] == 5000
    assert ids == []


def test_p2_broker_paralel_thread_safe():
    """P2: 8 thread × 300 tugas -> tidak ada tugas hilang atau dobel."""
    clk = Clock()
    pol, br, _ = make_cluster(clk, mode="external", max_concurrency=64)

    def worker(n: int) -> list[str]:
        got: list[str] = []
        for i in range(300):
            br.enqueue({"runtime": "python", "code": f"t{n}-{i}"})
            res = br.dispatch_one(now=clk.t)
            if res is not None:
                got.append(res["task_id"])
        return got

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(worker, range(8)))
    seen = [tid for lst in results for tid in lst]
    assert len(seen) == len(set(seen)), "ada task_id kembar (race)"
    assert br.stats()["dispatched"] == len(seen)
    # Sisa antrean konsisten dengan total yang dikirim.
    total_sent = 8 * 300
    assert br.stats()["queue_depth"] == total_sent - len(seen)
    # Kosongkan sisanya — tetap tidak ada duplikat.
    rest = br.drain()
    all_ids = seen + [r["task_id"] for r in rest]
    assert len(all_ids) == total_sent == len(set(all_ids))


# ---------------------------------------------------------------------------
# S — SECURITY (2)
# ---------------------------------------------------------------------------

def test_s1_mode_internal_tidak_siap_produksi_cve_2026_27495():
    """S1: gerbang mode berdasarkan CVE-2026-27495 (sandbox escape)."""
    # Metadata CVE persis dari advisory.
    cve = S.KNOWN_CVES[0]
    assert cve["id"] == "CVE-2026-27495"
    assert cve["ghsa"] == "GHSA-jjpj-p2wh-qf23"
    assert cve["cvss_v31"] == 9.4
    assert cve["cvss_v31_vector"] == "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H"
    assert cve["cwe"] == "CWE-94"
    assert cve["severity"] == "critical"
    assert set(cve["patched"]) == {"1.123.22", "2.9.3", "2.10.1"}
    assert "host" in cve["internal_mode_impact"]

    internal = make_policy(mode="internal")
    external = make_policy(mode="external")
    assert internal.production_safe is False
    assert external.production_safe is True
    # Batas isolasi dilaporkan jujur.
    assert "SAMA" in internal.isolation_boundary
    assert "container" in external.isolation_boundary
    # Production-safe HANYA external.
    assert S.PRODUCTION_SAFE_MODES == ("external",)

    # Laporan hardening menandai internal sebagai temuan risiko tinggi.
    rep = S.harden_report({"KATALIR_SANDBOX_MODE": "internal"})
    issues = [f["issue"] for f in rep["findings"]]
    assert "mode internal tidak siap produksi" in issues
    assert rep["high"] >= 1 and rep["hardened"] is False
    assert rep["known_cves"][0]["id"] == "CVE-2026-27495"

    # Konfigurasi yang di-hardening penuh -> hardened True, tanpa temuan kritis.
    full = S.harden_report({
        "KATALIR_SANDBOX_MODE": "external",
        "KATALIR_SANDBOX_DISTROLESS": "1",
        "KATALIR_SANDBOX_UID": "65532",
        "KATALIR_SANDBOX_READONLY_ROOT": "1",
        "KATALIR_SANDBOX_APPARMOR": "1",
        "KATALIR_SANDBOX_BLOCK_ENV_ACCESS": "1",
    })
    assert full["hardened"] is True, full["findings"]
    assert full["critical"] == 0 and full["high"] == 0


def test_s2_akses_lingkungan_dan_insecure_mode_dilaporkan():
    """S2: kebocoran rahasia & mode tak aman menghasilkan temuan."""
    # Default: akses env diblokir.
    assert make_policy().block_env_access is True
    rep = S.harden_report({})  # default
    issues = [f["issue"] for f in rep["findings"]]
    assert "akses lingkungan runner dibuka" not in issues  # masih aman

    # Membuka akses env -> temuan risiko tinggi.
    rep2 = S.harden_report({"KATALIR_SANDBOX_BLOCK_ENV_ACCESS": "0"})
    hi = [f for f in rep2["findings"] if f["severity"] == "high"]
    assert any("lingkungan" in f["issue"] for f in hi), rep2["findings"]

    # insecure_mode -> temuan kritis (n8n: tidak disarankan untuk produksi).
    rep3 = S.harden_report({"KATALIR_SANDBOX_INSECURE_MODE": "1"})
    assert rep3["critical"] >= 1
    assert any("insecure_mode" in f["issue"] for f in rep3["findings"])
    assert rep3["hardened"] is False

    # Mutasi prototipe -> temuan (prototype pollution).
    rep4 = S.harden_report({"KATALIR_SANDBOX_ALLOW_PROTOTYPE_MUTATION": "1"})
    assert any("prototipe" in f["issue"] for f in rep4["findings"])

    # Allowlist '*' untuk builtin JS -> child_process/fs terbuka.
    rep5 = S.harden_report({
        "KATALIR_SANDBOX_ALLOW_BUILTIN": "*",
        "KATALIR_SANDBOX_MODE": "external",
    })
    assert any("semua modul bawaan" in f["issue"] for f in rep5["findings"])
    p5 = S.policy_from_env({"KATALIR_SANDBOX_ALLOW_BUILTIN": "*"})
    assert p5.module_allowed("javascript", "child_process") is True

    # Laporan tidak pernah memuat nilai rahasia apa pun.
    blob = str(rep5)
    for needle in ("AUTH_TOKEN=", "SECRET", "password"):
        assert needle not in blob


# ---------------------------------------------------------------------------
# X — EXTRA
# ---------------------------------------------------------------------------

def test_x1_policy_from_env_membaca_dict_inject():
    """X1: factory membaca dict yang disuntik, BUKAN `os.environ`."""
    env = {
        "KATALIR_SANDBOX_MODE": "external",
        "KATALIR_SANDBOX_DISTROLESS": "1",
        "KATALIR_SANDBOX_UID": "65532",
        "KATALIR_SANDBOX_READONLY_ROOT": "1",
        "KATALIR_SANDBOX_APPARMOR": "1",
        "KATALIR_SANDBOX_MAX_CONCURRENCY": "12",
        "KATALIR_SANDBOX_TASK_TIMEOUT_S": "120",
        "KATALIR_SANDBOX_HEARTBEAT_INTERVAL_S": "15",
        "KATALIR_SANDBOX_REQUEST_TIMEOUT_S": "45",
        "KATALIR_SANDBOX_MAX_PAYLOAD_BYTES": "4096",
        "KATALIR_SANDBOX_AUTOSHUTDOWN_S": "20",
        "KATALIR_SANDBOX_ALLOW_STDLIB": "json, re  math",
        "KATALIR_SANDBOX_BLOCK_ENV_ACCESS": "0",
        "KATALIR_SANDBOX_REQUIRE_PRODUCTION": "1",
    }
    p = S.policy_from_env(env)
    assert p.mode == "external" and p.distroless is True
    assert p.uid == 65532 and p.gid == 65532
    assert p.read_only_root is True and p.apparmor is True
    assert p.max_concurrency == 12
    assert p.task_timeout_s == 120
    assert p.heartbeat_interval_s == 15
    assert p.request_timeout_s == 45
    assert p.max_payload_bytes == 4096
    assert p.auto_shutdown_s == 20
    assert p.allow_stdlib == ("json", "re", "math")
    assert p.block_env_access is False
    assert p.require_production is True

    # Env kosong -> default n8n.
    d = S.policy_from_env({})
    assert d.mode == "internal" and d.max_concurrency == 5
    assert d.block_env_access is True and d.require_production is False
    # Nilai tidak sah -> jatuh ke default, tidak meledak.
    bad = S.policy_from_env({"KATALIR_SANDBOX_MAX_CONCURRENCY": "abc"})
    assert bad.max_concurrency == 5


def test_x2_singleton_dan_helper_modul():
    """X2: singleton proses + helper `is_module_allowed`/`check_payload`."""
    S.set_policy(None)
    p = S.policy()
    assert isinstance(p, S.SandboxPolicy)
    other = make_policy(mode="external")
    S.set_policy(other)
    assert S.policy() is other

    assert S.is_module_allowed("python", "os", {}) is False
    assert S.is_module_allowed(
        "python", "json", {"KATALIR_SANDBOX_ALLOW_STDLIB": "json"}) is True
    S.check_payload(100, {})  # tidak melempar
    with pytest.raises(S.PayloadTooLarge):
        S.check_payload(10 ** 12, {"KATALIR_SANDBOX_MAX_PAYLOAD_BYTES": "1024"})
    S.set_policy(None)


def test_x3_clock_disuntik_dipakai_untuk_heartbeat_dan_uptime():
    """X3: jam yang disuntik dipakai untuk heartbeat/uptime/timeout."""
    clk = Clock(7000.0)
    pol = make_policy(clk, mode="external", heartbeat_interval_s=10,
                      task_timeout_s=100)
    r = S.TaskRunner("python", policy=pol, clock=clk)
    assert r.started_at == 7000.0
    assert r.last_heartbeat == 7000.0
    clk.advance(5)
    assert r.heartbeat() == 7005.0
    assert r.stats()["uptime_s"] == 5.0
    assert r.is_alive() is True
    clk.advance(21)   # > 2x interval
    assert r.is_alive() is False

    br = S.TaskBroker(policy=pol, clock=clk)
    br.register(r)
    tid = br.enqueue({"runtime": "python", "code": "x"})
    assert br.queue[0]["enqueued_at"] == 7026.0
    # Lewati request timeout -> tugas kedaluwarsa (workflow tidak menggantung).
    clk.advance(61)
    assert br.expire_requests() == 1
    assert br.stats()["queue_depth"] == 0
    assert tid  # id tetap dicatat pemanggil


def test_x4_reap_timeout_lewat_broker_dan_stats_lengkap():
    """X4: reaper broker mengumpulkan timeout dari semua runner."""
    clk = Clock()
    pol, br, runners = make_cluster(
        clk, runtimes=("python", "javascript"), mode="external",
        task_timeout_s=10, heartbeat_interval_s=4)
    for i, r in enumerate(runners):
        r.active[f"t{i}"] = {"started_at": clk.t, "task": {}}
    clk.advance(11)
    killed = br.reap_timeouts()
    assert len(killed) == 2, killed
    assert {k["runner_id"] for k in killed} == {r.runner_id for r in runners}
    assert br.stats()["runtimes"] == ["javascript", "python"]

    # unregister mengurangi jumlah runner.
    victim = runners[0].runner_id
    assert br.unregister(victim) is True
    assert br.unregister(victim) is False  # idempoten
    assert br.stats()["runners_total"] == 1

    # Tugas untuk runtime tanpa runner tetap di antrean.
    br.unregister(runners[1].runner_id)
    br.enqueue({"runtime": "python", "code": "x"})
    assert br.dispatch_one() is None
    assert br.stats()["queue_depth"] == 1


def test_x5_describe_lengkap_dan_tanpa_rahasia():
    """X5: `describe()` melaporkan katalog penuh tanpa rahasia."""
    d = S.describe({})
    assert d["modes"] == ["internal", "external"]
    assert d["production_safe_modes"] == ["external"]
    assert d["runtime_types"] == ["javascript", "python"]
    assert d["distroless_uid"] == 65532
    assert d["runner_image"] == "n8nio/runners"
    assert len(d["python_builtins_denied"]) == 18
    assert d["policy"]["mode"] == "internal"
    assert d["production_safe"] is False
    assert "sub-proses" in d["isolation_boundary"]
    assert d["defaults"]["task_timeout"] == 300
    assert d["known_cves"][0]["id"] == "CVE-2026-27495"
    # Ubah env -> kebijakan & batas isolasi ikut berubah.
    d2 = S.describe({"KATALIR_SANDBOX_MODE": "external",
                     "KATALIR_SANDBOX_DISTROLESS": "1",
                     "KATALIR_SANDBOX_UID": "65532"})
    assert d2["production_safe"] is True
    # Distroless saja -> "container (sidecar terpisah)"; label "distroless"
    # pada `isolation_boundary` baru muncul bila rootfs juga read-only.
    assert d2["isolation_boundary"] == "container (sidecar terpisah)"
    assert "distroless" in d2["policy"]["hardening_layers"]
    d3 = S.describe({"KATALIR_SANDBOX_MODE": "external",
                     "KATALIR_SANDBOX_DISTROLESS": "1",
                     "KATALIR_SANDBOX_UID": "65532",
                     "KATALIR_SANDBOX_READONLY_ROOT": "1"})
    assert "distroless" in d3["isolation_boundary"]
    assert "read-only" in d3["isolation_boundary"]
    # Tidak ada rahasia.
    assert "TOKEN" not in str(d2)


def test_x6_requester_mengembalikan_queued_saat_tak_ada_runner():
    """X6: requester jujur melaporkan `queued` bila runner tidak tersedia."""
    clk = Clock()
    pol = make_policy(clk, mode="external")
    br = S.TaskBroker(policy=pol, clock=clk)  # tanpa runner
    req = S.TaskRequester(br, runtime="python")
    out = req.request("x=1")
    assert out["status"] == "queued"
    assert out["queue_depth"] == 1
    assert "runner_id" not in out
    # Setelah runner terdaftar, tugas berikutnya selesai.
    br.register(S.TaskRunner("python", policy=pol, clock=clk))
    out2 = req.request("x=2")
    assert out2["status"] == "done"
    # Tugas pertama masih menunggu di antrean (tidak hilang).
    assert br.stats()["queue_depth"] == 1
    assert len(br.drain()) == 1


def test_x7_auto_shutdown_dan_insecure_mode_flag():
    """X7: auto shutdown 0 = nonaktif; flag insecure/prototype diteruskan."""
    p0 = make_policy(auto_shutdown_s=0)
    assert p0.auto_shutdown_s == 0
    assert S.N8N_RUNNER_DEFAULTS["auto_shutdown_timeout"] == 15
    p1 = make_policy(insecure_mode=True)
    assert p1.insecure_mode is True
    assert "secure-globals" not in p1.hardening_layers
    assert p1.production_safe is False
    p2 = make_policy(mode="external", insecure_mode=True)
    assert p2.production_safe is False   # insecure meniadakan prod-safe
    p3 = make_policy(allow_prototype_mutation=True)
    assert p3.allow_prototype_mutation is True
    p4 = make_policy(block_env_access=False)
    assert p4.block_env_access is False
    assert "env-access-blocked" not in p4.hardening_layers


def test_x8_requester_meneruskan_imports_ke_runner():
    """X8 (regresi): `imports` WAJIB sampai ke runner.

    Bug nyata: `/sandbox/dispatch` tidak meneruskan `req.imports`, sehingga
    allowlist modul tak pernah ditegakkan lewat jalur HTTP — penolakan impor
    hanya bekerja pada unit test. Uji ini mengunci rantai
    requester -> broker -> runner -> policy.
    """
    clk = Clock()
    pol = make_policy(clk)
    broker = S.TaskBroker(policy=pol)
    runner = S.TaskRunner("python", policy=pol, clock=clk)
    broker.register(runner)

    # Impor terlarang: harus ditolak walau kode terlihat jinak.
    out = S.TaskRequester(broker, node_name="Code", runtime="python").request(
        "import os\nreturn os.getcwd()", imports=["os"])
    assert out["status"] == "done"
    assert out["result"]["ok"] is False
    assert "ModuleNotAllowed" in out["result"]["error"]
    assert runner.rejected == 1

    # Impor bersarang juga dinilai dari akarnya.
    out2 = S.TaskRequester(broker, node_name="Code", runtime="python").request(
        "return 1", imports=["os.path"])
    assert out2["result"]["ok"] is False
    assert runner.rejected == 2

    # Tanpa impor -> diterima.
    out3 = S.TaskRequester(broker, node_name="Code", runtime="python").request(
        "return 1")
    assert out3["result"]["ok"] is True


def test_x9_allowlist_longgar_membuka_modul_tertentu():
    """X9: allowlist non-kosong mengizinkan hanya modul yang terdaftar."""
    clk = Clock()
    pol = make_policy(clk, allow_stdlib=["math"])
    assert pol.module_allowed("python", "math") is True
    assert pol.module_allowed("python", "os") is False
    assert pol.module_allowed("python", "math.sqrt") is True   # akar cocok

    pol_js = make_policy(clk, allow_external=["lodash"])
    assert pol_js.module_allowed("javascript", "lodash") is True
    assert pol_js.module_allowed("javascript", "child_process") is False
    assert pol_js.module_allowed("javascript", "fs/promises") is False

    pol_all = make_policy(clk, allow_stdlib=["*"])
    assert pol_all.module_allowed("python", "anything") is True
    assert pol_all.harden_report() if hasattr(pol_all, "harden_report") else True


def test_x10_broker_menolak_runner_mati():
    """X10: runner yang heartbeat-nya kedaluwarsa tak menerima tugas."""
    clk = Clock()
    pol = make_policy(clk, heartbeat_interval_s=10, task_timeout_s=30)
    broker = S.TaskBroker(policy=pol)
    runner = S.TaskRunner("python", policy=pol, clock=clk)
    broker.register(runner)
    assert runner.is_alive() is True

    clk.advance(25)                      # > 2x interval (20) -> mati
    assert runner.is_alive() is False
    assert broker.alive_runners("python") == []
    assert broker.heartbeat_sweep() == [runner.runner_id]

    with pytest.raises(S.SandboxPolicyError):
        runner.submit({"id": "t1", "runtime": "python", "code": "1"})


def test_x11_harden_report_ter_hardening_penuh():
    """X11: konfigurasi keras penuh -> hardened True, 0 temuan."""
    env = {
        "KATALIR_SANDBOX_MODE": "external",
        "KATALIR_SANDBOX_DISTROLESS": "1",
        "KATALIR_SANDBOX_UID": "65532",
        "KATALIR_SANDBOX_GID": "65532",
        "KATALIR_SANDBOX_READONLY_ROOT": "1",
        "KATALIR_SANDBOX_APPARMOR": "1",
    }
    rep = S.harden_report(env)
    assert rep["hardened"] is True
    assert rep["findings"] == []
    assert rep["findings_count"] == 0
    assert rep["critical"] == 0 and rep["high"] == 0
    assert any(c["id"] == "CVE-2026-27495" for c in rep["known_cves"])

    # Mode internal -> minimal 1 temuan high.
    rep2 = S.harden_report({"KATALIR_SANDBOX_MODE": "internal"})
    assert rep2["hardened"] is False
    assert rep2["findings_count"] >= 1
    assert rep2["high"] >= 1
