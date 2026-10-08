# source_control.py — Fitur #5: Source Control / Git (Okt 2026)
# ======================================================================
# Versioning workflow via Git: workflow -> JSON -> commit ke repo; branch, PR,
# diff, rollback, dan sync dari webhook push.
#
# RISET (Okt 2026): GitHub/GitLab/Bitbucket REST API tetap cara paling ringan
# (tidak menambah dependensi SDK berat). Semua panggilan lewat TRANSPORT yang
# dapat disuntik -> diuji tanpa jaringan dengan server Git tiruan; produksi
# memakai `urllib` (stdlib).
#
# KEAMANAN: token TIDAK PERNAH ditulis ke log/pesan error (selalu di-redact).
# ======================================================================

from __future__ import annotations

import base64
import json
import re
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

#: Transport: (method, url, headers, body) -> (status:int, data:dict)
Transport = Callable[[str, str, dict, Optional[dict]], tuple[int, dict]]

_TOKEN_RE = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{10,}|glpat-[A-Za-z0-9_\-]{10,}|"
    r"ATATT[A-Za-z0-9_\-]{10,}|Bearer\s+[A-Za-z0-9._\-]{8,})")
MASK = "***"


class GitError(Exception):
    """Kesalahan umum lapisan source control."""


class ConflictError(GitError):
    """SHA dasar tidak cocok (orang lain sudah menulis lebih dulu)."""


class NotFoundError(GitError):
    """Berkas/ref tidak ditemukan."""


def redact(text: Any) -> Any:
    """Mask semua token/rahasia (rekursif) sebelum log/pesan error."""
    if isinstance(text, str):
        return _TOKEN_RE.sub(MASK, text)
    if isinstance(text, dict):
        return {k: redact(v) for k, v in text.items()}
    if isinstance(text, list):
        return [redact(v) for v in text]
    return text


# ---------------------------------------------------------------------------
# Serialisasi workflow (format kanonik untuk repo)
# ---------------------------------------------------------------------------

def serialize_workflow(workflow_id: str, flow_data: dict,
                       meta: Optional[dict] = None) -> str:
    """Workflow -> JSON kanonik (sort_keys) supaya diff stabil."""
    return json.dumps({
        "schema": "katalir/workflow/v1",
        "id": workflow_id,
        "flow_data": flow_data,
        "meta": meta or {},
    }, indent=2, sort_keys=True, ensure_ascii=False)


def deserialize_workflow(text: str) -> dict:
    """JSON repo -> flow_data (tahan bentuk lama yang polos)."""
    data = json.loads(text)
    if isinstance(data, dict) and "flow_data" in data:
        return data["flow_data"]
    return data


def workflow_path(workflow_id: str, prefix: str = "workflows/") -> str:
    return f"{prefix}{workflow_id}.json"


# ---------------------------------------------------------------------------
# Klien Git (provider)
# ---------------------------------------------------------------------------

class GitClient(ABC):
    provider = "?"

    def __init__(self, token: str, repo: str, transport: Optional[Transport] = None,
                 base: str = "") -> None:
        self.token = token or ""
        self.repo = repo or ""
        self._transport = transport
        self.base = base

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def _http(self, method: str, url: str, headers: dict,
              body: Optional[dict]) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in headers.items():
            req.add_header(k, v)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:  # pragma: no cover - jaringan
            try:
                return exc.code, json.loads(exc.read() or b"{}")
            except Exception:  # noqa: BLE001
                return exc.code, {}

    def call(self, method: str, path: str,
             body: Optional[dict] = None) -> dict:
        url = (path if path.startswith("http") else self.base + path)
        headers = self.headers()
        if self._transport is not None:
            status, data = self._transport(method, url, headers, body)
        else:  # pragma: no cover - jaringan
            status, data = self._http(method, url, headers, body)
        if status == 404:
            raise NotFoundError(f"tidak ditemukan: {redact(path)}")
        if status == 409:
            raise ConflictError("konflik: SHA dasar tidak cocok")
        if status >= 400:
            raise GitError(f"HTTP {status}: {redact(str(data)[:200])}")
        return data

    # -- abstraksi provider ------------------------------------------------
    @abstractmethod
    def read_file(self, path: str, ref: str) -> tuple[str, str]:
        """Return (konten, sha)."""

    @abstractmethod
    def write_file(self, path: str, content: str, message: str, branch: str,
                   sha: Optional[str]) -> dict:
        ...

    @abstractmethod
    def list_branches(self) -> list[str]:
        ...

    @abstractmethod
    def create_branch(self, name: str, from_ref: str) -> dict:
        ...

    @abstractmethod
    def create_pr(self, head: str, base: str, title: str,
                  body: str = "") -> dict:
        ...

    @abstractmethod
    def merge_pr(self, number: Any) -> dict:
        ...

    @abstractmethod
    def compare(self, base: str, head: str) -> dict:
        ...


