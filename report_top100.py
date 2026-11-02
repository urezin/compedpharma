"""
CompePharma flagship report: the therapeutic areas of the 100 best-selling drugs, 5-year outlook.

  /market-analysis/top-100-drugs        the report page (data: reports/top100_2025.json,
                                        built by reports/top100_model.py from reports/top100_sales_*.csv)
  /market-analysis/top-100-drugs.csv    the top-100 list with 2025 sales and 2026-2031 scenarios
"""
from __future__ import annotations

import csv
import io
import json
import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

from portal import _beatbar, _e, _page
from business import CSS as BZ_CSS

router = APIRouter()
_HERE = os.path.dirname(os.path.abspath(__file__))
PATH = "/market-analysis/top-100-drugs"
PUBLISHED = "2 November 2026"


def _data() -> dict:
    with open(os.path.join(_HERE, "reports", "top100_2025.json")) as f:
        return json.load(f)


SLUG = {"Oncology": "oncology", "Immunology & inflammation": "immunology", "Diabetes & obesity": "diabetes-obesity",
        "Cardiovascular & renal": "cardiovascular", "Neurology": "neurology", "Vaccines": "vaccines",
        "Infectious disease & HIV": "infectious-hiv", "Respiratory": "respiratory", "Rare disease": "rare-disease",
        "Ophthalmology": "ophthalmology", "Bone & other": "bone-other", "Haematology": "haematology"}
COLOR = {"Oncology": "#e4322b", "Immunology & inflammation": "#7c3aed", "Diabetes & obesity": "#0e9c8a",
         "Cardiovascular & renal": "#b45309", "Neurology": "#2563eb", "Vaccines": "#0891b2",
         "Infectious disease & HIV": "#be185d", "Respiratory": "#4d7c0f", "Rare disease": "#9333ea",
         "Ophthalmology": "#0f766e", "Bone & other": "#64748b", "Haematology": "#c2410c"}

