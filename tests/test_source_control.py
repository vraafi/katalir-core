# tests/test_source_control.py — Fitur #5 hard test (12 skenario, Okt 2026)
# Deterministik, tanpa jaringan: server GitHub tiruan di belakang transport.
from __future__ import annotations

import base64
import json
import time
import urllib.parse

import pytest

import source_control as sc


class FakeGitHub:
    """Server GitHub tiruan: branch -> {path: (content, sha)}."""

    def __init__(self):
        self.branches: dict[str, dict[str, tuple[str, str]]] = {"main": {}}
        self.commits: dict[str, dict[str, str]] = {}
        self._n = 0
        self.prs: dict[int, dict] = {}
        self.calls: list[str] = []

    def _sha(self) -> str:
        self._n += 1
        return f"{self._n:040x}"

    def transport(self, method, url, headers, body):
        self.calls.append(f"{method} {url}")
        u = urllib.parse.urlparse(url)
        path = u.path
        q = urllib.parse.parse_qs(u.query)
        # GET contents
        if method == "GET" and "/contents/" in path:
            rel = path.split("/contents/", 1)[1]
            ref = (q.get("ref") or ["main"])[0]
            if ref in self.branches:
                br = self.branches[ref]
                if rel not in br:
                    return 404, {"message": "Not Found"}
                content, sha = br[rel]
            elif ref in self.commits:  # baca pada commit historis
                snap = self.commits[ref]
                if rel not in snap:
                    return 404, {"message": "Not Found"}
                content, sha = snap[rel], ref
            else:
                return 404, {"message": "Not Found"}
            return 200, {"content": base64.b64encode(content.encode()).decode(),
                         "sha": sha}
        if method == "PUT" and "/contents/" in path:
            rel = path.split("/contents/", 1)[1]
            branch = body["branch"]
            br = self.branches.setdefault(branch, dict(self.branches["main"]))
            existing = br.get(rel)
            if body.get("sha") and existing and body["sha"] != existing[1]:
                return 409, {"message": "sha mismatch"}
            content = base64.b64decode(body["content"]).decode()
            sha = self._sha()
            br[rel] = (content, sha)
            self.branches[branch] = br
            self.commits[sha] = {p: c for p, (c, _s) in br.items()}
            return 200, {"commit": {"sha": sha}}
        if method == "GET" and path.endswith("/branches"):
            return 200, [{"name": n} for n in self.branches]
        if method == "GET" and "/commits/" in path:
            ref = path.split("/commits/", 1)[1]
            return 200, {"sha": self._sha() if ref not in self.branches else "a" * 40}
        if method == "POST" and path.endswith("/git/refs"):
            name = body["ref"].replace("refs/heads/", "")
            self.branches.setdefault(name, dict(self.branches.get("main", {})))
            return 201, {"ref": body["ref"]}
        if method == "POST" and path.endswith("/pulls"):
            num = len(self.prs) + 1
            self.prs[num] = {"number": num, "state": "open",
                             "head": body["head"], "base": body["base"]}
            return 201, dict(self.prs[num])
        if method == "PUT" and "/pulls/" in path and path.endswith("/merge"):
            num = int(path.split("/pulls/")[1].split("/")[0])
            if num in self.prs:
                self.prs[num]["state"] = "closed"
                return 200, {"merged": True, "sha": self._sha()}
            return 404, {"message": "Not Found"}
        if method == "GET" and "/compare/" in path:
            spec = path.split("/compare/", 1)[1]
            base, head = (spec.split("...") + [""])[:2]
            b = self.branches.get(base, {})
            h = self.branches.get(head, {})
            files = [p for p in set(b) | set(h) if b.get(p) != h.get(p)]
            return 200, {"files": [{"filename": f} for f in files],
                         "ahead_by": len(files), "status": "ahead"}
        return 404, {"message": "unhandled"}


@pytest.fixture
def gh():
    fake = FakeGitHub()
    client = sc.make_client("github", "ghp_secrettoken123456", "me/repo",
                            transport=fake.transport)
    return sc.SourceControl(client), fake


def _flow(nodes):
    return {"nodes": [{"id": n, "kind": "code"} for n in nodes], "edges": []}


# 1. Connect repo -> OK (list branch)
def test_01_connect(gh):
    scm, fake = gh
    assert scm.list_branches() == ["main"]


# 2. Commit workflow -> ter-push ke repo
def test_02_commit(gh):
    scm, fake = gh
    r = scm.commit_workflow("wf-1", _flow(["a", "b"]), message="init")
    assert r["created"] is True and r["path"] == "workflows/wf-1.json"
    assert "workflows/wf-1.json" in fake.branches["main"]


