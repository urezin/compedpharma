"""
Reader paywall for CompePharma article pages: one $4.99/month subscription unlocks every article on CompePharma AND
VigiEye.

This is a thin client. VigiEye (vigi-eye.com) is the hub: it holds the reader accounts, emails the confirmation links
(double opt-in), owns the Stripe subscription and answers "has this reader paid?" through its /api/readers/* endpoints.
Here we only keep VigiEye's signed access token in the cp_reader cookie.

Accounts (Nov 2026): create an account with email + username + password, sign in with username or email + password,
"Forgot password?" by emailed link, or "Continue with Google" (runs on vigi-eye.com, which hands back to /reader/sso).
All of it is answered by VigiEye's /api/readers/{register,login,forgot,reset,password,handoff}; we only keep the access
token it returns. The old email-link flow (/reader/signup -> /reader/confirm) still works for links already sent.
Paying readers go back to the article unlocked, others to Stripe Checkout on vigi-eye.com and back here after paying.

Search and ad crawlers get the full text; the locked part is marked with Google's paywalled-content markup.
"""
from __future__ import annotations

import os
import re
import time
from html import escape as _e
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

SITE = "compepharma"
SITE_NAME = "CompePharma"
COOKIE = "cp_reader"
MAX_AGE = 365 * 24 * 3600
PRICE_LABEL = os.getenv("READER_PRICE_LABEL", "$4.99")
_BOTS = re.compile(r"Googlebot|Mediapartners-Google|AdsBot-Google|Google-InspectionTool|GoogleOther|Storebot-Google|"
                   r"bingbot|BingPreview|DuckDuckBot|Applebot|LinkedInBot|Twitterbot|facebookexternalhit", re.I)

LD_GATED = {"isAccessibleForFree": False,
            "hasPart": {"@type": "WebPageElement", "isAccessibleForFree": False, "cssSelector": ".gated"}}


def _vigieye() -> str:
    return (os.getenv("VIGIEYE_API", "https://vigi-eye.com")).rstrip("/")


def _base() -> str:
    return (os.getenv("PORTAL_BASE_URL") or "https://compepharma.com").rstrip("/")


def _http():
    import httpx
    return httpx.Client(timeout=20, headers={"User-Agent": "CompePharma portal"})


# --- who is reading? (asks VigiEye, cached briefly) ----------------------------------------------------

_cache: dict[str, tuple[float, dict]] = {}


def _access(tok: str, fresh: bool = False) -> dict:
    """{'email':…, 'paid':bool, 'link':…} for a VigiEye access token, or {} if signed out / unknown."""
    if not tok:
        return {}
    hit = _cache.get(tok)
    if hit and not fresh and time.time() - hit[0] < 60:
        return hit[1]
    info: dict = {}
    try:
        with _http() as c:
            r = c.get(_vigieye() + "/api/readers/access", params={"t": tok})
        if r.status_code == 200:
            info = r.json()
    except Exception:
        info = (hit or (0, {}))[1]   # VigiEye unreachable: keep the last answer
    if len(_cache) > 5000:
        _cache.clear()
    _cache[tok] = (time.time(), info)
    return info


def reader(request: Request) -> str | None:
    return _access(request.cookies.get(COOKIE) or "").get("email")


def is_crawler(request: Request) -> bool:
    return bool(_BOTS.search(request.headers.get("user-agent", "")))


def can_read(request: Request) -> bool:
    return is_crawler(request) or bool(_access(request.cookies.get(COOKIE) or "").get("paid"))


# --- page fragments (same look as VigiEye's) -------------------------------------------------------------

