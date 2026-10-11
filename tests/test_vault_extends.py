"""Hard test TASK 4 — extendsCredential (pewarisan kredensial vault).

12 skenario: basic extends, multi-level, siklus, kedalaman, induk hilang,
override field, isolasi tenant, terenkripsi at rest, performa, resolve
paralel, audit log, dan regresi `secret://`.
"""
from __future__ import annotations

import threading
import time

import pytest

import vault_extends as ve

USER = "budi@katalir.test"


def _loader_from(store: dict):
    def _load(user_email: str, provider: str):
        return store.get((user_email, provider))
    return _load


# 1. Basic extends -> resolve OK ------------------------------------------
def test_01_basic_extends():
    store = {
        (USER, "base"): {"host": "smtp.test", "port": "587", "user": "budi"},
        (USER, "child"): {ve.EXTENDS_KEY: "extends://base", "user": "budi2"},
    }
    merged = ve.resolve_extends("child", USER, loader=_loader_from(store))
    assert merged["host"] == "smtp.test"   # warisan
    assert merged["user"] == "budi2"        # override anak


# 2. Multi-level (3 level) ------------------------------------------------
def test_02_multi_level_three():
    store = {
        (USER, "l1"): {"a": "1", "b": "1", "c": "1"},
        (USER, "l2"): {ve.EXTENDS_KEY: "extends://l1", "b": "2"},
        (USER, "l3"): {ve.EXTENDS_KEY: "extends://l2", "c": "3"},
    }
    merged = ve.resolve_extends("l3", USER, loader=_loader_from(store))
    assert merged == {"a": "1", "b": "2", "c": "3"}


# 3. Circular -> error ----------------------------------------------------
def test_03_circular_detected():
    store = {
        (USER, "a"): {ve.EXTENDS_KEY: "extends://b"},
        (USER, "b"): {ve.EXTENDS_KEY: "extends://a"},
    }
    with pytest.raises(ve.CircularCredentialError):
        ve.resolve_extends("a", USER, loader=_loader_from(store))


def test_03b_self_cycle_detected():
    store = {(USER, "self"): {ve.EXTENDS_KEY: "extends://self"}}
    with pytest.raises(ve.CircularCredentialError):
        ve.resolve_extends("self", USER, loader=_loader_from(store))


# 4. Max depth exceeded ---------------------------------------------------
def test_04_depth_exceeded():
    store = {}
    for i in range(10):
        store[(USER, f"p{i}")] = {ve.EXTENDS_KEY: f"extends://p{i+1}"}
    store[(USER, "p10")] = {"leaf": "x"}
    with pytest.raises(ve.DepthExceededError):
        ve.resolve_extends("p0", USER, loader=_loader_from(store), max_depth=5)


def test_04b_depth_boundary_ok():
    store = {}
    for i in range(4):
        store[(USER, f"d{i}")] = {ve.EXTENDS_KEY: f"extends://d{i+1}"}
    store[(USER, "d4")] = {"leaf": "x"}
    merged = ve.resolve_extends("d0", USER, loader=_loader_from(store), max_depth=5)
    assert merged["leaf"] == "x"


# 5. Missing parent -> error ----------------------------------------------
def test_05_missing_parent():
    store = {(USER, "child"): {ve.EXTENDS_KEY: "extends://ghost"}}
    with pytest.raises(ve.MissingParentError):
        ve.resolve_extends("child", USER, loader=_loader_from(store))


# 6. Field override -> child wins -----------------------------------------
def test_06_field_override_child_wins():
    store = {
        (USER, "base"): {"token": "LAMA", "region": "us"},
        (USER, "child"): {ve.EXTENDS_KEY: "extends://base", "token": "BARU"},
    }
    merged = ve.resolve_extends("child", USER, loader=_loader_from(store))
    assert merged["token"] == "BARU"
    assert merged["region"] == "us"


# 7. Multi-tenant isolation -----------------------------------------------
def test_07_multi_tenant_isolation():
    store = {
        (USER, "base"): {"secret": "punya-budi"},
        ("lain@katalir.test", "base"): {"secret": "punya-lain"},
    }
    a = ve.resolve_extends("base", USER, loader=_loader_from(store))
    b = ve.resolve_extends("base", "lain@katalir.test", loader=_loader_from(store))
    assert a["secret"] == "punya-budi"
    assert b["secret"] == "punya-lain"


# 8. Encrypted at rest -> loader default = jalur dekripsi ------------------
def test_08_default_loader_is_decrypting_path(monkeypatch):
    calls = {}

    def fake_load(user_email, provider):
        calls["args"] = (user_email, provider)
        return {"k": "v"}

    import credential_forms
    monkeypatch.setattr(credential_forms, "load_vault_credential", fake_load)
    merged = ve.resolve_extends("x", USER)  # tanpa loader -> default
    assert merged == {"k": "v"}
    assert calls["args"] == (USER, "x")


# 9. Performance ----------------------------------------------------------
def test_09_performance():
    store = {
        (USER, "base"): {"a": "1", "b": "2"},
        (USER, "child"): {ve.EXTENDS_KEY: "extends://base", "b": "3"},
    }
    load = _loader_from(store)
    t0 = time.perf_counter()
    for _ in range(1000):
        ve.resolve_extends("child", USER, loader=load)
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"1000 resolve = {elapsed:.3f}s"


# 10. Concurrent resolve --------------------------------------------------
def test_10_concurrent_resolve():
    store = {
        (USER, "base"): {"a": "1"},
        (USER, "child"): {ve.EXTENDS_KEY: "extends://base", "b": "2"},
    }
    load = _loader_from(store)
    results, errors = [], []

    def work():
        try:
            results.append(ve.resolve_extends("child", USER, loader=load))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(results) == 50
    assert all(r == {"a": "1", "b": "2"} for r in results)


# 11. Audit log -----------------------------------------------------------
def test_11_audit_log():
    store = {
        (USER, "base"): {"a": "RAHASIA-XYZ"},
        (USER, "child"): {ve.EXTENDS_KEY: "extends://base", "b": "2"},
    }
    audit: list[dict] = []
    ve.resolve_extends("child", USER, loader=_loader_from(store), audit=audit)
    provs = [e["provider"] for e in audit]
    assert provs == ["base", "child"]      # induk dulu, lalu anak
    assert audit[1]["parent"] == "base"
    # Tidak ada NILAI rahasia di audit (hanya nama provider/field).
    assert "RAHASIA-XYZ" not in str(audit)


# 12. Regresi: parsing ref + secret:// tetap jalan -------------------------
def test_12_parse_refs():
    assert ve.parse_ref("secret://gmail/app_password") == ("secret", "gmail", "app_password")
    assert ve.parse_ref("secret://gmail#app_password") == ("secret", "gmail", "app_password")
    assert ve.parse_ref("extends://team") == ("extends", "team", None)
    assert ve.parse_ref("extends://team#host") == ("extends", "team", "host")
    with pytest.raises(ve.RefParseError):
        ve.parse_ref("http://bukan-ref")


def test_12b_secret_ref_delegates_to_broker(monkeypatch):
    import vault_broker
    monkeypatch.setattr(vault_broker, "resolve_secret", lambda ref, user: f"OK:{ref}")
    assert ve.resolve_ref("secret://p/f", USER) == "OK:secret://p/f"


def test_12c_extends_field_selection():
    store = {(USER, "team"): {"host": "h", "port": "587"}}
    assert ve.resolve_ref("extends://team#port", USER, loader=_loader_from(store)) == "587"
    with pytest.raises(ve.CredentialResolveError):
        ve.resolve_ref("extends://team#nope", USER, loader=_loader_from(store))