# 3. Pull workflow -> ter-load
def test_03_pull(gh):
    scm, _ = gh
    scm.commit_workflow("wf-1", _flow(["a", "b"]))
    out = scm.pull_workflow("wf-1")
    assert len(out["flow_data"]["nodes"]) == 2
    assert out["sha"]


# 4. Diff view
def test_04_diff(gh):
    scm, _ = gh
    scm.commit_workflow("wf-1", _flow(["a"]))
    scm.create_branch("dev", "main")
    scm.commit_workflow("wf-1", _flow(["a", "b", "c"]), branch="dev")
    d = scm.diff("wf-1", "main", "dev")
    assert d["workflow_id"] == "wf-1"
    assert any("wf-1.json" in f["filename"] for f in d["files"])


# 5. Rollback -> kembali ke versi lama
def test_05_rollback(gh):
    scm, _ = gh
    r1 = scm.commit_workflow("wf-1", _flow(["a"]))
    scm.commit_workflow("wf-1", _flow(["a", "b", "c"]))
    assert len(scm.pull_workflow("wf-1")["flow_data"]["nodes"]) == 3
    scm.rollback("wf-1", to_sha=r1["sha"])
    assert len(scm.pull_workflow("wf-1")["flow_data"]["nodes"]) == 1


# 6. Branch main vs dev
def test_06_branches(gh):
    scm, fake = gh
    scm.commit_workflow("wf-1", _flow(["a"]))
    scm.create_branch("dev", "main")
    scm.commit_workflow("wf-1", _flow(["a", "b"]), branch="dev")
    assert set(scm.list_branches()) == {"main", "dev"}
    assert len(scm.pull_workflow("wf-1", "main")["flow_data"]["nodes"]) == 1
    assert len(scm.pull_workflow("wf-1", "dev")["flow_data"]["nodes"]) == 2


# 7. PR: create + merge
def test_07_pr(gh):
    scm, _ = gh
    scm.commit_workflow("wf-1", _flow(["a"]))
    scm.create_branch("feature", "main")
    scm.commit_workflow("wf-1", _flow(["a", "b"]), branch="feature")
    pr = scm.open_pr("feature", "main", "Tambah node b")
    assert pr["number"] == 1 and pr["state"] == "open"
    merged = scm.merge_pr(pr["number"])
    assert merged["merged"] is True


# 8. Conflict resolution (expect_sha)
def test_08_conflict(gh):
    scm, _ = gh
    scm.commit_workflow("wf-1", _flow(["a"]))
    base = scm.pull_workflow("wf-1")["sha"]
    # user lain menulis lebih dulu
    scm.commit_workflow("wf-1", _flow(["a", "x"]))
    with pytest.raises(sc.ConflictError):
        scm.commit_workflow("wf-1", _flow(["a", "y"]), expect_sha=base)
    # setelah mengambil sha terbaru -> sukses
    base2 = scm.pull_workflow("wf-1")["sha"]
    r = scm.commit_workflow("wf-1", _flow(["a", "y"]), expect_sha=base2)
    assert r["created"] is False


# 9. Multi-user: 2 user edit workflow (branch terpisah)
def test_09_multiuser(gh):
    scm, _ = gh
    scm.commit_workflow("wf-1", _flow(["a"]))
    scm.create_branch("alice", "main")
    scm.create_branch("bob", "main")
    scm.commit_workflow("wf-1", _flow(["a", "alice"]), branch="alice")
    scm.commit_workflow("wf-1", _flow(["a", "bob"]), branch="bob")
    assert len(scm.pull_workflow("wf-1", "alice")["flow_data"]["nodes"]) == 2
    assert len(scm.pull_workflow("wf-1", "bob")["flow_data"]["nodes"]) == 2


# 10. Webhook push -> sync
def test_10_webhook(gh):
    scm, _ = gh
    payload = {"ref": "refs/heads/main",
               "commits": [{"modified": ["workflows/wf-1.json",
                                         "workflows/wf-2.json"],
                            "added": ["README.md"]}]}
    out = scm.sync_from_webhook(payload)
    assert out["branch"] == "main"
    assert out["workflow_ids"] == ["wf-1", "wf-2"]


# 11. Performa: 100 commit
def test_11_performance_100(gh):
    scm, _ = gh
    t0 = time.perf_counter()
    for i in range(100):
        scm.commit_workflow(f"wf-{i}", _flow(["a", "b"]))
    dt = time.perf_counter() - t0
    assert dt < 3.0, f"100 commit terlalu lambat: {dt:.3f}s"