_CSS = """.rg{position:relative;margin:6px 0 26px}.rg .fade{height:90px;margin-top:-90px;position:relative;
background:linear-gradient(rgba(255,255,255,0),var(--bg,#fff))}
.rg .card{border:1px solid rgba(100,116,139,.35);border-radius:14px;padding:22px;background:#f8fafc!important;color:#0f172a!important}.rg .card h3,.rg .card p,.rg .card li,.rg .card label,.rg .card .price,.rg .card .fine,.rg .card .msg{color:#0f172a!important}.rg .card .fine{color:#475569!important}.rg .card a:not(.rg-btn){color:#e4322b!important}
.rg h3{margin:0 0 6px;font-size:21px}.rg p{margin:6px 0 12px;font-size:15px}.rg form{display:grid;gap:10px;grid-template-columns:1fr}
.rg input{width:100%;padding:11px 12px;border:1px solid rgba(100,116,139,.45);border-radius:9px;font-size:15px;background:#fff;color:#0f172a}
.rg label.ck{display:flex;gap:8px;align-items:flex-start;font-size:13.5px}.rg label.ck input{width:auto;margin-top:3px}
.rg button,.rg a.rg-btn{display:block!important;text-align:center;padding:12px 16px!important;border:0!important;border-radius:10px!important;
font-weight:800!important;font-size:16px!important;cursor:pointer;background:#e4322b!important;color:#fff!important;text-decoration:none!important;
opacity:1!important;-webkit-text-fill-color:#fff}.rg a.rg-btn:hover,.rg button:hover{filter:brightness(1.1)}.rg .msg{font-size:14px;min-height:1em}.rg ul{margin:4px 0 12px;padding-left:20px;font-size:14.5px}
.rg .fine{font-size:12.5px;opacity:.8}.rg .price{font-size:26px;font-weight:800}"""

_BENEFITS = ("<ul><li>Every article, analysis and opinion piece on CompePharma and VigiEye</li>"
             "<li>One subscription for both sites, cancel any time</li></ul>")


def signup_box(return_url: str, source: str = "article", heading: str = "Subscribe to keep reading", fade: bool = True) -> str:
    return f"""<style>{_CSS}</style><div class="rg">{'<div class="fade"></div>' if fade else ''}<div class="card">
<h3>{_e(heading)}</h3><p><span class="price">{_e(PRICE_LABEL)}</span> / month</p>{_BENEFITS}
<p class="fine" style="margin:-4px 0 10px">Already a subscriber? Enter your email below: we'll send you a sign-in link. No password needed.</p>
<form onsubmit="rgSignup(this);return false;" data-src="{_e(source)}" data-ret="{_e(return_url)}">
<input type="email" name="email" placeholder="Your email" required autocomplete="email">
<label class="ck"><input type="checkbox" name="newsletter" value="1"> Also send me the free daily CompePharma email (unsubscribe any time)</label>
<button type="submit">Continue</button><div class="msg" aria-live="polite"></div>
<div class="fine">We'll email you a link to confirm your address, then take you to secure checkout (Stripe). Billed monthly
until you cancel; access starts at once, so the 14-day withdrawal right ends when it does.
Already a subscriber? Enter your email and the link will sign you in.
See our <a href="/terms">terms</a> and <a href="/privacy">privacy policy</a>.</div>
</form></div></div>
<script>async function rgSignup(f){{const m=f.querySelector('.msg');m.textContent='…';
const d=Object.fromEntries(new FormData(f).entries());d.newsletter=!!d.newsletter;d.source=f.dataset.src||'article';d.return=f.dataset.ret||location.href;
try{{const r=await fetch('/reader/signup',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d),credentials:'same-origin'}});
const j=await r.json();if(r.ok){{f.innerHTML='<p><b>Check your inbox.</b> We sent a link to '+d.email.replace(/[<>&]/g,'')+'. Open it to continue (check spam if it is not there in a minute).</p>';}}else m.textContent=j.error||'That did not work.';}}
catch(e){{m.textContent='Something went wrong, please try again.';}}return false;}}</script>"""


def _subscribe_url(link: str, ret: str) -> str:
    return f"{_vigieye()}/reader/subscribe?t={quote(link, safe='')}&return={quote(ret, safe='')}"


def subscribe_box(email: str, subscribe_url: str) -> str:
    return f"""<style>{_CSS}</style><div class="rg"><div class="fade"></div><div class="card">
<h3>Subscribe to keep reading</h3><p><span class="price">{_e(PRICE_LABEL)}</span> / month</p>{_BENEFITS}
<a class="rg-btn" href="{_e(subscribe_url)}">Subscribe with Stripe</a>
<p class="fine" style="margin-top:8px">Billed monthly until you cancel. Access starts at once, so the 14-day withdrawal right ends when it does.
<a href="/terms">Terms</a></p>
<p class="fine">Signed in as {_e(email)} · <a href="/reader/signout">not you?</a></p></div></div>"""