# CompePharma's reading of each area. Facts carry their source in SOURCES below.
NARR = {
 "Oncology": {
  "verdict": "Flat as a group: the largest franchises lose exclusivity just as the next wave launches.",
  "points": [
   "Keytruda, Opdivo and Darzalex face US biosimilars between December 2028 and 2029; Keytruda's subcutaneous Qlex (close to 10% of Keytruda sales by Q3 2026) is the main cushion.",
   "Xtandi and Ibrance lose US exclusivity in 2027, the same year their Medicare negotiated prices start (about 48% and 50% below list).",
   "Growth comes from ADCs (Enhertu, Padcev, Datroway), radioligands (Pluvicto), CAR-T (Carvykti) and BTK share shifts toward Brukinsa and Calquence.",
   "PD-(L)1xVEGF bispecifics are the swing factor: ivonescimab has a US decision due 14 November 2026.",
  ],
  "context": "IQVIA puts the whole oncology market at about $291bn in 2025, rising to about $467bn in 2030. The gap with this group is the size of the opportunity for products that are not yet blockbusters."},
 "Immunology & inflammation": {
  "verdict": "The largest growth of any area, in dollars and in rate, driven by IL-23, JAK and newer mechanisms.",
  "points": [
   "Skyrizi, Rinvoq and Tremfya keep taking share in psoriasis and inflammatory bowel disease as Stelara and Humira erode under biosimilars (Stelara -41% in its first biosimilar year).",
   "Dupixent keeps adding indications (COPD, urticaria, bullous pemphigoid); this outlook assumes US biosimilar entry only in 2031.",
   "Newer mechanisms scale fast: Vyvgart (FcRn) almost doubled in 2025 and Bimzelx (IL-17A/F) nearly quadrupled.",
   "IRA prices hit Stelara and Enbrel in 2026, Otezla in 2027, and Cosentyx, Entyvio, Orencia and Cimzia in 2028.",
  ],
  "context": "Evaluate expects immunology to grow at about 10% a year to 2032."},
 "Diabetes & obesity": {
  "verdict": "Second-largest growth: incretin volumes keep rising while prices, SGLT2 generics and semaglutide erosion hold the total back.",
  "points": [
   "Tirzepatide (Mounjaro, Zepbound) reached $36.5bn in 2025; our base case is about $72bn in 2031, in line with Evaluate's forecast of above $70bn in 2032.",
   "Semaglutide faces generics in Canada, China and India from 2026, Medicare negotiated prices from 2027 (about 71% below list) and US cash prices under the November 2025 pricing deal.",
   "SGLT2 inhibitors fall away: US generic dapagliflozin from April 2026, empagliflozin's compound patent ends in 2029, and both carry 2026 Medicare prices.",
   "Oral and next-generation incretins (Foundayo, approved April 2026; retatrutide; CagriSema) add an estimated $26bn in 2031 in the base case.",
  ],
  "context": "Morgan Stanley sizes type 2 diabetes plus obesity at $79bn in 2025 and $190bn in 2035 in its base case."},
 "Cardiovascular & renal": {
  "verdict": "The steepest decline: the anticoagulant and heart-failure era ends inside the forecast window.",
  "points": [
   "Eliquis has a 2026 Medicare price (about 56% below list), EU generics from 2026 and US generics from April 2028; it is the single largest loss in the top 100.",
   "Entresto generics launched in the US in July 2025 (Q3 2026 sales -38%), and Xarelto loses EU protection in 2026.",
   "Vyndaqel keeps US protection to mid-2031 under settlements but faces ATTR-CM competition, including Amvuttra.",
   "Growth assets are smaller: Repatha, Amvuttra, Winrevair and cardiac myosin inhibitors; an Lp(a) breakthrough is now less likely after pelacarsen missed its primary endpoint in September 2026.",
  ],
  "context": ""},
 "Neurology": {
  "verdict": "Incumbents flatten; growth depends on Alzheimer's and psychiatry launches.",
  "points": [
   "Ocrevus loses US exclusivity in March 2029; Kesimpta keeps growing in multiple sclerosis.",
   "Austedo (2027), Vraylar (2027) and Rexulti (2028) carry Medicare negotiated prices.",
   "Anti-amyloid antibodies are still small but growing: Eisai guides Leqembi to ¥250-280bn in FY2027.",
   "Cobenfy brings the first new schizophrenia mechanism in decades.",
  ],
  "context": ""},
 "Vaccines": {
  "verdict": "A stagnant area after the COVID-19 decline and Gardasil's collapse in China.",
  "points": [
   "Gardasil fell from $8.6bn to $5.2bn in 2025 on China demand; this outlook assumes a slower decline from here.",
   "Comirnaty keeps shrinking with COVID-19 vaccination rates.",
   "Prevnar is defending against Merck's Capvaxive in adults; Shingrix and Beyfortus are steadier.",
  ],
  "context": ""},
 "Infectious disease & HIV": {
  "verdict": "HIV is durable: Biktarvy is protected in the US to 2036 under settlements.",
  "points": [
   "Biktarvy carries a Medicare negotiated price from 2028, but Medicare is a small share of HIV treatment.",
   "Long-acting HIV prevention and treatment grows: Yeztugo (twice-yearly lenacapavir) launched in June 2025, Cabenuva keeps growing.",
   "Paxlovid keeps declining as COVID-19 demand fades.",
  ],
  "context": ""},
 "Respiratory": {
  "verdict": "Declining: the inhaler franchises and Xolair face generics, biosimilars and Medicare prices.",
  "points": [
   "Trelegy carries a 2027 Medicare price about 73% below list; Ofev's 2027 price is about 50% below list.",
   "Omalizumab biosimilars erode Xolair.",
   "Biologics for COPD and asthma (Nucala, Fasenra, Dupixent in COPD) and Ohtuvayre partly offset the decline.",
  ],
  "context": ""},
 "Rare disease": {
  "verdict": "Stable growth from durable franchises with long exclusivity.",
  "points": [
   "Trikafta's sales are shifting to Vertex's own once-daily Alyftrek; exclusivity runs to the late 2030s.",
   "Ultomiris keeps converting Soliris patients (Soliris faces biosimilars).",
   "Evrysdi grows in spinal muscular atrophy.",
  ],
  "context": ""},
 "Ophthalmology": {
  "verdict": "Aflibercept biosimilars split the area: Eylea shrinks, Vabysmo grows.",
  "points": [
   "Multiple aflibercept biosimilars launch in the US through Q4 2026, and EU commercialisation was allowed from 2026.",
   "Vabysmo keeps gaining share in wet AMD and diabetic macular oedema; Eylea HD partly offsets the Eylea decline.",
  ],
  "context": ""},
 "Bone & other": {
  "verdict": "Denosumab biosimilars dominate the picture.",
  "points": [
   "Prolia fell about 30% in 2026 after biosimilar launches in 2025; Evenity keeps growing.",
   "Botox Cosmetic is flat in a weaker aesthetics market.",
  ],
  "context": ""},
 "Haematology": {
  "verdict": "Steady growth from Hemlibra and Reblozyl.",
  "points": [
   "Hemlibra keeps growing in haemophilia A against gene therapy and new rebalancing agents.",
   "Reblozyl grew 31% in 2025 on first-line MDS anaemia.",
  ],
  "context": ""},
}

