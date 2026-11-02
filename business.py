"""
CompePharma for business: the enterprise sales page and the 5-year market-analysis service.

  /enterprise                      what CompePharma offers companies: market analysis, the Business
                                   Suite (CRM, HR, Recruiting, Document Center), enterprise licence
  /market-analysis                 ready-to-go and custom 5-year market analyses, with a searchable
                                   catalogue of every product in the EU + US drug database
  POST /enterprise/enquiry         } both forward to VigiEye's /cp/enquiry, which stores the enquiry
  POST /market-analysis/order      } and e-mails it to the owner

The product catalogue comes from VigiEye (/api/cp-products): every EU-authorised medicine in the
EMA register and every FDA approval VigiEye has ingested.
"""
from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from portal import VIGIEYE, _beatbar, _e, _page
import main as _main

router = APIRouter()

# Prices shown on the pages (EUR, excl. VAT). Change here.
PRICE_STANDARD = "€1,250"
PRICE_CUSTOM = "from €4,500"
PRICE_PACK = "€4,950"
DELIVERY_STANDARD = "5 business days"

Y0 = date.today().year + 1
HORIZON = f"{Y0}–{Y0 + 4}"

KINDS = [("report-standard", f"Ready-to-go 5-year analysis ({PRICE_STANDARD} per product)"),
         ("report-pack", f"Portfolio pack: 5 products ({PRICE_PACK})"),
         ("report-custom", f"Custom analysis ({PRICE_CUSTOM})")]

