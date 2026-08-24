"""
CompedPharma — a modular CRM + HR platform.

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
APP_NAME = "CompedPharma"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./compedpharma.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgres://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]
IS_SQLITE = DATABASE_URL.startswith("sqlite")

SESSION_SECRET = os.getenv("SESSION_SECRET", "") or os.getenv("STRIPE_WEBHOOK_SECRET", "") or "dev-insecure-compedpharma"
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "30"))
COOKIE_NAME = "compedpharma_session"
APP_BASE_URL = os.getenv("APP_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
BILLING = bool(STRIPE_SECRET_KEY)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ModuleGrant(Base):
    __tablename__ = "module_grants"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    module: Mapped[str] = mapped_column(String(20), index=True)
    source: Mapped[str] = mapped_column(String(20), default="purchase")
    stripe_session_id: Mapped[str] = mapped_column(String(120), default="", index=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Acknowledgement(Base):
    __tablename__ = "docs_acks"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    document_id: Mapped[int] = mapped_column(Integer, index=True)
    who: Mapped[str] = mapped_column(String(200))
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
    if not token or "." not in token:
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
_STATIC = os.path.dirname(__file__)


@app.on_event("startup")
def _startup():
    Base.metadata.create_all(bind=engine)


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(os.path.join(_STATIC, "index.html"))


@app.get("/app", include_in_schema=False)
def app_ui():
    return FileResponse(os.path.join(_STATIC, "index.html"))


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


@app.post("/api/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
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
def login(body: LoginIn, db: Session = Depends(get_db)):
    email = (body.email or "").strip().lower()
    acc = db.execute(select(Account).where(func.lower(Account.email) == email)).scalars().first()
    if not acc or not verify_password(body.password or "", acc.password_salt, acc.password_hash):
        return JSONResponse({"error": "Incorrect email or password."}, status_code=401)
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, acc)
    return resp


@app.get("/api/logout")
def logout():
    resp = RedirectResponse("/", status_code=302)
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


@app.post("/api/checkout")
def checkout(body: BuyIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME),
             db: Session = Depends(get_db)):
    acc = current_account(db, session)
    if not acc:
        return JSONResponse({"error": "Please sign in."}, status_code=401)
    if not BILLING:
        return JSONResponse({"error": "Payments aren’t switched on yet."}, status_code=400)
    key = body.module
    base = APP_BASE_URL.rstrip("/")
    if key == "suite":
        name, amount, interval = f"{APP_NAME} Suite (all modules)", SUITE_PRICE_CENTS, "month"
        mode = "subscription"
    elif key in MODULES:
        if key in owned_modules(db, acc):
            return JSONResponse({"error": "You already own this module."}, status_code=400)
        name, amount, interval = f"{APP_NAME} · {MODULES[key]['name']}", MODULES[key]["price_cents"], "month"
        mode = "subscription"
    else:
        return JSONResponse({"error": "Unknown module."}, status_code=404)
    try:
        stripe = _stripe()
        line = {"price_data": {"currency": "usd", "unit_amount": amount,
                               "recurring": {"interval": interval}, "product_data": {"name": name}}, "quantity": 1}
        s = stripe.checkout.Session.create(
            mode=mode, line_items=[line],
            success_url=f"{base}/app?purchased=1&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}/app",
            customer_email=acc.email,
            metadata={"account_id": str(acc.id), "module": key})
        return {"url": s.url}
    except Exception as e:
        return JSONResponse({"error": f"Checkout error: {e}"}, status_code=400)


class FulfillIn(BaseModel):
    session_id: str


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
        acc.stripe_customer_id = sess["customer"]
    if key == "suite":
        acc.suite = True
        db.commit()
        return {"ok": True, "module": "suite"}
    if key in MODULES:
        exists = db.execute(select(ModuleGrant).where(ModuleGrant.stripe_session_id == body.session_id)).scalars().first()
        if not exists:
            db.add(ModuleGrant(account_id=aid, module=key, source="purchase", stripe_session_id=body.session_id))
        db.commit()
        return {"ok": True, "module": key}
    return {"ok": False, "error": "Unknown module."}


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
    allow_self = os.getenv("ALLOW_SELF_GRANT", "1") == "1"
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
DOC_F = ["title", "category", "body", "expires", "created_at"]


@app.get("/api/docs/summary")
def docs_summary(session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "docs")
    if err:
        return err
    docs = db.execute(select(func.count(Document.id)).where(Document.account_id == acc.id)).scalar()
    acks = db.execute(select(func.count(Acknowledgement.id)).where(Acknowledgement.account_id == acc.id)).scalar()
    today = date.today().isoformat()
    expiring = db.execute(select(func.count(Document.id)).where(
        Document.account_id == acc.id, Document.expires != "", Document.expires <= today)).scalar()
    return {"documents": docs, "acknowledgements": acks, "expired": expiring}


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
        out.append(d)
    return {"items": out}


@app.post("/api/docs/documents")
def docs_add(body: DocIn, session: str | None = Cookie(default=None, alias=COOKIE_NAME), db: Session = Depends(get_db)):
    acc, err = _require(db, session, "docs")
    if err:
        return err
    d = Document(account_id=acc.id, **body.model_dump())
    db.add(d); db.commit()
    out = _dump(d, DOC_F); out["acks"] = 0
    return out


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