def _here(request: Request) -> str:
    q = f"?{request.url.query}" if request.url.query else ""
    return f"{_base()}{request.url.path}{q}"


def gated(request: Request, lead_html: str, rest_html: str, source: str = "article") -> str:
    """Lead is always shown; the rest only to paying subscribers and crawlers (inside .gated for the markup)."""
    if not rest_html.strip():
        return lead_html
    if is_crawler(request):
        return f'{lead_html}<div class="gated">{rest_html}</div>'
    info = _access(request.cookies.get(COOKIE) or "", fresh="subscribed" in request.query_params)
    if info.get("paid"):
        return f'{lead_html}<div class="gated">{rest_html}</div>'
    here = _here(request)
    if info.get("email") and info.get("link"):
        return lead_html + subscribe_box(info["email"], _subscribe_url(info["link"], here))
    return lead_html + _auth_box(here, source)


def ld(obj: dict) -> dict:
    return {**obj, **LD_GATED}


def _safe_return(url: str | None) -> str:
    try:
        host = urlparse(url or "").hostname
    except Exception:
        host = None
    return url if host in ("compepharma.com", "www.compepharma.com", urlparse(_base()).hostname) else _base() + "/"


def _cookie(resp, request: Request, tok: str):
    resp.set_cookie(COOKIE, tok, max_age=MAX_AGE, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
    return resp


def _page(title: str, body: str) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex"><title>{_e(title)} | CompePharma</title></head>'
            f'<body style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:60px auto;padding:0 16px;color:#0f172a">'
            f'<h1 style="font-size:26px">{_e(title)}</h1>{body}<p><a href="/">CompePharma home</a></p></body></html>')


# --- routes --------------------------------------------------------------------------------------------

router = APIRouter()


@router.post("/reader/signup", include_in_schema=False)
async def reader_signup(request: Request):
    try:
        body = await request.json()
        body = body if isinstance(body, dict) else {}
    except Exception:
        body = {}
    payload = {k: body.get(k) for k in ("email", "name", "company", "role", "source", "newsletter")}
    payload.update(site=SITE, **{"return": _safe_return(str(body.get("return") or ""))})
    try:
        with _http() as c:
            r = c.post(_vigieye() + "/api/readers/start", json=payload)
        j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code >= 400:
            return JSONResponse({"error": j.get("error") or "Something went wrong, please try again."}, status_code=r.status_code)
    except Exception:
        return JSONResponse({"error": "Something went wrong, please try again."}, status_code=502)
    return {"ok": True}


@router.get("/reader/confirm", include_in_schema=False)
def reader_confirm(request: Request, t: str = ""):
    try:
        with _http() as c:
            r = c.post(_vigieye() + "/api/readers/confirm", json={"t": t})
        j = r.json() if r.status_code == 200 else {}
    except Exception:
        j = {}
    if not j.get("access"):
        return HTMLResponse(_page("Link expired", "<p>This link has expired or is not valid. Go back to the article and enter "
                                  "your email again to get a new one.</p>"), status_code=400)
    ret = _safe_return(j.get("return"))
    dest = ret if j.get("paid") else _subscribe_url(j.get("link") or "", ret)
    return _cookie(RedirectResponse(dest, status_code=303), request, j["access"])


HOW_IT_WORKS = ('<ol style="font-size:15px;line-height:1.6;padding-left:20px"><li><b>Create an account</b> with your email, a username and a '
                'password, or press <b>Continue with Google</b>.</li>'
                '<li>Next time, <b>sign in</b> with your username (or email) and password, on any phone or computer. The same account works on '
                'CompePharma and VigiEye.</li>'
                '<li>Subscribers go straight back to reading. Everyone else is taken to secure checkout (Stripe, '
                + PRICE_LABEL + ' a month, cancel any time).</li><li>Forgot your password, or signed up before with just your email? Use '
                '<b>Forgot password?</b> under Sign in and we email you a link to set one.</li></ol>')