CSS = """
.bz-hero{background:#000;color:#fff;padding:54px 0 50px;border-bottom:1px solid #222}
.bz-hero .k{font-size:12px;font-weight:900;letter-spacing:.16em;text-transform:uppercase;color:var(--red)}
.bz-hero h1{font:900 52px/1.04 var(--sans);letter-spacing:-.035em;max-width:900px;margin-top:12px}
.bz-hero p.sub{font-size:19px;color:#bfc6d2;max-width:760px;margin-top:16px;font-family:var(--serif)}
.bz-hero .row{display:flex;gap:10px;flex-wrap:wrap;margin-top:26px}.bz-hero .btn.ghost{color:#fff;border-color:#fff}
@media(max-width:700px){.bz-hero h1{font-size:32px}.bz-hero p.sub{font-size:16px}}
.bz-sec{padding:46px 0 10px}.bz-sec h2.t{font:900 32px/1.12 var(--sans);letter-spacing:-.025em;max-width:780px;margin-top:8px}
.bz-sec .k{font-size:12px;font-weight:900;letter-spacing:.14em;text-transform:uppercase;color:var(--red)}
.bz-sec p.lede{color:var(--mut);font-size:17px;max-width:760px;margin-top:10px}
.bz-g3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px;margin-top:24px}
.bz-g4{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;margin-top:24px}
@media(max-width:1000px){.bz-g3,.bz-g4{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:640px){.bz-g3,.bz-g4{grid-template-columns:1fr}}
.bz-card{border:1px solid var(--rule);border-top:4px solid var(--ink);padding:20px;background:var(--paper);display:flex;flex-direction:column}
.bz-card h3{font:800 19px/1.25 var(--sans);letter-spacing:-.01em}.bz-card p{color:var(--mut);font-size:14.5px;margin-top:8px}
.bz-card ul{margin:12px 0 0 18px;font-size:14.5px}.bz-card li{margin:5px 0}
.bz-card .pr{font:900 30px/1 var(--sans);letter-spacing:-.03em;margin-top:14px}.bz-card .pr small{font-size:13px;font-weight:600;color:var(--mut);letter-spacing:0}
.bz-card .go{margin-top:auto;padding-top:18px}
.bz-card.hl{border-top-color:var(--red);box-shadow:0 10px 30px rgba(0,0,0,.08)}
.bz-num{border-top:3px solid var(--red);padding-top:10px}.bz-num b{display:block;font:900 34px/1 var(--sans);letter-spacing:-.03em}
.bz-num span{font-size:13px;color:var(--mut)}
.bz-toc{counter-reset:s;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 34px;margin-top:20px}
@media(max-width:760px){.bz-toc{grid-template-columns:1fr}}
.bz-toc li{list-style:none;display:flex;gap:14px;padding:14px 0;border-bottom:1px solid var(--rule)}
.bz-toc li:before{counter-increment:s;content:counter(s,decimal-leading-zero);font:900 20px/1.2 var(--sans);color:var(--red);min-width:30px}
.bz-toc b{display:block;font-size:15.5px}.bz-toc span{color:var(--mut);font-size:14px}
.bz-form{border:1px solid var(--rule);border-top:4px solid var(--red);padding:22px;background:var(--tint);max-width:860px}
.bz-form .fg{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:640px){.bz-form .fg{grid-template-columns:1fr}}
.bz-form label{display:block;font-size:12.5px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:var(--mut);margin-bottom:5px}
.bz-form input,.bz-form select,.bz-form textarea{width:100%;padding:11px 12px;border:1px solid var(--rule);border-radius:3px;font:inherit;background:var(--paper);color:var(--ink)}
.bz-form textarea{min-height:110px;resize:vertical}.bz-form .full{grid-column:1/-1}.bz-form .hp{position:absolute;left:-9999px}
.bz-ok{border-left:4px solid var(--brand);background:var(--tint);padding:14px 18px;margin-bottom:16px;font-weight:700}
.bz-err{border-left:4px solid var(--red);background:var(--tint);padding:14px 18px;margin-bottom:16px;font-weight:700}
.bz-cat form.s{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 6px}
.bz-cat form.s input{flex:1;min-width:220px;padding:11px 12px;border:1px solid var(--rule);border-radius:3px;font:inherit;background:var(--paper);color:var(--ink)}
.bz-cat form.s select{max-width:100%;min-width:0;padding:11px;border:1px solid var(--rule);border-radius:3px;background:var(--paper);color:var(--ink);font:inherit}
.bz-tbl{width:100%;border-collapse:collapse;font-size:14px;margin-top:10px}
.bz-tbl th{font-size:11.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--mut);text-align:left;padding:10px 8px;border-bottom:2px solid var(--ink)}
.bz-tbl td{padding:11px 8px;border-bottom:1px solid var(--rule);vertical-align:top}.bz-tbl td b{font-size:15px}
.bz-tbl td small{color:var(--mut)}.bz-tbl .tg{display:inline-block;font-size:10.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;border:1px solid var(--rule);padding:1px 6px;margin:3px 4px 0 0;color:var(--mut)}
.bz-tbl .ob{white-space:nowrap;font-weight:800;color:var(--red);font-size:13px}.bz-tbl .ob:hover{text-decoration:underline}
@media(max-width:760px){.bz-tbl .hm{display:none}}
.bz-cta{background:#000;color:#fff;margin-top:50px;padding:40px 0}.bz-cta .wrap{display:flex;justify-content:space-between;gap:20px;align-items:center;flex-wrap:wrap}
.bz-cta h2{font:900 28px/1.15 var(--sans);letter-spacing:-.02em;max-width:720px}.bz-cta p{color:#bfc6d2;margin-top:8px}
"""


def _fmt_money(cents: int) -> str:
    return f"${cents / 100:,.0f}"


