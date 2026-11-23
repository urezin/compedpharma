"""
CompePharma — a modular CRM + HR platform.

Everything is organised as separately-sellable MODULES (crm, hr, ats, docs). An
account can own any subset (bought individually via Stripe, or all at once with
the Suite bundle). Module data endpoints are gated on ownership, so you can sell
parts of the service to different customers.

Self-contained single file: FastAPI + SQLAlchemy + stdlib-signed session cookies
+ PBKDF2 passwords + optional Stripe Checkout (inline price_data). Runs on SQLite
with no configuration, or Postgres via DATABASE_URL.
"""
from __future__ import annotations

import hmac, hashlib, base64, json, os, secrets, time
from datetime import datetime, timezone, date

from fastapi import FastAPI, Depends, Cookie, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import (create_engine, String, Integer, Text, Boolean, Float, DateTime,
                        ForeignKey, select, func)
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column, sessionmaker, Session)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
APP_NAME = "CompePharma"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./compedpharma.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgres://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]
IS_SQLITE = DATABASE_URL.startswith("sqlite")

import logging  # noqa: E402
log = logging.getLogger("compedpharma")

# Production = on Render or on Postgres. There, sessions are signed only with SESSION_SECRET: no fallback to
# the Stripe secret or a dev string (a guessable key would let anyone forge a session for any account).
# Without it the CRM/HR app refuses to sign anyone in (503) and says so loudly in the log; the news portal
# keeps running, so a missing variable cannot take the whole site down.
IS_PRODUCTION = bool(os.getenv("RENDER")) or not IS_SQLITE or os.getenv("ENV", "").lower() == "production"
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
if not SESSION_SECRET:
    if IS_PRODUCTION:
        log.critical("SESSION_SECRET is not set: /app sign-in is DISABLED until it is set in the environment.")
    else:
        SESSION_SECRET = "dev-only-" + secrets.token_hex(16)   # random per process, never a fixed string
AUTH_ENABLED = bool(SESSION_SECRET)
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "30"))
COOKIE_NAME = "compedpharma_session"
APP_BASE_URL = os.getenv("APP_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
BILLING = bool(STRIPE_SECRET_KEY)
# Closed accounts (no paid module left) are purged with all their data this long after closing.
PURGE_AFTER_DAYS = int(os.getenv("PURGE_AFTER_DAYS", "183"))

engine = create_engine(DATABASE_URL, future=True,
                       connect_args={"check_same_thread": False} if IS_SQLITE else {},
                       pool_pre_ping=not IS_SQLITE)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Modules — the sellable units
# ---------------------------------------------------------------------------
MODULES = {
    "crm":  {"name": "CRM Core", "icon": "📇", "price_cents": 4900,
             "tagline": "Contacts, companies, a sales pipeline and activity tracking.",
             "features": ["Company & contact directory", "Drag-free deal pipeline", "Activity log & notes"]},
    "hr":   {"name": "HR Core", "icon": "👥", "price_cents": 4900,
             "tagline": "Employee directory, time-off requests and onboarding.",
             "features": ["Employee records", "Leave requests & approvals", "Onboarding checklists"]},
    "ats":  {"name": "Recruiting (ATS)", "icon": "🧑‍💼", "price_cents": 3900,
             "tagline": "Job postings and a candidate pipeline.",
             "features": ["Job postings", "Candidate tracking", "Interview stages"]},
    "docs": {"name": "Document Center", "icon": "📄", "price_cents": 2900,
             "tagline": "Shared documents and policy acknowledgements.",
             "features": ["Document library", "Policy acknowledgements", "Expiry reminders"]},
}
SUITE_PRICE_CENTS = int(os.getenv("SUITE_PRICE_CENTS", "9900"))   # all modules, monthly
MODULE_KEYS = list(MODULES.keys())


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    org: Mapped[str] = mapped_column(String(200), default="")
    password_salt: Mapped[str] = mapped_column(String(64), default="")
    password_hash: Mapped[str] = mapped_column(String(128), default="")
    suite: Mapped[bool] = mapped_column(Boolean, default=False)      # owns everything
    stripe_customer_id: Mapped[str] = mapped_column(String(80), default="")
    suite_subscription_id: Mapped[str] = mapped_column(String(80), default="")
    # Set when the last paid module ends (cancelled / unpaid); the account and its data are purged
    # PURGE_AFTER_DAYS later unless the customer buys again. Empty while the account has paid access.
    closed_at: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ModuleGrant(Base):
    __tablename__ = "module_grants"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    module: Mapped[str] = mapped_column(String(20), index=True)
    source: Mapped[str] = mapped_column(String(20), default="purchase")
    stripe_session_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    stripe_subscription_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    # Record of the checkout declarations: buying as a business, and the request for immediate access
    # with the acknowledgement that the withdrawal right then ends (Directive 2011/83/EU art. 16(m)).
    business_confirmed_at: Mapped[str] = mapped_column(String(40), default="")
    waiver_at: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---- CRM ----
class Company(Base):
    __tablename__ = "crm_companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str] = mapped_column(String(120), default="")
    website: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Contact(Base):
    __tablename__ = "crm_contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    company: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Deal(Base):
    __tablename__ = "crm_deals"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(200), default="")
    value: Mapped[float] = mapped_column(Float, default=0)
    stage: Mapped[str] = mapped_column(String(40), default="Lead")  # Lead|Qualified|Proposal|Won|Lost
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Activity(Base):
    __tablename__ = "crm_activities"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(30), default="note")  # note|call|email|meeting
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    related: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---- HR ----
class Employee(Base):
    __tablename__ = "hr_employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), default="")
    department: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(120), default="")
    start_date: Mapped[str] = mapped_column(String(20), default="")
    status: Mapped[str] = mapped_column(String(30), default="Active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LeaveRequest(Base):
    __tablename__ = "hr_leave"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    employee: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40), default="Vacation")
    start_date: Mapped[str] = mapped_column(String(20), default="")
    end_date: Mapped[str] = mapped_column(String(20), default="")
    status: Mapped[str] = mapped_column(String(20), default="Pending")  # Pending|Approved|Declined
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OnboardingTask(Base):
    __tablename__ = "hr_onboarding"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    employee: Mapped[str] = mapped_column(String(200))
    task: Mapped[str] = mapped_column(String(200))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---- ATS ----
class Job(Base):
    __tablename__ = "ats_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(120), default="")
    location: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(30), default="Open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Candidate(Base):
    __tablename__ = "ats_candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), default="")
    job: Mapped[str] = mapped_column(String(200), default="")
    stage: Mapped[str] = mapped_column(String(40), default="Applied")  # Applied|Screen|Interview|Offer|Hired|Rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---- Docs ----