@router.get("/reader/login", include_in_schema=False)
def reader_login(request: Request):
    import portal as _portal
    info = _access(request.cookies.get(COOKIE) or "", fresh=True)
    if info.get("email"):
        btns = []
        if not info.get("paid") and info.get("link"):
            btns.append(f'<a class="rg-btn" href="{_e(_subscribe_url(info["link"], _base() + "/"))}">Subscribe for {_e(PRICE_LABEL)} / month</a>')
        if info.get("has_subscription") and not info.get("complimentary"):
            btns.append('<a class="rg-btn" style="background:#334155!important" href="/reader/manage">Manage or cancel subscription</a>')
        btns.append('<a class="rg-btn" style="background:#64748b!important" href="/reader/signout">Sign out</a>')
        status = ("Full access (site administrator / complimentary)" if info.get("complimentary") else
                  "Full access to every article") if info.get("paid") else "Not subscribed: you can read headlines and the opening of each story"
        body = (f'<style>{_CSS}</style><div class="rg"><div class="card"><h3>Your account</h3><p>Signed in as <b>{_e(info["email"])}</b></p>'
                f'<p><b>{_e(status)}</b></p><div style="display:grid;gap:10px">{"".join(btns)}</div>'
                + password_form(bool(info.get("has_password")), info.get("username") or "")
                + f'<p class="fine" style="margin-top:12px">One subscription covers CompePharma and VigiEye: sign in on VigiEye with the same username or email and password.</p></div></div>')
        title = "Your account"
    else:
        ret = _safe_return(request.query_params.get("return"))
        body = (f'<p style="font-size:16px">Headlines and the first paragraph of every story are free. Full articles on CompePharma and '
                f'VigiEye are for subscribers.</p><h2 style="font-size:19px;margin:18px 0 4px">How signing in works</h2>{HOW_IT_WORKS}'
                + _auth_box(ret, "login", heading="Sign in or create an account", fade=False, start="login"))
        title = "Sign in"
    html = f'<main style="max-width:640px;margin:30px auto;padding:0 16px"><h1 style="font-size:30px">{title}</h1>{body}</main>'
    return _portal._page("Sign in | CompePharma", "Sign in to CompePharma or subscribe to read every article.", "/reader/login", html)


@router.get("/reader/manage", include_in_schema=False)
def reader_manage(request: Request):
    info = _access(request.cookies.get(COOKIE) or "")
    if not info.get("link"):
        return RedirectResponse("/", status_code=303)
    return RedirectResponse(f"{_vigieye()}/reader/manage?t={quote(info['link'], safe='')}", status_code=303)


@router.get("/reader/signout", include_in_schema=False)
def reader_signout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# --- username/password + Google (answered by VigiEye) ----------------------------------------------------------

_cfg: dict = {}


def _google_on() -> bool:
    """Ask VigiEye once every 10 minutes whether Google sign-in is switched on."""
    if time.time() - _cfg.get("at", 0) > 600:
        try:
            with _http() as c:
                _cfg["google"] = bool(c.get(_vigieye() + "/api/readers/config").json().get("google"))
        except Exception:
            _cfg.setdefault("google", False)
        _cfg["at"] = time.time()
    return bool(_cfg.get("google"))


def _google_url(ret: str) -> str:
    return f"{_vigieye()}/reader/google/start?site={SITE}&return={quote(ret, safe='')}"


def _auth_box(return_url: str, source: str = "article", heading: str = "Subscribe to keep reading", fade: bool = True,
              start: str = "register") -> str:
    return auth_box(return_url, source, heading=heading, fade=fade, start=start,
                    google_url=_google_url(return_url) if _google_on() else None)


async def _jbody(request: Request) -> dict:
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


def _proxy(path: str, payload: dict) -> tuple[int, dict]:
    try:
        with _http() as c:
            r = c.post(_vigieye() + path, json=payload)
        j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return r.status_code, j if isinstance(j, dict) else {}
    except Exception:
        return 502, {"error": "Something went wrong, please try again."}


def _signed_in(request: Request, code: int, j: dict) -> JSONResponse:
    out = {k: v for k, v in j.items() if k not in ("access", "link")}
    if code >= 400 and not out.get("error"):
        out["error"] = "Something went wrong, please try again."
    resp = JSONResponse(out, status_code=code)
    if code == 200 and j.get("access"):
        _cache.pop(j["access"], None)
        _cookie(resp, request, j["access"])
    return resp