def _vg(path: str, params: dict | None = None, timeout: float = 15):
    import httpx
    r = httpx.get(VIGIEYE + path, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


async def _forward(request: Request, kind_default: str, source: str) -> bool:
    form = await request.form()
    g = lambda k: (form.get(k) or "").strip()
    payload = {"kind": g("kind") or kind_default, "email": g("email"), "name": g("name"), "company": g("company"),
               "role": g("role"), "product": g("product"), "markets": g("markets"), "message": g("message"),
               "source": f"cp:{source}"[:80], "website": g("website")}
    try:
        import httpx
        r = httpx.post(VIGIEYE + "/cp/enquiry", json=payload, timeout=20)
        return r.status_code == 200
    except Exception:
        return False


def _form(action: str, kinds: list[tuple[str, str]], kind: str = "", product: str = "", product_label: str = "Product(s)",
          button: str = "Send", message_ph: str = "") -> str:
    opts = "".join(f'<option value="{k}" {"selected" if k == kind else ""}>{_e(v)}</option>' for k, v in kinds)
    kind_field = (f'<div class="full"><label for="f-kind">What you need</label><select id="f-kind" name="kind">{opts}</select></div>'
                  if len(kinds) > 1 else f'<input type="hidden" name="kind" value="{_e(kinds[0][0])}">')
    prod = (f'<div class="full"><label for="f-prod">{_e(product_label)}</label><input id="f-prod" name="product" value="{_e(product)}" '
            f'placeholder="Brand or substance, e.g. Opuviz (aflibercept), or a pipeline asset"></div>') if product_label else ""
    return f"""<form class="bz-form" method="post" action="{action}"><div class="fg">{kind_field}{prod}
<div class="full"><label for="f-mk">Markets</label><input id="f-mk" name="markets" placeholder="e.g. Greece, EU5, US, Western Balkans"></div>
<div><label for="f-name">Name</label><input id="f-name" name="name" autocomplete="name"></div>
<div><label for="f-em">Work email *</label><input id="f-em" name="email" type="email" required autocomplete="email"></div>
<div><label for="f-co">Company</label><input id="f-co" name="company" autocomplete="organization"></div>
<div><label for="f-ro">Role</label><input id="f-ro" name="role" autocomplete="organization-title"></div>
<div class="full"><label for="f-msg">Anything we should know</label><textarea id="f-msg" name="message" placeholder="{_e(message_ph)}"></textarea></div>
<input class="hp" type="text" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
<div class="full"><button class="btn" type="submit">{_e(button)}</button>
<p class="note" style="margin-top:10px">We reply from info@compepharma.com, usually within one business day. Prices exclude VAT.</p></div></div></form>"""


def _status(sent: str) -> str:
    if sent == "1":
        return '<div class="bz-ok">Thank you. We have your request and will reply within one business day.</div>'
    if sent == "0":
        return ('<div class="bz-err">That did not go through. Please try again, or e-mail '
                '<a href="mailto:info@compepharma.com" style="text-decoration:underline">info@compepharma.com</a>.</div>')
    return ""


# --- /enterprise ---------------------------------------------------------------------------

@router.get("/enterprise", response_class=HTMLResponse, include_in_schema=False)
def enterprise(sent: str = ""):
    mods = _main.MODULES
    mod_cards = "".join(
        f'<div class="bz-card"><h3>{_e(m["name"])}</h3><p>{_e(m["tagline"])}</p>'
        f'<ul>{"".join(f"<li>{_e(f)}</li>" for f in m["features"])}</ul>'
        f'<div class="pr">{_fmt_money(m["price_cents"])} <small>per month</small></div></div>' for m in mods.values())
    suite = _fmt_money(_main.SUITE_PRICE_CENTS)
    body = f"""<style>{CSS}</style>{_beatbar("")}
<section class="bz-hero"><div class="wrap"><div class="k">CompePharma Enterprise</div>
<h1>Market intelligence and business tools for pharma and biotech companies</h1>
<p class="sub">The newsroom covers the business of pharma every day. For companies, CompePharma adds 5-year market analyses on any
product, and the CRM, HR, recruiting and document tools commercial teams run on.</p>
<div class="row"><a class="btn" href="#talk">Talk to us</a><a class="btn ghost" href="/market-analysis">5-year market analysis</a></div></div></section>

<main class="wrap">
<section class="bz-sec"><div class="k">Who it is for</div><h2 class="t">Built for the people who decide where a product goes next</h2>
<div class="bz-g3">
<div class="bz-card"><h3>Pharma &amp; biotech companies</h3><p>Commercial, market access and business development teams sizing launches,
in-licensing candidates and loss-of-exclusivity risk, market by market.</p></div>
<div class="bz-card"><h3>Affiliates, distributors &amp; licensees</h3><p>Regional partners who need a defensible 5-year view of a product before
they sign for a territory, and a CRM and HR stack sized for a lean team.</p></div>
<div class="bz-card"><h3>Investors &amp; consultancies</h3><p>Funds, advisers and agencies who need a fast, sourced read on a product's market
and competitors, without commissioning a months-long study.</p></div></div></section>

<section class="bz-sec"><div class="k">Market intelligence</div><h2 class="t">5-year market analysis on any pharma or biotech product</h2>
<p class="lede">Pick any product in our EU and US catalogue for a ready-to-go report, or brief us on a custom question: a pipeline asset, a
territory, a portfolio. Every forecast covers {HORIZON} with base, low and high scenarios and the assumptions behind them.</p>
<div class="bz-g3">
<div class="bz-card"><h3>Ready-to-go</h3><p>Standard scope, fixed price, no scoping call.</p><div class="pr">{PRICE_STANDARD} <small>per product</small></div>
<p>Delivered in {DELIVERY_STANDARD}.</p><div class="go"><a class="btn" href="/market-analysis#catalogue">Browse products</a></div></div>
<div class="bz-card hl"><h3>Portfolio pack</h3><p>Five ready-to-go analyses: a therapy area, a competitor set or your own portfolio.</p>
<div class="pr">{PRICE_PACK} <small>5 products</small></div><div class="go"><a class="btn" href="/market-analysis?kind=report-pack#order">Order a pack</a></div></div>
<div class="bz-card"><h3>Custom</h3><p>Your question, your markets: pipeline assets, country deep-dives, launch sequencing, deal screening.</p>
<div class="pr">{PRICE_CUSTOM}</div><div class="go"><a class="btn ghost" href="/market-analysis?kind=report-custom#order">Brief us</a></div></div></div></section>

<section class="bz-sec"><div class="k">Business Suite</div><h2 class="t">CRM, HR, recruiting and documents, sold as modules</h2>
<p class="lede">Buy only the modules you need, or the whole Suite for {suite} a month. Sign up and start today at
<a href="/app" style="text-decoration:underline">compepharma.com/app</a>.</p>
<div class="bz-g4">{mod_cards}</div></section>

<section class="bz-sec" id="plans"><div class="k">Plans</div><h2 class="t">From one report to an organisation-wide licence</h2>
<div class="bz-g3">
<div class="bz-card"><h3>Self-serve</h3><p>For individuals and small teams.</p><ul><li>Any Business Suite module, monthly</li>
<li>Ready-to-go market analyses, per product</li><li>CompePharma Daily for everyone on the team, free</li></ul>
<div class="pr">{suite} <small>Suite per month</small></div><div class="go"><a class="btn ghost" href="/app">Start in the app</a></div></div>
<div class="bz-card hl"><h3>Company</h3><p>For commercial, BD and market access teams.</p><ul><li>Business Suite for the team</li>
<li>A yearly allowance of ready-to-go analyses at a reduced rate</li><li>Annual invoice for procurement</li></ul>
<div class="pr">Annual <small>quoted per team</small></div><div class="go"><a class="btn" href="#talk">Get a quote</a></div></div>
<div class="bz-card"><h3>Enterprise</h3><p>For pharma groups, affiliates and distributors.</p><ul><li>All users in your organisation</li>
<li>Custom analyses and refreshes on your products and markets</li><li>Onboarding and import of your existing data</li>
<li>Named contact and service levels in contract</li></ul>
<div class="pr">Custom <small>organisation-wide</small></div><div class="go"><a class="btn" href="#talk">Talk to us</a></div></div></div></section>

<section class="bz-sec" id="talk"><div class="k">Talk to us</div><h2 class="t">Tell us what you need</h2>
<p class="lede" style="margin-bottom:18px">Products, markets and team size are enough to start. We come back with a proposal.</p>
{_status(sent)}{_form("/enterprise/enquiry", [("enterprise", "Enterprise")], product="", product_label="Products or therapy areas of interest",
                      button="Send enquiry", message_ph="Team size, modules you need, products and markets you want analysed")}</section>
</main>"""
    return _page("CompePharma Enterprise: market analysis and business tools for pharma",
                 "5-year market analyses on any pharma or biotech product, plus CRM, HR, recruiting and document tools, "
                 "for pharma and biotech companies, distributors and investors.", "/enterprise", body)


@router.post("/enterprise/enquiry", include_in_schema=False)
async def enterprise_enquiry(request: Request):
    ok = await _forward(request, "enterprise", "enterprise")
    return RedirectResponse(f"/enterprise?sent={'1' if ok else '0'}#talk", status_code=303)


# --- /market-analysis --------------------------------------------------------------------------

def _catalogue(q: str, region: str, type_: str, page: int) -> tuple[str, dict]:
    per = 20
    try:
        d = _vg("/api/cp-products", {"q": q, "region": region, "type": type_, "limit": per, "offset": (page - 1) * per})
    except Exception:
        return ('<p class="note">The product catalogue is not available right now. You can still order any product with the '
                'form below: type its name.</p>', {})
    flag = {"EU": "🇪🇺 EU", "US": "🇺🇸 US"}
    rows = ""
    for it in d.get("items", []):
        label = f'{it["name"]} ({it["inn"]}), {it["region"]}' if it.get("inn") else f'{it["name"]}, {it["region"]}'
        href = "/market-analysis?" + urlencode({"product": label}) + "#order"
        tags = "".join(f'<span class="tg">{_e(t)}</span>' for t in (it.get("flags") or [])[:3])
        rows += (f'<tr><td><b>{_e(it["name"])}</b><br><small>{_e(it.get("inn"))}</small><div>{tags}</div></td>'
                 f'<td class="hm">{_e(it.get("company"))}</td><td class="hm"><small>{_e(it.get("therapeutic_area"))}</small></td>'
                 f'<td>{flag.get(it["region"], _e(it["region"]))}<br><small>{_e(it.get("date"))}</small></td>'
                 f'<td><a class="ob" href="{_e(href)}">Order →</a></td></tr>')
    total = d.get("total", 0)
    if not rows:
        table = ('<p class="note">No product matches. Order it anyway with the form below: we cover pipeline and unlisted '
                 'products as custom analyses.</p>')
    else:
        table = (f'<table class="bz-tbl"><tr><th>Product</th><th class="hm">Company</th><th class="hm">Therapeutic area</th>'
                 f'<th>Market · date</th><th></th></tr>{rows}</table>')
    pages = max(1, -(-total // per))
    nav = ""
    if pages > 1:
        mk = lambda p: "/market-analysis?" + urlencode({k: v for k, v in (("q", q), ("region", region), ("type", type_), ("page", p)) if v}) + "#catalogue"
        nav = '<div class="pager">' + (f'<a href="{_e(mk(page - 1))}">← Previous</a>' if page > 1 else "") + \
              f'<span style="align-self:center;color:var(--mut);font-size:14px">Page {page} of {pages:,}</span>' + \
              (f'<a href="{_e(mk(page + 1))}">Next →</a>' if page < pages else "") + "</div>"
    head = f'<p class="note" style="margin-top:4px">{total:,} product{"s" if total != 1 else ""} match.</p>'
    return head + table + nav, d.get("catalogue") or {}


@router.get("/market-analysis", response_class=HTMLResponse, include_in_schema=False)
def market_analysis(q: str = "", region: str = "", type: str = "", page: int = 1, product: str = "", kind: str = "",
                    sent: str = ""):
    page = max(1, min(page, 1000))
    region = region.upper() if region.upper() in ("EU", "US") else ""
    type_ = type if type in ("biosimilar", "orphan", "new") else ""
    cat_html, counts = _catalogue(q, region, type_, page)
    n_all, n_eu, n_us = counts.get("all"), counts.get("EU"), counts.get("US")
    nums = ""
    if n_all:
        nums = (f'<div class="bz-g4"><div class="bz-num"><b>{n_all:,}</b><span>products in the catalogue</span></div>'
                f'<div class="bz-num"><b>{n_eu:,}</b><span>EU-authorised medicines (EMA)</span></div>'
                f'<div class="bz-num"><b>{n_us:,}</b><span>FDA approvals</span></div>'
                f'<div class="bz-num"><b>5 yrs</b><span>forecast horizon, {HORIZON}</span></div></div>')
    sel = lambda a, b: "selected" if a == b else ""
    kind = kind if kind in dict(KINDS) else ("report-standard" if product else "report-standard")
    body = f"""<style>{CSS}</style>{_beatbar("")}
<section class="bz-hero"><div class="wrap"><div class="k">CompePharma Market Analysis</div>
<h1>5-year market analysis for any pharma or biotech product</h1>
<p class="sub">Ready-to-go reports on every product in our EU and US catalogue, and custom analyses for pipeline assets, territories
and portfolios. Revenue scenarios for {HORIZON}, with every assumption stated and every fact sourced.</p>
<div class="row"><a class="btn" href="#catalogue">Find a product</a><a class="btn ghost" href="?kind=report-custom#order">Request a custom analysis</a></div></div></section>
<main class="wrap">
<section class="bz-sec">{nums}</section>
<section class="bz-sec"><a class="bz-card hl" href="/market-analysis/top-100-drugs" style="border-top-color:var(--red);display:block">
<div class="k" style="color:var(--red);font-size:12px;font-weight:900;letter-spacing:.14em;text-transform:uppercase">Free report</div>
<h3 style="font-size:24px;margin-top:6px">The top 100 drugs: a 5-year outlook by therapeutic area, 2026–2031</h3>
<p>$546bn of 2025 sales across 12 therapy areas, projected drug by drug with patent expiries, Medicare negotiated prices and new launches.
See the method our ready-to-go reports use. <b style="color:var(--red)">Read the report →</b></p></a></section>

<section class="bz-sec"><div class="k">Two ways to buy</div><h2 class="t">Ready-to-go or built around your question</h2>
<div class="bz-g3">
<div class="bz-card hl"><h3>Ready-to-go</h3><p>The standard report below, on any product in the catalogue. Fixed scope, fixed price,
no scoping call.</p><div class="pr">{PRICE_STANDARD} <small>per product</small></div>
<ul><li>Global view plus EU5 and US detail</li><li>Base, low and high scenarios, {HORIZON}</li><li>PDF report and Excel model</li>
<li>Delivered in {DELIVERY_STANDARD}</li></ul><div class="go"><a class="btn" href="#catalogue">Choose a product</a></div></div>
<div class="bz-card"><h3>Portfolio pack</h3><p>Five ready-to-go analyses ordered together: a therapy area, a competitor set or your own
portfolio.</p><div class="pr">{PRICE_PACK} <small>5 products</small></div><ul><li>Same standard scope per product</li>
<li>One cross-product summary</li><li>Delivered in 10 business days</li></ul>
<div class="go"><a class="btn ghost" href="?kind=report-pack#order">Order a pack</a></div></div>
<div class="bz-card"><h3>Custom</h3><p>Your markets, your question. For pipeline assets not yet approved, single-country
deep-dives (Greece, Cyprus, the Balkans, any EU market), launch sequencing, in-licensing and deal screening.</p>
<div class="pr">{PRICE_CUSTOM}</div><ul><li>Scoping call and written proposal</li><li>Your own scenarios and assumptions</li>
<li>Timeline agreed in the proposal</li></ul><div class="go"><a class="btn ghost" href="?kind=report-custom#order">Brief us</a></div></div></div></section>

<section class="bz-sec"><div class="k">What is in every report</div><h2 class="t">The ready-to-go 5-year market analysis</h2>
<ol class="bz-toc">
<li><div><b>Executive summary</b><span>The 5-year outlook in one page: peak-year range, key drivers and the risks that move it.</span></div></li>
<li><div><b>Product and regulatory profile</b><span>Indications, approvals and status in the EU and US, designations, label changes and exclusivity.</span></div></li>
<li><div><b>Patient population</b><span>Prevalence, diagnosed and treated patients by market, from published epidemiology.</span></div></li>
<li><div><b>Treatment landscape</b><span>Standard of care, guidelines and where the product sits in the treatment pathway.</span></div></li>
<li><div><b>Competition</b><span>Marketed competitors, late-stage pipeline, biosimilar and generic entry, and loss-of-exclusivity timing.</span></div></li>
<li><div><b>Pricing and access</b><span>List-price and reimbursement context, HTA outcomes and access barriers by market.</span></div></li>
<li><div><b>5-year revenue scenarios</b><span>Base, low and high cases for {HORIZON} by region, with uptake, share and price assumptions set out.</span></div></li>
<li><div><b>Risks and catalysts</b><span>Upcoming readouts, regulatory dates, patent events and policy changes that could change the forecast.</span></div></li>
</ol>
<p class="note">Sources: official regulator records (EMA, European Commission, FDA), company filings and reports, published literature
and HTA decisions; each fact is referenced. Forecasts are modelled scenarios built on stated assumptions, not guarantees. Not investment advice.</p></section>

<section class="bz-sec bz-cat" id="catalogue"><div class="k">Catalogue</div><h2 class="t">Find your product</h2>
<p class="lede">Every EU-authorised medicine in the EMA register and every FDA approval in our database. Not listed? Order it anyway:
pipeline and unlisted products are covered as custom analyses.</p>
<form class="s" method="get" action="/market-analysis#catalogue"><input name="q" value="{_e(q)}" placeholder="Brand, substance, company or therapy area" aria-label="Search products">
<select name="region" aria-label="Market"><option value="">EU + US</option><option value="EU" {sel(region, "EU")}>EU</option><option value="US" {sel(region, "US")}>US</option></select>
<select name="type" aria-label="Type"><option value="">All products</option><option value="biosimilar" {sel(type_, "biosimilar")}>Biosimilars</option>
<option value="orphan" {sel(type_, "orphan")}>Orphan medicines</option><option value="new" {sel(type_, "new")}>Innovative medicines</option></select>
<button class="btn" type="submit">Search</button></form>{cat_html}</section>

<section class="bz-sec" id="order"><div class="k">Order</div><h2 class="t">Order a report or brief us</h2>
<p class="lede" style="margin-bottom:18px">We confirm scope and send the invoice by e-mail; work starts on confirmation.</p>
{_status(sent)}{_form("/market-analysis/order", KINDS, kind=kind, product=product, button="Send order",
                      message_ph="Markets that matter most, deadline, the decision this analysis supports")}</section>
</main>
<section class="bz-cta"><div class="wrap"><div><h2>Need analyses across a portfolio, every year?</h2>
<p>Company and enterprise plans include a yearly allowance of analyses and refreshes.</p></div>
<a class="btn" href="/enterprise#plans">See enterprise plans</a></div></section>"""
    return _page(f"5-Year Pharma & Biotech Market Analysis, {HORIZON} | CompePharma",
                 f"Ready-to-go and custom 5-year market analyses ({HORIZON}) for any pharma or biotech product: "
                 "patient population, competition, pricing and revenue scenarios, sourced.", "/market-analysis", body)


@router.post("/market-analysis/order", include_in_schema=False)
async def market_analysis_order(request: Request):
    ok = await _forward(request, "report-standard", "market-analysis")
    return RedirectResponse(f"/market-analysis?sent={'1' if ok else '0'}#order", status_code=303)