SOURCES = [
 ("Company FY2025 results releases and annual reports (Merck & Co, Lilly, Novo Nordisk, Sanofi, Regeneron, AbbVie, BMS, Pfizer, J&J, Roche, Novartis, AstraZeneca, GSK, Gilead, Amgen, Vertex, Takeda, Bayer, Boehringer Ingelheim, Astellas, Daiichi Sankyo, argenx, CSL, BeOne, Incyte, UCB, Neurocrine, Alnylam, Eisai, Teva, Otsuka, United Therapeutics, Biogen, Jazz, Viatris)", ""),
 ("CMS: negotiated prices effective 2026 (first cycle)", "https://www.kiplinger.com/retirement/medicare/medicare-first-negotiated-drug-prices-list"),
 ("CMS: 15 negotiated prices effective 2027", "https://www.fiercepharma.com/pharma/medicare-unveils-price-reductions-15-drugs-including-novos-semaglutide"),
 ("CMS: third-cycle drugs (prices effective 2028)", "https://www.cms.gov/newsroom/press-releases/cms-announces-selection-drugs-third-cycle-medicare-drug-price-negotiation-program-including-first"),
 ("Pfizer FY2025 10-K (Eliquis, Ibrance, Xtandi, Vyndaqel exclusivity)", "https://www.sec.gov/Archives/edgar/data/78003/000007800326000026/pfe-20251231.htm"),
 ("Lilly FY2025 10-K (Jardiance, Trulicity exclusivity)", "https://www.sec.gov/Archives/edgar/data/59478/000005947826000013/lly-20251231.htm"),
 ("Novartis Q3 2026 (Entresto generic erosion)", "https://www.sec.gov/Archives/edgar/data/0001114448/000111444826000014/a261027-99_2.htm"),
 ("Amgen Q2 2026 10-Q (denosumab biosimilar erosion)", "https://www.sec.gov/Archives/edgar/data/0000318154/000031815426000126/amgn-20260630.htm"),
 ("Gilead Biktarvy settlements (US generics 2036)", "https://www.fiercepharma.com/pharma/gilead-notches-settlements-three-generic-drugmakers-waylaying-us-biktarvy-copycats-until"),
 ("Semaglutide generics in Canada", "https://www.pearceip.law/2026/05/14/apotex-dr-reddys-launch-generic-semaglutide-in-canada/"),
 ("Aflibercept biosimilars in the US and EU", "https://www.pearceip.law/2026/08/03/biocons-yesafiliaflibercept-launches-as-second-eylea-biosimilar-on-us-market/"),
 ("IQVIA, Global Medicine Use Trends 2026", "https://www.iqvia.com/insights/the-iqvia-institute/reports-and-publications/reports/global-medicine-use-trends-2026"),
 ("Evaluate World Preview 2026", "https://www.evaluate.com/press-release/evaluate-2026-world-preview-report-pharmaceutical-market/"),
 ("Evaluate: tirzepatide above $70bn in 2032", "https://www.biospace.com/business/lillys-tirzepatide-will-be-biggest-blockbuster-ever-topping-70b-by-2032-evaluate"),
 ("Morgan Stanley: GLP-1 market to 2035", "https://www.morganstanley.com/insights/articles/glp1-weight-loss-market-may-double-190-billion-2035"),
 ("Lilly/Novo pricing agreement, Nov 2025", "https://www.biopharmadive.com/news/lilly-novo-trump-obesity-drug-pricing-deal-zepbound-wegovy/804905/"),
 ("Section 232 pharmaceutical tariffs (Apr 2026)", "https://www.mayerbrown.com/en/insights/publications/2026/04/trump-administration-implements-tariffs-on-imported-patented-medication-and-pharmaceutical-ingredients-under-section-232-of-the-trade-expansion-act-of-1962"),
 ("Pelacarsen Lp(a) HORIZON result", "https://www.hcplive.com/view/pelacarsen-misses-primary-endpoint-in-lp-a-horizon-phase-3-trial"),
]


def _b(x: float) -> str:
    return f"${x:,.1f}bn"


def _pct(x: float) -> str:
    return f"{'+' if x > 0 else ''}{x:.1f}%"