@router.post("/reader/register", include_in_schema=False)
async def reader_register(request: Request):
    b = await _jbody(request)
    payload = {k: b.get(k) for k in ("email", "username", "password", "name", "company", "role", "source", "newsletter")}
    payload.update(site=SITE, **{"return": _safe_return(str(b.get("return") or ""))})
    return _signed_in(request, *_proxy("/api/readers/register", payload))


@router.post("/reader/password-login", include_in_schema=False)
async def reader_password_login(request: Request):
    b = await _jbody(request)
    return _signed_in(request, *_proxy("/api/readers/login", {"login": b.get("login"), "password": b.get("password"), "site": SITE,
                                                              "return": _safe_return(str(b.get("return") or ""))}))


@router.post("/reader/forgot", include_in_schema=False)
async def reader_forgot(request: Request):
    b = await _jbody(request)
    code, j = _proxy("/api/readers/forgot", {"email": b.get("email"), "site": SITE})
    return JSONResponse(j or {"error": "Something went wrong, please try again."}, status_code=code)


@router.post("/reader/reset", include_in_schema=False)
async def reader_reset_post(request: Request):
    b = await _jbody(request)
    return _signed_in(request, *_proxy("/api/readers/reset", {"t": b.get("t"), "password": b.get("password"), "site": SITE}))


@router.get("/reader/reset", include_in_schema=False)
def reader_reset_page(t: str = ""):
    import portal as _portal
    html = ('<main style="max-width:520px;margin:30px auto;padding:0 16px"><h1 style="font-size:30px">Set a new password</h1>'
            + (reset_form(t) if t else '<p>This link is not complete. <a href="/reader/login">Ask for a new one</a>.</p>') + '</main>')
    return _portal._page("Set a new password | CompePharma", "Set a new password for your CompePharma account.", "/reader/reset", html)


@router.post("/reader/password", include_in_schema=False)
async def reader_password(request: Request):
    b = await _jbody(request)
    code, j = _proxy("/api/readers/password", {"access": request.cookies.get(COOKIE) or "", "current": b.get("current"),
                                               "password": b.get("password"), "username": b.get("username")})
    return JSONResponse(j or {"error": "Something went wrong, please try again."}, status_code=code)


@router.get("/reader/sso", include_in_schema=False)
def reader_sso(request: Request, t: str = ""):
    """Back from Google sign-in on vigi-eye.com: swap the 10-minute hand-off token for an access token."""
    ret = _safe_return(request.query_params.get("return"))
    code, j = _proxy("/api/readers/handoff", {"t": t, "return": ret})
    if code != 200 or not j.get("access"):
        return HTMLResponse(_page("Sign-in expired", '<p>That sign-in took too long. <a href="/reader/login">Try again</a>.</p>'), status_code=400)
    return _cookie(RedirectResponse(j.get("next") or ret, status_code=303), request, j["access"])


AUTH_CSS = """.rg form[hidden]{display:none!important}.rg .tabs{display:flex;gap:0;margin:4px 0 14px;border-bottom:1px solid rgba(100,116,139,.35)}
.rg .tabs button{flex:1;background:none!important;color:#475569!important;-webkit-text-fill-color:#475569;border:0!important;
border-bottom:3px solid transparent!important;border-radius:0!important;padding:10px 6px!important;font-size:15px!important}
.rg .tabs button.on{color:#0f172a!important;-webkit-text-fill-color:#0f172a;border-bottom-color:var(--rg-accent,#0f766e)!important}
.rg a.rg-google{display:flex!important;align-items:center;justify-content:center;gap:10px;background:#fff!important;color:#1f2937!important;
-webkit-text-fill-color:#1f2937;border:1px solid #cbd5e1!important;border-radius:10px;padding:11px 16px;font-weight:700;text-decoration:none!important;font-size:15.5px}
.rg .or{display:flex;align-items:center;gap:10px;color:#64748b;font-size:13px;margin:12px 0}.rg .or:before,.rg .or:after{content:"";flex:1;height:1px;background:rgba(100,116,139,.35)}
.rg .lnk{background:none!important;border:0!important;padding:0!important;color:var(--rg-accent,#0f766e)!important;-webkit-text-fill-color:var(--rg-accent,#0f766e);
font-weight:600!important;font-size:13.5px!important;text-decoration:underline!important;display:inline!important;cursor:pointer}
.rg .hint{font-size:12.5px;color:#64748b!important;margin:-6px 0 0}"""