class GitHubClient(GitClient):
    provider = "github"

    def __init__(self, token, repo, transport=None, base="https://api.github.com"):
        super().__init__(token, repo, transport, base)

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json"}

    def read_file(self, path, ref):
        d = self.call("GET", f"/repos/{self.repo}/contents/{path}?ref={ref}")
        konten = base64.b64decode(d.get("content", "")).decode("utf-8")
        return konten, d.get("sha", "")

    def write_file(self, path, content, message, branch, sha):
        body = {"message": message,
                "content": base64.b64encode(content.encode()).decode(),
                "branch": branch}
        if sha:
            body["sha"] = sha
        return self.call("PUT", f"/repos/{self.repo}/contents/{path}", body)

    def list_branches(self):
        return [b["name"] for b in self.call("GET", f"/repos/{self.repo}/branches")]

    def create_branch(self, name, from_ref):
        sha = self.call("GET", f"/repos/{self.repo}/commits/{from_ref}")["sha"]
        return self.call("POST", f"/repos/{self.repo}/git/refs",
                         {"ref": f"refs/heads/{name}", "sha": sha})

    def create_pr(self, head, base, title, body=""):
        return self.call("POST", f"/repos/{self.repo}/pulls",
                         {"head": head, "base": base, "title": title,
                          "body": body})

    def merge_pr(self, number):
        return self.call("PUT", f"/repos/{self.repo}/pulls/{number}/merge", {})

    def compare(self, base, head):
        return self.call("GET", f"/repos/{self.repo}/compare/{base}...{head}")


class GitLabClient(GitClient):
    provider = "gitlab"

    def __init__(self, token, repo, transport=None,
                 base="https://gitlab.com/api/v4"):
        super().__init__(token, repo, transport, base)
        # repo = "namespace/project" -> dipakai apa adanya (URL-encoded).
        self._pid = urllib.parse.quote(repo, safe="")

    def headers(self):
        return {"PRIVATE-TOKEN": self.token}

    def read_file(self, path, ref):
        p = urllib.parse.quote(path, safe="")
        raw = self.call("GET", f"/projects/{self._pid}/repository/files/{p}/raw?ref={ref}")
        return raw.get("_raw", ""), raw.get("_sha", "")

    def write_file(self, path, content, message, branch, sha):
        p = urllib.parse.quote(path, safe="")
        method = "PUT" if sha else "POST"
        return self.call(method, f"/projects/{self._pid}/repository/files/{p}",
                         {"branch": branch, "content": content,
                          "commit_message": message})

    def list_branches(self):
        return [b["name"] for b in
                self.call("GET", f"/projects/{self._pid}/repository/branches")]

    def create_branch(self, name, from_ref):
        return self.call("POST", f"/projects/{self._pid}/repository/branches",
                         {"branch": name, "ref": from_ref})

    def create_pr(self, head, base, title, body=""):
        return self.call("POST", f"/projects/{self._pid}/merge_requests",
                         {"source_branch": head, "target_branch": base,
                          "title": title, "description": body})

    def merge_pr(self, number):
        return self.call("PUT", f"/projects/{self._pid}/merge_requests/{number}/merge",
                         {})

    def compare(self, base, head):
        return self.call("GET",
                         f"/projects/{self._pid}/repository/compare"
                         f"?from={base}&to={head}")


