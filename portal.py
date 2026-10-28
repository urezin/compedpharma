"""
CompePharma News: the business of pharma.

A trade-news front end (deals, launches, marketing, manufacturing, pricing, legal, earnings,
pipeline) for pharma business readers. Its stories come from VigiEye's shared news engine
(https://vigi-eye.com/api/business-news), which collects company press releases filed with the
SEC, novel FDA/EU approvals, recalls and health-care enforcement from official sources, and
writes every article from scratch (/api/story). Outbound links go only to official sources.

Routes: /  /news/{beat}  /story/{id}  /thumb/{beat}/{seed}.svg  /robots.txt  /sitemap.xml
The CRM/HR product lives at /app.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
import time
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

router = APIRouter()

VIGIEYE = os.getenv("VIGIEYE_API", "https://vigi-eye.com").rstrip("/")
BASE = (os.getenv("PORTAL_BASE_URL") or os.getenv("APP_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL")
        or "http://localhost:8000").rstrip("/")

BEATS = [("deals", "Deals & M&A", "#7c3aed"), ("launches", "Approvals & launches", "#0369a1"),
         ("marketing", "Marketing & sales", "#db2777"), ("manufacturing", "Manufacturing & supply", "#b45309"),
         ("pricing", "Pricing & policy", "#047857"), ("legal", "Legal", "#475569"),
         ("earnings", "Earnings", "#0f766e"), ("pipeline", "Pipeline & R&D", "#4338ca"),
         ("industry", "Industry", "#334155")]
BEAT_LABEL = {k: v for k, v, _ in BEATS}
BEAT_COLOR = {k: c for k, _, c in BEATS}
BEAT_BLURB = {
    "deals": "Acquisitions, licensing, partnerships and financing across pharma and biotech.",
    "launches": "New approvals in the US and EU, label expansions and commercial launches.",
    "marketing": "Commercial strategy, DTC and HCP promotion, sales forces and launch performance.",
    "manufacturing": "Plants, CDMOs, supply chains, shortages, recalls and warning letters.",
    "pricing": "Drug pricing, IRA, MFN, 340B, PBMs, payers and reimbursement policy.",
    "legal": "Patent fights, litigation, enforcement and settlements.",
    "earnings": "Quarterly results and guidance from the drugmakers that matter.",
    "pipeline": "Readouts, trials and R&D strategy.",
    "industry": "Everything else moving the pharma business.",
}

PQRA = {"cta_url": "https://www.pqra.gr/", "site": "https://www.pqra.gr/"}

_cache: dict = {"t": 0.0, "items": [], "editorial": [], "ticker": [], "insights": [], "error": None}
_lock = threading.Lock()


def _e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _get(path: str, timeout: float = 25):
    import httpx
    r = httpx.get(VIGIEYE + path, timeout=timeout, headers={"User-Agent": "CompePharma portal"})
    r.raise_for_status()
    return r.json()


def _load(force: bool = False) -> dict:
    with _lock:
        if not force and time.time() - _cache["t"] < 600 and _cache["items"]:
            return _cache
        try:
            items = _get("/api/business-news?limit=400&days=45").get("items", [])
            if items:
                _cache["items"] = items
            try:
                _cache["editorial"] = _get("/api/editorial?limit=6").get("items", [])
                _cache["ticker"] = _get("/api/ticker?limit=14&region=US").get("items", [])
                _cache["insights"] = _get("/api/cp-articles?limit=60").get("items", []) or _cache["insights"]
            except Exception:
                pass
            _cache["t"], _cache["error"] = time.time(), None
        except Exception as ex:            # keep serving the last good copy
            _cache["error"] = str(ex)
            _cache["t"] = time.time() - 480   # retry in ~2 minutes
        return _cache


def _fmt(d: str) -> str:
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        return d


def _sid(it: dict) -> str:
    return re.sub(r"[^a-zA-Z0-9\-]", "", it.get("id", ""))[:60]


def _href(it: dict) -> str:
    return f"/story/{_sid(it)}"       # every story opens on CompePharma


def _thumb(it: dict, cls: str) -> str:
    b = it.get("beat") if it.get("beat") in BEAT_COLOR else "industry"
    seed = hashlib.sha1((it.get("id") or it.get("title", "")).encode()).hexdigest()[:10]
    return f'<img class="th {cls}" loading="lazy" alt="" src="/thumb/{b}/{seed}.svg?v=2">'


def _a(it: dict, inner: str, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f'<a{c} href="{_e(_href(it))}">{inner}</a>'


def _kind(it: dict) -> str:
    return {"company": "Company news", "approval": "Approval", "official": "Regulator", "notice": "Regulator"}.get(it["kind"], "")


def _label(it: dict) -> str:
    b = it.get("beat", "industry")
    return f'<a class="lab" style="--c:{BEAT_COLOR.get(b, "#334155")}" href="/news/{b}">{_e(BEAT_LABEL.get(b, b))}</a>'


def _meta(it: dict) -> str:
    pub = _e(it.get("publisher")) + (f' <span class="tk">{_e(it["ticker"])}</span>' if it.get("ticker") else "")
    k = _kind(it)
    return f'<div class="by">{_e(_fmt(it.get("date", "")))} · {pub}{(" · " + _e(k)) if k else ""}</div>'


def _dek(it: dict, cls: str = "dek") -> str:
    return f'<p class="{cls}">{_e(it.get("summary"))}</p>' if it.get("summary") else ""


def hero(it):
    return (f'<article class="hero">{_a(it, _thumb(it, "hw"), "hi")}<div class="hov">{_label(it)}'
            f'<h2>{_a(it, _e(it["title"]))}</h2>{_dek(it)}{_meta(it)}</div></article>')


def mini(it):
    return f'<article class="mini">{_a(it, _thumb(it, "sq"))}<div>{_label(it)}<h3>{_a(it, _e(it["title"]))}</h3>{_meta(it)}</div></article>'


def river(it):
    return (f'<article class="river">{_a(it, _thumb(it, "rv"))}<div>{_label(it)}<h3>{_a(it, _e(it["title"]))}</h3>'
            f'{_dek(it)}{_meta(it)}</div></article>')


def gcard(it, big: bool = False):
    return (f'<article class="gc{" big" if big else ""}">{_a(it, _thumb(it, "wide"))}<div class="gb">{_label(it)}'
            f'<h3>{_a(it, _e(it["title"]))}</h3>{_dek(it) if big else ""}{_meta(it)}</div></article>')


KIND_LABEL = {"earnings": "CP+ Earnings analysis", "analysis": "CP+ Analysis", "opinion": "Opinion · CompePharma View"}


def _ins_thumb(a: dict, cls: str = "wide") -> str:
    b = a.get("beat") if a.get("beat") in BEAT_COLOR else "industry"
    seed = hashlib.sha1(a.get("slug", "").encode()).hexdigest()[:10]
    return f'<img class="th {cls}" loading="lazy" alt="" src="/thumb/{b}/{seed}.svg?v=2">'


def _figs(a: dict, n: int = 3) -> str:
    f = [x for x in (a.get("figures") or []) if x.get("value")][:n]
    return ('<div class="figs">' + "".join(f'<span><b>{_e(x["value"])}</b>{_e(x.get("label"))}</span>' for x in f) + "</div>") if f else ""


def icard(a: dict, big: bool = False) -> str:
    k = a.get("type", "analysis")
    who = (f'<div class="co">{_e(a.get("company"))}{(" · " + _e(a["ticker"])) if a.get("ticker") else ""}'
           f'{(" · " + _e(a["period"])) if a.get("period") else ""}</div>') if a.get("company") else ""
    return (f'<article class="ic {k}{" big" if big else ""}"><a href="/insights/{_e(a["slug"])}">{_ins_thumb(a)}</a><div class="gb">'
            f'<span class="kk {k}">{_e(KIND_LABEL.get(k, "Analysis"))}</span>{who}'
            f'<h3><a href="/insights/{_e(a["slug"])}">{_e(a["title"])}</a></h3>'
            f'{_figs(a) if k == "earnings" else ""}<p class="dek">{_e(a.get("dek"))}</p>'
            f'<div class="by">{_e(_fmt(a.get("date", "")))} · CompePharma editorial</div></div></article>')


def _nl_box(place: str) -> str:
    return (f'<section class="box nlb"><h2>CompePharma Daily</h2><p>Earnings analysis, deals, launches and pricing news, '
            f'every weekday morning. Free.</p><form method="post" action="/newsletter/subscribe" class="nlf">'
            f'<input type="hidden" name="src" value="{_e(place)}"><input type="email" name="email" required placeholder="Work email" aria-label="Work email">'
            f'<button class="btn" type="submit">Subscribe</button></form></section>')


FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700;8..60,800&display=swap" rel="stylesheet">')

CSS = """
:root{--ink:#0d1321;--mut:#5d6677;--rule:#e3e6eb;--paper:#fff;--tint:#f3f5f8;--navy:#0a1730;--brand:#0e9c8a;--red:#d7263d;
--sans:Inter,system-ui,Segoe UI,Roboto,sans-serif;--serif:'Source Serif 4',Georgia,'Times New Roman',serif}
@media (prefers-color-scheme: dark){:root:not([data-theme=light]){--ink:#e7eaf0;--mut:#9aa4b5;--rule:#1f2a3a;--paper:#0a0f18;--tint:#0f1622}}
*{box-sizing:border-box;margin:0;padding:0}html{scroll-behavior:smooth}
body{font:16px/1.55 var(--sans);color:var(--ink);background:var(--paper);-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}img{max-width:100%}
.wrap{max-width:1480px;margin:0 auto;padding:0 32px}@media(max-width:700px){.wrap{padding:0 16px}}
.util{background:var(--navy);color:#aab6cc;font-size:12.5px}.util .wrap{display:flex;justify-content:space-between;align-items:center;height:34px;gap:12px}
.util a{color:#e5ebf5;font-weight:600;margin-left:18px}.util a:hover{color:#fff}@media(max-width:700px){.util .d{display:none}.util .wrap{justify-content:flex-end}.mast .cta .ghost{display:none}.logo{font-size:38px}}
.mast{border-bottom:1px solid var(--rule);background:var(--paper)}
.mast .wrap{display:flex;align-items:center;justify-content:space-between;gap:20px;padding-top:20px;padding-bottom:18px;flex-wrap:wrap}
.logo{font:900 46px/1 var(--sans);letter-spacing:-.045em}.logo b{color:var(--brand)}.logo i{font-style:normal;color:var(--red)}
.tag{font-size:13.5px;color:var(--mut);margin-top:6px;font-weight:500}
.mast .cta{display:flex;gap:10px;align-items:center}
.btn{display:inline-flex;align-items:center;gap:8px;background:var(--red);color:#fff;padding:11px 18px;border-radius:4px;font-weight:800;font-size:13.5px;letter-spacing:.02em}
.btn:hover{filter:brightness(1.08)}.btn.ghost{background:transparent;color:var(--ink);border:1.5px solid var(--ink)}.btn.teal{background:var(--brand)}
nav.beats{background:var(--navy);position:sticky;top:0;z-index:20;box-shadow:0 2px 10px rgba(0,0,0,.18)}
nav.beats .wrap{display:flex;overflow-x:auto;scrollbar-width:none;gap:2px}
nav.beats a{color:#dfe6f2;padding:15px 14px 13px;font-weight:800;font-size:12.5px;letter-spacing:.08em;text-transform:uppercase;white-space:nowrap;border-bottom:3px solid transparent}
nav.beats a:hover{color:#fff;background:rgba(255,255,255,.06)}nav.beats a.on{color:#fff;border-bottom-color:var(--c,var(--red))}
.tick{background:var(--tint);border-bottom:1px solid var(--rule);font-size:13px;overflow:hidden}
.tick .wrap{display:flex;align-items:center;gap:0;height:40px}
.tick .tl{flex:none;background:var(--red);color:#fff;font-weight:900;font-size:11px;letter-spacing:.1em;text-transform:uppercase;padding:6px 10px;border-radius:3px;margin-right:16px}
.tick .tr{overflow:hidden;flex:1;mask-image:linear-gradient(90deg,transparent,#000 3%,#000 97%,transparent)}
.tick .tm{display:inline-flex;gap:34px;white-space:nowrap;animation:scroll 70s linear infinite}.tick:hover .tm{animation-play-state:paused}
.tick b{color:var(--red);margin-right:6px}@keyframes scroll{from{transform:translateX(0)}to{transform:translateX(-50%)}}
@media (prefers-reduced-motion:reduce){.tick .tm{animation:none}}
.th{display:block;width:100%;background:#0b1220;object-fit:cover;border-radius:3px}
.th.wide{aspect-ratio:16/9;height:auto}.th.hw{aspect-ratio:16/9;height:auto;border-radius:0}
.th.sq{width:112px;height:76px;flex:none}.th.rv{width:220px;aspect-ratio:16/10;height:auto;flex:none}
@media(max-width:700px){.th.rv{width:110px}.th.sq{width:88px;height:62px}}
.lab{display:inline-block;font-weight:800;font-size:11.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--c);border-left:3px solid var(--c);padding-left:7px;line-height:1.1}
.by{font-size:12.5px;color:var(--mut);margin-top:6px}.tk{font-weight:700;color:var(--ink)}
h2 a:hover,h3 a:hover{color:var(--brand)}
.front{display:grid;grid-template-columns:minmax(0,1.75fr) minmax(0,1fr) 300px;gap:30px;padding-top:28px}
@media(max-width:1250px){.front{grid-template-columns:minmax(0,1.6fr) minmax(0,1fr)}.front>.adcol{display:none}}
@media(max-width:860px){.front{grid-template-columns:1fr}}
.hero{position:relative;overflow:hidden;border-radius:4px;background:#0b1220}
.hero .hi{display:block}.hero .hov{position:absolute;inset:auto 0 0 0;padding:90px 30px 26px;background:linear-gradient(180deg,transparent,rgba(5,10,22,.78) 38%,rgba(5,10,22,.96));color:#fff}
.hero .lab{color:#fff;border-color:var(--c)}.hero h2{font:800 40px/1.1 var(--serif);margin:10px 0 10px;letter-spacing:-.01em}
.hero h2 a:hover{color:#9ff2e5}.hero .dek{font-size:16.5px;color:#d9e1ee;max-width:820px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.hero .by{color:#b9c4d6}@media(max-width:700px){.hero .hov{position:static;padding:16px;background:#0b1220}.hero h2{font-size:26px}}
.hd{display:flex;justify-content:space-between;align-items:baseline;border-top:4px solid var(--c,var(--ink));padding-top:10px;margin-bottom:6px}
.hd span{font-weight:900;font-size:14px;letter-spacing:.1em;text-transform:uppercase}.hd a{font-size:12.5px;font-weight:700;color:var(--mut)}.hd a:hover{color:var(--brand)}
.mini{display:flex;gap:14px;padding:14px 0;border-bottom:1px solid var(--rule)}.mini:last-child{border:0}
.mini h3{font:700 17px/1.28 var(--serif);margin-top:5px}
.cols{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:40px;margin-top:40px}@media(max-width:960px){.cols{grid-template-columns:1fr}}
.cols aside{position:relative}.stick{position:sticky;top:64px}
.river{display:flex;gap:20px;padding:20px 0;border-bottom:1px solid var(--rule)}
.river h3{font:800 22px/1.22 var(--serif);margin-top:6px}.river .dek{color:var(--mut);font-size:15px;margin-top:6px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
@media(max-width:700px){.river h3{font-size:17px}.river .dek{display:none}}
.band{margin-top:46px;padding:34px 0 38px}.band.alt{background:var(--tint)}
.bg{display:grid;grid-template-columns:minmax(0,1.5fr) repeat(3,minmax(0,1fr));gap:24px;margin-top:14px}
@media(max-width:1100px){.bg{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.bg{grid-template-columns:1fr}}
.gc .gb{padding-top:12px}.gc h3{font:700 18px/1.28 var(--serif);margin-top:6px}.gc.big h3{font-size:25px;line-height:1.18}
.gc .dek{color:var(--mut);font-size:15px;margin-top:6px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.box{border:1px solid var(--rule);border-radius:4px;padding:18px;margin-bottom:24px;background:var(--paper)}
.box h2{font-weight:900;font-size:13px;letter-spacing:.1em;text-transform:uppercase;border-top:4px solid var(--ink);padding-top:9px;margin:-18px -18px 10px;padding-left:18px;padding-right:18px}
.most{counter-reset:n}.most li{list-style:none;display:flex;gap:12px;padding:11px 0;border-bottom:1px solid var(--rule);font:700 15.5px/1.3 var(--serif)}
.most li:last-child{border:0}.most li:before{counter-increment:n;content:counter(n);font:900 26px/1 var(--sans);color:var(--red);min-width:26px}
.ad{position:relative;background:linear-gradient(160deg,#ecfdf9,#fff 60%);border-color:#a7eee2}
@media (prefers-color-scheme: dark){:root:not([data-theme=light]) .ad{background:linear-gradient(160deg,#052b27,var(--paper))}}
.ad .adt{position:absolute;top:9px;right:12px;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:#94a3b8}
.ad .al{font:900 28px var(--sans);letter-spacing:-.03em;color:#0d9488}.ad ul{margin:10px 0 10px 18px;font-size:14px}.ad li{margin:3px 0}
.ve{background:var(--navy);color:#e5ebf5;border-color:var(--navy)}.ve h2{color:#fff;border-color:var(--brand)}.ve p{font-size:14px;color:#c3cede}
.cu{display:flex;gap:12px;padding:9px 0;border-bottom:1px solid var(--rule);font-size:14px}.cu:last-child{border:0}
.cu b{flex:none;width:54px;color:var(--red);font-size:12px;font-weight:900;text-transform:uppercase}
.banner{display:flex;justify-content:space-between;gap:24px;align-items:center;flex-wrap:wrap;padding:26px 30px}
.dark{background:var(--navy);color:#e5ebf5;margin-top:46px;padding:38px 0 42px}.dark .hd{border-color:var(--brand)}.dark .hd span{color:#fff}
.eds{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:24px;margin-top:14px}@media(max-width:1000px){.eds{grid-template-columns:repeat(2,1fr)}}
@media(max-width:560px){.eds{grid-template-columns:1fr}}
.ed{border-top:1px solid #23314a;padding-top:14px}.ed .k{font-size:11px;font-weight:900;letter-spacing:.1em;text-transform:uppercase;color:#5eead4}
.ed h3{font:700 20px/1.25 var(--serif);margin-top:8px;color:#fff}.ed p{color:#aebad0;font-size:14px;margin-top:6px}
.shead{padding:30px 0 22px;border-bottom:1px solid var(--rule);background:linear-gradient(90deg,color-mix(in srgb,var(--c) 14%,var(--paper)),var(--paper) 70%)}
.shead h1{font:900 48px/1.05 var(--sans);letter-spacing:-.03em;color:var(--c)}.shead p{color:var(--mut);margin-top:8px;max-width:760px;font-size:16px}
.art{max-width:780px}.art h1{font:800 46px/1.1 var(--serif);margin:14px 0 14px;letter-spacing:-.01em}
@media(max-width:700px){.art h1{font-size:30px}.shead h1{font-size:32px}}
.art .dek{font-size:21px;line-height:1.45;color:var(--mut);margin-bottom:14px;font-family:var(--serif)}
.art .body p{font:19px/1.7 var(--serif);margin:0 0 20px}.art .body p:first-child::first-letter{font:800 60px/.9 var(--serif);float:left;margin:6px 10px 0 0;color:var(--c)}
.take{border-left:4px solid var(--c);background:var(--tint);padding:18px 22px;margin:26px 0;border-radius:0 4px 4px 0}
.take h2{font-weight:900;font-size:13px;letter-spacing:.1em;text-transform:uppercase}.take ul{margin:10px 0 0 18px}.take li{margin:7px 0}
.share{display:flex;gap:8px;margin:16px 0;flex-wrap:wrap}.share a{border:1px solid var(--rule);padding:7px 12px;border-radius:3px;font-size:12.5px;font-weight:700}
.note{font-size:12.5px;color:var(--mut);margin-top:16px}
.pager{display:flex;gap:10px;margin:22px 0}.pager a{border:1px solid var(--rule);padding:9px 16px;border-radius:4px;font-weight:700}
.kk{display:inline-block;font-size:11px;font-weight:900;letter-spacing:.09em;text-transform:uppercase;padding:3px 7px;border-radius:3px;background:#e8f7f4;color:#0e7c6f}
.kk.earnings{background:#fde8eb;color:var(--red)}.kk.opinion{background:#eef0ff;color:#4338ca}
@media (prefers-color-scheme: dark){:root:not([data-theme=light]) .kk{background:#0f2a27}:root:not([data-theme=light]) .kk.earnings{background:#3a0f16}:root:not([data-theme=light]) .kk.opinion{background:#1c1f45}}
.co{font-size:12.5px;font-weight:700;color:var(--mut);margin-top:8px;text-transform:uppercase;letter-spacing:.04em}
.ic .gb{padding-top:12px}.ic h3{font:700 19px/1.25 var(--serif);margin-top:6px}.ic.big h3{font-size:27px;line-height:1.15}
.ic .dek{color:var(--mut);font-size:14.5px;margin-top:6px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.ic.opinion h3{font-style:italic}
.figs{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.figs span{background:var(--tint);border:1px solid var(--rule);border-radius:3px;padding:4px 8px;font-size:12px;color:var(--mut)}
.figs b{display:block;color:var(--ink);font-size:15px;font-weight:900}
.ig{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:24px;margin-top:14px}
.ig.e3{grid-template-columns:minmax(0,1.4fr) repeat(2,minmax(0,1fr))}
@media(max-width:1100px){.ig,.ig.e3{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.ig,.ig.e3{grid-template-columns:1fr}}
.earn{background:linear-gradient(180deg,#fff5f6,var(--paper));border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}
@media (prefers-color-scheme: dark){:root:not([data-theme=light]) .earn{background:linear-gradient(180deg,#1a0b10,var(--paper))}}
.nlb{background:var(--tint)}.nlf{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}.nlf input{flex:1;min-width:160px;padding:10px;border:1px solid var(--rule);border-radius:4px;font:inherit;background:var(--paper);color:var(--ink)}
.opn{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:26px;margin-top:14px}@media(max-width:900px){.opn{grid-template-columns:1fr}}
.op{border-top:3px solid #4338ca;padding-top:14px}.op .kk{background:transparent;padding:0;color:#4338ca}
.op h3{font:italic 700 23px/1.22 var(--serif);margin-top:8px}.op p{color:var(--mut);margin-top:8px;font-size:15px}
.statp{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0}
.statp div{border:1px solid var(--rule);border-top:4px solid var(--red);padding:12px 14px;border-radius:3px}
.statp b{display:block;font:900 24px/1.1 var(--sans)}.statp span{font-size:12.5px;color:var(--mut)}
.art h2.sh{font:800 24px/1.25 var(--serif);margin:30px 0 12px}
.srcs li{list-style:none;padding:6px 0;border-bottom:1px solid var(--rule);font-size:14px}
/* --- STAT-style editorial skin --- */
:root{--navy:#000;--red:#e4322b}
body{font-family:var(--sans)}
.util{background:#000;border-bottom:1px solid #222}
.mast{background:#000;border:0}.mast .wrap{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding-top:16px;padding-bottom:14px}
.mast .ml{display:flex;gap:18px}.mast .ml a{color:#fff;font-weight:700;font-size:13px;text-transform:uppercase;letter-spacing:.08em}
.mast .mc{text-align:center}.mast .logo{color:#fff;font-size:50px}.mast .logo b{color:var(--red)}
.mast .tag{color:#9a9a9a;font-size:11.5px;text-transform:uppercase;letter-spacing:.24em;margin-top:6px}
.mast .cta{justify-content:flex-end}
@media(max-width:700px){.mast .wrap{grid-template-columns:1fr auto}.mast .ml{display:none}.mast .mc{text-align:left}.mast .logo{font-size:34px}.mast .tag{display:none}}
nav.beats{background:#000;border-top:1px solid #2a2a2a;box-shadow:none}
nav.beats a{font-size:12px;color:#d6d6d6}nav.beats a.on{border-bottom-color:var(--red)}
.tick{background:#fff;border-bottom:1px solid var(--rule)}
@media (prefers-color-scheme: dark){:root:not([data-theme=light]) .tick{background:var(--paper)}}
.lab{border:0;padding:0;color:var(--red);font-size:11.5px;letter-spacing:.1em}
.hero{background:transparent;border-radius:0;overflow:visible}.hero .hov{position:static;padding:14px 0 0;background:none;color:var(--ink)}
.hero .lab{color:var(--red)}.hero h2{font:800 40px/1.08 var(--sans);letter-spacing:-.025em;margin:8px 0}.hero h2 a:hover{color:var(--red)}
.hero .dek{color:var(--mut);font-family:var(--serif);font-size:18px}.hero .by{color:var(--mut)}
.th,.th.hw{border-radius:0}
.front{grid-template-columns:minmax(0,1.9fr) minmax(0,1fr) minmax(0,.95fr);gap:28px;border-bottom:1px solid var(--ink);padding-bottom:30px}
@media(max-width:1200px){.front{grid-template-columns:minmax(0,1.6fr) minmax(0,1fr)}.front .latest{grid-column:1/-1}}
@media(max-width:800px){.front{grid-template-columns:1fr}}
.sec2{display:flex;flex-direction:column;gap:22px;border-left:1px solid var(--rule);padding-left:28px}
@media(max-width:800px){.sec2{border:0;padding:0}}
.latest{border-left:1px solid var(--rule);padding-left:24px}.latest .hd{border-top:0;padding-top:0}.latest .hd span{color:var(--red)}
.lt{padding:11px 0;border-bottom:1px solid var(--rule)}.lt:last-child{border:0}.lt>span{font-size:11.5px;font-weight:700;color:var(--mut);margin-right:8px}
.lt h4{font:700 15.5px/1.3 var(--sans);margin-top:4px}.lt h4 a:hover{color:var(--red)}
.hd{border-top:3px solid var(--ink)}.hd span{font-size:13px;letter-spacing:.14em}
.mini h3,.gc h3,.ic h3,.river h3,.most li{font-family:var(--sans);font-weight:800;letter-spacing:-.01em}
.gc h3{font-size:18px;line-height:1.25}.gc.big h3{font-size:26px}.river h3{font-size:21px}.ic h3{font-size:19px}.ic.big h3{font-size:28px}
.op h3{font-family:var(--serif)}
.btn{border-radius:2px}.btn.teal{background:var(--red)}
.band.alt{background:#f6f6f4}@media (prefers-color-scheme: dark){:root:not([data-theme=light]) .band.alt{background:var(--tint)}}
.earn{background:#fff;border-top:0}@media (prefers-color-scheme: dark){:root:not([data-theme=light]) .earn{background:var(--paper)}}
.art h1{font-family:var(--sans);font-weight:900;letter-spacing:-.025em}
.dark{background:#000}
footer{background:#000;color:#9eabc2;margin-top:56px;padding:44px 0 28px;font-size:14px}
footer .fg{display:grid;grid-template-columns:1.4fr repeat(3,1fr);gap:30px}@media(max-width:800px){footer .fg{grid-template-columns:1fr 1fr}}
footer h4{color:#fff;font-size:12px;letter-spacing:.12em;text-transform:uppercase;margin-bottom:10px}footer li{list-style:none;margin:6px 0}
footer a:hover{color:#fff}footer .logo{font-size:32px;color:#fff}footer .fine{border-top:1px solid #1b2840;margin-top:30px;padding-top:18px;font-size:12.5px}

/* --- richer STAT-style layer --- */
.trend{background:#111;color:#ddd;font-size:12.5px;border-bottom:1px solid #222}.trend .wrap{display:flex;gap:10px;align-items:center;height:38px;overflow-x:auto;scrollbar-width:none}
.trend b{color:var(--red);text-transform:uppercase;letter-spacing:.14em;font-size:11px;font-weight:900;margin-right:6px;flex:none}
.chip{flex:none;border:1px solid #333;border-radius:999px;padding:3px 11px;font-weight:600;color:#eee;white-space:nowrap}
.th{transition:transform .5s ease,filter .3s}a:hover>.th{transform:scale(1.03);filter:saturate(1.15)}
a.hi,a.mi,.gc>a,.river>a,.mini>a,.ic>a{display:block;overflow:hidden}
.river>a{flex:0 0 220px}.mini>a{flex:0 0 112px}.river>a .th.rv,.mini>a .th.sq{width:100%}.mini>a .th.sq{height:76px}
@media(max-width:700px){.river>a{flex-basis:110px}.mini>a{flex-basis:88px}.mini>a .th.sq{height:62px}}
.kk{background:var(--red)!important;color:#fff!important;border-radius:2px}.kk.opinion{background:#1f2937!important}
.lab{position:relative;padding-left:14px}.lab:before{content:"";position:absolute;left:0;top:50%;width:8px;height:8px;margin-top:-4px;background:var(--red)}
.hero h2{font-size:46px}@media(max-width:700px){.hero h2{font-size:28px}}
.nums{background:#0b0d12;color:#e8ebf1;margin-top:44px;padding:34px 0 40px}
.nums .hd{border-color:var(--red)}.nums .hd span{color:#fff}.live{font-style:normal;font-size:12px;color:#fca5a5;font-weight:700;letter-spacing:.04em}
.ntg{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:1px;background:#1d222d;border:1px solid #1d222d;margin-top:16px}
@media(max-width:1100px){.ntg{grid-template-columns:repeat(3,1fr)}}@media(max-width:560px){.ntg{grid-template-columns:repeat(2,1fr)}}
.nt{background:#0f131a;padding:16px 16px 10px;display:flex;flex-direction:column;gap:2px}
.nt span{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#9aa3b2;font-weight:800}
.nt b{font:900 44px/1 var(--sans);letter-spacing:-.04em;color:#fff;margin-top:6px}
.nt small{font-size:12px;color:#8b94a5}.nt em{font-style:normal;font-weight:800;color:#9aa3b2}.nt em.up{color:#4ade80}.nt em.dn{color:#f87171}
.spk{width:100%;height:38px;margin-top:8px}
.nrow{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:24px;margin-top:24px}@media(max-width:860px){.nrow{grid-template-columns:1fr}}
.nbox{border-top:1px solid #262c38;padding-top:12px}.nbox h4{font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;color:#9aa3b2;margin-bottom:8px}
.cb{display:grid;grid-template-columns:170px 1fr 44px;align-items:center;gap:12px;padding:6px 0;font-size:13.5px;color:#d7dce5}
.cb i{display:block;height:12px;background:var(--c);border-radius:1px;min-width:4px}.cb b{text-align:right;font-weight:800;color:#fff}
.cb:hover span{color:#fff;text-decoration:underline}
.cos{list-style:none;counter-reset:c}.cos li{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #1d222d;font-size:14px}
.cos li:before{counter-increment:c;content:counter(c);font:900 20px/1 var(--sans);color:var(--red);width:22px}
.cos li span{flex:1;font-weight:700}.cos code,.dtr code{font:700 11.5px/1 ui-monospace,monospace;background:#1f2937;color:#e5e7eb;padding:3px 6px;border-radius:3px}
.cos b{color:#fff}.cos.up li span{font-weight:600;font-size:13.5px}.cos.up a:hover{color:#fff;text-decoration:underline}
.hstrip{display:grid;grid-template-columns:1fr 1fr;gap:0 24px;margin-top:22px;border-top:3px solid var(--ink)}@media(max-width:700px){.hstrip{grid-template-columns:1fr}}
.hstrip .mini h3{font-size:15.5px}
.mods{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:30px 26px;margin-top:16px}
@media(max-width:1200px){.mods{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.mods{grid-template-columns:1fr}}
.mod{border-top:4px solid var(--c);padding-top:10px}.mh{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px}
.mh>a:first-child{font-weight:900;font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:var(--c)}
.more{font-size:12px;font-weight:800;color:var(--mut)}.more:hover{color:var(--red)}
.mod h3{font:800 19px/1.25 var(--sans);letter-spacing:-.01em;margin-top:10px}.mod h3 a:hover{color:var(--red)}
.mod .dek{color:var(--mut);font-size:14px;margin-top:6px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.mod ul{list-style:none;margin-top:10px}.mod li{border-top:1px solid var(--rule);padding:9px 0;font:700 14.5px/1.3 var(--sans)}
.mod li a:hover{color:var(--red)}.mod li span{display:block;font-size:11.5px;color:var(--mut);font-weight:600;margin-top:3px}
.dtr table{width:100%;border-collapse:collapse;font-size:13px}.dtr td{border-bottom:1px solid var(--rule);padding:8px 6px 8px 0;vertical-align:top}
.dtr td a{font-weight:600}.dtr td a:hover{color:var(--red)}.dtr .dt{color:var(--red);font-weight:900;white-space:nowrap;font-size:11.5px}
.dtr code{background:var(--tint);color:var(--ink)}
"""


def _ad_box(place: str) -> str:
    u = f'{PQRA["cta_url"]}?utm_source=compepharma&utm_medium=house_ad&utm_campaign=pqra&utm_content={place}'
    return (f'<aside class="box ad" aria-label="Advertisement"><span class="adt">Advertisement</span><div class="al">PQRA</div>'
            f'<p style="font-weight:700;margin-top:6px">Regulatory, quality and pharmacovigilance consulting for the pharmaceutical industry</p>'
            f'<ul><li>Regulatory affairs &amp; market access</li><li>Quality management &amp; audit readiness</li>'
            f'<li>Pharmacovigilance &amp; medical information</li></ul>'
            f'<p class="by">25+ years with EOF and EMA · human and veterinary medicines</p>'
            f'<p style="margin-top:12px"><a class="btn teal" href="{_e(u)}" target="_blank" rel="noopener sponsored">Visit pqra.gr →</a></p></aside>')


def _ad_banner(place: str) -> str:
    u = f'{PQRA["cta_url"]}?utm_source=compepharma&utm_medium=house_ad&utm_campaign=pqra&utm_content={place}'
    return (f'<div class="wrap" style="margin-top:46px"><aside class="box ad banner" aria-label="Advertisement"><span class="adt">Advertisement</span>'
            f'<div><div class="al">PQRA</div><p style="font-weight:700;font-size:18px;margin-top:4px">Regulatory, quality and pharmacovigilance support, '
            f'backed by 25+ years with EOF and EMA.</p><p class="by">Marketing authorisations · QMS &amp; GMP/GDP audit readiness · local PV &amp; medical information</p></div>'
            f'<a class="btn teal" href="{_e(u)}" target="_blank" rel="noopener sponsored">Visit pqra.gr →</a></aside></div>')


def _vigieye_box() -> str:
    return (f'<section class="box ve"><h2>Regulatory &amp; safety</h2><p>PRAC signals, EMA and FDA guidance, recalls, PDUFA dates and EU '
            f'approvals: our sister site VigiEye covers the regulatory side every day.</p>'
            f'<p style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap"><a class="btn teal" href="{VIGIEYE}/?utm_source=compepharma">Open VigiEye</a>'
            f'<a class="btn ghost" style="color:#fff;border-color:#fff" href="{VIGIEYE}/newsletter?utm_source=compepharma">Daily email</a></p></section>')


def _coming_up(c: dict) -> str:
    items = c.get("ticker") or []
    if not items:
        return ""
    rows = "".join(f'<div class="cu"><b>{_e(_fmt(i["date"])[:6])}</b><div><a href="{_e(i["url"])}">{_e(i["title"])}</a>'
                   f'<div class="by" style="margin-top:2px">{_e(i["label"])}</div></div></div>' for i in items[:7])
    return f'<section class="box"><h2>Coming up: FDA dates</h2>{rows}</section>'


def _most(c: dict, exclude: set | None = None) -> str:
    ex = exclude or set()
    top = [i for i in sorted(c["items"][:80], key=_score, reverse=True) if i["id"] not in ex][:6]
    if not top:
        return ""
    return '<section class="box"><h2>Most read</h2><ol class="most">' + "".join(f'<li>{_a(i, _e(i["title"]))}</li>' for i in top) + "</ol></section>"


def _side(c: dict, place: str, exclude: set | None = None, ad: bool = True) -> str:
    return f'<aside><div class="stick">{_ad_box(place) if ad else ""}{_nl_box(place)}{_most(c, exclude)}{_coming_up(c)}{_vigieye_box()}</div></aside>'


def _beatbar(active: str = "") -> str:
    links = [f'<a class="{"on" if active == "home" else ""}" href="/">Home</a>',
             f'<a class="{"on" if active == "insights" else ""}" style="--c:#d7263d" href="/insights">Insights &amp; opinion</a>']
    links += [f'<a class="{"on" if active == k else ""}" style="--c:{c}" href="/news/{k}">{_e(v)}</a>' for k, v, c in BEATS]
    return f'<nav class="beats" aria-label="Sections"><div class="wrap">{"".join(links)}</div></nav>'


def _ticker(c: dict) -> str:
    items = (c.get("ticker") or [])[:12]
    if not items:
        return ""
    parts = "".join(f'<a href="{_e(i["url"])}"><b>{_e(_fmt(i["date"])[:6])}</b>{_e(i["label"])}: {_e(i["title"])}</a>' for i in items)
    return f'<div class="tick"><div class="wrap"><span class="tl">Coming up</span><div class="tr"><div class="tm">{parts}{parts}</div></div></div></div>'


def _mast() -> str:
    return (f'<header class="mast"><div class="wrap"><div class="ml"><a href="/insights?type=earnings">Earnings</a>'
            f'<a href="/insights?type=opinion">Opinion</a></div><div class="mc"><a href="/" class="logo">Compe<b>Pharma</b></a>'
            f'<div class="tag">The business of pharma</div></div>'
            f'<div class="cta"><a class="btn" href="/newsletter">Subscribe free</a></div></div></header>')


def _page(title: str, desc: str, path: str, body: str, canonical: str | None = None, ld: list | None = None) -> HTMLResponse:
    can = canonical or (BASE + path)
    lds = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in (ld or []))
    beats_li = "".join(f'<li><a href="/news/{k}">{_e(v)}</a></li>' for k, v, _ in BEATS)
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title><meta name="description" content="{_e(desc)}"><link rel="canonical" href="{_e(can)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="CompePharma"><meta property="og:title" content="{_e(title)}">
<meta property="og:description" content="{_e(desc)}"><meta property="og:url" content="{_e(can)}"><meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#0a1730">{FONTS}<style>{CSS}</style>{lds}</head><body>
<div class="util"><div class="wrap"><span class="d">{_e(date.today().strftime("%A %d %B %Y"))}</span>
<span><a href="{VIGIEYE}/?utm_source=compepharma">VigiEye regulatory news</a><a href="/app">CompePharma CRM &amp; HR →</a></span></div></div>
{_mast()}{body}
<footer><div class="wrap"><div class="fg"><div><div class="logo">Compe<b style="color:#2dd4bf">Pharma</b></div>
<p style="margin-top:10px;max-width:420px">Pharma business news written by CompePharma's editorial system from company filings with the SEC and
official FDA, EMA and European Commission records. Not investment advice.</p></div>
<div><h4>Sections</h4><ul>{beats_li}</ul></div>
<div><h4>Regulatory</h4><ul><li><a href="{VIGIEYE}/">VigiEye news</a></li><li><a href="{VIGIEYE}/pdufa">PDUFA calendar</a></li>
<li><a href="{VIGIEYE}/approvals">Approvals</a></li><li><a href="{VIGIEYE}/safety">Safety</a></li><li><a href="{VIGIEYE}/newsletter">Daily email</a></li></ul></div>
<div><h4>Company</h4><ul><li><a href="/app">CRM &amp; HR app</a></li><li><a href="/sitemap.xml">Sitemap</a></li></ul></div></div>
<div class="fine">© {date.today().year} CompePharma. Every story is original reporting by CompePharma; outbound links go only to official
sources (regulators and SEC filings).</div></div></footer></body></html>""")


def _score(it: dict) -> float:
    s = float(it.get("score") or 0)
    s += 3 if it["kind"] in ("company", "approval") else 0
    s += 2 if it.get("summary") else 0
    s += 1.5 if it.get("beat") in ("deals", "launches", "pricing", "manufacturing", "legal") else 0
    return s



def _spark(vals: list, w: int = 120, h: int = 34, col: str = "#e4322b") -> str:
    m = max(vals) or 1
    step = w / max(1, len(vals) - 1)
    pts = " ".join(f"{k * step:.1f},{h - 3 - (v / m) * (h - 8):.1f}" for k, v in enumerate(vals))
    return (f'<svg class="spk" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">'
            f'<polygon points="0,{h} {pts} {w},{h}" fill="{col}" fill-opacity=".16"/>'
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.2" stroke-linejoin="round"/></svg>')


def _daily(items: list, pred, days: int = 14) -> list:
    from datetime import timedelta
    today = date.today()
    keys = [(today - timedelta(days=d)).isoformat() for d in range(days - 1, -1, -1)]
    cnt = {k: 0 for k in keys}
    for i in items:
        d = (i.get("date") or "")[:10]
        if d in cnt and pred(i):
            cnt[d] += 1
    return [cnt[k] for k in keys]


def _numbers(c: dict) -> str:
    """'By the numbers': live counts computed from the stories on the site, with 14-day sparklines."""
    items = c["items"]
    from datetime import timedelta
    wk = (date.today() - timedelta(days=7)).isoformat()
    tiles = [("All stories", lambda i: True, "#ffffff"), ("Deals & M&A", lambda i: i.get("beat") == "deals", BEAT_COLOR["deals"]),
             ("Approvals & launches", lambda i: i.get("beat") == "launches", "#38bdf8"),
             ("Manufacturing & supply", lambda i: i.get("beat") == "manufacturing", "#f59e0b"),
             ("Pricing & policy", lambda i: i.get("beat") == "pricing", "#34d399"),
             ("Legal", lambda i: i.get("beat") == "legal", "#cbd5e1")]
    cells = []
    for lab, pred, colr in tiles:
        series = _daily(items, pred)
        n7 = sum(1 for i in items if (i.get("date") or "") >= wk and pred(i))
        prev = sum(series[:7])
        cur = sum(series[7:])
        delta = cur - prev
        arrow = (f'<em class="up">▲ {delta}</em>' if delta > 0 else f'<em class="dn">▼ {abs(delta)}</em>' if delta < 0 else '<em>— 0</em>')
        cells.append(f'<div class="nt"><span>{_e(lab)}</span><b>{n7}</b><small>last 7 days {arrow} vs prior week</small>{_spark(series, col=colr)}</div>')
    # coverage by section, 30 days
    wk30 = (date.today() - timedelta(days=30)).isoformat()
    by = {}
    for i in items:
        if (i.get("date") or "") >= wk30:
            by[i.get("beat", "industry")] = by.get(i.get("beat", "industry"), 0) + 1
    top = sorted(by.items(), key=lambda x: -x[1])[:8]
    mx = max([v for _, v in top] or [1])
    bars = "".join(f'<a class="cb" href="/news/{_e(k)}"><span>{_e(BEAT_LABEL.get(k, k))}</span><i style="width:{max(4, v / mx * 100):.0f}%;--c:{BEAT_COLOR.get(k, "#64748b")}"></i><b>{v}</b></a>'
                   for k, v in top)
    # most-covered companies
    co = {}
    for i in items:
        if (i.get("date") or "") >= wk30 and i.get("kind") == "company" and i.get("publisher"):
            key = (i.get("publisher"), i.get("ticker") or "")
            co[key] = co.get(key, 0) + 1
    tc = sorted(co.items(), key=lambda x: -x[1])[:6]
    cos = "".join(f'<li><span>{_e(p)}</span>{f"<code>{_e(t)}</code>" if t else ""}<b>{n}</b></li>' for (p, t), n in tc)
    if tc and tc[0][1] >= 2:
        right = f'<h4>Most-covered companies · 30 days</h4><ol class="cos">{cos}</ol>'
    else:
        up = (c.get("ticker") or [])[:6]
        right = ('<h4>Coming up · FDA decision dates</h4><ol class="cos up">' + "".join(
            f'<li><span><a href="{_e(i["url"])}">{_e(i["title"])}</a></span><code>{_e(_fmt(i["date"])[:6])}</code></li>' for i in up) + '</ol>') if up else ""
    return (f'<section class="nums"><div class="wrap"><div class="hd"><span>By the numbers</span><em class="live">● Live from today\'s coverage</em></div>'
            f'<div class="ntg">{"".join(cells)}</div><div class="nrow"><div class="nbox"><h4>Coverage by section · 30 days</h4>{bars}</div>'
            f'<div class="nbox">{right}</div></div></div></section>')


def _trending(c: dict) -> str:
    from datetime import timedelta
    since = (date.today() - timedelta(days=10)).isoformat()
    co = {}
    for i in c["items"]:
        if (i.get("date") or "") >= since and i.get("publisher") and i.get("kind") == "company":
            co[i["publisher"]] = co.get(i["publisher"], 0) + 1
    top = [k for k, _ in sorted(co.items(), key=lambda x: -x[1])[:9]]
    if not top:
        return ""
    chips = "".join(f'<span class="chip">{_e(t)}</span>' for t in top)
    return f'<div class="trend"><div class="wrap"><b>Trending</b>{chips}</div></div>'


def _tick(i: dict) -> str:
    return f' <code>{_e(i["ticker"])}</code>' if i.get("ticker") else ""


def _deal_tracker(c: dict) -> str:
    rows = [i for i in c["items"] if i.get("beat") == "deals"][:8]
    if len(rows) < 3:
        return ""
    tr = "".join(f'<tr><td class="dt">{_e(_fmt(i.get("date", ""))[:6])}</td><td><b>{_e(i.get("publisher"))}</b>'
                 f'{_tick(i)}</td>'
                 f'<td>{_a(i, _e(i["title"]))}</td></tr>' for i in rows)
    return (f'<section class="box dtr"><h2>Deal tracker</h2><table>{tr}</table>'
            f'<p style="margin-top:10px"><a class="more" href="/news/deals">All deals →</a></p></section>')


def _module(k: str, items: list, used: set) -> str:
    rs = [i for i in items if i.get("beat") == k and i["id"] not in used][:4]
    if len(rs) < 2:
        return ""
    used.update(i["id"] for i in rs)
    lead, rest = rs[0], rs[1:]
    lis = "".join(f'<li>{_a(i, _e(i["title"]))}<span>{_e(_fmt(i.get("date", ""))[:6])}</span></li>' for i in rest)
    return (f'<section class="mod" style="--c:{BEAT_COLOR[k]}"><div class="mh"><a href="/news/{k}">{_e(BEAT_LABEL[k])}</a><a class="more" href="/news/{k}">More →</a></div>'
            f'{_a(lead, _thumb(lead, "wide"), "mi")}<h3>{_a(lead, _e(lead["title"]))}</h3>{_dek(lead)}<ul>{lis}</ul></section>')


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def home():
    c = _load()
    items = c["items"]
    if not items:
        body = f'{_beatbar("home")}<main class="wrap"><p class="note" style="padding:40px 0">The news desk is warming up. Refresh in a minute.</p></main>'
        return _page("CompePharma: the business of pharma", "Pharma business news.", "/", body)
    ranked = sorted(items[:120], key=_score, reverse=True)
    ld_ = ranked[0]
    tops = [i for i in ranked[1:] if i.get("beat") != ld_.get("beat")][:5] or ranked[1:6]
    used = {ld_["id"]} | {i["id"] for i in tops}
    # STAT-style section modules get first call on the remaining stories
    mods = "".join(_module(k, items, used) for k in ("deals", "launches", "pricing", "manufacturing", "marketing", "legal", "pipeline", "earnings"))
    riv = [i for i in items if i["id"] not in used][:34]
    used |= {i["id"] for i in riv}

    def band(k, alt):
        rs = [i for i in items if i.get("beat") == k and i["id"] not in used][:4]
        if len(rs) < 2:
            return ""
        used.update(i["id"] for i in rs)
        cards = gcard(rs[0], True) + "".join(gcard(i) for i in rs[1:])
        return (f'<section class="band{" alt" if alt else ""}"><div class="wrap"><div class="hd" style="--c:{BEAT_COLOR[k]}">'
                f'<span style="color:{BEAT_COLOR[k]}">{_e(BEAT_LABEL[k])}</span><a href="/news/{k}">More {_e(BEAT_LABEL[k])} →</a></div>'
                f'<div class="bg">{cards}</div></div></section>')
    ed = c.get("editorial") or []
    ed_html = ""
    if ed:
        ed_html = ('<section class="dark"><div class="wrap"><div class="hd"><span>Regulatory analysis from VigiEye</span>'
                   f'<a href="{VIGIEYE}/analysis" style="color:#9fb0c9">All analysis →</a></div><div class="eds">'
                   + "".join(f'<article class="ed"><div class="k">{_e("Opinion" if a.get("type") == "opinion" else "Analysis")}</div>'
                             f'<h3><a href="{_e(a["url"])}">{_e(a["title"])}</a></h3><p>{_e(a.get("dek") or "")}</p>'
                             f'<div class="by" style="color:#7f8ea8">{_e(_fmt(a.get("date", "")))}</div></article>' for a in ed[:4])
                   + "</div></div></section>")
    ins = c.get("insights") or []
    earn = [a for a in ins if a.get("type") == "earnings"][:6]
    anal = [a for a in ins if a.get("type") == "analysis"][:8]
    opin = [a for a in ins if a.get("type") == "opinion"][:3]
    earn_html = (f'<section class="band earn"><div class="wrap"><div class="hd" style="--c:var(--red)"><span style="color:var(--red)">Earnings analysis</span>'
                 f'<a href="/insights?type=earnings">All earnings analysis →</a></div><div class="ig e3">'
                 f'{icard(earn[0], True)}{"".join(icard(a) for a in earn[1:3])}</div>'
                 + (f'<div class="ig" style="margin-top:26px">{"".join(icard(a) for a in earn[3:6])}</div>' if len(earn) > 3 else "")
                 + '</div></section>') if earn else ""
    op_html = (f'<section class="band"><div class="wrap"><div class="hd" style="--c:#4338ca"><span style="color:#4338ca">Opinion · CompePharma View</span>'
               f'<a href="/insights?type=opinion">All opinion →</a></div><div class="opn">'
               + "".join(f'<article class="op"><span class="kk">CompePharma View</span><h3><a href="/insights/{_e(a["slug"])}">{_e(a["title"])}</a></h3>'
                         f'<p>{_e(a.get("dek"))}</p><div class="by">{_e(_fmt(a.get("date", "")))}</div></article>' for a in opin)
               + '</div></div></section>') if opin else ""
    an_html = (f'<section class="band alt"><div class="wrap"><div class="hd" style="--c:var(--brand)"><span style="color:var(--brand)">Insights &amp; analysis</span>'
               f'<a href="/insights?type=analysis">All analysis →</a></div><div class="ig">{"".join(icard(a) for a in anal[:4])}</div>'
               + (f'<div class="ig" style="margin-top:26px">{"".join(icard(a) for a in anal[4:8])}</div>' if len(anal) > 4 else "")
               + '</div></section>') if anal else ""
    mods_html = (f'<section class="band"><div class="wrap"><div class="hd"><span>Sections</span></div><div class="mods">{mods}</div></div></section>') if mods else ""
    bands, bands2 = mods_html, ""
    body = f"""{_beatbar("home")}{_trending(c)}{_ticker(c)}<main>
<div class="wrap"><div class="front"><div>{hero(ld_)}<div class="hstrip">{"".join(mini(i) for i in riv[19:23])}</div></div>
<div class="sec2">{"".join(gcard(i) for i in tops[:2])}</div>
<div class="latest"><div class="hd"><span>Latest</span></div>{"".join(f'<div class="lt"><span>{_e(_fmt(i.get("date", ""))[:6])}</span>{_label(i)}<h4>{_a(i, _e(i["title"]))}</h4></div>' for i in sorted(tops[2:] + riv[:7], key=lambda x: x.get("date", ""), reverse=True)[:8])}</div></div>
</div>{_numbers(c)}{earn_html}{op_html}<div class="wrap">
<div class="cols"><div><div class="hd"><span>More top stories</span></div>{"".join(river(i) for i in riv[7:19])}</div><aside><div class="stick">{_deal_tracker(c)}{_ad_box("home")}{_nl_box("home")}{_most(c, used)}{_coming_up(c)}{_vigieye_box()}</div></aside></div></div>
{an_html}{bands}{ed_html}{_ad_banner("home-banner")}{bands2}
<div class="wrap"><div class="cols"><div><div class="hd"><span>More news</span></div>{"".join(river(i) for i in riv[23:])}</div><div></div></div></div></main>"""
    ld = [{"@context": "https://schema.org", "@type": "NewsMediaOrganization", "name": "CompePharma", "url": BASE + "/"}]
    return _page("CompePharma: pharma business news, deals, launches, pricing & manufacturing",
                 "Daily pharma business news: deals and M&A, approvals and launches, marketing, manufacturing and supply, "
                 "pricing policy, legal and earnings.", "/", body, ld=ld)


@router.get("/news/{beat}", response_class=HTMLResponse, include_in_schema=False)
def beat_page(beat: str, page: int = 1):
    if beat not in BEAT_LABEL:
        raise HTTPException(404)
    c = _load()
    rows = [i for i in c["items"] if i.get("beat") == beat]
    page = max(1, page)
    per = 30
    shown = rows[(page - 1) * per: page * per]
    lead_html = ""
    if page == 1 and shown:
        best = sorted(shown[:15], key=_score, reverse=True)[0]
        shown = [i for i in shown if i is not best]
        lead_html = f'<div style="margin:6px 0 10px">{hero(best)}</div>'
    pager = '<div class="pager">' + (f'<a href="/news/{beat}?page={page - 1}">← Newer</a>' if page > 1 else "") + \
            (f'<a href="/news/{beat}?page={page + 1}">Older →</a>' if len(rows) > page * per else "") + "</div>"
    body = f"""{_beatbar(beat)}{_ticker(c)}<div class="shead" style="--c:{BEAT_COLOR[beat]}"><div class="wrap"><h1>{_e(BEAT_LABEL[beat])}</h1>
<p>{_e(BEAT_BLURB[beat])}</p></div></div><main class="wrap">
<div class="cols" style="margin-top:28px"><div>{lead_html}{"".join(river(i) for i in shown) or '<p class="note">No stories in this section right now.</p>'}{pager}</div>{_side(c, beat)}</div></main>"""
    return _page(f"{BEAT_LABEL[beat]}: pharma industry news | CompePharma", BEAT_BLURB[beat], f"/news/{beat}", body)


_STORY: dict = {}


def _story_data(it: dict) -> dict:
    """The full article for one item, written by the shared editorial engine (cached 30 min)."""
    sid = it.get("id", "")
    k, _, nid = sid.partition("-")
    if k not in ("c", "o", "n") or not nid:
        return {}
    hit = _STORY.get(sid)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    try:
        d = _get(f"/api/story/{k}/{nid}", timeout=15)
    except Exception:
        d = hit[1] if hit else {}
    _STORY[sid] = (time.time(), d)
    if len(_STORY) > 800:
        for key in sorted(_STORY, key=lambda x: _STORY[x][0])[:200]:
            _STORY.pop(key, None)
    return d


@router.get("/story/{sid}", response_class=HTMLResponse, include_in_schema=False)
def story(sid: str):
    c = _load()
    it = next((i for i in c["items"] if _sid(i) == sid), None)
    if not it:
        raise HTTPException(404)
    st = _story_data(it)
    title = st.get("headline") or it["title"]
    body_p = st.get("body") or []
    dek = st.get("dek") or ("" if body_p else it.get("summary") or st.get("summary") or "")
    src = st.get("source_url") or it.get("source_url")      # official sources only (filtered upstream)
    src_label = "Company's press release (SEC filing)" if it["kind"] == "company" else "Official record"
    paras = "".join(f"<p>{_e(p)}</p>" for p in body_p)
    take = st.get("takeaways") or []
    take_html = (f'<div class="take"><h2>Why it matters</h2><ul>{"".join(f"<li>{_e(t)}</li>" for t in take)}</ul></div>') if take else ""
    rel = [i for i in c["items"] if i.get("beat") == it.get("beat") and i["id"] != it["id"]][:6]
    from urllib.parse import quote
    share = BASE + f"/story/{sid}"
    color = BEAT_COLOR.get(it.get("beat"), "#334155")
    body = f"""{_beatbar(it.get("beat"))}<main class="wrap"><div class="cols" style="margin-top:26px"><article class="art" style="--c:{color}">
{_label(it)}<h1>{_e(title)}</h1>{f'<p class="dek">{_e(dek)}</p>' if dek else ""}{_meta(it)}
<div class="share"><a href="https://www.linkedin.com/sharing/share-offsite/?url={quote(share)}" target="_blank" rel="noopener">Share on LinkedIn</a>
<a href="mailto:?subject={quote(title)}&body={quote(share)}">Email</a></div>
<div style="margin:20px 0 26px">{_thumb(it, "wide")}</div>
<div class="body">{paras}</div>{take_html}
{f'<p><a class="btn teal" href="{_e(src)}" target="_blank" rel="noopener">{_e(src_label)}: {_e(it.get("publisher"))} ↗</a></p>' if src else ""}
<p class="note">{"Written by CompePharma's editorial system from the company's filing; claims are the company's." if it["kind"] == "company" else "Written by CompePharma's editorial system from the official record."}
AI-assisted; check the source before acting. Not investment advice.</p>
<section style="margin-top:40px"><div class="hd" style="--c:{color}"><span>More {_e(BEAT_LABEL.get(it.get("beat"), ""))}</span><a href="/news/{_e(it.get("beat"))}">All →</a></div>
<div class="bg" style="grid-template-columns:repeat(3,minmax(0,1fr))">{"".join(gcard(i) for i in rel)}</div></section>
</article>{_side(c, "story", {it["id"]})}</div></main>"""
    ld = [{"@context": "https://schema.org", "@type": "NewsArticle", "headline": title[:110], "datePublished": it.get("date"),
           "description": (dek or (body_p[0] if body_p else ""))[:300], "isBasedOn": src,
           "image": [f"{BASE}/thumb/{it.get('beat', 'industry')}/{hashlib.sha1(it['id'].encode()).hexdigest()[:10]}.svg"],
           "publisher": {"@type": "Organization", "name": "CompePharma", "url": BASE + "/"}}]
    # the article also lives on VigiEye; point search engines at one copy
    return _page(f"{title[:90]} | CompePharma", (dek or title)[:155], f"/story/{sid}", body,
                 canonical=it.get("vigieye_url") or None, ld=ld)


_GLYPH = {
    "deals": '<path d="M-30 6 L-12 -10 L0 0 L12 -10 L30 6 M-30 6 L-14 22 M30 6 L14 22 M-6 6 L6 18" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>',
    "launches": '<path d="M0 -32 C14 -18 14 6 6 22 H-6 C-14 6 -14 -18 0 -32Z M-6 22 L-14 32 M6 22 L14 32" fill="none" stroke="#fff" stroke-width="3.5"/><circle cy="-8" r="5" fill="none" stroke="#fff" stroke-width="3"/>',
    "marketing": '<path d="M-26 -8 H-10 L18 -24 V24 L-10 8 H-26Z M24 -10 C30 -4 30 4 24 10" fill="none" stroke="#fff" stroke-width="3.5" stroke-linejoin="round"/>',
    "manufacturing": '<path d="M-30 24 V-6 L-14 4 V-6 L2 4 V-20 H14 V24 Z" fill="none" stroke="#fff" stroke-width="3.5" stroke-linejoin="round"/>',
    "pricing": '<path d="M-24 -24 H4 L28 0 L4 24 L-24 -4Z" fill="none" stroke="#fff" stroke-width="3.5" stroke-linejoin="round"/><circle cx="-12" cy="-12" r="4" fill="#fff"/>',
    "legal": '<path d="M0 -30 V26 M-22 26 H22 M-26 -18 H26 M-26 -18 L-34 2 H-18Z M26 -18 L18 2 H34Z" fill="none" stroke="#fff" stroke-width="3.5" stroke-linejoin="round"/>',
    "earnings": '<path d="M-30 22 L-12 2 L2 12 L28 -18 M14 -18 H28 V-4" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>',
    "pipeline": '<circle cx="-18" r="8" fill="none" stroke="#fff" stroke-width="3.5"/><circle cx="18" r="8" fill="none" stroke="#fff" stroke-width="3.5"/><path d="M-10 0 H10" stroke="#fff" stroke-width="3.5"/>',
    "industry": '<rect x="-24" y="-24" width="48" height="48" rx="6" fill="none" stroke="#fff" stroke-width="3.5"/><path d="M-12 0 H12 M0 -12 V12" stroke="#fff" stroke-width="3.5"/>',
}


_ART: dict = {}


def _cp_article(slug: str) -> dict | None:
    hit = _ART.get(slug)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    try:
        a = _get(f"/api/cp-article/{slug}", timeout=15)
    except Exception:
        a = hit[1] if hit else None
    if a:
        _ART[slug] = (time.time(), a)
    return a


@router.get("/insights", response_class=HTMLResponse, include_in_schema=False)
def insights(type: str = ""):
    c = _load()
    ins = [a for a in c.get("insights") or [] if not type or a.get("type") == type]
    tabs = "".join(f'<a class="btn {"" if (type == k) else "ghost"}" style="padding:8px 14px" href="/insights{("?type=" + k) if k else ""}">{_e(v)}</a>'
                   for k, v in (("", "All"), ("earnings", "Earnings analysis"), ("analysis", "Analysis"), ("opinion", "Opinion")))
    grid = "".join(icard(a, i == 0) for i, a in enumerate(ins[:60])) or '<p class="note">The first pieces are being written.</p>'
    body = f"""{_beatbar("insights")}<div class="shead" style="--c:#d7263d"><div class="wrap"><h1>Insights &amp; opinion</h1>
<p>Earnings analysis of drugmakers' quarterly results, in-depth business analysis and the CompePharma View, ten new pieces every day.</p>
<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px">{tabs}</div></div></div>
<main class="wrap"><div class="cols" style="margin-top:28px"><div class="ig" style="grid-template-columns:repeat(2,minmax(0,1fr))">{grid}</div>{_side(c, "insights")}</div></main>"""
    return _page("Pharma earnings analysis, insights & opinion | CompePharma",
                 "Earnings analysis of pharma quarterly results, business analysis and opinion from CompePharma.", "/insights", body)


@router.get("/insights/{slug}", response_class=HTMLResponse, include_in_schema=False)
def insight(slug: str):
    if not re.match(r"^[a-z0-9\-]{5,120}$", slug):
        raise HTTPException(404)
    c = _load()
    a = _cp_article(slug)
    if not a:
        raise HTTPException(404)
    k = a.get("type", "analysis")
    color = "#d7263d" if k == "earnings" else ("#4338ca" if k == "opinion" else BEAT_COLOR.get(a.get("beat"), "#0e9c8a"))
    figs = "".join(f'<div><b>{_e(f.get("value"))}</b><span>{_e(f.get("label"))}</span></div>' for f in a.get("figures") or [])
    secs = "".join(f'<h2 class="sh">{_e(x.get("heading"))}</h2>' + "".join(f"<p>{_e(p)}</p>" for p in x.get("paragraphs") or [])
                   for x in a.get("sections") or [])
    take = a.get("takeaways") or []
    srcs = "".join((f'<li><a href="{_e(x["url"])}" target="_blank" rel="noopener" style="color:var(--brand);font-weight:700">{_e(x.get("title"))}</a>'
                    if x.get("url") else f'<li>{_e(x.get("title"))}') + f' <span class="by">{_e(x.get("publisher"))} · {_e(_fmt(x.get("date", "")))}</span></li>'
                   for x in a.get("sources") or [])
    who = (f'<div class="co" style="font-size:14px">{_e(a.get("company"))}{(" · " + _e(a["ticker"])) if a.get("ticker") else ""}'
           f'{(" · " + _e(a["period"])) if a.get("period") else ""}</div>') if a.get("company") else ""
    more = [x for x in c.get("insights") or [] if x.get("slug") != slug and x.get("type") == k][:3]
    from urllib.parse import quote
    share = BASE + f"/insights/{slug}"
    body = f"""{_beatbar("insights")}<main class="wrap"><div class="cols" style="margin-top:26px"><article class="art" style="--c:{color}">
<span class="kk {k}">{_e(KIND_LABEL.get(k, "Analysis"))}</span>{who}<h1>{_e(a["title"])}</h1><p class="dek">{_e(a.get("dek"))}</p>
<div class="by">{_e(_fmt(a.get("date", "")))} · CompePharma editorial</div>
<div class="share"><a href="https://www.linkedin.com/sharing/share-offsite/?url={quote(share)}" target="_blank" rel="noopener">Share on LinkedIn</a>
<a href="mailto:?subject={quote(a["title"])}&body={quote(share)}">Email</a></div>
{f'<div class="statp">{figs}</div>' if figs else f'<div style="margin:20px 0 6px">{_ins_thumb(a)}</div>'}
<div class="body">{secs}</div>
{f'<div class="take"><h2>{"What to watch" if k == "earnings" else "What leaders should do"}</h2><ul>{"".join(f"<li>{_e(t)}</li>" for t in take)}</ul></div>' if take else ""}
{f'<h2 class="sh" style="font-size:18px">Sources</h2><ul class="srcs">{srcs}</ul>' if srcs else ""}
<p class="note">Written by CompePharma's editorial system (AI-assisted, model {_e(a.get("model"))}) strictly from the official material listed.
{"Earnings analysis is based on the company's results release filed with the SEC, not on the earnings call. " if k == "earnings" else ""}It can contain errors; check the sources. Not investment advice.</p>
{f'<section style="margin-top:36px"><div class="hd" style="--c:{color}"><span>More {_e(KIND_LABEL.get(k, ""))}</span><a href="/insights?type={k}">All →</a></div><div class="ig" style="grid-template-columns:repeat(3,minmax(0,1fr))">{"".join(icard(x) for x in more)}</div></section>' if more else ""}
</article>{_side(c, "insight")}</div></main>"""
    ld = [{"@context": "https://schema.org", "@type": "OpinionNewsArticle" if k == "opinion" else "AnalysisNewsArticle",
           "headline": a["title"][:110], "description": a.get("dek", ""), "datePublished": a.get("date"),
           "author": {"@type": "Organization", "name": "CompePharma editorial"},
           "publisher": {"@type": "Organization", "name": "CompePharma", "url": BASE + "/"}}]
    return _page(f"{a['title'][:90]} | CompePharma {KIND_LABEL.get(k, '')}", (a.get("dek") or a["title"])[:155], f"/insights/{slug}", body, ld=ld)


@router.get("/newsletter", response_class=HTMLResponse, include_in_schema=False)
def newsletter(ok: str = ""):
    c = _load()
    msg = {"1": "You're in. CompePharma Daily arrives every weekday morning.", "0": "That didn't work. Check the address and try again."}.get(ok, "")
    body = f"""{_beatbar("")}<div class="shead" style="--c:#0e9c8a"><div class="wrap"><h1>CompePharma Daily</h1>
<p>The business of pharma in your inbox every weekday morning: earnings analysis, deals, launches, pricing, manufacturing and the CompePharma View. Free.</p></div></div>
<main class="wrap"><div class="cols" style="margin-top:28px"><div style="max-width:620px">{f'<p class="box" style="font-weight:700">{_e(msg)}</p>' if msg else ""}
{_nl_box("newsletter-page")}<ul style="margin:10px 0 0 18px;line-height:1.9"><li>Earnings analysis of drugmakers' quarterly results</li>
<li>Top deals, launches and pricing stories</li><li>The CompePharma View opinion column</li><li>Upcoming FDA dates</li></ul></div>{_side(c, "newsletter")}</div></main>"""
    return _page("CompePharma Daily: the pharma business newsletter", "Free daily pharma business newsletter.", "/newsletter", body)


@router.post("/newsletter/subscribe", include_in_schema=False)
async def newsletter_subscribe(request: Request):
    from fastapi.responses import RedirectResponse
    form = await request.form()
    email = (form.get("email") or "").strip()
    ok = "0"
    try:
        import httpx
        r = httpx.post(VIGIEYE + "/cp/subscribe", json={"email": email, "source": f"cp:{form.get('src') or 'site'}"[:60]}, timeout=20)
        ok = "1" if r.status_code == 200 else "0"
    except Exception:
        pass
    return RedirectResponse(f"/newsletter?ok={ok}", status_code=303)


@router.get("/thumb/{beat}/{seed}.svg", include_in_schema=False)
def thumb(beat: str, seed: str):
    """Editorial illustration for a story: a duotone scene in one of five styles, varied by seed."""
    b = beat if beat in BEAT_COLOR else "industry"
    h = hashlib.sha1(seed.encode()).digest()
    col = BEAT_COLOR[b]
    style = h[0] % 5
    W, H = 640, 360
    acc = "#e4322b"
    def r(k, lo, hi):
        return lo + (h[k % 20] * 7 + k * 13) % max(1, hi - lo)
    layers = []
    # halftone dot field, fading across the frame
    for y in range(12, H, 16):
        for x in range(8 + (y // 16 % 2) * 8, W, 16):
            d = ((x - r(1, 80, 560)) ** 2 + (y - r(2, 60, 300)) ** 2) ** .5
            rad = max(0.0, 3.4 - d / 120)
            if rad > .35:
                layers.append(f'<circle cx="{x}" cy="{y}" r="{rad:.2f}" fill="#fff" fill-opacity=".16"/>')
    if style == 0:      # molecule network
        pts = [(r(3 + k * 2, 60, 580), r(4 + k * 2, 50, 310)) for k in range(9)]
        for a in range(9):
            for bb in range(a + 1, 9):
                if (pts[a][0] - pts[bb][0]) ** 2 + (pts[a][1] - pts[bb][1]) ** 2 < 210 ** 2:
                    layers.append(f'<line x1="{pts[a][0]}" y1="{pts[a][1]}" x2="{pts[bb][0]}" y2="{pts[bb][1]}" stroke="#fff" stroke-opacity=".35" stroke-width="3"/>')
        for k, (x, y) in enumerate(pts):
            rr = 10 + h[k] % 22
            fill = acc if k == h[9] % 9 else "#fff"
            layers.append(f'<circle cx="{x}" cy="{y}" r="{rr}" fill="{fill}" fill-opacity="{.95 if fill == acc else .85}"/>'
                          f'<circle cx="{x - rr * .3:.0f}" cy="{y - rr * .3:.0f}" r="{rr * .3:.0f}" fill="#fff" fill-opacity=".5"/>')
    elif style == 1:    # capsules and tablets
        for k in range(7):
            x, y, ang = r(3 + k, 40, 600), r(10 + k, 40, 320), h[k] % 180
            L = 70 + h[k + 5] % 80
            c1 = acc if k % 3 == 0 else "#fff"
            layers.append(f'<g transform="translate({x} {y}) rotate({ang})"><rect x="{-L / 2}" y="-18" width="{L}" height="36" rx="18" fill="{c1}" fill-opacity=".9"/>'
                          f'<rect x="0" y="-18" width="{L / 2}" height="36" rx="18" fill="{col}" fill-opacity=".85"/>'
                          f'<rect x="{-L / 2 + 8}" y="-12" width="{L / 2 - 14}" height="7" rx="3.5" fill="#fff" fill-opacity=".45"/></g>')
        for k in range(5):
            layers.append(f'<circle cx="{r(30 + k, 30, 610)}" cy="{r(40 + k, 30, 330)}" r="{18 + h[k + 9] % 14}" fill="#fff" fill-opacity=".8"/>')
    elif style == 2:    # market chart
        n = 18
        ys = [r(5 + k, 90, 290) for k in range(n)]
        ys = [int(sum(ys[max(0, k - 2):k + 1]) / len(ys[max(0, k - 2):k + 1])) for k in range(n)]
        pts = " ".join(f"{30 + k * 34},{y}" for k, y in enumerate(ys))
        for k, y in enumerate(ys):
            hh = 20 + h[k % 20] % 70
            layers.append(f'<rect x="{24 + k * 34}" y="{340 - hh}" width="14" height="{hh}" fill="#fff" fill-opacity=".14"/>')
        layers.append(f'<polygon points="30,340 {pts} {30 + (n - 1) * 34},340" fill="#fff" fill-opacity=".10"/>'
                      f'<polyline points="{pts}" fill="none" stroke="#fff" stroke-width="5" stroke-linejoin="round"/>'
                      f'<circle cx="{30 + (n - 1) * 34}" cy="{ys[-1]}" r="11" fill="{acc}"/><circle cx="{30 + (n - 1) * 34}" cy="{ys[-1]}" r="22" fill="none" stroke="{acc}" stroke-width="3" stroke-opacity=".6"/>')
        for g in range(1, 5):
            layers.append(f'<line x1="0" x2="{W}" y1="{g * 72}" y2="{g * 72}" stroke="#fff" stroke-opacity=".08"/>')
    elif style == 3:    # cells under the microscope
        for k in range(11):
            x, y, rr = r(3 + k, 20, 620), r(12 + k, 20, 340), 26 + h[k] % 46
            layers.append(f'<circle cx="{x}" cy="{y}" r="{rr}" fill="#fff" fill-opacity=".10" stroke="#fff" stroke-opacity=".5" stroke-width="2.5"/>'
                          f'<circle cx="{x + rr * .2:.0f}" cy="{y - rr * .15:.0f}" r="{rr * .32:.0f}" fill="{acc if k % 4 == 0 else "#fff"}" fill-opacity="{.9 if k % 4 == 0 else .55}"/>')
        layers.append(f'<circle cx="{W / 2}" cy="{H / 2}" r="230" fill="none" stroke="#000" stroke-opacity=".35" stroke-width="80"/>')
    else:               # plant and supply line
        base = 300
        for k in range(6):
            x = 30 + k * 100
            hh = 60 + h[k] % 130
            layers.append(f'<rect x="{x}" y="{base - hh}" width="80" height="{hh}" fill="#fff" fill-opacity="{.12 + (k % 3) * .08:.2f}"/>')
            for w in range(3):
                layers.append(f'<rect x="{x + 10 + w * 22}" y="{base - hh + 16}" width="12" height="12" fill="#fff" fill-opacity=".45"/>')
            if k % 2 == 0:
                sh = 40 + h[k + 6] % 60
                layers.append(f'<rect x="{x + 56}" y="{base - hh - sh}" width="14" height="{sh}" fill="#fff" fill-opacity=".3"/>'
                              f'<circle cx="{x + 63}" cy="{base - hh - sh - 14}" r="{12 + h[k] % 10}" fill="#fff" fill-opacity=".18"/>')
        layers.append(f'<rect x="0" y="{base}" width="{W}" height="10" fill="#fff" fill-opacity=".5"/>')
        for k in range(9):
            layers.append(f'<rect x="{20 + k * 70}" y="{base + 18}" width="46" height="26" rx="3" fill="{acc if k == h[3] % 9 else "#fff"}" fill-opacity=".8"/>')
    ang = h[5] % 180
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice">
<defs><linearGradient id="g" gradientTransform="rotate({ang} .5 .5)"><stop offset="0" stop-color="{col}"/><stop offset=".7" stop-color="#0b0f17"/><stop offset="1" stop-color="#05070b"/></linearGradient>
<radialGradient id="v" cx="50%" cy="45%" r="75%"><stop offset=".55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".55"/></radialGradient></defs>
<rect width="{W}" height="{H}" fill="url(#g)"/>{"".join(layers)}<rect width="{W}" height="{H}" fill="url(#v)"/>
<rect x="0" y="{H - 6}" width="{W}" height="6" fill="{acc}"/></svg>"""
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


INDEXNOW_KEY = os.getenv("INDEXNOW_KEY", "9177237c1d4269414fc9178f1355df96")


@router.get(f"/{INDEXNOW_KEY}.txt", response_class=PlainTextResponse, include_in_schema=False)
def indexnow_key():
    return INDEXNOW_KEY


@router.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots():
    return (f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /app\nSitemap: {BASE}/sitemap.xml\n"
            f"Sitemap: {BASE}/news-sitemap.xml\n")


@router.get("/news-sitemap.xml", include_in_schema=False)
def news_sitemap():
    from datetime import timedelta
    since = (date.today() - timedelta(days=2)).isoformat()
    arts = [a for a in (_load().get("insights") or []) if (a.get("date") or "") >= since]
    body = "".join(f"<url><loc>{_e(BASE)}/insights/{_e(a['slug'])}</loc><news:news><news:publication><news:name>CompePharma</news:name>"
                   f"<news:language>en</news:language></news:publication><news:publication_date>{_e(a.get('date'))}</news:publication_date>"
                   f"<news:title>{_e(a['title'])}</news:title></news:news></url>" for a in arts)
    return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                    f'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">{body}</urlset>', media_type="application/xml")


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    today = date.today().isoformat()
    urls = ["/", "/insights", "/newsletter"] + [f"/news/{k}" for k, _, _ in BEATS] + \
           [f"/insights/{a['slug']}" for a in (_load().get("insights") or [])[:200]]
    body = "".join(f"<url><loc>{_e(BASE + u)}</loc><lastmod>{today}</lastmod><changefreq>hourly</changefreq></url>" for u in urls)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
                    media_type="application/xml")