G_ICON = ('<svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.4 30.2 0 24 0 '
          '14.6 0 6.6 5.4 2.6 13.3l7.8 6.1C12.3 13.6 17.7 9.5 24 9.5z"/><path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9h12.4c-.5 2.9-2.2 '
          '5.3-4.6 6.9l7.4 5.7c4.3-4 6.9-9.9 6.9-17z"/><path fill="#FBBC05" d="M10.4 28.6c-.5-1.4-.8-3-.8-4.6s.3-3.2.8-4.6l-7.8-6.1C1 16.6 0 20.2 0 24s1 '
          '7.4 2.6 10.7l7.8-6.1z"/><path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.4-5.7c-2.1 1.4-4.8 2.3-8.5 2.3-6.3 0-11.7-4.1-13.6-9.9l-7.8 '
          '6.1C6.6 42.6 14.6 48 24 48z"/></svg>')


def auth_box(return_url: str, source: str = "article", heading: str = "Subscribe to keep reading", fade: bool = True,
             site_name: str = SITE_NAME, accent: str = "#e4322b", google_url: str | None = None, prefix: str = "/reader",
             login_path: str = "/reader/password-login", start: str = "register", show_price: bool = True) -> str:
    """Create account / Sign in / Forgot password card, with Continue with Google when google_url is given."""
    g = (f'<a class="rg-google" href="{_e(google_url)}">{G_ICON}<span>Continue with Google</span></a><div class="or">or</div>'
         if google_url else "")
    price = (f'<p><span class="price">{_e(PRICE_LABEL)}</span> / month</p>{_BENEFITS}' if show_price else "")
    nl = f"Also send me the free daily {site_name} email (unsubscribe any time)"
    return f"""<style>{_CSS}{AUTH_CSS}</style><div class="rg" style="--rg-accent:{accent}">{'<div class="fade"></div>' if fade else ''}<div class="card">
<h3>{_e(heading)}</h3>{price}
<div class="tabs" role="tablist"><button type="button" data-t="register">Create account</button><button type="button" data-t="login">Sign in</button></div>
{g}
<form data-mode="register" onsubmit="rgAuth(this);return false;" data-src="{_e(source)}" data-ret="{_e(return_url)}">
<input type="email" name="email" placeholder="Email" required autocomplete="email">
<input type="text" name="username" placeholder="Username" required autocomplete="username" minlength="3" maxlength="30" pattern="[A-Za-z0-9][A-Za-z0-9._-]{{2,29}}">
<input type="password" name="password" placeholder="Password (at least 8 characters)" required autocomplete="new-password" minlength="8">
<label class="ck"><input type="checkbox" name="newsletter" value="1"> {_e(nl)}</label>
<button type="submit">Create account</button><div class="msg" aria-live="polite"></div>
<div class="fine">You'll be signed in straight away; we also email you a link to confirm your address. Reading every article takes a
{_e(PRICE_LABEL)}/month subscription (secure checkout by Stripe), billed monthly until you cancel; access starts at once, so the
14-day withdrawal right ends when it does. See our <a href="/terms">terms</a> and <a href="/privacy">privacy policy</a>.</div>
</form>
<form data-mode="login" onsubmit="rgAuth(this);return false;" data-src="{_e(source)}" data-ret="{_e(return_url)}" hidden>
<input type="text" name="login" placeholder="Email or username" required autocomplete="username">
<input type="password" name="password" placeholder="Password" required autocomplete="current-password">
<button type="submit">Sign in</button><div class="msg" aria-live="polite"></div>
<p class="fine" style="margin:0"><button type="button" class="lnk" onclick="rgForgot(this)">Forgot password?</button> · Signed up before with
just your email? Use “Forgot password?” once to set a password.</p>
</form>
<form data-mode="forgot" onsubmit="rgAuth(this);return false;" hidden>
<p class="fine" style="margin:0">Enter your email or username and we'll email you a link to set a new password.</p>
<input type="text" name="email" placeholder="Email or username" required autocomplete="username">
<button type="submit">Email me a link</button><div class="msg" aria-live="polite"></div>
<p class="fine" style="margin:0"><button type="button" class="lnk" onclick="rgTab(this,'login')">Back to sign in</button></p>
</form></div></div>
<script>(function(){{const s=document.currentScript.previousElementSibling;
s.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>rgTab(b,b.dataset.t));rgTab(s.querySelector('.tabs button'),'{start}');}})();
function rgTab(el,t){{const c=el.closest('.card');c.querySelectorAll('form').forEach(f=>f.hidden=f.dataset.mode!==t);
c.querySelectorAll('.tabs button').forEach(b=>b.classList.toggle('on',b.dataset.t===t||(t==='forgot'&&b.dataset.t==='login')));}}
function rgForgot(el){{rgTab(el,'forgot');}}
async function rgAuth(f){{const m=f.querySelector('.msg');m.textContent='…';const mode=f.dataset.mode;
const d=Object.fromEntries(new FormData(f).entries());d.newsletter=!!d.newsletter;d.source=f.dataset.src||'article';d.return=f.dataset.ret||location.href;
const url={{register:'{prefix}/register',login:'{login_path}',forgot:'{prefix}/forgot'}}[mode];
try{{const r=await fetch(url,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d),credentials:'same-origin'}});
const j=await r.json();if(!r.ok){{m.textContent=j.error||'That did not work.';return false;}}
if(mode==='forgot'){{m.textContent=j.message||'Check your inbox.';return false;}}
if(j.notice)alert(j.notice);location.href=j.next||d.return;}}catch(e){{m.textContent='Something went wrong, please try again.';}}return false;}}</script>"""