class BitbucketClient(GitClient):
    provider = "bitbucket"

    def __init__(self, token, repo, transport=None,
                 base="https://api.bitbucket.org/2.0"):
        super().__init__(token, repo, transport, base)

    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def read_file(self, path, ref):
        d = self.call("GET", f"/repositories/{self.repo}/src/{ref}/{path}")
        return d.get("_raw", ""), d.get("_sha", "")

    def write_file(self, path, content, message, branch, sha):
        return self.call("POST", f"/repositories/{self.repo}/src",
                         {"path": path, "content": content, "message": message,
                          "branch": branch})

    def list_branches(self):
        d = self.call("GET", f"/repositories/{self.repo}/refs/branches")
        return [b["name"] for b in d.get("values", [])]

    def create_branch(self, name, from_ref):
        return self.call("POST", f"/repositories/{self.repo}/refs/branches",
                         {"name": name, "target": {"hash": from_ref}})

    def create_pr(self, head, base, title, body=""):
        return self.call("POST", f"/repositories/{self.repo}/pullrequests",
                         {"source": {"branch": {"name": head}},
                          "destination": {"branch": {"name": base}},
                          "title": title, "description": body})

    def merge_pr(self, number):
        return self.call("POST",
                         f"/repositories/{self.repo}/pullrequests/{number}/merge",
                         {})

    def compare(self, base, head):
        return self.call("GET",
                         f"/repositories/{self.repo}/diff/{head}..{base}")


import urllib.error  # noqa: E402  (dipakai _http)
import urllib.parse  # noqa: E402

PROVIDERS: dict[str, type[GitClient]] = {
    "github": GitHubClient,
    "gitlab": GitLabClient,
    "bitbucket": BitbucketClient,
}


def make_client(provider: str, token: str, repo: str,
                transport: Optional[Transport] = None) -> GitClient:
    cls = PROVIDERS.get((provider or "").strip().lower())
    if not cls:
        raise GitError(f"provider tidak dikenal: {provider!r} "
                       f"(pilih {sorted(PROVIDERS)})")
    return cls(token, repo, transport=transport)


# ---------------------------------------------------------------------------
# Operasi tingkat tinggi
# ---------------------------------------------------------------------------

class SourceControl:
    """Operasi workflow di atas sebuah `GitClient`."""

    def __init__(self, client: GitClient, prefix: str = "workflows/") -> None:
        self.client = client
        self.prefix = prefix

    def _path(self, workflow_id: str) -> str:
        return workflow_path(workflow_id, self.prefix)

    def commit_workflow(self, workflow_id: str, flow_data: dict,
                        branch: str = "main", message: str = "",
                        expect_sha: Optional[str] = None,
                        meta: Optional[dict] = None) -> dict:
        """Commit workflow ke repo. `expect_sha` -> deteksi konflik."""
        path = self._path(workflow_id)
        sha: Optional[str] = None
        try:
            _, sha = self.client.read_file(path, branch)
        except NotFoundError:
            sha = None
        if expect_sha is not None and expect_sha != (sha or ""):
            raise ConflictError(
                f"konflik pada {workflow_id}: dasar {expect_sha[:7]} "
                f"≠ remote {(sha or 'none')[:7]}")
        text = serialize_workflow(workflow_id, flow_data, meta)
        res = self.client.write_file(
            path, text, message or f"chore: update workflow {workflow_id}",
            branch, sha)
        commit_sha = ""
        if isinstance(res, dict):
            commit_sha = (res.get("commit") or {}).get("sha") or res.get("sha") or ""
        return {"workflow_id": workflow_id, "path": path, "branch": branch,
                "sha": commit_sha, "created": sha is None}

    def pull_workflow(self, workflow_id: str, ref: str = "main") -> dict:
        text, sha = self.client.read_file(self._path(workflow_id), ref)
        return {"workflow_id": workflow_id, "flow_data":
                deserialize_workflow(text), "sha": sha, "ref": ref}

    def diff(self, workflow_id: str, base: str, head: str) -> dict:
        d = self.client.compare(base, head)
        files = d.get("files") or d.get("diffs") or []
        return {"workflow_id": workflow_id, "base": base, "head": head,
                "files": files,
                "ahead_by": d.get("ahead_by", len(files)),
                "status": d.get("status", "")}

    def rollback(self, workflow_id: str, to_sha: str,
                 branch: str = "main") -> dict:
        text, _ = self.client.read_file(self._path(workflow_id), to_sha)
        flow = deserialize_workflow(text)
        return self.commit_workflow(
            workflow_id, flow, branch=branch,
            message=f"revert: rollback {workflow_id} ke {to_sha[:7]}")

    def create_branch(self, name: str, from_ref: str = "main") -> dict:
        self.client.create_branch(name, from_ref)
        return {"branch": name, "from": from_ref}

    def list_branches(self) -> list[str]:
        return self.client.list_branches()

    def open_pr(self, head: str, base: str, title: str,
                body: str = "") -> dict:
        d = self.client.create_pr(head, base, title, body)
        return {"number": d.get("number") or d.get("iid"),
                "head": head, "base": base, "state": d.get("state", "open")}

    def merge_pr(self, number: Any) -> dict:
        d = self.client.merge_pr(number)
        return {"number": number, "merged": bool(d.get("merged", True)),
                "sha": d.get("sha", "")}

    def sync_from_webhook(self, payload: dict,
                          prefix: Optional[str] = None) -> dict:
        """Terjemahkan event push Git -> daftar workflow yang berubah."""
        prefix = prefix or self.prefix
        ref = str(payload.get("ref") or payload.get("branch") or "")
        branch = ref.replace("refs/heads/", "") if ref else ""
        berubah: set[str] = set()
        for c in payload.get("commits") or []:
            for key in ("added", "modified", "removed"):
                for f in c.get(key) or []:
                    if f.startswith(prefix) and f.endswith(".json"):
                        berubah.add(f[len(prefix):-len(".json")])
        return {"branch": branch, "workflow_ids": sorted(berubah),
                "count": len(berubah)}


