"""
Reader paywall for CompePharma article pages: one $4.99/month subscription unlocks every article on CompePharma AND
VigiEye.

This is a thin client. VigiEye (vigi-eye.com) is the hub: it holds the reader accounts, emails the confirmation links
(double opt-in), owns the Stripe subscription and answers "has this reader paid?" through its /api/readers/* endpoints.
Here we only keep VigiEye's signed access token in the cp_reader cookie.

Flow: email under an article -> confirmation link (to compepharma.com/reader/confirm) -> signed in -> paying readers go
back to the article unlocked, others to Stripe Checkout on vigi-eye.com and back here after paying.

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
.rg .card{border:1px solid rgba(100,116,139,.35);border-radius:14px;padding:22px;background:var(--card,#f8fafc)}
.rg h3{margin:0 0 6px;font-size:21px}.rg p{margin:6px 0 12px;font-size:15px}.rg form{display:grid;gap:10px;grid-template-columns:1fr}
.rg input{width:100%;padding:11px 12px;border:1px solid rgba(100,116,139,.45);border-radius:9px;font-size:15px;background:#fff;color:#0f172a}
.rg label.ck{display:flex;gap:8px;align-items:flex-start;font-size:13.5px}.rg label.ck input{width:auto;margin-top:3px}
.rg button,.rg a.rg-btn{display:block!important;text-align:center;padding:12px 16px!important;border:0!important;border-radius:10px!important;
font-weight:800!important;font-size:16px!important;cursor:pointer;background:#7c3aed!important;color:#fff!important;text-decoration:none!important;
opacity:1!important;-webkit-text-fill-color:#fff}.rg a.rg-btn:hover,.rg button:hover{filter:brightness(1.1)}.rg .msg{font-size:14px;min-height:1em}.rg ul{margin:4px 0 12px;padding-left:20px;font-size:14.5px}
.rg .fine{font-size:12.5px;opacity:.8}.rg .price{font-size:26px;font-weight:800}"""

_BENEFITS = ("<ul><li>Every article, analysis and opinion piece on CompePharma and VigiEye</li>"
             "<li>One subscription for both sites, cancel any time</li></ul>")


def signup_box(return_url: str, source: str = "article") -> str:
    return f"""<style>{_CSS}</style><div class="rg"><div class="fade"></div><div class="card">
<h3>Subscribe to keep reading</h3><p><span class="price">{_e(PRICE_LABEL)}</span> / month</p>{_BENEFITS}
<form onsubmit="return rgSignup(this)" data-src="{_e(source)}" data-ret="{_e(return_url)}">
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
    return lead_html + signup_box(here, source)


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
