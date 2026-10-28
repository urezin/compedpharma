"""
CompePharma News: the business of pharma.

A trade-news front end (deals, launches, marketing, manufacturing, pricing, legal, earnings,
pipeline) for pharma business readers. Its stories come from VigiEye's shared news engine
(https://vigi-eye.com/api/business-news), which collects company press releases filed with the
SEC, trade-press headlines (link-only), novel FDA/EU approvals, recalls and health-care
enforcement, and writes CompePharma's short briefs. Nothing here copies another publication:
trade-press items are headline + link to the publisher.

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


def _has_page(it: dict) -> bool:
    return it["kind"] in ("company", "approval") and bool(it.get("summary"))


def _href(it: dict) -> str:
    return f"/story/{_sid(it)}" if _has_page(it) else (it.get("source_url") or it.get("vigieye_url") or "#")


def _ext(it: dict) -> bool:
    return not _has_page(it)


def _thumb(it: dict, cls: str) -> str:
    b = it.get("beat") if it.get("beat") in BEAT_COLOR else "industry"
    seed = hashlib.sha1((it.get("id") or it.get("title", "")).encode()).hexdigest()[:10]
    return f'<img class="th {cls}" loading="lazy" alt="" src="/thumb/{b}/{seed}.svg">'


def _a(it: dict, inner: str) -> str:
    t = ' target="_blank" rel="noopener nofollow"' if _ext(it) else ""
    ext = ' <span class="ext">↗</span>' if _ext(it) and not inner.startswith("<img") else ""
    return f'<a href="{_e(_href(it))}"{t}>{inner}{ext}</a>'


def _kind(it: dict) -> str:
    return {"company": "Company release", "approval": "Approval", "press": "", "official": "Official",
            "notice": "Official"}.get(it["kind"], "")


def _label(it: dict) -> str:
    b = it.get("beat", "industry")
    k = _kind(it)
    return (f'<a class="lab" style="color:{BEAT_COLOR.get(b, "#334155")}" href="/news/{b}">{_e(BEAT_LABEL.get(b, b))}</a>'
            + (f'<span class="kd">{_e(k)}</span>' if k else ""))


def _meta(it: dict) -> str:
    pub = _e(it.get("publisher")) + (f' ({_e(it["ticker"])})' if it.get("ticker") else "")
    return f'<div class="by">{pub} · {_e(_fmt(it.get("date", "")))}</div>'


def lead(it):
    s = f'<p>{_e(it.get("summary"))}</p>' if it.get("summary") else ""
    return f'<article class="lead">{_a(it, _thumb(it, "wide"))}<div class="lb">{_label(it)}<h2>{_a(it, _e(it["title"]))}</h2>{s}{_meta(it)}</div></article>'


def mini(it):
    return f'<article class="mini">{_a(it, _thumb(it, "sq"))}<div>{_label(it)}<h3>{_a(it, _e(it["title"]))}</h3>{_meta(it)}</div></article>'


def river(it):
    s = f'<p>{_e(it.get("summary"))}</p>' if it.get("summary") else ""
    return f'<article class="river">{_a(it, _thumb(it, "rv"))}<div>{_label(it)}<h3>{_a(it, _e(it["title"]))}</h3>{s}{_meta(it)}</div></article>'


def gcard(it):
    return f'<article class="gc">{_a(it, _thumb(it, "wide"))}{_label(it)}<h3>{_a(it, _e(it["title"]))}</h3>{_meta(it)}</article>'


CSS = """
:root{--ink:#0b1220;--mut:#5b6474;--rule:#e6e8ec;--paper:#fff;--brand:#0e9c8a;--accent:#c2410c}
@media (prefers-color-scheme: dark){:root{--ink:#e6e8ec;--mut:#9aa3b2;--rule:#1d2633;--paper:#0a0f17}}
*{box-sizing:border-box;margin:0;padding:0}body{font:16px/1.55 system-ui,Segoe UI,Roboto,sans-serif;color:var(--ink);background:var(--paper)}
a{color:inherit;text-decoration:none}.wrap{max-width:1200px;margin:0 auto;padding:0 16px}
.top{background:#0b1220;color:#cbd5e1;font-size:13px}.top .wrap{display:flex;justify-content:space-between;align-items:center;height:36px;gap:12px}
.top a{color:#e2e8f0;font-weight:600;margin-left:14px}.top .app{background:var(--brand);color:#fff;padding:4px 10px;border-radius:5px}
.mast{display:flex;justify-content:space-between;align-items:flex-end;padding:22px 0 12px;border-bottom:4px solid var(--ink);gap:12px;flex-wrap:wrap}
.mast h1{font:900 44px/1 Georgia,'Times New Roman',serif;letter-spacing:-.02em}.mast h1 b{color:var(--brand)}
.mast p{color:var(--mut);font-size:14px;margin-top:6px}.mast .d{font-size:12.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--mut)}
.beats{border-bottom:1px solid var(--rule);position:sticky;top:0;background:var(--paper);z-index:5}
.beats .wrap{display:flex;overflow-x:auto;scrollbar-width:none}
.beats a{padding:12px 12px;font-weight:800;font-size:12.5px;letter-spacing:.06em;text-transform:uppercase;white-space:nowrap;border-bottom:3px solid transparent}
.beats a:hover,.beats a.on{border-bottom-color:var(--c)}
.tick{background:#f8fafc;border-bottom:1px solid var(--rule);font-size:13.5px;overflow:hidden;white-space:nowrap}
@media (prefers-color-scheme: dark){.tick{background:#0e1520}}
.tick .wrap{display:flex;gap:26px;padding-top:8px;padding-bottom:8px;overflow-x:auto;scrollbar-width:none}.tick b{color:var(--accent)}
.th{display:block;width:100%;border-radius:4px;background:#0b1220;object-fit:cover}.th.wide{aspect-ratio:16/9;height:auto}
.th.sq{width:96px;height:72px;flex:none}.th.rv{width:176px;height:108px;flex:none}@media(max-width:640px){.th.rv{width:104px;height:72px}}
.lab{font-weight:800;font-size:11.5px;text-transform:uppercase;letter-spacing:.07em}.kd{font-size:11px;color:var(--mut);margin-left:8px;text-transform:uppercase}
.by{font-size:12.5px;color:var(--mut);margin-top:4px}.ext{font-size:.75em;color:var(--mut)}
article h2 a:hover,article h3 a:hover{color:var(--brand)}
.front{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:28px;margin-top:22px}@media(max-width:900px){.front{grid-template-columns:1fr}}
.lead .lb{padding-top:12px}.lead h2{font:800 32px/1.14 Georgia,'Times New Roman',serif;margin:6px 0 8px}.lead p{font-size:16.5px;opacity:.9}
.hd{font-weight:900;font-size:13px;letter-spacing:.08em;text-transform:uppercase;border-bottom:2px solid var(--c,var(--ink));padding-bottom:6px;margin-bottom:6px;display:flex;justify-content:space-between}
.hd a{font-size:12px}
.mini{display:flex;gap:12px;padding:12px 0;border-bottom:1px solid var(--rule)}.mini:last-child{border:0}.mini h3{font-size:15.5px;line-height:1.3;margin-top:3px}
.cols{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:30px;margin-top:30px}@media(max-width:900px){.cols{grid-template-columns:1fr}}
.river{display:flex;gap:16px;padding:16px 0;border-bottom:1px solid var(--rule)}.river h3{font:800 19px/1.25 Georgia,'Times New Roman',serif;margin-top:3px}
.river p{color:var(--mut);font-size:14.5px;margin-top:5px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.row{margin-top:34px}.g4{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:20px;margin-top:10px}
@media(max-width:1000px){.g4{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:560px){.g4{grid-template-columns:1fr}}
.gc h3{font-size:16px;line-height:1.3;margin-top:4px}.gc .lab{display:inline-block;margin-top:10px}
.box{border:1px solid var(--rule);border-radius:6px;padding:14px;margin-bottom:20px}.box h2{font-weight:900;font-size:13px;letter-spacing:.08em;text-transform:uppercase;border-bottom:2px solid var(--ink);padding-bottom:6px;margin-bottom:8px}
.box li{list-style:none;padding:8px 0;border-bottom:1px solid var(--rule);font-size:14px;font-weight:600;line-height:1.35}.box li:last-child{border:0}
.btn{display:inline-block;background:var(--brand);color:#fff;padding:10px 16px;border-radius:6px;font-weight:700;font-size:14px}
.ad{position:relative;background:linear-gradient(180deg,#f0fdfa,var(--paper));border-color:#99f6e4}.ad .tag{position:absolute;top:8px;right:10px;font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:#94a3b8}
@media (prefers-color-scheme: dark){.ad{background:#062a28;border-color:#115e59}}
.ad .logo{font:900 24px Georgia,serif;color:#0d9488}.ad ul{margin:8px 0 8px 18px;font-size:13.5px}
.ve{background:#0b1626;color:#e2e8f0;border-color:#0b1626}.ve h2{color:#fff;border-color:#e2e8f0}.ve p{font-size:13.5px;color:#cbd5e1}
.cu{display:flex;gap:10px;padding:7px 0;border-bottom:1px solid var(--rule);font-size:13.5px}.cu:last-child{border:0}.cu b{flex:none;width:50px;color:var(--accent);font-size:12.5px}
.banner{display:flex;justify-content:space-between;gap:18px;align-items:center;flex-wrap:wrap;padding:20px 22px;margin-top:34px}
.article{max-width:760px}.article h1{font:800 36px/1.15 Georgia,'Times New Roman',serif;margin:10px 0}.article .sum{font-size:18px;margin:16px 0}
.note{font-size:12.5px;color:var(--mut);margin-top:14px}.pager{display:flex;gap:10px;margin:18px 0}.pager a{border:1px solid var(--rule);padding:8px 14px;border-radius:6px;font-weight:600}
footer{border-top:1px solid var(--rule);margin-top:44px;padding:22px 0;color:var(--mut);font-size:13px}footer a{color:var(--ink)}
"""


def _ad_box(place: str) -> str:
    u = f'{PQRA["cta_url"]}?utm_source=compepharma&utm_medium=house_ad&utm_campaign=pqra&utm_content={place}'
    s = f'{PQRA["site"]}?utm_source=compepharma&utm_medium=house_ad&utm_campaign=pqra&utm_content={place}'
    return (f'<aside class="box ad" aria-label="Advertisement"><span class="tag">Advertisement</span><div class="logo">PQRA</div>'
            f'<p style="font-weight:700;margin-top:6px">Regulatory, quality and pharmacovigilance consulting for the pharmaceutical industry</p>'
            f'<ul><li style="border:0;padding:2px 0;font-weight:500">Regulatory affairs &amp; market access</li>'
            f'<li style="border:0;padding:2px 0;font-weight:500">Quality management &amp; audit readiness</li>'
            f'<li style="border:0;padding:2px 0;font-weight:500">Pharmacovigilance &amp; medical information</li></ul>'
            f'<p class="by">25+ years with EOF and EMA · human and veterinary medicines</p>'
            f'<p style="margin-top:10px"><a class="btn" href="{_e(u)}" target="_blank" rel="noopener sponsored">Visit pqra.gr</a></p>'
            f'<p class="by"><a href="{_e(s)}" target="_blank" rel="noopener sponsored">pqra.gr</a> · info@pqra.gr</p></aside>')


def _ad_banner(place: str) -> str:
    u = f'{PQRA["cta_url"]}?utm_source=compepharma&utm_medium=house_ad&utm_campaign=pqra&utm_content={place}'
    return (f'<aside class="box ad banner" aria-label="Advertisement"><span class="tag">Advertisement</span><div><div class="logo">PQRA</div>'
            f'<p style="font-weight:700">Regulatory, quality and pharmacovigilance support, backed by 25+ years with EOF and EMA.</p>'
            f'<p class="by">Marketing authorisations · QMS &amp; GMP/GDP audit readiness · local PV &amp; medical information</p></div>'
            f'<a class="btn" href="{_e(u)}" target="_blank" rel="noopener sponsored">Visit pqra.gr</a></aside>')


def _vigieye_box() -> str:
    return (f'<section class="box ve"><h2>Regulatory &amp; safety news</h2><p>Pharmacovigilance, regulatory, quality and market-access '
            f'coverage with PDUFA dates and EU approvals is on our sister site VigiEye.</p>'
            f'<p style="margin-top:10px"><a class="btn" href="{VIGIEYE}/?utm_source=compepharma" target="_blank" rel="noopener">Open VigiEye</a> '
            f'<a class="btn" style="background:#334155" href="{VIGIEYE}/newsletter?utm_source=compepharma" target="_blank" rel="noopener">Daily email</a></p></section>')


def _coming_up(c: dict) -> str:
    items = c.get("ticker") or []
    if not items:
        return ""
    rows = "".join(f'<div class="cu"><b>{_e(_fmt(i["date"])[:6])}</b><div><a href="{_e(i["url"])}" target="_blank" rel="noopener">{_e(i["title"])}</a>'
                   f'<div class="by">{_e(i["label"])}</div></div></div>' for i in items[:8])
    return f'<section class="box"><h2>Coming up: FDA dates</h2>{rows}</section>'


def _heads(items: list[dict]) -> str:
    press = [i for i in items if i["kind"] == "press"][:10]
    if not press:
        return ""
    li = "".join(f'<li>{_a(i, _e(i["title"]))}<div class="by">{_e(i["publisher"])} · {_e(_fmt(i["date"]))}</div></li>' for i in press)
    return f'<section class="box"><h2>Around the trade press</h2><ul>{li}</ul><p class="by">Links open the publisher.</p></section>'


def _side(c: dict, place: str) -> str:
    return f'<aside>{_ad_box(place)}{_vigieye_box()}{_coming_up(c)}{_heads(c["items"])}</aside>'


def _beatbar(active: str = "") -> str:
    links = [f'<a class="{"on" if active == "home" else ""}" style="--c:#0b1220" href="/">Home</a>']
    links += [f'<a class="{"on" if active == k else ""}" style="--c:{c}" href="/news/{k}">{_e(v)}</a>' for k, v, c in BEATS]
    return f'<nav class="beats" aria-label="Sections"><div class="wrap">{"".join(links)}</div></nav>'


def _ticker(c: dict) -> str:
    items = c.get("ticker") or []
    if not items:
        return ""
    parts = "".join(f'<span><b>{_e(_fmt(i["date"])[:6])}</b> {_e(i["label"])}: {_e(i["title"])}</span>' for i in items[:10])
    return f'<div class="tick"><div class="wrap">{parts}</div></div>'


def _page(title: str, desc: str, path: str, body: str, canonical: str | None = None, ld: list | None = None) -> HTMLResponse:
    can = canonical or (BASE + path)
    lds = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in (ld or []))
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title><meta name="description" content="{_e(desc)}"><link rel="canonical" href="{_e(can)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="CompePharma"><meta property="og:title" content="{_e(title)}">
<meta property="og:description" content="{_e(desc)}"><meta property="og:url" content="{_e(can)}"><meta name="twitter:card" content="summary_large_image">
<style>{CSS}</style>{lds}</head><body>
<div class="top"><div class="wrap"><span>The business of pharma · {_e(date.today().strftime("%A %d %B %Y"))}</span>
<span><a href="{VIGIEYE}/?utm_source=compepharma" target="_blank" rel="noopener">VigiEye regulatory news</a><a class="app" href="/app">CompePharma CRM &amp; HR</a></span></div></div>
{body}
<footer><div class="wrap"><b>CompePharma</b> · the business of pharma. Briefs are written by our editorial system from company press releases
filed with the SEC and official FDA/EU records; trade-press headlines link to the publisher. Not investment advice.
· <a href="/">Home</a> · {" · ".join(f'<a href="/news/{k}">{_e(v)}</a>' for k, v, _ in BEATS)} · <a href="/app">CRM &amp; HR app</a>
· <a href="{VIGIEYE}/" target="_blank" rel="noopener">VigiEye</a></div></footer></body></html>""")


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
        body = f'{_beatbar("home")}<main class="wrap"><div class="mast"><div><h1>Compe<b>Pharma</b></h1></div></div><p class="note">The news desk is warming up. Refresh in a minute.</p></main>'
        return _page("CompePharma: the business of pharma", "Pharma business news.", "/", body)
    ranked = sorted(items[:120], key=_score, reverse=True)
    ld_ = ranked[0]
    tops = [i for i in ranked[1:] if i.get("beat") != ld_.get("beat")][:4] or ranked[1:5]
    used = {ld_["id"]} | {i["id"] for i in tops}
    riv = [i for i in items if i["id"] not in used][:30]
    used |= {i["id"] for i in riv}

    def row(k):
        rs = [i for i in items if i.get("beat") == k and i["id"] not in used][:4]
        if len(rs) < 2:
            return ""
        used.update(i["id"] for i in rs)
        return (f'<section class="row" style="--c:{BEAT_COLOR[k]}"><div class="hd"><span style="color:{BEAT_COLOR[k]}">{_e(BEAT_LABEL[k])}</span>'
                f'<a href="/news/{k}">More →</a></div><div class="g4">{"".join(gcard(i) for i in rs)}</div></section>')
    ed = c.get("editorial") or []
    ed_html = ""
    if ed:
        ed_html = ('<section class="box ve" style="margin-top:28px"><h2>Analysis from VigiEye</h2><ul>'
                   + "".join(f'<li style="border-color:#1e2d44"><a href="{_e(a["url"])}" target="_blank" rel="noopener" style="color:#fff">{_e(a["title"])}</a>'
                             f'<div class="by" style="color:#94a3b8">{_e("Opinion" if a.get("type") == "opinion" else "Analysis")} · {_e(_fmt(a.get("date", "")))}</div></li>' for a in ed[:4])
                   + "</ul></section>")
    rows_html = "".join(row(k) for k in ("deals", "launches", "marketing"))
    rows_html += _ad_banner("home-banner") + "".join(row(k) for k in ("manufacturing", "pricing", "legal", "earnings", "pipeline"))
    body = f"""{_beatbar("home")}{_ticker(c)}<main class="wrap">
<div class="mast"><div><h1>Compe<b>Pharma</b></h1><p>Deals, launches, marketing, manufacturing, pricing and legal news from the pharma industry, every day.</p></div>
<div class="d">{_e(date.today().strftime("%A %d %B %Y"))}</div></div>
<div class="front"><div>{lead(ld_)}</div><div><div class="hd">Top stories</div>{"".join(mini(i) for i in tops)}{ed_html}</div></div>
<div class="cols"><div><div class="hd">Latest</div>{"".join(river(i) for i in riv)}</div>{_side(c, "home")}</div>
{rows_html}</main>"""
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
        lead_html = f'<div style="margin:18px 0">{lead(best)}</div>'
    pager = '<div class="pager">' + (f'<a href="/news/{beat}?page={page - 1}">← Newer</a>' if page > 1 else "") + \
            (f'<a href="/news/{beat}?page={page + 1}">Older →</a>' if len(rows) > page * per else "") + "</div>"
    body = f"""{_beatbar(beat)}{_ticker(c)}<main class="wrap"><div class="mast"><div><h1 style="font-size:36px;color:{BEAT_COLOR[beat]}">{_e(BEAT_LABEL[beat])}</h1>
<p>{_e(BEAT_BLURB[beat])}</p></div><div class="d">{_e(date.today().strftime("%d %B %Y"))}</div></div>
<div class="cols"><div>{lead_html}{"".join(river(i) for i in shown) or '<p class="note">No stories in this section right now.</p>'}{pager}</div>{_side(c, beat)}</div></main>"""
    return _page(f"{BEAT_LABEL[beat]}: pharma industry news | CompePharma", BEAT_BLURB[beat], f"/news/{beat}", body)


@router.get("/story/{sid}", response_class=HTMLResponse, include_in_schema=False)
def story(sid: str):
    c = _load()
    it = next((i for i in c["items"] if _sid(i) == sid), None)
    if not it or not _has_page(it):
        raise HTTPException(404)
    rel = [i for i in c["items"] if i.get("beat") == it.get("beat") and i["id"] != it["id"]][:6]
    src = it.get("source_url")
    src_label = "Read the company's press release (SEC filing)" if it["kind"] == "company" else "Open the official record"
    body = f"""{_beatbar(it.get("beat"))}<main class="wrap"><div class="cols"><article class="article">
<div style="margin-top:16px">{_label(it)}</div><h1>{_e(it["title"])}</h1>{_meta(it)}
<div style="margin:18px 0">{_thumb(it, "wide")}</div><p class="sum">{_e(it.get("summary"))}</p>
{f'<p><a class="btn" href="{_e(src)}" target="_blank" rel="noopener">{_e(src_label)} ↗</a></p>' if src else ""}
<p class="note">{"Brief written by our editorial system from the company's own press release; claims are the company's." if it["kind"] == "company" else "From the official regulator record."}
AI-assisted; check the source before acting. Not investment advice.</p>
<div class="row" style="--c:{BEAT_COLOR.get(it.get("beat"))}"><div class="hd"><span>More {_e(BEAT_LABEL.get(it.get("beat"), ""))}</span><a href="/news/{_e(it.get("beat"))}">All →</a></div>
<div class="g4" style="grid-template-columns:repeat(3,minmax(0,1fr))">{"".join(gcard(i) for i in rel)}</div></div>
</article>{_side(c, "story")}</div></main>"""
    ld = [{"@context": "https://schema.org", "@type": "NewsArticle", "headline": it["title"][:110], "datePublished": it.get("date"),
           "description": (it.get("summary") or "")[:300], "isBasedOn": src,
           "publisher": {"@type": "Organization", "name": "CompePharma", "url": BASE + "/"}}]
    # the brief also lives on VigiEye; point search engines at one copy
    return _page(f"{it['title'][:90]} | CompePharma", (it.get("summary") or it["title"])[:155], f"/story/{sid}", body,
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
    rings = "".join(f'<circle cx="{(h[i] * 3) % 640}" cy="{(h[i + 1] * 2) % 360}" r="{30 + h[i + 2] % 120}" fill="none" '
                    f'stroke="#fff" stroke-opacity=".08" stroke-width="{2 + h[i] % 6}"/>' for i in range(0, 15, 3))
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360" preserveAspectRatio="xMidYMid slice">
<defs><linearGradient id="g" gradientTransform="rotate({h[5] % 180} .5 .5)"><stop offset="0" stop-color="{BEAT_COLOR[b]}"/><stop offset="1" stop-color="#0b1220"/></linearGradient></defs>
<rect width="640" height="360" fill="url(#g)"/>{rings}<g transform="translate(320 175) scale(2.3)">{_GLYPH[b]}</g>
<text x="24" y="336" font-family="Georgia,serif" font-size="22" font-weight="700" fill="#fff" opacity=".85">CompePharma · {_e(BEAT_LABEL[b])}</text></svg>"""
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