def reset_form(t: str, prefix: str = "/reader", accent: str = "#e4322b") -> str:
    return f"""<style>{_CSS}</style><div class="rg" style="--rg-accent:{accent}"><div class="card">
<form onsubmit="rgReset(this);return false;" data-t="{_e(t)}">
<input type="password" name="password" placeholder="New password (at least 8 characters)" required minlength="8" autocomplete="new-password">
<input type="password" name="password2" placeholder="New password again" required minlength="8" autocomplete="new-password">
<button type="submit">Save password and sign in</button><div class="msg" aria-live="polite"></div></form></div></div>
<script>async function rgReset(f){{const m=f.querySelector('.msg');const d=Object.fromEntries(new FormData(f).entries());
if(d.password!==d.password2){{m.textContent='The two passwords are not the same.';return false;}}m.textContent='…';
try{{const r=await fetch('{prefix}/reset',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{t:f.dataset.t,password:d.password}}),credentials:'same-origin'}});
const j=await r.json();if(!r.ok){{m.textContent=j.error||'That did not work.';return false;}}location.href=j.next||'/';}}
catch(e){{m.textContent='Something went wrong, please try again.';}}return false;}}</script>"""


def password_form(has_password: bool, username: str, prefix: str = "/reader") -> str:
    cur = ('<input type="password" name="current" placeholder="Current password" required autocomplete="current-password">'
           if has_password else "")
    return f"""<form onsubmit="rgPw(this);return false;" style="margin-top:14px">
<h3 style="font-size:17px">{'Change password' if has_password else 'Set a password'}</h3>
<p class="fine" style="margin:0">Username: <b>{_e(username or '—')}</b>. You can sign in with it or with your email.</p>
<input type="text" name="username" placeholder="Username (optional change)" value="{_e(username)}" autocomplete="username">
{cur}<input type="password" name="password" placeholder="New password (at least 8 characters)" required minlength="8" autocomplete="new-password">
<button type="submit">Save</button><div class="msg" aria-live="polite"></div></form>
<script>async function rgPw(f){{const m=f.querySelector('.msg');m.textContent='…';const d=Object.fromEntries(new FormData(f).entries());
try{{const r=await fetch('{prefix}/password',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d),credentials:'same-origin'}});
const j=await r.json();m.textContent=r.ok?'Saved.':(j.error||'That did not work.');if(r.ok)f.reset();}}catch(e){{m.textContent='Something went wrong.';}}return false;}}</script>"""
