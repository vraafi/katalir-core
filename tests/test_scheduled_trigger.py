"""Hard test suite — Fitur #1 Scheduled Trigger (cron).

Standar 8 Okt 2026: setiap skenario menghasilkan bukti raw. Test DB operations
memakai klien Supabase nyata (service role) dan membersihkan barisnya sendiri
di akhir (fixture `_bersihkan`), sehingga tidak meninggalkan residu.

Test yang menembak cron sungguhan memakai tick() langsung (deterministik)
alih-alih menunggu loop 20s — sama seperti rekomendasi conftest.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import database as db
import scheduler_manager as sm

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

WIB = "Asia/Jakarta"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def _bersihkan():
    """Hapus semua baris workflow_schedules yang dibuat test ini."""
    dibuat: list[str] = []
    yield dibuat
    if not dibuat:
        return
    try:
        cli = db.get_write_client()
        for sid in dibuat:
            cli.table("workflow_schedules").delete().eq("id", sid).execute()
    except Exception:  # noqa: BLE001
        pass


def _user_id_nyata() -> str | None:
    """Ambil user_id pertama dari tabel users (dipakai sebagai owner test)."""
    try:
        res = db.get_write_client().table("users").select("id").limit(1).execute()
        rows = res.data or []
        return str(rows[0]["id"]) if rows else None
    except Exception:  # noqa: BLE001
        return None


def _workflow_id_nyata() -> str | None:
    try:
        res = db.get_write_client().table("workflows").select("id").limit(1).execute()
        rows = res.data or []
        return str(rows[0]["id"]) if rows else None
    except Exception:  # noqa: BLE001
        return None


def _pasangan_nyata() -> tuple[str, str] | None:
    """Return (workflow_id, user_id) yang BENAR-BENAR berpasangan sebagai owner.

    Penting: scheduler_manager._fire memverifikasi db.get_workflow(wid, uid)
    yang mencocokkan owner. Memakai id acak akan (dengan benar) dianggap
    "workflow hilang" -> jadwal dimatikan. Jadi test e2e harus memakai
    pasangan yang sah.
    """
    try:
        res = (db.get_write_client().table("workflows")
               .select("id,user_id").limit(1).execute())
        rows = res.data or []
        if not rows:
            return None
        return str(rows[0]["id"]), str(rows[0]["user_id"])
    except Exception:  # noqa: BLE001
        return None


def _pasangan_atau_skip() -> tuple[str, str]:
    pasangan = _pasangan_nyata()
    if not pasangan:
        pytest.skip("butuh pasangan workflow/user nyata di DB")
    return pasangan


def _buat_jadwal(workflow_id: str, user_id: str, expr: str, tz: str = WIB,
                 enabled: bool = True, next_at: datetime | None = None) -> dict:
    row = {
        "workflow_id": workflow_id,
        "user_id": user_id,
        "cron_expression": expr,
        "timezone": tz,
        "enabled": enabled,
        "next_fire_at": sm.iso_utc(next_at or sm.utc_now()),
    }
    res = (db.get_write_client().table("workflow_schedules")
           .upsert(row, on_conflict="workflow_id").execute())
    return (res.data or [{}])[0]


# ===========================================================================
# TEST 1-5: Basic cron
# ===========================================================================
class TestBasicCron:
    def test_01_cron_setiap_2_menit_tervalidasi_dan_terhitung(self):
        """"*/2 * * * *" valid; next_fire harus kelipatan 2 menit."""
        assert sm.is_valid_cron("*/2 * * * *") is True
        base = datetime(2026, 10, 8, 10, 1, 30, tzinfo=timezone.utc)
        n = sm.next_fire_utc("*/2 * * * *", WIB, base=base)
        print(f"\n[1] base={base.isoformat()} next={n.isoformat()}")
        # 10:01:30Z -> menit berikut kelipatan 2 = 10:02Z
        assert n.minute % 2 == 0
        assert n.second == 0
        assert n > base

    def test_02_cron_22_00_WIB_menghasilkan_15_00_UTC(self):
        """KRITIS: "0 22 * * *" WIB harus 15:00Z (WIB = UTC+7), BUKAN 22:00Z."""
        base = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
        n = sm.next_fire_utc("0 22 * * *", WIB, base=base)
        print(f"\n[2] WIB '0 22 * * *' dari {base.isoformat()} -> {n.isoformat()}")
        assert n == datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc), (
            f"WIB 22:00 harus 15:00Z, dapat {n.isoformat()}"
        )

    def test_03_cron_awal_bulan(self):
        """"0 0 1 * *" -> tanggal 1 bulan berikutnya."""
        base = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
        n = sm.next_fire_utc("0 0 1 * *", WIB, base=base)
        print(f"\n[3] '0 0 1 * *' -> {n.isoformat()}")
        # 1 Nov 00:00 WIB = 31 Okt 17:00Z
        assert n == datetime(2026, 10, 31, 17, 0, tzinfo=timezone.utc)

    def test_04_cron_hari_kerja_saja(self):
        """"0 9 * * 1-5" harus jatuh di hari kerja (bukan weekend)."""
        base = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)  # Kamis
        n = sm.next_fire_utc("0 9 * * 1-5", WIB, base=base)
        print(f"\n[4] '0 9 * * 1-5' -> {n.isoformat()} weekday={n.weekday()}")
        assert n.weekday() < 5, "harus hari kerja"
        assert n == datetime(2026, 10, 9, 2, 0, tzinfo=timezone.utc)  # 9 WIB Jumat

    def test_05_cron_invalid_ditolak(self):
        """Berbagai bentuk cron invalid harus False (dipakai endpoint -> 400)."""
        for bad in ("99 99 * * *", "bad", "", "   ", "* * * *", "a b c d e"):
            hasil = sm.is_valid_cron(bad)
            print(f"\n[5] {bad!r} -> {hasil}")
            assert hasil is False, f"{bad!r} seharusnya invalid"


# ===========================================================================
# TEST 6-8: Durability
# ===========================================================================
class TestDurability:
    def test_06_jadwal_bertahan_setelah_restart(self, _bersihkan):
        """Simulasi restart: baris tetap ada di DB dan recover_on_startup tidak
        merusaknya. (Railway redeploy = proses baru, DB Supabase persisten.)"""
        wid, uid = _pasangan_atau_skip()

        jadwal = _buat_jadwal(wid, uid, "*/30 * * * *",
                              next_at=sm.utc_now() + timedelta(minutes=30))
        _bersihkan.append(jadwal["id"])
        sid = jadwal["id"]
        print(f"\n[6] jadwal dibuat id={sid} next={jadwal.get('next_fire_at')}")

        # "restart": baca ulang dari DB
        res = (db.get_write_client().table("workflow_schedules")
               .select("*").eq("id", sid).execute())
        assert res.data, "jadwal harus tetap ada di DB setelah restart"
        assert res.data[0]["cron_expression"] == "*/30 * * * *"

        # recovery tidak boleh menghapus jadwal yang sehat
        sm.recover_on_startup()
        res2 = (db.get_write_client().table("workflow_schedules")
                .select("*").eq("id", sid).execute())
        assert res2.data, "jadwal sehat harus selamat dari recovery"
        print(f"[6] setelah recovery, next={res2.data[0].get('next_fire_at')}")

    def test_07_recovery_memajukan_jadwal_yang_sangat_overdue(self, _bersihkan):
        """Jadwal overdue >24h di-majukan TANPA ditembak (anti-burst)."""
        wid, uid = _pasangan_atau_skip()

        jauh_lampau = sm.utc_now() - timedelta(days=5)
        jadwal = _buat_jadwal(wid, uid, "0 3 * * *", next_at=jauh_lampau)
        _bersihkan.append(jadwal["id"])
        sid = jadwal["id"]

        n_fixed = sm.recover_on_startup()
        res = (db.get_write_client().table("workflow_schedules")
               .select("next_fire_at").eq("id", sid).execute())
        baru = res.data[0]["next_fire_at"]
        print(f"\n[7] overdue 5 hari -> next baru={baru} (fixed={n_fixed})")

        baru_dt = datetime.fromisoformat(str(baru).replace("Z", "+00:00"))
        assert baru_dt > sm.utc_now(), "harus dimajukan ke masa depan"

    def test_08_claim_optimistis_anti_dobel(self, _bersihkan):
        """Claim kedua pada baris yang sama harus GAGAL (anti double-fire)."""
        wid, uid = _pasangan_atau_skip()

        now = sm.utc_now()
        jadwal = _buat_jadwal(wid, uid, "*/5 * * * *", next_at=now - timedelta(seconds=5))
        _bersihkan.append(jadwal["id"])

        # ambil baris seperti yang dilakukan tick()
        due = [s for s in sm.fetch_due_schedules(now) if s["id"] == jadwal["id"]]
        assert due, "jadwal harus terlihat due"
        sched = due[0]

        first = sm.claim_schedule(sched, now)
        second = sm.claim_schedule(sched, now)  # pakai snapshot lama
        print(f"\n[8] claim pertama={first} claim kedua={second}")
        assert first is not None, "claim pertama harus sukses"
        assert second is None, "claim kedua harus GAGAL (replica lain menang)"


# ===========================================================================
# TEST 9-10: Enable/disable
# ===========================================================================
class TestEnableDisable:
    def test_09_jadwal_disabled_tidak_pernah_due(self, _bersihkan):
        """enabled=False -> fetch_due_schedules tidak mengembalikannya."""
        wid, uid = _pasangan_atau_skip()

        now = sm.utc_now()
        jadwal = _buat_jadwal(wid, uid, "*/5 * * * *",
                              enabled=False, next_at=now - timedelta(minutes=10))
        _bersihkan.append(jadwal["id"])

        due_ids = [s["id"] for s in sm.fetch_due_schedules(now)]
        print(f"\n[9] disabled jadwal id={jadwal['id']} ada di due? {jadwal['id'] in due_ids}")
        assert jadwal["id"] not in due_ids, "jadwal disabled tidak boleh due"

    def test_10_reenable_menjadwalkan_ulang(self, _bersihkan):
        """Setelah enable kembali, next_fire_at di masa depan -> tidak langsung
        menembak (kecuali memang sudah lewat)."""
        wid, uid = _pasangan_atau_skip()

        jadwal = _buat_jadwal(wid, uid, "0 6 * * *", enabled=False)
        _bersihkan.append(jadwal["id"])
        sid = jadwal["id"]

        # enable + hitung next dari sekarang
        nxt = sm.next_fire_utc("0 6 * * *", WIB, base=sm.utc_now())
        db.get_write_client().table("workflow_schedules").update({
            "enabled": True, "next_fire_at": sm.iso_utc(nxt),
        }).eq("id", sid).execute()

        res = (db.get_write_client().table("workflow_schedules")
               .select("enabled,next_fire_at").eq("id", sid).execute())
        row = res.data[0]
        print(f"\n[10] setelah re-enable: enabled={row['enabled']} next={row['next_fire_at']}")
        assert row["enabled"] is True
        nxt_dt = datetime.fromisoformat(str(row["next_fire_at"]).replace("Z", "+00:00"))
        assert nxt_dt > sm.utc_now()

        due_ids = [s["id"] for s in sm.fetch_due_schedules(sm.utc_now())]
        assert sid not in due_ids, "jadwal masa depan tidak boleh langsung due"


# ===========================================================================
# TEST 11-12: Performance
# ===========================================================================
class TestPerformance:
    def test_11_banyak_jadwal_tidak_membanjiri_loop(self, _bersihkan):
        """MAX_DUE_PER_TICK membatasi jumlah tembakan per tick (anti burst)."""
        wid, uid = _pasangan_atau_skip()

        now = sm.utc_now()
        jadwal = _buat_jadwal(wid, uid, "* * * * *", next_at=now - timedelta(seconds=1))
        _bersihkan.append(jadwal["id"])

        due = sm.fetch_due_schedules(now)
        print(f"\n[11] MAX_DUE_PER_TICK={sm.MAX_DUE_PER_TICK} jumlah due={len(due)}")
        assert len(due) <= sm.MAX_DUE_PER_TICK

    def test_12_latensi_perhitungan_cron_di_bawah_2_detik(self):
        """Benchmark: 200x next_fire_utc harus jauh di bawah 2s."""
        import time
        base = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
        t0 = time.perf_counter()
        for i in range(200):
            sm.next_fire_utc("*/5 * * * *", WIB, base=base + timedelta(minutes=i))
        elapsed = time.perf_counter() - t0
        print(f"\n[12] 200x next_fire_utc = {elapsed:.4f}s "
              f"(rata-rata {elapsed/200*1000:.2f} ms)")
        assert elapsed < 2.0, f"terlalu lambat: {elapsed:.3f}s"


# ===========================================================================
# TEST TAMBAHAN: Timezone, izin, validasi
# ===========================================================================
class TestTimezoneDanKeamanan:
    def test_13_timezone_berbeda_menghasilkan_instant_berbeda(self):
        """Regression bug 8 Okt: WIB vs NY vs UTC harus BEDA."""
        base = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
        jakarta = sm.next_fire_utc("0 22 * * *", "Asia/Jakarta", base=base)
        newyork = sm.next_fire_utc("0 22 * * *", "America/New_York", base=base)
        utc = sm.next_fire_utc("0 22 * * *", "UTC", base=base)
        print(f"\n[13] Jakarta={jakarta.isoformat()}")
        print(f"     NewYork={newyork.isoformat()}")
        print(f"     UTC    ={utc.isoformat()}")
        assert len({jakarta, newyork, utc}) == 3, "timezone harus berpengaruh!"
        assert jakarta == datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)
        assert utc == datetime(2026, 10, 8, 22, 0, tzinfo=timezone.utc)

    def test_14_timezone_invalid_ditolak(self):
        """'WIB' bukan IANA -> ditolak (endpoint -> 400)."""
        for bad in ("WIB", "Nope/Bad", "", "   ", "GMT+7"):
            hasil = sm.is_valid_timezone(bad)
            print(f"\n[14] {bad!r} -> {hasil}")
            assert hasil is False

    def test_15_timezone_iana_valid(self):
        for good in ("Asia/Jakarta", "UTC", "America/New_York", "Europe/London"):
            assert sm.is_valid_timezone(good) is True
        print("\n[15] semua IANA valid diterima")

    def test_16_kill_switch_env(self, monkeypatch):
        """SCHEDULER_ENABLED=0 harus mematikan loop (dipakai pytest)."""
        monkeypatch.setenv("SCHEDULER_ENABLED", "0")
        assert sm.scheduler_enabled() is False
        monkeypatch.setenv("SCHEDULER_ENABLED", "1")
        assert sm.scheduler_enabled() is True
        monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
        assert sm.scheduler_enabled() is True
        print("\n[16] kill-switch bekerja")

    def test_17_claim_menghitung_next_dengan_timezone_jadwal(self, _bersihkan):
        """next_fire_at hasil claim harus memakai timezone jadwal (bukan UTC)."""
        wid, uid = _pasangan_atau_skip()

        now = sm.utc_now()
        jadwal = _buat_jadwal(wid, uid, "0 22 * * *", tz=WIB,
                              next_at=now - timedelta(seconds=5))
        _bersihkan.append(jadwal["id"])
        due = [s for s in sm.fetch_due_schedules(now) if s["id"] == jadwal["id"]]
        assert due
        nxt = sm.claim_schedule(due[0], now)
        print(f"\n[17] claim berikutnya (WIB 22:00) -> {nxt}")
        assert nxt is not None
        nxt_dt = datetime.fromisoformat(nxt.replace("Z", "+00:00"))
        # 22:00 WIB harus jam 15:00 UTC
        assert nxt_dt.hour == 15, f"harus 15:00Z (22:00 WIB), dapat {nxt_dt.hour}"


# ===========================================================================
# TEST: tick() end-to-end dengan engine yang di-mock
# ===========================================================================
class TestTickEndToEnd:
    def test_18_tick_menembak_dan_mencatat_eksekusi(self, _bersihkan, monkeypatch):
        """tick() harus menembak jadwal due SATU kali dan update last_fired_at."""
        wid, uid = _pasangan_atau_skip()

        tembakan: list[dict] = []
        # kolom last_execution_id bertipe uuid -> pakai UUID sah
        exec_id = str(uuid.uuid4())

        def fake_engine(workflow_id, flow_data, trigger_input, owner_email):
            tembakan.append({"workflow_id": workflow_id, "trigger": trigger_input})
            return exec_id

        monkeypatch.setattr(sm, "engine_launch", fake_engine)

        now = sm.utc_now()
        jadwal = _buat_jadwal(wid, uid, "*/5 * * * *", next_at=now - timedelta(seconds=5))
        _bersihkan.append(jadwal["id"])
        sid = jadwal["id"]

        fired = asyncio.run(sm.tick(user_id=uid))
        print(f"\n[18] tick fired={fired} tembakan={tembakan}")

        res = (db.get_write_client().table("workflow_schedules")
               .select("last_fired_at,last_execution_id,next_fire_at")
               .eq("id", sid).execute())
        row = res.data[0]
        print(f"[18] row setelah tick: last_fired_at={row['last_fired_at']} "
              f"exec={row['last_execution_id']}")
        assert row["last_fired_at"] is not None, "last_fired_at harus terisi"
        assert row["last_execution_id"] == exec_id

        # tick kedua: next_fire_at sekarang di masa depan -> tidak menembak lagi
        fired2 = asyncio.run(sm.tick(user_id=uid))
        print(f"[18] tick kedua fired={fired2} (harus 0)")
        assert fired2 == 0, "tidak boleh menembak dua kali"

    def test_19_tick_melewati_jadwal_terlalu_tua(self, _bersihkan, monkeypatch):
        """Jadwal overdue >24h di-skip tanpa menembak."""
        wid, uid = _pasangan_atau_skip()

        tembakan: list = []
        monkeypatch.setattr(sm, "engine_launch",
                            lambda *a, **k: tembakan.append(a) or "x")

        jadwal = _buat_jadwal(wid, uid, "0 3 * * *",
                              next_at=sm.utc_now() - timedelta(days=3))
        _bersihkan.append(jadwal["id"])

        asyncio.run(sm.tick(user_id=uid))
        print(f"\n[19] tembakan untuk jadwal 3 hari overdue = {len(tembakan)}")
        assert len(tembakan) == 0, "jadwal terlalu tua tidak boleh ditembak"


# ===========================================================================
# TEST: isolasi antar-user (keamanan)
# ===========================================================================
class TestIsolasiKeamanan:
    def test_20_jadwal_terikat_user_pemiliknya(self, _bersihkan):
        """Baris jadwal menyimpan user_id; tidak ada jadwal tanpa pemilik."""
        wid, uid = _pasangan_atau_skip()

        jadwal = _buat_jadwal(wid, uid, "*/10 * * * *")
        _bersihkan.append(jadwal["id"])
        res = (db.get_write_client().table("workflow_schedules")
               .select("user_id").eq("id", jadwal["id"]).execute())
        print(f"\n[20] user_id tersimpan={res.data[0]['user_id']} (harus={uid})")
        assert res.data[0]["user_id"] == uid

    def test_21_unik_satu_jadwal_per_workflow(self, _bersihkan):
        """Constraint uq_schedules_workflow: upsert 2x -> tetap 1 baris."""
        wid, uid = _pasangan_atau_skip()

        a = _buat_jadwal(wid, uid, "*/15 * * * *")
        _bersihkan.append(a["id"])
        b = _buat_jadwal(wid, uid, "*/20 * * * *")  # upsert -> harus ganti
        res = (db.get_write_client().table("workflow_schedules")
               .select("id,cron_expression").eq("workflow_id", wid).execute())
        rows = res.data
        print(f"\n[21] baris untuk workflow={wid}: {len(rows)} ekspresi={[r['cron_expression'] for r in rows]}")
        assert len(rows) == 1, "harus tepat satu jadwal per workflow"
        assert rows[0]["cron_expression"] == "*/20 * * * *"