# 12. Keamanan: token tidak bocor
def test_12_no_token_leak(gh):
    scm, _ = gh
    bocor = sc.redact("Authorization Bearer ghp_secrettoken123456 "
                      "dan glpat-abcdefghijklmnop")
    assert "ghp_secrettoken123456" not in bocor
    assert "glpat-abcdefghijklmnop" not in bocor
    assert sc.MASK in bocor
    # pesan error pun tidak memuat token
    try:
        scm.client.call("GET", "/repos/me/repo/contents/x?ref=main")
    except sc.GitError as exc:
        assert "ghp_secrettoken123456" not in str(exc)


# ---------------------------------------------------------------------------
# REGRESI konsistensi eventual Contents API (Okt 2026).
# GitHub kadang mengembalikan SHA basi (409) atau "sha wasn't supplied" (422)
# tepat sesudah PUT. Praktik terbaik = retry terbatas + backoff (go-github
# #2707). Test ini GAGAL bila penanganan retry hilang.
# ---------------------------------------------------------------------------
class _Inject:
    """Transport pembungkus: `n_fail` PUT pertama dipaksa gagal (bisa di-arm)."""

    def __init__(self, fake, n_fail: int, status: int, body: dict,
                 armed: bool = True):
        self.fake = fake
        self.n_fail = n_fail
        self.status = status
        self.body = body
        self.armed = armed
        self.n = 0

    def __call__(self, method, url, headers, b):
        if (self.armed and self.n < self.n_fail
                and method == "PUT" and "/contents/" in url):
            self.n += 1
            return self.status, dict(self.body)
        return self.fake.transport(method, url, headers, b)


@pytest.fixture
def no_sleep(monkeypatch):
    """Hilangkan jeda backoff supaya test tetap cepat."""
    monkeypatch.setattr(sc.time, "sleep", lambda *_: None)


# 13. 409 transien (SHA basi) -> otomatis dicoba ulang, akhirnya SUKSES
def test_13_retry_transient_409(no_sleep):
    fake = FakeGitHub()
    inj = _Inject(fake, 2, 409, {"message": "sha mismatch"})
    client = sc.make_client("github", "ghp_secrettoken123456", "me/repo",
                            transport=inj)
    scm = sc.SourceControl(client)
    r1 = scm.commit_workflow("wf-1", _flow(["a"]))  # 2x 409 lalu sukses
    assert r1["sha"] and r1["created"] is True
    r2 = scm.commit_workflow("wf-1", _flow(["a", "b"]))
    assert r2["sha"] and r2["created"] is False
    assert len(scm.pull_workflow("wf-1")["flow_data"]["nodes"]) == 2
    assert inj.n == 2  # benar-benar ada 2 kegagalan transien yang di-retry


# 14. 422 "sha wasn't supplied" (berkas baru belum tersinkron) -> retry SUKSES
def test_14_retry_transient_422(no_sleep):
    fake = FakeGitHub()
    inj = _Inject(fake, 1, 422,
                  {"message": 'Invalid request. "sha" wasn\'t supplied.'})
    client = sc.make_client("github", "ghp_secrettoken123456", "me/repo",
                            transport=inj)
    scm = sc.SourceControl(client)
    r = scm.commit_workflow("wf-1", _flow(["a"]))  # 1x 422 lalu sukses
    assert r["sha"] and r["created"] is True
    assert inj.n == 1


# 15. Konflik OPTIMISTIK (expect_sha) TIDAK di-retry -> naik ke pemanggil
def test_15_expect_sha_not_retried(no_sleep):
    fake = FakeGitHub()
    inj = _Inject(fake, 99, 409, {"message": "sha mismatch"}, armed=False)
    client = sc.make_client("github", "ghp_secrettoken123456", "me/repo",
                            transport=inj)
    scm = sc.SourceControl(client)
    scm.commit_workflow("wf-1", _flow(["a"]))          # belum di-arm -> sukses
    base = scm.pull_workflow("wf-1")["sha"]
    inj.armed = True
    with pytest.raises(sc.ConflictError):
        scm.commit_workflow("wf-1", _flow(["a", "b"]), expect_sha=base)
    assert inj.n == 1  # HANYA 1 percobaan: tidak di-retry


# 16. 409 PERSISTEN -> menyerah setelah 5 percobaan (tidak menggantung)
def test_16_retry_gives_up(no_sleep):
    fake = FakeGitHub()
    inj = _Inject(fake, 99, 409, {"message": "sha mismatch"})
    client = sc.make_client("github", "ghp_secrettoken123456", "me/repo",
                            transport=inj)
    scm = sc.SourceControl(client)
    with pytest.raises(sc.ConflictError):
        scm.commit_workflow("wf-1", _flow(["a"]))
    assert inj.n == 6  # 1 percobaan awal + 5 retry, lalu menyerah