def _chart(tas: list[dict]) -> str:
    """Horizontal bars: 2025 vs 2031 base, with the 2031 low-high range as a whisker."""
    w, lab, rowh, top = 920, 210, 34, 30
    mx = max(t["total"]["high"][-1] for t in tas) * 1.04
    sx = lambda v: lab + (w - lab - 70) * v / mx
    h = top + rowh * len(tas) + 30
    g = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="2025 sales and 2031 outlook by therapeutic area" '
         f'style="width:100%;min-width:680px;height:auto;font:12px Inter,system-ui,sans-serif">']
    for v in range(0, int(mx) + 1, 50):
        x = sx(v)
        g.append(f'<line x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" y2="{h - 26}" stroke="currentColor" stroke-opacity=".12"/>'
                 f'<text x="{x:.1f}" y="{h - 10}" text-anchor="middle" fill="currentColor" fill-opacity=".6">${v}bn</text>')
    for i, t in enumerate(tas):
        y = top + i * rowh
        c = COLOR.get(t["ta"], "#334155")
        lo, base, hi = t["total"]["low"][-1], t["total"]["base"][-1], t["total"]["high"][-1]
        g.append(f'<text x="{lab - 10}" y="{y + 15}" text-anchor="end" fill="currentColor" font-weight="700">{_e(t["ta"])}</text>'
                 f'<rect x="{lab}" y="{y + 2}" width="{sx(t["s2025"]) - lab:.1f}" height="11" fill="currentColor" fill-opacity=".28"/>'
                 f'<rect x="{lab}" y="{y + 15}" width="{sx(base) - lab:.1f}" height="11" fill="{c}"/>'
                 f'<line x1="{sx(lo):.1f}" y1="{y + 20.5}" x2="{sx(hi):.1f}" y2="{y + 20.5}" stroke="currentColor" stroke-width="1.5"/>'
                 f'<line x1="{sx(lo):.1f}" y1="{y + 16}" x2="{sx(lo):.1f}" y2="{y + 25}" stroke="currentColor" stroke-width="1.5"/>'
                 f'<line x1="{sx(hi):.1f}" y1="{y + 16}" x2="{sx(hi):.1f}" y2="{y + 25}" stroke="currentColor" stroke-width="1.5"/>'
                 f'<text x="{sx(hi) + 6:.1f}" y="{y + 25}" fill="currentColor" fill-opacity=".75">{_pct(t["cagr"]["base"])}/yr</text>')
    g.append(f'<rect x="{lab}" y="6" width="12" height="9" fill="currentColor" fill-opacity=".28"/><text x="{lab + 17}" y="14" fill="currentColor">2025 sales</text>'
             f'<rect x="{lab + 100}" y="6" width="12" height="9" fill="#e4322b"/><text x="{lab + 117}" y="14" fill="currentColor">2031 base case (area colour), low–high range</text></svg>')
    return "".join(g)


def _spark(t: dict, w: int = 220, h: int = 60) -> str:
    ys = [t["s2025"]]
    ser = {s: [t["s2025"]] + t["total"][s] for s in ("low", "base", "high")}
    mx = max(ser["high"]) * 1.08
    mn = min(min(ser["low"]), t["s2025"]) * 0.9
    px = lambda i: 4 + (w - 8) * i / 6
    py = lambda v: h - 4 - (h - 8) * (v - mn) / (mx - mn or 1)
    band = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(ser["high"])) + " " + \
           " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in reversed(list(enumerate(ser["low"]))))
    line = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(ser["base"]))
    c = COLOR.get(t["ta"], "#334155")
    return (f'<svg viewBox="0 0 {w} {h}" style="width:100%;max-width:{w}px;height:auto" aria-hidden="true">'
            f'<polygon points="{band}" fill="{c}" fill-opacity=".15"/><polyline points="{line}" fill="none" stroke="{c}" stroke-width="2.5"/>'
            f'<text x="4" y="{h - 2}" font-size="9" fill="currentColor" fill-opacity=".6">2025</text>'
            f'<text x="{w - 4}" y="{h - 2}" font-size="9" text-anchor="end" fill="currentColor" fill-opacity=".6">2031</text></svg>')


def _flags(d: dict) -> str:
    out = []
    if d.get("loe_us") and d["loe_us"] >= 2026:
        out.append(f'US LOE {d["loe_us"]}')
    elif d.get("loe_us"):
        out.append("Off-patent (US)")
    if d.get("loe_x") and d["loe_x"] >= 2026 and d["loe_x"] != d.get("loe_us"):
        out.append(f'Ex-US LOE {d["loe_x"]}')
    if d.get("ira"):
        out.append(f'IRA {d["ira"][0]}')
    return "".join(f'<span class="tg">{_e(x)}</span>' for x in out)