# ---------------------------------------------------------------------------
# Simpanan koneksi git (token DIENKRIPSI saat disimpan, TIDAK pernah dikembalikan)
# ---------------------------------------------------------------------------

def _encrypt(token: str) -> str:
    try:
        import vault_security
        return vault_security.encrypt_key(token)
    except Exception:  # noqa: BLE001 - dev tanpa kunci: simpan bertanda
        return "plain:" + token


def _decrypt(cipher: str) -> str:
    if cipher.startswith("plain:"):
        return cipher[6:]
    import vault_security
    return vault_security.decrypt_key(cipher)


def _mask(token: str) -> str:
    if not token:
        return ""
    return token[:4] + "…" + token[-2:] if len(token) > 8 else MASK


class ConnectionStore:
    """Koneksi git per (owner, provider). Token disimpan terenkripsi."""

    def __init__(self) -> None:
        self._d: dict[tuple[str, str], dict] = {}

    def save(self, owner: str, provider: str, repo: str, token: str) -> dict:
        if provider not in PROVIDERS:
            raise GitError(f"provider tidak dikenal: {provider!r}")
        if not repo:
            raise GitError("repo wajib diisi")
        self._d[(owner, provider)] = {"repo": repo,
                                      "enc": _encrypt(token or "")}
        return {"provider": provider, "repo": repo, "token": _mask(token or "")}

    def get(self, owner: str, provider: str) -> Optional[dict]:
        rec = self._d.get((owner, provider))
        if not rec:
            return None
        return {"provider": provider, "repo": rec["repo"],
                "token": _decrypt(rec["enc"])}

    def list(self, owner: str) -> list[dict]:
        return [{"provider": p, "repo": r["repo"],
                 "token": _mask(_decrypt(r["enc"]))}
                for (o, p), r in sorted(self._d.items()) if o == owner]

    def delete(self, owner: str, provider: str) -> bool:
        return self._d.pop((owner, provider), None) is not None

    def client(self, owner: str, provider: str,
               transport: Optional[Transport] = None) -> "GitClient":
        rec = self.get(owner, provider)
        if not rec:
            raise GitError(f"belum terhubung ke {provider}")
        return make_client(provider, rec["token"], rec["repo"],
                           transport=transport)
