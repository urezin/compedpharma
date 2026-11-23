"""App tests: auth and rate limiting, deletion/export, Stripe webhook revocation, legal pages.

Run from the repo root:  python -m pytest -q tests
No network: VigiEye and Stripe calls are replaced with fakes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
from datetime import timedelta

import pytest

_DB = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_DB}",
    "SESSION_SECRET": "test-session-secret",
    "STRIPE_SECRET_KEY": "sk_test_dummy",
    "STRIPE_WEBHOOK_SECRET": "whsec_test_dummy",
    "DISABLE_PURGE_THREAD": "1",
    "READERS_API_SECRET": "readers-secret",
    "VIGIEYE_API": "https://vigieye.invalid",
})
for k in ("RENDER", "ENV", "ALLOW_SELF_GRANT", "ADMIN_TOKEN"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
import portal  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

portal._get = lambda path, timeout=25: {"items": []}      # no VigiEye calls from the news pages


@pytest.fixture()
def client():
    main._hits.clear()
    with TestClient(main.app) as c:
        yield c


def _register(c, email="a@example.com", pw="password123"):
    r = c.post("/api/register", json={"email": email, "password": pw, "name": "A", "org": "Org"})
    assert r.status_code == 200, r.text
    return r


def _acc(email):
    with main.SessionLocal() as db:
        return db.execute(main.select(main.Account).where(main.Account.email == email)).scalars().first()


def _grant(email, module, sub_id):
    with main.SessionLocal() as db:
        acc = db.execute(main.select(main.Account).where(main.Account.email == email)).scalars().first()
        db.add(main.ModuleGrant(account_id=acc.id, module=module, stripe_subscription_id=sub_id))
        db.commit()
        return acc.id


def _signed(payload: dict, secret="whsec_test_dummy", ts=None):
    body = json.dumps(payload)
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return body, {"stripe-signature": f"t={ts},v1={sig}", "content-type": "application/json"}


def _event(etype, obj):
    return {"id": "evt_1", "object": "event", "type": etype, "data": {"object": obj}}


# ---------------------------------------------------------------- auth

def test_register_login_me(client):
    _register(client, "u1@example.com")
    assert client.get("/api/me").json()["authenticated"] is True
    client.get("/api/logout", follow_redirects=False)
    assert client.get("/api/me").json()["authenticated"] is False
    assert client.post("/api/login", json={"email": "u1@example.com", "password": "wrong-pass"}).status_code == 401
    assert client.post("/api/login", json={"email": "u1@example.com", "password": "password123"}).status_code == 200


def test_forged_session_rejected(client):
    _register(client, "u2@example.com")
    acc = _acc("u2@example.com")
    raw = json.dumps({"uid": acc.id, "exp": int(time.time()) + 999}, separators=(",", ":")).encode()
    for key in ("dev-insecure-compedpharma", "whsec_test_dummy"):     # the old fallbacks
        tok = main._b64(raw) + "." + main._b64(hmac.new(key.encode(), raw, hashlib.sha256).digest())
        client.cookies.set(main.COOKIE_NAME, tok)
        assert client.get("/api/me").json()["authenticated"] is False


def test_login_rate_limited(client):
    _register(client, "u3@example.com")
    client.cookies.clear()
    for _ in range(main.LOGIN_MAX_FAILS):
        assert client.post("/api/login", json={"email": "u3@example.com", "password": "nope-nope"}).status_code == 401
    r = client.post("/api/login", json={"email": "u3@example.com", "password": "password123"})
    assert r.status_code == 429


def test_auth_disabled_without_secret(monkeypatch, client):
    monkeypatch.setattr(main, "AUTH_ENABLED", False)
    assert client.post("/api/register", json={"email": "x@example.com", "password": "password123"}).status_code == 503
    assert client.post("/api/login", json={"email": "x@example.com", "password": "password123"}).status_code == 503
    assert main.read_session("anything.here") is None


def test_module_data_requires_auth_and_ownership(client):
    assert client.get("/api/crm/contacts").status_code == 401
    _register(client, "u4@example.com")
    assert client.get("/api/crm/contacts").status_code == 403


# ---------------------------------------------------------------- deletion and export

def test_delete_records_and_cross_account_isolation(client):
    _register(client, "owner@example.com")
    _grant("owner@example.com", "crm", "")
    _grant("owner@example.com", "hr", "")
    _grant("owner@example.com", "ats", "")
    _grant("owner@example.com", "docs", "")
    cid = client.post("/api/crm/contacts", json={"name": "Dr Who", "email": "dr@example.com"}).json()["id"]
    eid = client.post("/api/hr/employees", json={"name": "Emp"}).json()["id"]
    lid = client.post("/api/hr/leave", json={"employee": "Emp"}).json()["id"]
    oid = client.post("/api/hr/onboarding", json={"employee": "Emp", "task": "Sign"}).json()["id"]
    kid = client.post("/api/ats/candidates", json={"name": "Cand"}).json()["id"]
    did = client.post("/api/docs/documents", json={"title": "SOP"}).json()["id"]
    client.post(f"/api/docs/documents/{did}/route", json={"steps": [{"role": "QA", "name": "Q"}]})
    client.post("/api/docs/ack", json={"document_id": did, "who": "Emp"})

    other = TestClient(main.app)
    _register(other, "intruder@example.com")
    _grant("intruder@example.com", "crm", "")
    assert other.delete(f"/api/crm/contacts/{cid}").status_code == 404     # not theirs

    for path in (f"/api/crm/contacts/{cid}", f"/api/hr/employees/{eid}", f"/api/hr/leave/{lid}",
                 f"/api/hr/onboarding/{oid}", f"/api/ats/candidates/{kid}", f"/api/docs/documents/{did}"):
        assert client.delete(path).status_code == 200, path
    assert client.get("/api/crm/contacts").json()["items"] == []
    with main.SessionLocal() as db:
        for m in (main.Contact, main.Employee, main.LeaveRequest, main.OnboardingTask, main.Candidate,
                  main.Document, main.ApprovalStep, main.Acknowledgement):
            assert db.execute(main.select(main.func.count(m.id))).scalar() == 0, m.__tablename__
    assert client.delete("/api/crm/nothing/1").status_code == 404


def test_export_json_and_csv(client):
    _register(client, "exp@example.com")
    _grant("exp@example.com", "crm", "")
    client.post("/api/crm/contacts", json={"name": "Jane", "email": "jane@example.com"})
    j = client.get("/api/account/export?format=json")
    assert j.status_code == 200 and "attachment" in j.headers["content-disposition"]
    data = j.json()
    assert data["account"]["email"] == "exp@example.com"
    assert data["crm_contacts"][0]["name"] == "Jane"
    assert "password_hash" not in json.dumps(data)
    z = client.get("/api/account/export?format=csv")
    import io, zipfile
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert "crm_contacts.csv" in names and "account.csv" in names


def test_delete_account_removes_everything_and_cancels_stripe(monkeypatch, client):
    _register(client, "gone@example.com")
    aid = _grant("gone@example.com", "crm", "sub_123")
    client.post("/api/crm/contacts", json={"name": "C"})
    cancelled = []

    class FakeSub:
        @staticmethod
        def cancel(sid):
            cancelled.append(sid)

    class FakeStripe:
        Subscription = FakeSub
    monkeypatch.setattr(main, "_stripe", lambda: FakeStripe)
    assert client.post("/api/account/delete", json={"password": "wrong-one"}).status_code == 401
    r = client.post("/api/account/delete", json={"password": "password123"})
    assert r.status_code == 200
    assert cancelled == ["sub_123"]
    with main.SessionLocal() as db:
        assert db.get(main.Account, aid) is None
        for m in main.ACCOUNT_TABLES:
            assert db.execute(main.select(main.func.count(m.id)).where(m.account_id == aid)).scalar() == 0
    assert client.get("/api/me").json()["authenticated"] is False


def test_purge_closed_accounts():
    with main.SessionLocal() as db:
        old = main.Account(email="old@example.com", closed_at=(main.utcnow() - timedelta(days=200)).isoformat())
        new = main.Account(email="new@example.com", closed_at=(main.utcnow() - timedelta(days=10)).isoformat())
        db.add_all([old, new]); db.commit()
        db.add(main.Contact(account_id=old.id, name="x")); db.commit()
        old_id, new_id = old.id, new.id
        assert main.purge_closed_accounts(db) >= 1
        assert db.get(main.Account, old_id) is None
        assert db.get(main.Account, new_id) is not None
        assert db.execute(main.select(main.func.count(main.Contact.id)).where(main.Contact.account_id == old_id)).scalar() == 0


# ---------------------------------------------------------------- Stripe webhook

def test_webhook_fails_closed_without_secret(monkeypatch, client):
    monkeypatch.setattr(main, "STRIPE_WEBHOOK_SECRET", "")
    body, h = _signed(_event("customer.subscription.deleted", {"id": "sub_x"}))
    assert client.post("/api/stripe/webhook", content=body, headers=h).status_code == 503


def test_webhook_rejects_bad_signature(client):
    _register(client, "sig@example.com")
    _grant("sig@example.com", "crm", "sub_sig")
    body, h = _signed(_event("customer.subscription.deleted", {"id": "sub_sig"}), secret="whsec_wrong")
    assert client.post("/api/stripe/webhook", content=body, headers=h).status_code == 400
    assert "crm" in client.get("/api/me").json()["owned"]


def test_webhook_deleted_revokes_module_and_closes_account(client):
    _register(client, "wh@example.com")
    _grant("wh@example.com", "crm", "sub_del")
    assert client.get("/api/crm/contacts").status_code == 200
    body, h = _signed(_event("customer.subscription.deleted", {"id": "sub_del", "object": "subscription"}))
    assert client.post("/api/stripe/webhook", content=body, headers=h).status_code == 200
    assert client.get("/api/crm/contacts").status_code == 403
    assert _acc("wh@example.com").closed_at != ""


def test_webhook_payment_failed_revokes_suite_and_active_restores(client):
    _register(client, "suite@example.com")
    with main.SessionLocal() as db:
        acc = db.execute(main.select(main.Account).where(main.Account.email == "suite@example.com")).scalars().first()
        acc.suite, acc.suite_subscription_id = True, "sub_suite"
        db.commit()
        aid = acc.id
    assert client.get("/api/hr/employees").status_code == 200
    body, h = _signed(_event("invoice.payment_failed", {"id": "in_1", "object": "invoice", "subscription": "sub_suite"}))
    assert client.post("/api/stripe/webhook", content=body, headers=h).status_code == 200
    assert client.get("/api/hr/employees").status_code == 403
    sub = {"id": "sub_suite", "object": "subscription", "status": "active",
           "metadata": {"account_id": str(aid), "module": "suite"}}
    body, h = _signed(_event("customer.subscription.updated", sub))
    assert client.post("/api/stripe/webhook", content=body, headers=h).status_code == 200
    assert client.get("/api/hr/employees").status_code == 200
    assert _acc("suite@example.com").closed_at == ""


def test_webhook_updated_canceled_revokes(client):
    _register(client, "upd@example.com")
    _grant("upd@example.com", "ats", "sub_upd")
    body, h = _signed(_event("customer.subscription.updated", {"id": "sub_upd", "object": "subscription", "status": "canceled"}))
    client.post("/api/stripe/webhook", content=body, headers=h)
    assert "ats" not in client.get("/api/me").json()["owned"]


# ---------------------------------------------------------------- checkout rules

def test_checkout_requires_declarations_and_blocks_suite_rebuy(monkeypatch, client):
    _register(client, "buy@example.com")
    seen = {}

    class FakeSession:
        @staticmethod
        def create(**kw):
            seen.update(kw)
            return type("S", (), {"url": "https://checkout.example/s"})()

    class FakeStripe:
        checkout = type("C", (), {"Session": FakeSession})
    monkeypatch.setattr(main, "_stripe", lambda: FakeStripe)
    assert client.post("/api/checkout", json={"module": "crm"}).status_code == 400
    assert client.post("/api/checkout", json={"module": "crm", "business": True}).status_code == 400
    r = client.post("/api/checkout", json={"module": "crm", "business": True, "waiver": True})
    assert r.status_code == 200 and r.json()["url"]
    assert seen["tax_id_collection"] == {"enabled": True}
    assert seen["subscription_data"]["metadata"]["waiver_at"]
    with main.SessionLocal() as db:
        acc = db.execute(main.select(main.Account).where(main.Account.email == "buy@example.com")).scalars().first()
        acc.suite = True
        db.commit()
    r = client.post("/api/checkout", json={"module": "suite", "business": True, "waiver": True})
    assert r.status_code == 400 and "already" in r.json()["error"]


def test_billing_portal_needs_customer(client):
    _register(client, "portal@example.com")
    assert client.post("/api/billing/portal").status_code == 400


# ---------------------------------------------------------------- pages

def test_pages_and_legal(client):
    app_html = client.get("/app").text
    assert 'href="/privacy"' in app_html and 'href="/dpa"' in app_html
    assert "Start free" not in app_html and "fonts.googleapis" not in app_html
    assert "By continuing you agree to the" in app_html
    for p in ("/privacy", "/privacy/el", "/cookies", "/cookies/el", "/terms", "/terms/el", "/dpa", "/dpa/el",
              "/about", "/contact", "/disclaimer", "/editorial-policy"):
        r = client.get(p)
        assert r.status_code == 200, p
        assert "info@pqra.gr" not in r.text, p
    priv = client.get("/privacy").text
    assert "info@compepharma.com or info@compepharma.com" not in priv
    assert "Microsoft" not in priv and "cpDaily" in priv and "VigiEye" in priv and "e-signature" in priv
    assert "30 days" in client.get("/cookies").text
    ed = client.get("/editorial-policy").text
    assert "we do not link to trade" not in ed and "secondary" in ed


def test_news_pages_use_self_hosted_fonts_and_consent(client):
    home = client.get("/")
    assert home.status_code == 200
    assert "fonts.googleapis" not in home.text and "/fonts/fonts.css" in home.text
    nl = client.get("/newsletter").text
    assert "By continuing you agree to the" in nl
    ent = client.get("/enterprise")
    assert ent.status_code == 200 and "By continuing you agree to the" in ent.text and "excl. VAT" in ent.text


def test_fonts_served(client):
    css = client.get("/fonts/fonts.css")
    assert css.status_code == 200 and "Inter" in css.text
    import hashlib as _h
    good = b"wOF2" + b"x" * 60
    monkey = {"inter-latin-wght-normal.woff2": _h.sha256(good).hexdigest()}
    orig_sha, orig_fetch, orig_dir = dict(main.FONT_SHA256), main._fetch_font, main._FONT_DIR
    main._FONT_DIR = tempfile.mkdtemp()
    main.FONT_SHA256.update(monkey)
    main._font_cache.clear()
    calls = []
    main._fetch_font = lambda n: calls.append(n) or good
    try:
        w = client.get("/fonts/inter-latin-wght-normal.woff2")
        assert w.status_code == 200 and w.content[:4] == b"wOF2" and "immutable" in w.headers["cache-control"]
        client.get("/fonts/inter-latin-wght-normal.woff2")
        assert calls == ["inter-latin-wght-normal.woff2"]          # fetched once, then served locally
        assert client.get("/fonts/not-a-font.woff2").status_code == 404
    finally:
        main.FONT_SHA256.clear(); main.FONT_SHA256.update(orig_sha)
        main._fetch_font, main._FONT_DIR = orig_fetch, orig_dir
        main._font_cache.clear()
    assert client.get("/fonts/OFL-Inter.txt").status_code == 200
    assert client.get("/fonts/..%2Fmain.py").status_code == 404


def test_robots_tdm(client):
    t = client.get("/robots.txt").text
    for bot in ("GPTBot", "CCBot", "Google-Extended", "ClaudeBot"):
        assert f"User-agent: {bot}" in t
    assert "Googlebot" not in t     # search crawling is untouched (falls under User-agent: *)
    assert "User-agent: Mediapartners-Google\nAllow: /" in t
    assert "User-agent: *\nAllow: /" in t
    assert client.get("/.well-known/tdmrep.json").json()[0]["tdm-reservation"] == 1


def test_vigieye_header():
    import gate
    assert gate.vigieye_headers()["X-Readers-Secret"] == "readers-secret"
    os.environ.pop("READERS_API_SECRET")
    try:
        assert "X-Readers-Secret" not in gate.vigieye_headers()
    finally:
        os.environ["READERS_API_SECRET"] = "readers-secret"


def test_reader_paywall_waiver_box():
    import gate
    box = gate.auth_box("https://compepharma.com/x")
    assert 'name="withdrawal_waiver"' in box and "checked" not in box.split('name="withdrawal_waiver"')[1][:40]
    sub = gate.subscribe_box("a@example.com", gate._subscribe_url("lnk", "https://compepharma.com/"))
    assert "withdrawal_waiver=1" in sub and 'name="withdrawal_waiver"' in sub