CSS = """
.rp-kpi{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;margin-top:6px}
@media(max-width:900px){.rp-kpi{grid-template-columns:repeat(2,minmax(0,1fr))}}
.rp-find{list-style:none;margin-top:16px}.rp-find li{padding:14px 0 14px 34px;border-bottom:1px solid var(--rule);position:relative;font-size:16.5px}
.rp-find li:before{content:"";position:absolute;left:4px;top:22px;width:12px;height:12px;background:var(--red)}
.rp-chart{border:1px solid var(--rule);padding:18px;margin-top:18px;color:var(--ink);overflow-x:auto}
.rp-toc{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}.rp-toc a{border:1px solid var(--rule);padding:6px 11px;font-size:13px;font-weight:700}
.rp-toc a:hover{border-color:var(--red);color:var(--red)}
.rp-area{border-top:4px solid var(--c);padding-top:16px;margin-top:44px}
.rp-ah{display:grid;grid-template-columns:minmax(0,1fr) 240px;gap:24px;align-items:start}@media(max-width:760px){.rp-ah{grid-template-columns:1fr}}
.rp-area h3{font:900 28px/1.1 var(--sans);letter-spacing:-.02em;color:var(--c)}
.rp-area .vd{font:600 18px/1.4 var(--serif);margin-top:8px}
.rp-stats{display:flex;flex-wrap:wrap;gap:8px 22px;margin-top:12px;font-size:13.5px;color:var(--mut)}.rp-stats b{color:var(--ink);font-size:15px}
.rp-area ul.pts{margin:14px 0 0 18px}.rp-area ul.pts li{margin:7px 0;font-size:15.5px}
.rp-ctx{font-size:14px;color:var(--mut);margin-top:10px;border-left:3px solid var(--rule);padding-left:12px}
.rp-num{text-align:right;white-space:nowrap}.bz-tbl td.rp-num,.bz-tbl th.rp-num{text-align:right}
.rp-l{font-size:13.5px;margin-top:12px}.rp-l b{font-weight:800}
details.rp-all summary{cursor:pointer;font-weight:800;margin-top:14px;font-size:15px}
.rp-meth p,.rp-meth li{font-size:15px;margin-top:8px}.rp-meth ul{margin-left:18px}
.rp-src li{font-size:13.5px;padding:6px 0;border-bottom:1px solid var(--rule);list-style:none}.rp-src a{text-decoration:underline}
.rp-tblw{overflow-x:auto}@media(max-width:760px){.rp-chart{padding:10px}.bz-tbl{font-size:13px}.bz-tbl td,.bz-tbl th{padding:9px 5px}}
"""


