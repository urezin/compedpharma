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

from fastapi import APIRouter, HTTPException
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

_cache: dict = {"t": 0.0, "items": [], "editorial": [], "ticker": [], "error": None}
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
    return f'<img class="th {cls}" loading="lazy" alt="" src="/thumb/{b}/{seed}.svg">'


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
footer{background:#060d1c;color:#9eabc2;margin-top:56px;padding:44px 0 28px;font-size:14px}
footer .fg{display:grid;grid-template-columns:1.4fr repeat(3,1fr);gap:30px}@media(max-width:800px){footer .fg{grid-template-columns:1fr 1fr}}
footer h4{color:#fff;font-size:12px;letter-spacing:.12em;text-transform:uppercase;margin-bottom:10px}footer li{list-style:none;margin:6px 0}
footer a:hover{color:#fff}footer .logo{font-size:32px;color:#fff}footer .fine{border-top:1px solid #1b2840;margin-top:30px;padding-top:18px;font-size:12.5px}
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
    return f'<aside><div class="stick">{_ad_box(place) if ad else ""}{_most(c, exclude)}{_coming_up(c)}{_vigieye_box()}</div></aside>'


def _beatbar(active: str = "") -> str:
    links = [f'<a class="{"on" if active == "home" else ""}" href="/">Home</a>']
    links += [f'<a class="{"on" if active == k else ""}" style="--c:{c}" href="/news/{k}">{_e(v)}</a>' for k, v, c in BEATS]
    return f'<nav class="beats" aria-label="Sections"><div class="wrap">{"".join(links)}</div></nav>'


def _ticker(c: dict) -> str:
    items = (c.get("ticker") or [])[:12]
    if not items:
        return ""
    parts = "".join(f'<a href="{_e(i["url"])}"><b>{_e(_fmt(i["date"])[:6])}</b>{_e(i["label"])}: {_e(i["title"])}</a>' for i in items)
    return f'<div class="tick"><div class="wrap"><span class="tl">Coming up</span><div class="tr"><div class="tm">{parts}{parts}</div></div></div></div>'


def _mast() -> str:
    return (f'<header class="mast"><div class="wrap"><div><a href="/" class="logo">Compe<b>Pharma</b></a>'
            f'<div class="tag">The business of pharma: deals, launches, pricing, manufacturing and legal, every day.</div></div>'
            f'<div class="cta"><a class="btn ghost" href="/news/deals">Deals</a><a class="btn" href="{VIGIEYE}/newsletter?utm_source=compepharma">Subscribe free</a></div></div></header>')


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
    riv = [i for i in items if i["id"] not in used][:24]
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
        ed_html = ('<section class="dark"><div class="wrap"><div class="hd"><span>Analysis &amp; opinion</span>'
                   f'<a href="{VIGIEYE}/analysis" style="color:#9fb0c9">All analysis →</a></div><div class="eds">'
                   + "".join(f'<article class="ed"><div class="k">{_e("Opinion" if a.get("type") == "opinion" else "Analysis")}</div>'
                             f'<h3><a href="{_e(a["url"])}">{_e(a["title"])}</a></h3><p>{_e(a.get("dek") or "")}</p>'
                             f'<div class="by" style="color:#7f8ea8">{_e(_fmt(a.get("date", "")))}</div></article>' for a in ed[:4])
                   + "</div></div></section>")
    bands = "".join(band(k, n % 2 == 0) for n, k in enumerate(("deals", "launches", "marketing")))
    bands2 = "".join(band(k, n % 2 == 0) for n, k in enumerate(("manufacturing", "pricing", "legal", "earnings", "pipeline")))
    body = f"""{_beatbar("home")}{_ticker(c)}<main>
<div class="wrap"><div class="front"><div>{hero(ld_)}</div>
<div><div class="hd"><span>Top stories</span></div>{"".join(mini(i) for i in tops)}</div>
<div class="adcol">{_ad_box("home-top")}</div></div>
<div class="cols"><div><div class="hd"><span>Latest news</span></div>{"".join(river(i) for i in riv[:12])}</div>{_side(c, "home", used, ad=False)}</div></div>
{bands}{ed_html}{_ad_banner("home-banner")}{bands2}
<div class="wrap"><div class="cols"><div><div class="hd"><span>More news</span></div>{"".join(river(i) for i in riv[12:])}</div><div></div></div></div></main>"""
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


@router.get("/thumb/{beat}/{seed}.svg", include_in_schema=False)
def thumb(beat: str, seed: str):
    b = beat if beat in BEAT_COLOR else "industry"
    h = hashlib.sha1(seed.encode()).digest()
    col = BEAT_COLOR[b]
    rings = "".join(f'<circle cx="{(h[i] * 3) % 640}" cy="{(h[i + 1] * 2) % 360}" r="{40 + h[i + 2] % 140}" fill="none" '
                    f'stroke="#fff" stroke-opacity=".07" stroke-width="{2 + h[i] % 8}"/>' for i in range(0, 12, 3))
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="1.6" fill="#fff" fill-opacity=".14"/>'
                   for x in range(20 + h[13] % 20, 640, 28) for y in range(18, 360, 28) if (x * 7 + y * 3 + h[14]) % 5 == 0)
    bars = "".join(f'<rect x="{430 + k * 26}" y="{300 - (20 + h[k] % 120)}" width="16" height="{20 + h[k] % 120}" rx="2" fill="#fff" fill-opacity=".10"/>'
                   for k in range(7))
    ang = h[5] % 180
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360" preserveAspectRatio="xMidYMid slice">
<defs><linearGradient id="g" gradientTransform="rotate({ang} .5 .5)"><stop offset="0" stop-color="{col}"/><stop offset=".65" stop-color="#0a1730"/><stop offset="1" stop-color="#050b18"/></linearGradient>
<radialGradient id="r" cx="{20 + h[6] % 60}%" cy="{20 + h[7] % 50}%" r="60%"><stop offset="0" stop-color="#fff" stop-opacity=".22"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient></defs>
<rect width="640" height="360" fill="url(#g)"/><rect width="640" height="360" fill="url(#r)"/>{dots}{rings}{bars}
<path d="M0 {250 + h[8] % 60} C 160 {200 + h[9] % 80}, 320 {300 - h[10] % 60}, 640 {220 + h[11] % 70}" fill="none" stroke="#fff" stroke-opacity=".18" stroke-width="3"/>
<g transform="translate(320 168) scale(2.4)"><circle r="46" fill="#fff" fill-opacity=".08"/>{_GLYPH[b]}</g>
<rect x="0" y="0" width="8" height="360" fill="{col}"/>
<text x="26" y="334" font-family="Inter,Arial,sans-serif" font-size="19" font-weight="800" letter-spacing="2" fill="#fff" opacity=".9">COMPEPHARMA · {_e(BEAT_LABEL[b].upper())}</text></svg>"""
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=604800, immutable"})


@router.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots():
    return f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /app\nSitemap: {BASE}/sitemap.xml\n"


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    today = date.today().isoformat()
    urls = ["/"] + [f"/news/{k}" for k, _, _ in BEATS]
    body = "".join(f"<url><loc>{_e(BASE + u)}</loc><lastmod>{today}</lastmod><changefreq>hourly</changefreq></url>" for u in urls)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
                    media_type="application/xml")