class Document(Base):
    __tablename__ = "docs_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(120), default="Policy")
    body: Mapped[str] = mapped_column(Text, default="")
    expires: Mapped[str] = mapped_column(String(20), default="")
    # Approval workflow ("material approval"): a document is Draft until routed
    # for sign-off, In Review while roles sign in order, then Approved/Rejected.
    status: Mapped[str] = mapped_column(String(20), default="Draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    submitted_at: Mapped[str] = mapped_column(String(40), default="")
    approved_at: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Acknowledgement(Base):
    __tablename__ = "docs_acks"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    document_id: Mapped[int] = mapped_column(Integer, index=True)
    who: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApprovalStep(Base):
    """One sign-off in a document's approval route (DocuSign-style, sequential).

    Each step is assigned to a named person acting in a role (Regulatory,
    Pharmacovigilance, Management, …). Steps activate in order; a signature
    captures the typed name, a meaning-of-signature statement, and a timestamp.
    """
    __tablename__ = "docs_approval_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    document_id: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    role: Mapped[str] = mapped_column(String(80), default="")
    assignee_name: Mapped[str] = mapped_column(String(160), default="")
    assignee_email: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")   # pending|active|approved|rejected
    signed_name: Mapped[str] = mapped_column(String(160), default="")
    intent: Mapped[str] = mapped_column(Text, default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    signed_at: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Auth (stdlib signed cookies + PBKDF2)
# ---------------------------------------------------------------------------
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(pw: str, salt: str = "") -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000)
    return salt, dk.hex()


def verify_password(pw: str, salt: str, expected: str) -> bool:
    if not salt or not expected:
        return False
    _, h = hash_password(pw, salt)
    return hmac.compare_digest(h, expected)


def make_session(acc: Account) -> str:
    payload = {"uid": acc.id, "exp": int(time.time()) + SESSION_TTL_DAYS * 86400}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(SESSION_SECRET.encode(), raw, hashlib.sha256).digest()
    return _b64(raw) + "." + _b64(sig)


def read_session(token: str | None):
    if not AUTH_ENABLED or not token or "." not in token:
        return None
    try:
        raw_b64, sig_b64 = token.split(".", 1)
        raw = _unb64(raw_b64)
        expected = hmac.new(SESSION_SECRET.encode(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(sig_b64), expected):
            return None
        payload = json.loads(raw)
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_account(db: Session, token: str | None) -> Account | None:
    p = read_session(token)
    if not p:
        return None
    return db.get(Account, p.get("uid"))


def owned_modules(db: Session, acc: Account) -> set:
    if not acc:
        return set()
    if acc.suite:
        return set(MODULE_KEYS)
    rows = db.execute(select(ModuleGrant.module).where(ModuleGrant.account_id == acc.id)).scalars().all()
    return set(rows)


def _set_cookie(resp, acc: Account):
    resp.set_cookie(COOKIE_NAME, make_session(acc), max_age=SESSION_TTL_DAYS * 86400,
                    httponly=True, samesite="lax", secure=not IS_SQLITE, path="/")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title=APP_NAME)
from adsense import AdSenseMiddleware
# Google AdSense on the news portal only (never inside the CRM/HR app, admin or APIs); serves /ads.txt
app.add_middleware(AdSenseMiddleware, exclude=("/app", "/api", "/admin", "/login", "/account"))
_STATIC = os.path.dirname(__file__)


def _migrate():
    """Add approval-workflow columns to docs_documents on existing databases.

    create_all() only creates new tables (docs_approval_steps is picked up
    automatically), so for a persisted DB we add the new Document columns with
    idempotent ALTERs. Works on SQLite and Postgres; ignores 'already exists'.
    """
    cols = {
        "docs_documents": {
            "status": "VARCHAR(20) DEFAULT 'Draft'",
            "version": "INTEGER DEFAULT 1",
            "submitted_at": "VARCHAR(40) DEFAULT ''",
            "approved_at": "VARCHAR(40) DEFAULT ''",
        },
        "accounts": {
            "suite_subscription_id": "VARCHAR(80) DEFAULT ''",
            "closed_at": "VARCHAR(40) DEFAULT ''",
        },
        "module_grants": {
            "stripe_subscription_id": "VARCHAR(80) DEFAULT ''",
            "business_confirmed_at": "VARCHAR(40) DEFAULT ''",
            "waiver_at": "VARCHAR(40) DEFAULT ''",
        },
    }
    for table, tcols in cols.items():
        for name, ddl in tcols.items():
            try:
                with engine.begin() as conn:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            except Exception:
                pass


def _purge_loop():
    while True:
        try:
            with SessionLocal() as db:
                n = purge_closed_accounts(db)
            if n:
                log.info("purged %d closed account(s)", n)
        except Exception:
            log.exception("purge of closed accounts failed")
        time.sleep(24 * 3600)


@app.on_event("startup")
def _startup():
    Base.metadata.create_all(bind=engine)
    _migrate()
    if os.getenv("DISABLE_PURGE_THREAD") != "1":
        import threading
        threading.Thread(target=_purge_loop, name="purge-closed-accounts", daemon=True).start()


# Public news portal (the business of pharma) is the homepage; the CRM/HR app lives at /app.
import portal as _portal  # noqa: E402
app.include_router(_portal.router)
import legal as _legal  # noqa: E402
import gate as _gate_mod  # noqa: E402
app.include_router(_gate_mod.router)   # reader paywall ($4.99/month, accounts live on VigiEye)
app.include_router(_legal.make_router(
    {"name": "CompePharma", "domain": "compepharma.com",
     "what": "CompePharma is a daily news and analysis service on the business of pharma: deals and M&A, financing, "
             "approvals and launches, manufacturing and supply, pricing policy, legal disputes and quarterly earnings.",
     "audience": "business development, commercial, finance, market-access and strategy professionals in pharma and biotech",
     "sister": ("VigiEye", "https://vigi-eye.com/"), "sister_scope": "regulatory side: approvals, pharmacovigilance, quality, guidelines and the PDUFA calendar",
     "accounts": True, "payments": True},
    lambda t, d, p, b: _portal._page(f"{t} | CompePharma" if "CompePharma" not in t else t, d, p, b)))
import business as _business  # noqa: E402  (enterprise page + market-analysis service)
app.include_router(_business.router)
import report_top100 as _report_top100  # noqa: E402  (top-100 drugs 5-year outlook report)
app.include_router(_report_top100.router)


@app.get("/app", include_in_schema=False)
def app_ui():
    return FileResponse(os.path.join(_STATIC, "index.html"))


# ---------- favicon / app icons ----------
_ICONS = {
    "favicon.ico": "image/x-icon", "favicon.svg": "image/svg+xml", "favicon-32.png": "image/png",
    "apple-touch-icon.png": "image/png", "icon-192.png": "image/png", "icon-512.png": "image/png",
}


def _icon_route(name: str, mime: str):
    path = os.path.join(_STATIC, "static", name)

    def _serve():
        return FileResponse(path, media_type=mime, headers={"Cache-Control": "public, max-age=86400"})
    return _serve


for _n, _m in _ICONS.items():
    app.add_api_route(f"/{_n}", _icon_route(_n, _m), methods=["GET"], include_in_schema=False)


# ---------- self-hosted fonts (static/fonts; Fontsource, SIL OFL 1.1) ----------
# Visitors load fonts only from this server, so no visitor IP reaches Google or a CDN. The .woff2 files are served
# from static/fonts when present; otherwise the server downloads the pinned Fontsource release once, checks its
# SHA-256 and keeps it in memory (and on disk when writable). If that fails the CSS falls back to system fonts.
_FONT_DIR = os.path.join(_STATIC, "static", "fonts")
_FONT_TYPES = {".woff2": "font/woff2", ".css": "text/css; charset=utf-8", ".txt": "text/plain; charset=utf-8"}
_FONT_PKG = {"inter": "@fontsource-variable/inter@5.3.0", "source-serif-4": "@fontsource-variable/source-serif-4@5.3.1"}
FONT_SHA256 = {
    "inter-latin-wght-normal.woff2": "3100e775e8616cd2611beecfa23a4263d7037586789b43f035236a2e6fbd4c62",
    "inter-latin-ext-wght-normal.woff2": "34b9c504cab7a73e37b746343a449132e56cf7b5481af2cb81dc74dcff25c956",
    "source-serif-4-latin-wght-normal.woff2": "382475f38242c52d42a3e5ff8dc69b5d73f10d0d21e4550b5fe232984688779a",
    "source-serif-4-latin-ext-wght-normal.woff2": "d10ccbbd0dc4ebae2938958dc1f622a53460fe297e9c958564742dd684309c3f",
}
_font_cache: dict[str, bytes] = {}


def _fetch_font(name: str) -> bytes | None:
    """Download a pinned Fontsource file (server side only) and accept it only if the SHA-256 matches."""
    pkg = _FONT_PKG["source-serif-4" if name.startswith("source-serif-4") else "inter"]
    import httpx
    for host in ("https://cdn.jsdelivr.net/npm/", "https://unpkg.com/"):
        try:
            r = httpx.get(f"{host}{pkg}/files/{name}", timeout=15, follow_redirects=True)
            if r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == FONT_SHA256[name]:
                return r.content
        except Exception:
            pass
    log.warning("could not fetch font %s; pages fall back to system fonts", name)
    return None


@app.get("/fonts/{name}", include_in_schema=False)
def font_file(name: str):
    from fastapi.responses import Response
    ext = os.path.splitext(name)[1]
    path = os.path.join(_FONT_DIR, name)
    if "/" in name or "\\" in name or name.startswith(".") or ext not in _FONT_TYPES:
        return JSONResponse({"error": "Not found."}, status_code=404)
    cache = "public, max-age=31536000, immutable" if ext == ".woff2" else "public, max-age=86400"
    if os.path.isfile(path):
        return FileResponse(path, media_type=_FONT_TYPES[ext], headers={"Cache-Control": cache})
    if name not in FONT_SHA256:
        return JSONResponse({"error": "Not found."}, status_code=404)
    if name not in _font_cache:
        data = _fetch_font(name)
        if data is None:
            return JSONResponse({"error": "Font unavailable."}, status_code=404)
        _font_cache[name] = data
        try:
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            pass
    return Response(_font_cache[name], media_type="font/woff2", headers={"Cache-Control": cache})


@app.get("/site.webmanifest", include_in_schema=False)
def webmanifest():
    from fastapi.responses import JSONResponse
    return JSONResponse({"name": "CompePharma", "short_name": "CompePharma", "theme_color": "#000000",
                         "background_color": "#000000", "display": "standalone", "start_url": "/",
                         "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                                   {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}]},
                        media_type="application/manifest+json")


@app.get("/health")
def health():
    return {"ok": True, "app": APP_NAME, "billing": BILLING}


# ---------- auth endpoints ----------
class RegisterIn(BaseModel):
    email: str
    password: str
    name: str = ""
    org: str = ""


class LoginIn(BaseModel):
    email: str
    password: str


# ---------- sign-in rate limiting (in memory, per process) ----------
LOGIN_MAX_FAILS = int(os.getenv("LOGIN_MAX_FAILS", "8"))        # failed logins per IP+email per window
REGISTER_MAX = int(os.getenv("REGISTER_MAX", "10"))             # sign-ups per IP per window
RATE_WINDOW = int(os.getenv("RATE_WINDOW_SECONDS", "900"))
_hits: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")   # Render's proxy puts the client first
    return (fwd.split(",")[0].strip() if fwd else "") or (request.client.host if request.client else "?")


def _too_many(key: str, limit: int) -> bool:
    now = time.time()
    recent = [t for t in _hits.get(key, []) if now - t < RATE_WINDOW]
    _hits[key] = recent
    if len(_hits) > 20000:
        _hits.clear()
    return len(recent) >= limit


def _hit(key: str):
    _hits.setdefault(key, []).append(time.time())


def _auth_off():
    return JSONResponse({"error": "Sign-in is temporarily unavailable. Please try again later."}, status_code=503)


def _slow_down():
    return JSONResponse({"error": "Too many attempts. Please wait 15 minutes and try again."}, status_code=429)


@app.post("/api/register")
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    if not AUTH_ENABLED:
        return _auth_off()
    rk = "reg:" + _client_ip(request)
    if _too_many(rk, REGISTER_MAX):
        return _slow_down()
    _hit(rk)
    email = (body.email or "").strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        return JSONResponse({"error": "Enter a valid email address."}, status_code=400)
    if len(body.password or "") < 8:
        return JSONResponse({"error": "Password must be at least 8 characters."}, status_code=400)
    if db.execute(select(Account).where(func.lower(Account.email) == email)).scalars().first():
        return JSONResponse({"error": "An account with this email already exists — sign in instead."}, status_code=409)
    salt, h = hash_password(body.password)
    acc = Account(email=email, name=(body.name or "").strip(), org=(body.org or "").strip(),
                  password_salt=salt, password_hash=h)
    db.add(acc)
    db.commit()
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, acc)
    return resp


@app.post("/api/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    if not AUTH_ENABLED:
        return _auth_off()
    email = (body.email or "").strip().lower()
    ip = _client_ip(request)
    keys = (f"login:{ip}:{email}", f"login-ip:{ip}")
    if _too_many(keys[0], LOGIN_MAX_FAILS) or _too_many(keys[1], LOGIN_MAX_FAILS * 5):
        return _slow_down()
    acc = db.execute(select(Account).where(func.lower(Account.email) == email)).scalars().first()
    if not acc or not verify_password(body.password or "", acc.password_salt, acc.password_hash):
        for k in keys:
            _hit(k)
        return JSONResponse({"error": "Incorrect email or password."}, status_code=401)
    _hits.pop(keys[0], None)
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, acc)
    return resp


@app.get("/api/logout")
def logout():
    resp = RedirectResponse("/app", status_code=302)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@app.get("/api/me")
def me(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc = current_account(db, session)
    if not acc:
        return {"authenticated": False, "modules": _module_catalog(set())}
    owned = owned_modules(db, acc)
    return {"authenticated": True, "email": acc.email, "name": acc.name, "org": acc.org,
            "suite": acc.suite, "owned": sorted(owned), "billing": BILLING,
            "can_manage_billing": BILLING and bool(acc.stripe_customer_id),
            "modules": _module_catalog(owned), "suite_price": SUITE_PRICE_CENTS / 100.0}


def _module_catalog(owned: set) -> list:
    return [{"key": k, "name": m["name"], "icon": m["icon"], "tagline": m["tagline"],
             "features": m["features"], "price": m["price_cents"] / 100.0, "owned": k in owned}
            for k, m in MODULES.items()]


# ---------- billing ----------
def _stripe():
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
    return stripe


class BuyIn(BaseModel):
    module: str   # a module key, or "suite"
    business: bool = False   # "I am buying for my business, not as a consumer"
    waiver: bool = False     # "Start access now; I understand the withdrawal right then ends"


@app.post("/api/checkout")
def checkout(body: BuyIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME),
             db: Session = Depends(get_db)):
    acc = current_account(db, session)
    if not acc:
        return JSONResponse({"error": "Please sign in."}, status_code=401)
    if not BILLING:
        return JSONResponse({"error": "Payments aren’t switched on yet."}, status_code=400)
    # The app is sold to business customers only (Terms P6). Both declarations are explicit, unticked
    # boxes in the checkout dialog; they are recorded on the grant when the payment is confirmed.
    if not body.business:
        return JSONResponse({"error": "The CompePharma app is sold to business customers only. "
                                      "Please confirm you are buying for your business."}, status_code=400)
    if not body.waiver:
        return JSONResponse({"error": "Please confirm that access should start now."}, status_code=400)
    key = body.module
    base = APP_BASE_URL.rstrip("/")
    if key == "suite":
        if acc.suite:
            return JSONResponse({"error": "You already have the Suite."}, status_code=400)
        name, amount, interval = f"{APP_NAME} Suite (all modules)", SUITE_PRICE_CENTS, "month"
        mode = "subscription"
    elif key in MODULES:
        if key in owned_modules(db, acc):
            return JSONResponse({"error": "You already own this module."}, status_code=400)
        name, amount, interval = f"{APP_NAME} · {MODULES[key]['name']}", MODULES[key]["price_cents"], "month"
        mode = "subscription"
    else:
        return JSONResponse({"error": "Unknown module."}, status_code=404)
    now = utcnow().isoformat()
    meta = {"account_id": str(acc.id), "module": key, "business_confirmed_at": now, "waiver_at": now}
    try:
        stripe = _stripe()
        line = {"price_data": {"currency": "usd", "unit_amount": amount, "tax_behavior": "exclusive",
                               "recurring": {"interval": interval}, "product_data": {"name": name}}, "quantity": 1}
        kw = dict(mode=mode, line_items=[line],
                  success_url=f"{base}/app?purchased=1&session_id={{CHECKOUT_SESSION_ID}}",
                  cancel_url=f"{base}/app",
                  metadata=meta, subscription_data={"metadata": meta},
                  billing_address_collection="required", tax_id_collection={"enabled": True})
        if os.getenv("STRIPE_AUTOMATIC_TAX") == "1":       # needs Stripe Tax set up in the dashboard
            kw["automatic_tax"] = {"enabled": True}
        if acc.stripe_customer_id:
            kw["customer"] = acc.stripe_customer_id
            kw["customer_update"] = {"address": "auto", "name": "auto"}
        else:
            kw["customer_email"] = acc.email
        s = stripe.checkout.Session.create(**kw)
        return {"url": s.url}
    except Exception as e:
        return JSONResponse({"error": f"Checkout error: {e}"}, status_code=400)


class FulfillIn(BaseModel):
    session_id: str


def _sid(x) -> str:
    """Stripe ids arrive as a string or an expanded object."""
    if not x:
        return ""
    return x if isinstance(x, str) else (x.get("id") or "")


@app.post("/api/fulfill")
def fulfill(body: FulfillIn, db: Session = Depends(get_db)):
    if not BILLING:
        return JSONResponse({"error": "Billing not configured."}, status_code=400)
    try:
        stripe = _stripe()
        sess = stripe.checkout.Session.retrieve(body.session_id)
    except Exception as e:
        return JSONResponse({"error": f"Could not verify: {e}"}, status_code=400)
    if not (sess.get("payment_status") == "paid" or sess.get("status") == "complete"):
        return JSONResponse({"error": "Payment not completed."}, status_code=400)
    meta = sess.get("metadata", {}) or {}
    aid = int(meta.get("account_id") or 0)
    key = meta.get("module")
    acc = db.get(Account, aid)
    if not acc:
        return JSONResponse({"error": "Missing account."}, status_code=400)
    if sess.get("customer"):
        acc.stripe_customer_id = _sid(sess["customer"])
    sub_id = _sid(sess.get("subscription"))
    if key == "suite":
        acc.suite = True
        acc.suite_subscription_id = sub_id
        acc.closed_at = ""
        db.commit()
        return {"ok": True, "module": "suite"}
    if key in MODULES:
        exists = db.execute(select(ModuleGrant).where(ModuleGrant.stripe_session_id == body.session_id)).scalars().first()
        if not exists:
            db.add(ModuleGrant(account_id=aid, module=key, source="purchase", stripe_session_id=body.session_id,
                               stripe_subscription_id=sub_id,
                               business_confirmed_at=meta.get("business_confirmed_at", ""),
                               waiver_at=meta.get("waiver_at", "")))
        acc.closed_at = ""
        db.commit()
        return {"ok": True, "module": key}
    return {"ok": False, "error": "Unknown module."}


@app.post("/api/billing/portal")
def billing_portal(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    """Stripe Customer Portal: update the card, see invoices, cancel any subscription in two clicks."""
    acc = current_account(db, session)
    if not acc:
        return JSONResponse({"error": "Please sign in."}, status_code=401)
    if not BILLING or not acc.stripe_customer_id:
        return JSONResponse({"error": "There is no billing account yet: nothing has been bought."}, status_code=400)
    try:
        p = _stripe().billing_portal.Session.create(customer=acc.stripe_customer_id,
                                                    return_url=APP_BASE_URL.rstrip("/") + "/app")
        return {"url": p.url}
    except Exception as e:
        return JSONResponse({"error": f"Billing portal error: {e}"}, status_code=400)


# ---------- Stripe webhook: access follows the subscription ----------
ENDED = {"canceled", "unpaid", "incomplete_expired", "past_due", "paused"}


def _close_if_empty(db: Session, acc: Account):
    if not acc.suite and not owned_modules(db, acc) and not acc.closed_at:
        acc.closed_at = utcnow().isoformat()


def revoke_subscription(db: Session, sub_id: str) -> int:
    """Remove every grant (and the Suite flag) paid for by this subscription. Returns how many were removed."""
    if not sub_id:
        return 0
    n = 0
    touched = set()
    for g in db.execute(select(ModuleGrant).where(ModuleGrant.stripe_subscription_id == sub_id)).scalars().all():
        touched.add(g.account_id)
        db.delete(g)
        n += 1
    for acc in db.execute(select(Account).where(Account.suite_subscription_id == sub_id)).scalars().all():
        acc.suite = False
        touched.add(acc.id)
        n += 1
    db.flush()
    for aid in touched:
        acc = db.get(Account, aid)
        if acc:
            _close_if_empty(db, acc)
    db.commit()
    return n


def restore_subscription(db: Session, sub: dict) -> bool:
    """Back to active (e.g. a retried payment succeeded): give access again from the subscription metadata."""
    sub_id = _sid(sub.get("id"))
    meta = sub.get("metadata") or {}
    acc = db.get(Account, int(meta.get("account_id") or 0))
    key = meta.get("module")
    if not acc or not sub_id:
        return False
    if key == "suite":
        acc.suite, acc.suite_subscription_id = True, sub_id
    elif key in MODULES:
        has = db.execute(select(ModuleGrant).where(ModuleGrant.stripe_subscription_id == sub_id)).scalars().first()
        if not has:
            db.add(ModuleGrant(account_id=acc.id, module=key, source="purchase", stripe_subscription_id=sub_id,
                               business_confirmed_at=meta.get("business_confirmed_at", ""),
                               waiver_at=meta.get("waiver_at", "")))
    else:
        return False
    acc.closed_at = ""
    db.commit()
    return True


@app.post("/api/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    # Fail closed: without the signing secret no event is trusted.
    if not STRIPE_WEBHOOK_SECRET:
        log.error("Stripe webhook called but STRIPE_WEBHOOK_SECRET is not set: event rejected.")
        return JSONResponse({"error": "Webhook not configured."}, status_code=503)
    payload = await request.body()
    try:
        import stripe
        event = stripe.Webhook.construct_event(payload, request.headers.get("stripe-signature", ""), STRIPE_WEBHOOK_SECRET)
    except Exception:
        return JSONResponse({"error": "Invalid signature."}, status_code=400)
    etype = event["type"]
    obj = event["data"]["object"]
    if etype == "customer.subscription.deleted":
        revoke_subscription(db, _sid(obj.get("id")))
    elif etype == "customer.subscription.updated":
        if obj.get("status") in ENDED:
            revoke_subscription(db, _sid(obj.get("id")))
        elif obj.get("status") in ("active", "trialing"):
            restore_subscription(db, obj)
    elif etype == "invoice.payment_failed":
        revoke_subscription(db, _sid(obj.get("subscription")))
    return {"ok": True}


# Demo grant — lets an owner switch a module on without paying (for evaluation).
# Guarded by ADMIN_TOKEN; if unset, allows the signed-in user to self-grant so the
# product is explorable before Stripe is configured.
class GrantIn(BaseModel):
    module: str
    token: str = ""


@app.post("/api/grant")
def grant(body: GrantIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME),
          db: Session = Depends(get_db)):
    acc = current_account(db, session)
    if not acc:
        return JSONResponse({"error": "Please sign in."}, status_code=401)
    admin = os.getenv("ADMIN_TOKEN", "")
    # Public self-serve grants are OFF: no free module access without payment.
    # Only an admin token (owner provisioning) can grant without Stripe checkout.
    allow_self = os.getenv("ALLOW_SELF_GRANT", "0") == "1"
    if admin and body.token != admin and not allow_self:
        return JSONResponse({"error": "Not authorized."}, status_code=403)
    if not (allow_self or (admin and body.token == admin)):
        return JSONResponse({"error": "Not authorized."}, status_code=403)
    if body.module == "suite":
        acc.suite = True
    elif body.module in MODULES:
        if body.module not in owned_modules(db, acc):
            db.add(ModuleGrant(account_id=acc.id, module=body.module, source="grant"))
    else:
        return JSONResponse({"error": "Unknown module."}, status_code=404)
    db.commit()
    return {"ok": True, "owned": sorted(owned_modules(db, acc))}


# ---------------------------------------------------------------------------
# Module gate + generic CRUD helpers
# ---------------------------------------------------------------------------
def _require(db, session, module):
    acc = current_account(db, session)
    if not acc:
        return None, JSONResponse({"error": "Please sign in."}, status_code=401)
    if module not in owned_modules(db, acc):
        return None, JSONResponse({"error": f"The {MODULES[module]['name']} module isn't active on your account.",
                                   "locked": module}, status_code=403)
    return acc, None


def _dump(obj, fields):
    d = {"id": obj.id}
    for f in fields:
        v = getattr(obj, f)
        if isinstance(v, datetime):
            v = v.isoformat()
        d[f] = v
    return d


# ---------------------------------------------------------------------------
# CRM endpoints
# ---------------------------------------------------------------------------
CRM_CONTACT_F = ["name", "email", "phone", "company", "title", "created_at"]
CRM_COMPANY_F = ["name", "industry", "website", "created_at"]
CRM_DEAL_F = ["title", "company", "value", "stage", "created_at"]
CRM_ACT_F = ["kind", "subject", "body", "related", "created_at"]
DEAL_STAGES = ["Lead", "Qualified", "Proposal", "Won", "Lost"]


@app.get("/api/crm/summary")
def crm_summary(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "crm")
    if err:
        return err
    q = lambda M: db.execute(select(func.count(M.id)).where(M.account_id == acc.id)).scalar()
    pipeline = {}
    for st in DEAL_STAGES:
        pipeline[st] = db.execute(select(func.coalesce(func.sum(Deal.value), 0)).where(
            Deal.account_id == acc.id, Deal.stage == st)).scalar() or 0
    return {"contacts": q(Contact), "companies": q(Company), "deals": q(Deal),
            "activities": q(Activity), "pipeline": pipeline, "stages": DEAL_STAGES}


class ContactIn(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    company: str = ""
    title: str = ""


@app.get("/api/crm/contacts")
def crm_contacts(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "crm")
    if err:
        return err
    rows = db.execute(select(Contact).where(Contact.account_id == acc.id).order_by(Contact.id.desc())).scalars().all()
    return {"items": [_dump(r, CRM_CONTACT_F) for r in rows]}


@app.post("/api/crm/contacts")
def crm_add_contact(body: ContactIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "crm")
    if err:
        return err
    c = Contact(account_id=acc.id, **body.model_dump())
    db.add(c); db.commit()
    return _dump(c, CRM_CONTACT_F)


class CompanyIn(BaseModel):
    name: str
    industry: str = ""
    website: str = ""


@app.get("/api/crm/companies")
def crm_companies(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "crm")
    if err:
        return err
    rows = db.execute(select(Company).where(Company.account_id == acc.id).order_by(Company.id.desc())).scalars().all()
    return {"items": [_dump(r, CRM_COMPANY_F) for r in rows]}


@app.post("/api/crm/companies")
def crm_add_company(body: CompanyIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "crm")
    if err:
        return err
    c = Company(account_id=acc.id, **body.model_dump())
    db.add(c); db.commit()
    return _dump(c, CRM_COMPANY_F)


class DealIn(BaseModel):
    title: str
    company: str = ""
    value: float = 0
    stage: str = "Lead"


@app.get("/api/crm/deals")
def crm_deals(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "crm")
    if err:
        return err
    rows = db.execute(select(Deal).where(Deal.account_id == acc.id).order_by(Deal.id.desc())).scalars().all()
    return {"items": [_dump(r, CRM_DEAL_F) for r in rows]}


@app.post("/api/crm/deals")
def crm_add_deal(body: DealIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "crm")
    if err:
        return err
    stage = body.stage if body.stage in DEAL_STAGES else "Lead"
    d = Deal(account_id=acc.id, title=body.title, company=body.company, value=body.value, stage=stage)
    db.add(d); db.commit()
    return _dump(d, CRM_DEAL_F)


class DealStageIn(BaseModel):
    stage: str


@app.post("/api/crm/deals/{deal_id}/stage")
def crm_deal_stage(deal_id: int, body: DealStageIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "crm")
    if err:
        return err
    d = db.get(Deal, deal_id)
    if not d or d.account_id != acc.id:
        return JSONResponse({"error": "Not found."}, status_code=404)
    if body.stage in DEAL_STAGES:
        d.stage = body.stage; db.commit()
    return _dump(d, CRM_DEAL_F)


class ActivityIn(BaseModel):
    kind: str = "note"
    subject: str
    body: str = ""
    related: str = ""


@app.get("/api/crm/activities")
def crm_activities(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "crm")
    if err:
        return err
    rows = db.execute(select(Activity).where(Activity.account_id == acc.id).order_by(Activity.id.desc())).scalars().all()
    return {"items": [_dump(r, CRM_ACT_F) for r in rows]}


@app.post("/api/crm/activities")
def crm_add_activity(body: ActivityIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "crm")
    if err:
        return err
    a = Activity(account_id=acc.id, **body.model_dump())
    db.add(a); db.commit()
    return _dump(a, CRM_ACT_F)


# ---------------------------------------------------------------------------
# HR endpoints
# ---------------------------------------------------------------------------
HR_EMP_F = ["name", "email", "department", "role", "start_date", "status", "created_at"]
HR_LEAVE_F = ["employee", "kind", "start_date", "end_date", "status", "note", "created_at"]
HR_ONB_F = ["employee", "task", "done", "created_at"]


@app.get("/api/hr/summary")
def hr_summary(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "hr")
    if err:
        return err
    emp = db.execute(select(func.count(Employee.id)).where(Employee.account_id == acc.id)).scalar()
    pending = db.execute(select(func.count(LeaveRequest.id)).where(
        LeaveRequest.account_id == acc.id, LeaveRequest.status == "Pending")).scalar()
    onb_open = db.execute(select(func.count(OnboardingTask.id)).where(
        OnboardingTask.account_id == acc.id, OnboardingTask.done == False)).scalar()  # noqa: E712
    return {"employees": emp, "leave_pending": pending, "onboarding_open": onb_open}


class EmployeeIn(BaseModel):
    name: str
    email: str = ""
    department: str = ""
    role: str = ""
    start_date: str = ""


@app.get("/api/hr/employees")
def hr_employees(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "hr")
    if err:
        return err
    rows = db.execute(select(Employee).where(Employee.account_id == acc.id).order_by(Employee.id.desc())).scalars().all()
    return {"items": [_dump(r, HR_EMP_F) for r in rows]}


@app.post("/api/hr/employees")
def hr_add_employee(body: EmployeeIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "hr")
    if err:
        return err
    e = Employee(account_id=acc.id, **body.model_dump())
    db.add(e); db.commit()
    return _dump(e, HR_EMP_F)


class LeaveIn(BaseModel):
    employee: str
    kind: str = "Vacation"
    start_date: str = ""
    end_date: str = ""
    note: str = ""


@app.get("/api/hr/leave")
def hr_leave(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "hr")
    if err:
        return err
    rows = db.execute(select(LeaveRequest).where(LeaveRequest.account_id == acc.id).order_by(LeaveRequest.id.desc())).scalars().all()
    return {"items": [_dump(r, HR_LEAVE_F) for r in rows]}


@app.post("/api/hr/leave")
def hr_add_leave(body: LeaveIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "hr")
    if err:
        return err
    lr = LeaveRequest(account_id=acc.id, **body.model_dump())
    db.add(lr); db.commit()
    return _dump(lr, HR_LEAVE_F)


class LeaveStatusIn(BaseModel):
    status: str


@app.post("/api/hr/leave/{lid}/status")
def hr_leave_status(lid: int, body: LeaveStatusIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "hr")
    if err:
        return err
    lr = db.get(LeaveRequest, lid)
    if not lr or lr.account_id != acc.id:
        return JSONResponse({"error": "Not found."}, status_code=404)
    if body.status in ("Pending", "Approved", "Declined"):
        lr.status = body.status; db.commit()
    return _dump(lr, HR_LEAVE_F)


class OnboardIn(BaseModel):
    employee: str
    task: str


@app.get("/api/hr/onboarding")
def hr_onboarding(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "hr")
    if err:
        return err
    rows = db.execute(select(OnboardingTask).where(OnboardingTask.account_id == acc.id).order_by(OnboardingTask.id.desc())).scalars().all()
    return {"items": [_dump(r, HR_ONB_F) for r in rows]}


@app.post("/api/hr/onboarding")
def hr_add_onboarding(body: OnboardIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "hr")
    if err:
        return err
    t = OnboardingTask(account_id=acc.id, employee=body.employee, task=body.task)
    db.add(t); db.commit()
    return _dump(t, HR_ONB_F)


@app.post("/api/hr/onboarding/{tid}/toggle")
def hr_toggle_onboarding(tid: int, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "hr")
    if err:
        return err
    t = db.get(OnboardingTask, tid)
    if not t or t.account_id != acc.id:
        return JSONResponse({"error": "Not found."}, status_code=404)
    t.done = not t.done; db.commit()
    return _dump(t, HR_ONB_F)


# ---------------------------------------------------------------------------
# ATS endpoints
# ---------------------------------------------------------------------------
ATS_JOB_F = ["title", "department", "location", "status", "created_at"]
ATS_CAND_F = ["name", "email", "job", "stage", "created_at"]
CAND_STAGES = ["Applied", "Screen", "Interview", "Offer", "Hired", "Rejected"]


@app.get("/api/ats/summary")
def ats_summary(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "ats")
    if err:
        return err
    jobs = db.execute(select(func.count(Job.id)).where(Job.account_id == acc.id, Job.status == "Open")).scalar()
    cand = db.execute(select(func.count(Candidate.id)).where(Candidate.account_id == acc.id)).scalar()
    by_stage = {}
    for st in CAND_STAGES:
        by_stage[st] = db.execute(select(func.count(Candidate.id)).where(
            Candidate.account_id == acc.id, Candidate.stage == st)).scalar()
    return {"open_jobs": jobs, "candidates": cand, "by_stage": by_stage, "stages": CAND_STAGES}


class JobIn(BaseModel):
    title: str
    department: str = ""
    location: str = ""


@app.get("/api/ats/jobs")
def ats_jobs(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "ats")
    if err:
        return err
    rows = db.execute(select(Job).where(Job.account_id == acc.id).order_by(Job.id.desc())).scalars().all()
    return {"items": [_dump(r, ATS_JOB_F) for r in rows]}


@app.post("/api/ats/jobs")
def ats_add_job(body: JobIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "ats")
    if err:
        return err
    j = Job(account_id=acc.id, **body.model_dump())
    db.add(j); db.commit()
    return _dump(j, ATS_JOB_F)


class CandidateIn(BaseModel):
    name: str
    email: str = ""
    job: str = ""
    stage: str = "Applied"


@app.get("/api/ats/candidates")
def ats_candidates(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "ats")
    if err:
        return err
    rows = db.execute(select(Candidate).where(Candidate.account_id == acc.id).order_by(Candidate.id.desc())).scalars().all()
    return {"items": [_dump(r, ATS_CAND_F) for r in rows]}


@app.post("/api/ats/candidates")
def ats_add_candidate(body: CandidateIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "ats")
    if err:
        return err
    stage = body.stage if body.stage in CAND_STAGES else "Applied"
    c = Candidate(account_id=acc.id, name=body.name, email=body.email, job=body.job, stage=stage)
    db.add(c); db.commit()
    return _dump(c, ATS_CAND_F)


class CandStageIn(BaseModel):
    stage: str


@app.post("/api/ats/candidates/{cid}/stage")
def ats_cand_stage(cid: int, body: CandStageIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "ats")
    if err:
        return err
    c = db.get(Candidate, cid)
    if not c or c.account_id != acc.id:
        return JSONResponse({"error": "Not found."}, status_code=404)
    if body.stage in CAND_STAGES:
        c.stage = body.stage; db.commit()
    return _dump(c, ATS_CAND_F)


# ---------------------------------------------------------------------------
# Docs endpoints
# ---------------------------------------------------------------------------
DOC_F = ["title", "category", "body", "expires", "status", "version",
         "submitted_at", "approved_at", "created_at"]
STEP_F = ["seq", "role", "assignee_name", "assignee_email", "status",
          "signed_name", "intent", "comment", "signed_at"]

# Preset approval roles for pharmacovigilance / regulatory material sign-off,
# each with a default meaning-of-signature statement (editable at signing time).
ROLE_PRESETS = [
    {"role": "Regulatory Affairs",
     "intent": "Reviewed and approved for regulatory compliance."},
    {"role": "Pharmacovigilance (QPPV)",
     "intent": "Approved from a pharmacovigilance and drug-safety standpoint."},
    {"role": "Quality Assurance",
     "intent": "Reviewed and approved for quality and document control."},
    {"role": "Medical Affairs",
     "intent": "Reviewed and approved for medical accuracy."},
    {"role": "Management",
     "intent": "Approved for release and authorised for use."},
]


def _steps_for(db, doc_id):
    return db.execute(select(ApprovalStep).where(ApprovalStep.document_id == doc_id)
                      .order_by(ApprovalStep.seq)).scalars().all()


def _route_summary(steps):
    total = len(steps)
    approved = sum(1 for s in steps if s.status == "approved")
    current = next((s for s in steps if s.status == "active"), None)
    return {"steps": total, "approved": approved,
            "current_role": current.role if current else "",
            "current_seq": current.seq if current else 0}


@app.get("/api/docs/roles")
def docs_roles(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "docs")
    if err:
        return err
    return {"roles": ROLE_PRESETS}


@app.get("/api/docs/summary")
def docs_summary(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "docs")
    if err:
        return err
    docs = db.execute(select(func.count(Document.id)).where(Document.account_id == acc.id)).scalar()
    in_review = db.execute(select(func.count(Document.id)).where(
        Document.account_id == acc.id, Document.status == "In Review")).scalar()
    approved = db.execute(select(func.count(Document.id)).where(
        Document.account_id == acc.id, Document.status == "Approved")).scalar()
    today = date.today().isoformat()
    expiring = db.execute(select(func.count(Document.id)).where(
        Document.account_id == acc.id, Document.expires != "", Document.expires <= today)).scalar()
    return {"documents": docs, "in_review": in_review, "approved": approved, "expired": expiring}


class DocIn(BaseModel):
    title: str
    category: str = "Policy"
    body: str = ""
    expires: str = ""


@app.get("/api/docs/documents")
def docs_list(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "docs")
    if err:
        return err
    rows = db.execute(select(Document).where(Document.account_id == acc.id).order_by(Document.id.desc())).scalars().all()
    out = []
    for r in rows:
        d = _dump(r, DOC_F)
        d["acks"] = db.execute(select(func.count(Acknowledgement.id)).where(
            Acknowledgement.document_id == r.id)).scalar()
        d["route"] = _route_summary(_steps_for(db, r.id))
        out.append(d)
    return {"items": out}


@app.get("/api/docs/documents/{doc_id}")
def docs_detail(doc_id: int, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "docs")
    if err:
        return err
    doc = db.get(Document, doc_id)
    if not doc or doc.account_id != acc.id:
        return JSONResponse({"error": "Not found."}, status_code=404)
    d = _dump(doc, DOC_F)
    steps = _steps_for(db, doc_id)
    d["steps"] = [_dump(s, STEP_F) for s in steps]
    d["route"] = _route_summary(steps)
    d["acks"] = db.execute(select(func.count(Acknowledgement.id)).where(
        Acknowledgement.document_id == doc_id)).scalar()
    return d


@app.post("/api/docs/documents")
def docs_add(body: DocIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "docs")
    if err:
        return err
    d = Document(account_id=acc.id, **body.model_dump())
    db.add(d); db.commit()
    out = _dump(d, DOC_F); out["acks"] = 0
    out["route"] = _route_summary([])
    return out


class StepIn(BaseModel):
    role: str
    name: str = ""
    email: str = ""


class RouteIn(BaseModel):
    steps: list[StepIn]


@app.post("/api/docs/documents/{doc_id}/route")
def docs_route(doc_id: int, body: RouteIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    """Send a material for approval: define the ordered sign-off route and
    move it into review. The first role's step is activated immediately."""
    acc, err = _require(db, session, "docs")
    if err:
        return err
    doc = db.get(Document, doc_id)
    if not doc or doc.account_id != acc.id:
        return JSONResponse({"error": "Not found."}, status_code=404)
    if doc.status == "In Review":
        return JSONResponse({"error": "This material is already in review."}, status_code=400)
    steps = [s for s in body.steps if (s.role or "").strip()]
    if not steps:
        return JSONResponse({"error": "Add at least one approval step."}, status_code=400)
    # clear any prior route (e.g. re-sending after a rejection) and rebuild
    for old in _steps_for(db, doc_id):
        db.delete(old)
    for i, s in enumerate(steps, start=1):
        db.add(ApprovalStep(account_id=acc.id, document_id=doc_id, seq=i,
                            role=s.role.strip(), assignee_name=(s.name or "").strip(),
                            assignee_email=(s.email or "").strip(),
                            status="active" if i == 1 else "pending"))
    doc.status = "In Review"
    doc.submitted_at = utcnow().isoformat()
    doc.approved_at = ""
    db.commit()
    return docs_detail(doc_id, session, db)


class SignIn(BaseModel):
    signed_name: str
    intent: str = ""
    comment: str = ""


@app.post("/api/docs/steps/{step_id}/sign")
def docs_sign(step_id: int, body: SignIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    """Apply an e-signature to the active step. Advances to the next role, or
    marks the whole material Approved when the last role has signed."""
    acc, err = _require(db, session, "docs")
    if err:
        return err
    step = db.get(ApprovalStep, step_id)
    if not step or step.account_id != acc.id:
        return JSONResponse({"error": "Not found."}, status_code=404)
    if step.status != "active":
        return JSONResponse({"error": "This step is not awaiting signature."}, status_code=400)
    if not (body.signed_name or "").strip():
        return JSONResponse({"error": "Type your full name to sign."}, status_code=400)
    step.status = "approved"
    step.signed_name = body.signed_name.strip()
    step.intent = (body.intent or "").strip()
    step.comment = (body.comment or "").strip()
    step.signed_at = utcnow().isoformat()
    db.flush()
    steps = _steps_for(db, step.document_id)
    nxt = next((s for s in steps if s.status == "pending"), None)
    doc = db.get(Document, step.document_id)
    if nxt:
        nxt.status = "active"
    else:
        doc.status = "Approved"
        doc.approved_at = utcnow().isoformat()
    db.commit()
    return docs_detail(step.document_id, session, db)


@app.post("/api/docs/steps/{step_id}/reject")
def docs_reject(step_id: int, body: SignIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    """Reject the active step. The material returns to Rejected; the author can
    revise and re-route it for approval."""
    acc, err = _require(db, session, "docs")
    if err:
        return err
    step = db.get(ApprovalStep, step_id)
    if not step or step.account_id != acc.id:
        return JSONResponse({"error": "Not found."}, status_code=404)
    if step.status != "active":
        return JSONResponse({"error": "This step is not awaiting signature."}, status_code=400)
    step.status = "rejected"
    step.signed_name = (body.signed_name or "").strip()
    step.comment = (body.comment or "").strip()
    step.signed_at = utcnow().isoformat()
    doc = db.get(Document, step.document_id)
    doc.status = "Rejected"
    db.commit()
    return docs_detail(step.document_id, session, db)


@app.post("/api/docs/documents/{doc_id}/reset")
def docs_reset(doc_id: int, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    """Withdraw / revise: clear the route and return the material to Draft."""
    acc, err = _require(db, session, "docs")
    if err:
        return err
    doc = db.get(Document, doc_id)
    if not doc or doc.account_id != acc.id:
        return JSONResponse({"error": "Not found."}, status_code=404)
    for old in _steps_for(db, doc_id):
        db.delete(old)
    doc.status = "Draft"
    doc.submitted_at = ""
    doc.approved_at = ""
    db.commit()
    return docs_detail(doc_id, session, db)


class AckIn(BaseModel):
    document_id: int
    who: str


@app.post("/api/docs/ack")
def docs_ack(body: AckIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "docs")
    if err:
        return err
    doc = db.get(Document, body.document_id)
    if not doc or doc.account_id != acc.id:
        return JSONResponse({"error": "Not found."}, status_code=404)
    db.add(Acknowledgement(account_id=acc.id, document_id=body.document_id, who=body.who))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Deleting records, exporting data, closing the account
# ---------------------------------------------------------------------------
# (module, kind) -> model. Every record type a customer can create can also be deleted.
DELETABLE = {
    ("crm", "contacts"): Contact, ("crm", "companies"): Company, ("crm", "deals"): Deal,
    ("crm", "activities"): Activity,
    ("hr", "employees"): Employee, ("hr", "leave"): LeaveRequest, ("hr", "onboarding"): OnboardingTask,
    ("ats", "candidates"): Candidate, ("ats", "jobs"): Job,
    ("docs", "documents"): Document,
}
# Every table holding a customer's data, keyed by account_id (used by export, account deletion and purge).
ACCOUNT_TABLES = [ModuleGrant, Company, Contact, Deal, Activity, Employee, LeaveRequest, OnboardingTask,
                  Job, Candidate, Document, Acknowledgement, ApprovalStep]


@app.delete("/api/{module}/{kind}/{item_id}")
def delete_record(module: str, kind: str, item_id: int, session: str | None = Cookie(default=None, alias=COOKIE_NAME),
                  db: Session = Depends(get_db)):
    """Delete one record for good (it is removed from the database, not hidden)."""
    model = DELETABLE.get((module, kind))
    if not model:
        return JSONResponse({"error": "Not found."}, status_code=404)
    acc = current_account(db, session)
    if not acc:
        return JSONResponse({"error": "Please sign in."}, status_code=401)
    # Deleting stays possible after a module lapses, so customers can always remove what they stored.
    row = db.get(model, item_id)
    if not row or row.account_id != acc.id:
        return JSONResponse({"error": "Not found."}, status_code=404)
    if model is Document:
        for m in (ApprovalStep, Acknowledgement):
            db.execute(m.__table__.delete().where(m.document_id == item_id, m.account_id == acc.id))
    db.delete(row)
    db.commit()
    return {"ok": True}


def _rows(db: Session, model, account_id: int) -> list[dict]:
    out = []
    for r in db.execute(select(model).where(model.account_id == account_id).order_by(model.id)).scalars().all():
        d = {}
        for c in model.__table__.columns:
            v = getattr(r, c.name)
            d[c.name] = v.isoformat() if isinstance(v, datetime) else v
        out.append(d)
    return out


@app.get("/api/account/export")
def export_account(format: str = "json", session: str | None = Cookie(default=None, alias=COOKIE_NAME),
                   db: Session = Depends(get_db)):
    """Everything stored for this account: JSON, or a ZIP with one CSV per table (GDPR art. 20)."""
    acc = current_account(db, session)
    if not acc:
        return JSONResponse({"error": "Please sign in."}, status_code=401)
    from fastapi.responses import Response
    profile = {"id": acc.id, "email": acc.email, "name": acc.name, "org": acc.org, "suite": acc.suite,
               "created_at": acc.created_at.isoformat() if acc.created_at else ""}
    tables = {m.__tablename__: _rows(db, m, acc.id) for m in ACCOUNT_TABLES}
    stamp = date.today().isoformat()
    if format == "csv":
        import csv, io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, rows in [("account", [profile])] + list(tables.items()):
                s = io.StringIO()
                cols = list(rows[0].keys()) if rows else [c.name for c in next(
                    (m for m in ACCOUNT_TABLES if m.__tablename__ == name)).__table__.columns]
                w = csv.DictWriter(s, fieldnames=cols)
                w.writeheader()
                w.writerows(rows)
                z.writestr(f"{name}.csv", s.getvalue())
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="compepharma-export-{stamp}.zip"'})
    return Response(json.dumps({"account": profile, **tables}, ensure_ascii=False, indent=2),
                    media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="compepharma-export-{stamp}.json"'})


def _subscription_ids(db: Session, acc: Account) -> set:
    ids = {g for g in db.execute(select(ModuleGrant.stripe_subscription_id)
                                 .where(ModuleGrant.account_id == acc.id)).scalars().all() if g}
    if acc.suite_subscription_id:
        ids.add(acc.suite_subscription_id)
    return ids


def erase_account(db: Session, acc: Account):
    """Delete the account and every row it owns. Invoices stay with Stripe (tax law), not here."""
    for m in ACCOUNT_TABLES:
        db.execute(m.__table__.delete().where(m.account_id == acc.id))
    db.delete(acc)
    db.commit()


class DeleteAccountIn(BaseModel):
    password: str


@app.post("/api/account/delete")
def delete_account(body: DeleteAccountIn, request: Request, session: str | None = Cookie(default=None, alias=COOKIE_NAME),
                   db: Session = Depends(get_db)):
    acc = current_account(db, session)
    if not acc:
        return JSONResponse({"error": "Please sign in."}, status_code=401)
    rk = f"del:{acc.id}"
    if _too_many(rk, LOGIN_MAX_FAILS):
        return _slow_down()
    if not verify_password(body.password or "", acc.password_salt, acc.password_hash):
        _hit(rk)
        return JSONResponse({"error": "Incorrect password."}, status_code=401)
    subs = _subscription_ids(db, acc)
    if subs and BILLING:
        stripe = _stripe()
        for sid in subs:
            try:
                stripe.Subscription.cancel(sid)
            except Exception as e:      # already cancelled is fine; anything else stops the deletion
                if "No such subscription" not in str(e) and "canceled" not in str(e):
                    return JSONResponse({"error": f"Could not cancel your subscription ({e}). Nothing was deleted; "
                                                  "please try again or write to info@compepharma.com."}, status_code=502)
    erase_account(db, acc)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


def purge_closed_accounts(db: Session, now: datetime | None = None) -> int:
    """Erase accounts closed more than PURGE_AFTER_DAYS ago (privacy policy: 6 months after closure)."""
    from datetime import timedelta
    cutoff = ((now or utcnow()) - timedelta(days=PURGE_AFTER_DAYS)).isoformat()
    n = 0
    for acc in db.execute(select(Account).where(Account.closed_at != "", Account.closed_at < cutoff)).scalars().all():
        if acc.suite or owned_modules(db, acc):      # bought again since: keep
            acc.closed_at = ""
            db.commit()
            continue
        erase_account(db, acc)
        n += 1
    return n