@router.get(PATH, response_class=HTMLResponse, include_in_schema=False)
def report():
    d = _data()
    tas, drugs = d["tas"], d["drugs"]
    tot25 = sum(t["s2025"] for t in tas)
    tot31 = {s: sum(t["total"][s][-1] for t in tas) for s in ("low", "base", "high")}
    top31 = {s: sum(t["top"][s][-1] for t in tas) for s in ("low", "base", "high")}
    cagr = lambda a, b: ((b / a) ** (1 / 6) - 1) * 100
    loe = [x for x in drugs if x.get("loe_us") and 2026 <= x["loe_us"] <= 2031]
    ira = [x for x in drugs if x.get("ira")]
    n_co = len({c.strip() for x in drugs for c in x["company"].split("/")})

    rows = "".join(
        f'<tr><td><a href="#{SLUG.get(t["ta"], "")}" style="font-weight:800;color:{COLOR.get(t["ta"])}">{_e(t["ta"])}</a></td>'
        f'<td class="rp-num hm">{t["n"]}</td><td class="rp-num">{_b(t["s2025"])}</td><td class="rp-num hm">{t["s2025"] / tot25 * 100:.0f}%</td>'
        f'<td class="rp-num">{_b(t["total"]["base"][-1])}</td><td class="rp-num hm">{_b(t["total"]["low"][-1])} – {_b(t["total"]["high"][-1])}</td>'
        f'<td class="rp-num"><b>{_pct(t["cagr"]["base"])}</b></td></tr>' for t in tas)
    summary = (f'<div class="rp-tblw"><table class="bz-tbl"><tr><th>Therapeutic area</th><th class="rp-num hm">Drugs</th><th class="rp-num">2025 sales</th>'
               f'<th class="rp-num hm">Share</th><th class="rp-num">2031 base</th><th class="rp-num hm">2031 low – high</th><th class="rp-num">CAGR 2025–31</th></tr>{rows}'
               f'<tr><td><b>All areas</b></td><td class="rp-num hm"><b>100</b></td><td class="rp-num"><b>{_b(tot25)}</b></td><td class="rp-num hm">100%</td>'
               f'<td class="rp-num"><b>{_b(tot31["base"])}</b></td><td class="rp-num hm">{_b(tot31["low"])} – {_b(tot31["high"])}</td>'
               f'<td class="rp-num"><b>{_pct(cagr(tot25, tot31["base"]))}</b></td></tr></table></div>')

    areas = ""
    for t in tas:
        n = NARR.get(t["ta"], {"verdict": "", "points": [], "context": ""})
        ds = [x for x in drugs if x["ta"] == t["ta"]]
        trs = "".join(
            f'<tr><td><b>{_e(x["brand"])}</b><br><small>{_e(x["inn"])} · {_e(x["company"])}</small><div>{_flags(x)}</div></td>'
            f'<td class="rp-num">#{x["rank"]}</td><td class="rp-num">{x["s2025"]:.2f}</td>'
            f'<td class="rp-num hm">{x["proj"]["base"][2]:.2f}</td>'
            f'<td class="rp-num"><b>{x["proj"]["base"][-1]:.2f}</b><br><small>{x["proj"]["low"][-1]:.1f}–{x["proj"]["high"][-1]:.1f}</small></td></tr>'
            for x in ds)
        launches = "".join(f'<li><b>{_e(l["name"])}</b>: {_b(l["v2031"]["base"])} in 2031 (range {_b(l["v2031"]["low"])}–{_b(l["v2031"]["high"])}). '
                           f'<small>{_e(l["note"])}</small></li>' for l in t["launches"])
        areas += f"""<section class="rp-area" id="{SLUG.get(t['ta'], '')}" style="--c:{COLOR.get(t['ta'], '#334155')}">
<div class="rp-ah"><div><h3>{_e(t['ta'])}</h3><p class="vd">{_e(n['verdict'])}</p>
<div class="rp-stats"><span><b>{t['n']}</b> top-100 drugs</span><span><b>{_b(t['s2025'])}</b> in 2025</span>
<span><b>{_b(t['total']['base'][-1])}</b> in 2031 (base)</span><span><b>{_pct(t['cagr']['base'])}</b> a year</span>
<span>Range {_b(t['total']['low'][-1])}–{_b(t['total']['high'][-1])}</span></div></div>
<div>{_spark(t)}<div class="note" style="margin-top:4px">Base case line, low–high band, incl. named launches</div></div></div>
<ul class="pts">{"".join(f"<li>{_e(p)}</li>" for p in n['points'])}</ul>
{f'<p class="rp-ctx">{_e(n["context"])}</p>' if n.get("context") else ""}
<div class="rp-tblw"><table class="bz-tbl"><tr><th>Drug</th><th class="rp-num">Rank</th><th class="rp-num">2025 $bn</th><th class="rp-num hm">2028 base</th><th class="rp-num">2031 base (range)</th></tr>{trs}</table></div>
{f'<div class="rp-l"><b>New launches counted in this area</b><ul style="margin:6px 0 0 18px">{launches}</ul></div>' if launches else ''}
</section>"""

    all_rows = "".join(
        f'<tr><td class="rp-num">{x["rank"]}</td><td><b>{_e(x["brand"])}</b><br><small>{_e(x["inn"])}</small></td><td class="hm">{_e(x["company"])}</td>'
        f'<td><small>{_e(x["ta"])}</small></td><td class="rp-num">{x["s2025"]:.2f}</td><td class="rp-num"><b>{x["proj"]["base"][-1]:.2f}</b></td></tr>'
        for x in drugs)
    toc = "".join(f'<a href="#{SLUG.get(t["ta"])}" style="color:{COLOR.get(t["ta"])}">{_e(t["ta"])}</a>' for t in tas)
    gainers = sorted(drugs, key=lambda x: -(x["proj"]["base"][-1] - x["s2025"]))[:3]
    losers = sorted(drugs, key=lambda x: (x["proj"]["base"][-1] - x["s2025"]))[:3]
    names = lambda xs: ", ".join(f'{x["brand"]} ({"+" if x["proj"]["base"][-1] >= x["s2025"] else ""}{x["proj"]["base"][-1] - x["s2025"]:.0f}bn)' for x in xs)
    dob = next(t for t in tas if t["ta"] == "Diabetes & obesity")
    imm = next(t for t in tas if t["ta"] == "Immunology & inflammation")
    onc = next(t for t in tas if t["ta"] == "Oncology")
    cv = next(t for t in tas if t["ta"] == "Cardiovascular & renal")

    body = f"""<style>{BZ_CSS}{CSS}</style>{_beatbar("")}
<section class="bz-hero"><div class="wrap"><div class="k">CompePharma Market Analysis · Report</div>
<h1>The top 100 drugs: a 5-year outlook by therapeutic area, 2026–2031</h1>
<p class="sub">The 100 best-selling medicines earned {_b(tot25)} in 2025. We grouped them into {len(tas)} therapeutic areas and projected each
drug through 2031, with patent expiries, US Medicare negotiated prices and the launches most likely to take their place.</p>
<div class="row"><a class="btn" href="#findings">Key findings</a><a class="btn ghost" href="{PATH}.csv">Download the data (CSV)</a></div>
<p class="note" style="color:#9aa3b2">Published {PUBLISHED}. Sales: company-reported FY2025, USD.</p></div></section>
<main class="wrap">
<section class="bz-sec"><div class="rp-kpi">
<div class="bz-num"><b>{_b(tot25)}</b><span>2025 sales of the top 100 drugs, from {n_co} companies</span></div>
<div class="bz-num"><b>{_b(tot31["base"])}</b><span>2031 base case incl. named launches ({_pct(cagr(tot25, tot31["base"]))} a year)</span></div>
<div class="bz-num"><b>{_b(sum(x["s2025"] for x in loe))}</b><span>2025 sales of {len(loe)} drugs losing US exclusivity in 2026–2031</span></div>
<div class="bz-num"><b>{_b(sum(x["s2025"] for x in ira))}</b><span>2025 sales of {len(ira)} drugs with a Medicare negotiated price by 2028</span></div>
</div></section>

<section class="bz-sec" id="findings"><div class="k">Key findings</div><h2 class="t">Growth concentrates in two areas while the old blockbusters roll off</h2>
<ul class="rp-find">
<li><b>The top 100 barely grow without new launches.</b> Today's top-100 products reach {_b(top31["base"])} in 2031 in the base case
({_pct(cagr(tot25, top31["base"]))} a year), within a range of {_b(top31["low"])} to {_b(top31["high"])}. Named launches lift the total to {_b(tot31["base"])}.</li>
<li><b>Diabetes & obesity and immunology carry the growth.</b> Together they add {_b(dob["total"]["base"][-1] + imm["total"]["base"][-1] - dob["s2025"] - imm["s2025"])}
by 2031 in the base case: incretins and IL-23/JAK/FcRn medicines.</li>
<li><b>Oncology is flat as a group</b> ({_pct(onc["cagr"]["base"])} a year) because Keytruda, Opdivo, Darzalex, Xtandi and Ibrance lose US exclusivity in 2027–2029,
while the overall oncology market keeps growing through new products.</li>
<li><b>Cardiovascular & renal falls furthest</b> ({_pct(cv["cagr"]["base"])} a year): Eliquis, Entresto, Xarelto and the SGLT2 inhibitors all face generics and Medicare prices before 2031.</li>
<li><b>Biggest gains, 2025 to 2031 (base):</b> {_e(names(gainers))}. <b>Biggest losses:</b> {_e(names(losers))}.</li>
<li><b>US pricing policy is now a forecast input, not a footnote.</b> {len(ira)} of the 100 drugs carry Medicare negotiated prices by 2028, and Section 232 tariffs and
most-favoured-nation deals reshape US net prices from 2026.</li>
</ul></section>

<section class="bz-sec"><div class="k">At a glance</div><h2 class="t">2025 sales and the 2031 outlook, by therapeutic area</h2>
<div class="rp-chart">{_chart(tas)}</div>{summary}
<p class="note">On a phone, swipe the chart sideways. CAGR from 2025 to 2031. Totals include the named launches listed under each area.</p></section>

<section class="bz-sec"><div class="k">Area by area</div><h2 class="t">Drivers, risks and drug-level outlook</h2>
<div class="rp-toc">{toc}</div>{areas}</section>

<section class="bz-sec" id="list"><div class="k">The list</div><h2 class="t">The 100 best-selling drugs of 2025</h2>
<details class="rp-all"><summary>Show all 100 drugs with 2025 sales and the 2031 base case</summary>
<div class="rp-tblw"><table class="bz-tbl"><tr><th class="rp-num">#</th><th>Drug</th><th class="hm">Company</th><th>Area</th><th class="rp-num">2025 $bn</th><th class="rp-num">2031 base</th></tr>{all_rows}</table></div></details></section>

<section class="bz-sec rp-meth" id="method"><div class="k">Method</div><h2 class="t">How we built the outlook</h2>
<ul>
<li><b>Ranking.</b> Worldwide FY2025 net sales from each company's results release or annual report (Japanese companies: fiscal year to March 2026;
CSL: fiscal year to June 2025), converted at 2025 average exchange rates. Co-marketed drugs are counted once at their worldwide total
(e.g. Eylea = Regeneron US + Bayer ex-US; Xolair = Roche + Novartis). Company-reported product groups (insulin categories, plasma portfolios
other than named brands, vaccine categories) are excluded.</li>
<li><b>Momentum.</b> Each drug grows at an assumed 2026 rate that fades by about 18% a year (faster for tirzepatide), set from 2025 growth, 2026 reported results and company guidance.</li>
<li><b>Loss of exclusivity.</b> From the US and ex-US LOE year, sales follow erosion curves: small molecules in the US keep 60%, 28% and 17% of
pre-LOE sales in years 1–3; biologics 85%, 62% and 48%; ex-US generics erode more slowly. Curves are checked against Entresto, Stelara and denosumab.</li>
<li><b>US Medicare negotiation.</b> From the year a negotiated price applies, the Medicare share of US sales is reduced by the published discount (third-cycle discounts, not yet published, assumed at 40%).</li>
<li><b>Scenarios.</b> Low: weaker momentum, faster erosion, deeper price effects. High: stronger momentum, slower erosion. Base sits between.</li>
<li><b>New launches.</b> Only named assets with public data are added, on an S-curve to an assumed 2031 value. Everything else that launches by 2031 is outside these totals.</li>
</ul>
<p class="note">These are modelled scenarios built on stated assumptions, not guarantees, and not investment advice. Company-reported figures can be restated.
For a product, market or country cut of this analysis, <a href="/market-analysis?kind=report-custom#order" style="text-decoration:underline">brief us on a custom analysis</a>.</p></section>

<section class="bz-sec"><div class="k">Sources</div><ol class="rp-src">{"".join(f'<li>{f"<a href={chr(34)}{_e(u)}{chr(34)} target={chr(34)}_blank{chr(34)} rel={chr(34)}noopener{chr(34)}>{_e(n)}</a>" if u else _e(n)}</li>' for n, u in SOURCES)}</ol>
<p class="note">Product-level sources are in the CSV download.</p></section>
</main>
<section class="bz-cta"><div class="wrap"><div><h2>Need this for your products, markets or a therapy area?</h2>
<p>Ready-to-go 5-year analyses on any product, or a custom cut for your portfolio and countries.</p></div>
<a class="btn" href="/market-analysis#order">Order an analysis</a></div></section>"""
    ld = [{"@context": "https://schema.org", "@type": "Report", "name": "The top 100 drugs: a 5-year outlook by therapeutic area, 2026–2031",
           "datePublished": "2026-11-02", "publisher": {"@type": "Organization", "name": "CompePharma"}}]
    return _page("Top 100 Drugs: 5-Year Outlook by Therapeutic Area, 2026–2031 | CompePharma",
                 f"The 100 best-selling drugs earned {_b(tot25)} in 2025. 5-year outlook for oncology, immunology, obesity, cardiovascular and 8 more "
                 "areas, with patent expiries, IRA prices and new launches.", PATH, body, ld=ld)


@router.get(PATH + ".csv", include_in_schema=False)
def report_csv():
    d = _data()
    buf = io.StringIO()
    w = csv.writer(buf)
    yrs = d["years"]
    w.writerow(["Rank", "Brand", "Active ingredient", "Company", "Therapeutic area", "FY2025 sales USD bn", "FY2024 sales USD bn"] +
               [f"{y} {s}" for s in ("low", "base", "high") for y in yrs] + ["US LOE year", "Ex-US LOE year", "Medicare price year", "Note", "Source"])
    for x in d["drugs"]:
        ira = x.get("ira")
        w.writerow([x["rank"], x["brand"], x["inn"], x["company"], x["ta"], x["s2025"], x.get("s2024") or ""] +
                   [v for s in ("low", "base", "high") for v in x["proj"][s]] +
                   [x.get("loe_us") or "", x.get("loe_x") or "", ira[0] if ira else "", x.get("note", ""),
                    x["src"] if str(x["src"]).startswith("http") else ""])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="compepharma-top100-drugs-outlook-2026-2031.csv"'})
