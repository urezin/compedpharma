"""
CompePharma 5-year outlook for the therapeutic areas of the top-100 drugs (FY2025 sales).

Per drug, per year 2026-2031, three scenarios (low / base / high):
  sales_t = sales_{t-1} * (1 + g_t)                         underlying momentum, g decays each year
          then x LOE retention (US and ex-US separately, by molecule type and years since loss of exclusivity)
          then x (1 - Medicare share x IRA discount) on the US part, from the negotiated-price year
Area outlook = top-100 products in the area + new launches (named pipeline/launch assets, explicit assumptions).
"""
from __future__ import annotations

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
YEARS = list(range(2026, 2032))

# retained share of pre-LOE sales by years since LOE (0 = the LOE year, a part year)
RET = {"sm": [0.60, 0.28, 0.17, 0.13, 0.11, 0.10, 0.10],
       "smx": [0.80, 0.55, 0.40, 0.32, 0.28, 0.25, 0.25],   # ex-US generics: slower, tender/reference-price driven
       "bio": [0.85, 0.62, 0.48, 0.40, 0.35, 0.32, 0.30]}
DECAY = 0.82          # momentum fades each year
SCEN = {"low": {"g": -0.04, "gmul": 0.6, "ret": 0.85},
        "base": {"g": 0.0, "gmul": 1.0, "ret": 1.0},
        "high": {"g": 0.03, "gmul": 1.3, "ret": 1.12}}
US_SHARE = {"Oncology": .55, "Immunology & inflammation": .70, "Diabetes & obesity": .62, "Cardiovascular & renal": .58,
            "Neurology": .65, "Infectious disease & HIV": .75, "Vaccines": .50, "Haematology": .55, "Ophthalmology": .60,
            "Respiratory": .60, "Rare disease": .55, "Bone & other": .65, "Other": .60}

# brand -> assumptions. g: 2026 underlying growth before LOE/IRA; us: US share of sales;
# loe_us/loe_x: year of loss of exclusivity (US / ex-US); mol: sm|bio; ira: (year, discount, Medicare share of US sales)
A: dict[str, dict] = {
 "Keytruda": dict(g=.05, loe_us=2029, loe_x=2030, mol="bio", us=.60, note="US biosimilars from Dec 2028; subcutaneous Keytruda Qlex (patents to ~2033) cushions the erosion", ret_boost=1.15),
 "Mounjaro": dict(g=.26, decay=.62, note="Tirzepatide demand growth offset by US price cuts under the Nov 2025 MFN deal"),
 "Zepbound": dict(g=.36, decay=.62, note="Obesity uptake; Medicare coverage from 2026 at $245/month under the MFN deal"),
 "Ozempic": dict(g=-.08, ira=(2027, .71, .30), note="Generic semaglutide in Canada, China and India from 2026; IRA price from 2027; US/EU patents run past 2031"),
 "Wegovy": dict(g=.10, ira=(2027, .71, .15), note="Oral Wegovy launched Jan 2026; lower US prices; IRA price from 2027"),
 "Rybelsus": dict(g=-.12, ira=(2027, .71, .35), note="Oral semaglutide; IRA price from 2027"),
 "Dupixent": dict(g=.15, loe_us=2031, loe_x=2032, mol="bio", note="New indications (COPD, CSU, BP); US biosimilar entry assumed 2031"),
 "Skyrizi": dict(g=.22, note="IL-23 share gains in psoriasis and IBD; exclusivity beyond 2031"),
 "Eliquis": dict(g=.03, loe_us=2028, loe_x=2026, mol="sm", us=.62, ira=(2026, .56, .55), note="IRA price 2026; EU generics 2026; US generics Apr 2028"),
 "Darzalex (incl. Faspro)": dict(g=.12, loe_us=2029, loe_x=2031, mol="bio", note="US exclusivity to 2029, EU 2031 (Genmab)"),
 "Biktarvy": dict(g=.05, us=.80, ira=(2028, .40, .20), note="US generics settled to 2036; IRA price from 2028"),
 "Opdivo": dict(g=.01, loe_us=2028, loe_x=2030, mol="bio", note="US biosimilars around 2028; Opdivo Qvantig switch"),
 "Jardiance": dict(g=.02, loe_us=2029, loe_x=2029, mol="sm", ira=(2026, .66, .50), note="IRA price 2026; compound patent 2029"),
 "Ocrevus": dict(g=.04, loe_us=2029, loe_x=2030, mol="bio", note="12-year US exclusivity to Mar 2029; Ocrevus Zunovo subcutaneous"),
 "Farxiga/Forxiga": dict(g=.12, loe_us=2026, loe_x=2027, mol="sm", ira=(2026, .68, .50), note="US generics Apr 2026; China VBP; IRA price 2026"),
 "Rinvoq": dict(g=.22, note="JAK share gains; US settlements to 2033"),
 "Entresto": dict(g=.14, loe_us=2025, loe_x=2026, mol="sm", ira=(2026, .53, .55), note="US generics Jul 2025; Q3 2026 sales -38%"),
 "Tagrisso": dict(g=.08, note="US compound patents to 2032"),
 "Cosentyx": dict(g=.07, loe_us=2029, loe_x=2030, mol="bio", ira=(2028, .40, .15), note="IRA price 2028; US biosimilars 2029"),
 "Prevnar family": dict(g=.00, note="Competition from Merck's Capvaxive"),
 "Vyndaqel family": dict(g=.06, loe_us=2031, loe_x=2026, mol="sm", note="EU generics 2026; US settlements push generics to mid-2031; new ATTR-CM competition"),
 "Stelara": dict(g=-.25, loe_us=2025, loe_x=2025, mol="bio", ira=(2026, .66, .15), note="Biosimilars since 2025 (-41% in year 1)"),
 "Imfinzi": dict(g=.15, note="Expansion in lung, bladder and gastric cancer"),
 "Verzenio": dict(g=.06, loe_us=2031, mol="sm", ira=(2028, .40, .30), note="IRA price 2028"),
 "Gardasil/Gardasil 9": dict(g=-.10, note="China demand collapse; recovery ex-China"),
 "Tremfya": dict(g=.25, note="IBD launches"),
 "Vabysmo": dict(g=.10, note="Share gains in nAMD/DME despite aflibercept biosimilars"),
 "Kisqali": dict(g=.22, loe_us=2031, mol="sm", ira=(2028, .40, .30), note="Early breast cancer label; IRA price 2028"),
 "Shingrix": dict(g=.02),
 "Humira": dict(g=-.30, loe_us=2023, loe_x=2018, mol="bio", note="Biosimilars in the US since 2023"),
 "Kesimpta": dict(g=.12),
 "Comirnaty": dict(g=-.20, note="Shrinking COVID-19 vaccination"),
 "Ibrance": dict(g=-.06, loe_us=2027, loe_x=2028, mol="sm", ira=(2027, .50, .45), note="IRA price 2027; US LOE 2027"),
 "Trelegy Ellipta": dict(g=.04, loe_us=2029, mol="sm", ira=(2027, .73, .60), note="IRA price 2027"),
 "Orencia": dict(g=.00, ira=(2028, .40, .30), note="IRA price 2028"),
 "Revlimid": dict(g=-.55, loe_us=2022, loe_x=2022, mol="sm", note="Full US generic entry Jan 2026"),
 "Yervoy": dict(g=.03),
 "Imbruvica": dict(g=-.12, ira=(2026, .38, .60), note="BTK competition; IRA price 2026; US generics 2032"),
 "Pomalyst/Imnovid": dict(g=-.05, loe_us=2026, loe_x=2025, mol="sm", ira=(2027, .60, .55), note="US generics Mar 2026"),
 "Paxlovid": dict(g=-.20),
 "Reblozyl": dict(g=.20),
 "Xarelto": dict(g=-.05, loe_us=2027, loe_x=2026, mol="sm", us=.50, ira=(2026, .62, .55), note="EU generics 2026; US higher strengths later; IRA price 2026"),
 "Trikafta/Kaftrio": dict(g=.03, note="Shift to Alyftrek (same company); exclusivity to late 2030s"),
 "Entyvio": dict(g=.05, ira=(2028, .40, .30), note="IRA (Part B) price 2028"),
 "Hemlibra": dict(g=.05),
 "Xolair": dict(g=-.02, loe_us=2026, loe_x=2025, mol="bio", ira=(2028, .40, .15), note="Omalizumab biosimilars; IRA price 2028"),
 "Eylea / Eylea HD": dict(g=.00, loe_us=2026, loe_x=2026, mol="bio", note="US biosimilars broadly from Q3-Q4 2026, EU from 2026; Eylea HD switch"),
 "Ultomiris": dict(g=.12),
 "Prolia": dict(g=-.10, loe_us=2025, loe_x=2025, mol="bio", note="Denosumab biosimilars since mid-2025 (-29-33% in 2026)"),
 "Xgeva": dict(g=-.10, loe_us=2025, loe_x=2025, mol="bio"),
 "Ofev": dict(g=.00, loe_us=2027, loe_x=2026, mol="sm", ira=(2027, .50, .60), note="IRA price 2027; Jascayd (nerandomilast) successor"),
 "Tecentriq": dict(g=-.02, loe_us=2031, mol="bio"),
 "Perjeta": dict(g=-.10, loe_us=2026, loe_x=2027, mol="bio", note="Interchangeable biosimilar approved Nov 2025; Phesgo switch"),
 "Dovato": dict(g=.12),
 "Calquence": dict(g=.08, ira=(2027, .40, .60), note="IRA price 2027"),
 "Lynparza": dict(g=.00, loe_us=2028, loe_x=2029, mol="sm"),
 "Repatha": dict(g=.22),
 "Actemra/RoActemra": dict(g=-.08, loe_us=2024, loe_x=2024, mol="bio"),
 "Phesgo": dict(g=.15),
 "Symbicort": dict(g=-.06),
 "Descovy": dict(g=.06, note="PrEP; Yeztugo (lenacapavir) launch shifts PrEP within Gilead"),
 "Nubeqa": dict(g=.28),
 "Nucala": dict(g=.06), "Kadcyla": dict(g=.00), "Benlysta": dict(g=.10),
 "Otezla": dict(g=.00, loe_us=2028, mol="sm", ira=(2027, .65, .30), note="IRA price 2027"),
 "Enbrel": dict(g=-.10, loe_us=2029, mol="bio", us=.95, ira=(2026, .67, .25), note="IRA price 2026; US biosimilars 2029"),
 "Tafinlar + Mekinist": dict(g=.03, loe_us=2030, mol="sm"),
 "Evrysdi": dict(g=.08), "Jakavi": dict(g=.02, loe_x=2028, mol="sm", us=0.0),
 "Evenity": dict(g=.20), "Pluvicto": dict(g=.30), "Fasenra": dict(g=.10), "Tepezza": dict(g=.02),
 "Ilaris": dict(g=.12), "Alecensa": dict(g=.03), "Cabenuva": dict(g=.25), "Soliris": dict(g=-.25, loe_us=2025, loe_x=2023, mol="bio"),
 "Polivy": dict(g=.12), "Tivicay": dict(g=-.08), "Strensiq": dict(g=.08),
 "Trajenta/Jentadueto": dict(g=-.10, ira=(2026, .84, .55), note="IRA price; generic DPP-4s"),
 "Promacta/Revolade": dict(g=-.20, loe_us=2025, loe_x=2026, mol="sm"),
 "Blincyto": dict(g=.18), "Nplate": dict(g=.00), "Bexsero": dict(g=.04),
 "MabThera/Rituxan": dict(g=-.08, loe_us=2019, loe_x=2017, mol="bio"),
 "Takhzyro": dict(g=.04), "Genvoya": dict(g=-.10), "Yescarta": dict(g=.03),
 # group A others
 "Januvia/Janumet": dict(g=-.15, loe_us=2026, loe_x=2022, mol="sm", ira=(2026, .79, .55), note="US generics 2026; IRA price"),
 "ProQuad/M-M-R II/Varivax": dict(g=.00), "Bridion": dict(g=-.05, loe_us=2026, loe_x=2026, mol="sm"),
 "Verzenio_": dict(),
 "Trulicity": dict(g=-.20, loe_us=2027, loe_x=2029, mol="bio", ira=(2028, .40, .50), note="Switch to tirzepatide; US exclusivity 2027"),
 "Taltz": dict(g=.08), "Lantus": dict(g=-.03), "Toujeo": dict(g=.03), "Beyfortus": dict(g=.12),
 "Botox Therapeutic": dict(g=.06), "Vraylar": dict(g=.06, loe_us=2029, mol="sm", us=.98, ira=(2027, .44, .30), note="IRA price 2027"),
 "Venclexta": dict(g=.08), "Botox Cosmetic": dict(g=.00), "Creon": dict(g=.02),
 "Padcev": dict(g=.15), "Erleada": dict(g=.12, ira=(2028, .40, .60), note="IRA price 2028"),
 "Simponi/Simponi Aria": dict(g=-.03), "Opsumit/Opsynvi": dict(g=.00, loe_us=2027, mol="sm"),
 "Uptravi": dict(g=.03, loe_us=2027, mol="sm"), "Carvykti": dict(g=.40), "Remicade": dict(g=-.10),
 "Spravato": dict(g=.30), "Invega Sustenna/Trinza": dict(g=-.06), "Libtayo": dict(g=.22),
 "Winrevair": dict(g=.40), "Nurtec ODT": dict(g=.08), "Edurant": dict(g=.00), "Breyanzi": dict(g=.25),
 "Mavyret": dict(g=-.05), "Ubrelvy": dict(g=.10),
}


SRC = {
 "msd": "https://www.msd.com/news/merck-co-inc-rahway-n-j-usa-announces-fourth-quarter-and-full-year-2025-financial-results-highlights-progress-advancing-broad-diverse-pipeline/",
 "lilly": "https://investor.lilly.com/news-releases/news-release-details/lilly-reports-fourth-quarter-2025-financial-results-and-provides",
 "novo": "https://www.sec.gov/Archives/edgar/data/353278/000035327826000006/caq42025.htm",
 "sanofi": "https://www.sec.gov/Archives/edgar/data/1121404/000112140426000001/pressreleaseq42025english.htm",
 "regeneron": "https://investor.regeneron.com/news-releases/news-release-details/regeneron-reports-fourth-quarter-and-full-year-2025-financial",
 "abbvie": "https://news.abbvie.com/2026-02-04-AbbVie-Reports-Full-Year-and-Fourth-Quarter-2025-Financial-Results",
 "bms": "https://www.boardroomalpha.com/sec/bmy-8-k-2026-02-05-0000014272-26-000002/a2025q4ex991.htm",
 "pfizer": "https://www.sec.gov/Archives/edgar/data/78003/000007800326000005/pfe-12312025xex99.htm",
 "jnj": "https://d18rn0p25nwr6d.cloudfront.net/CIK-0000200406/35975f5e-1620-40f3-8303-9257b1f68897.pdf",
 "jnj+bayer": "https://flcube.com/?p=58854",
 "az": "https://www.lse.co.uk/rns/final-results-yioyg37wzzdrexs.html",
 "novartis": "https://www.novartis.com/Investors/financial-data/product-sales",
 "roche": "https://www.marktpuls.ch/artikel/permalink/654444",
 "roche+novartis": "https://www.marktpuls.ch/artikel/permalink/654444",
 "gsk": "https://www.directorstalkinterviews.com/wp-content/uploads/2026/02/fy-2025-results-announcement.pdf",
 "gilead": "https://s29.q4cdn.com/585078350/files/doc_financials/2025/q4/GILD-Q425-FY25-Earnings-Press-Release-10-February-2026.pdf",
 "amgen": "https://investors.amgen.com/news-releases/news-release-details/amgen-reports-fourth-quarter-and-full-year-2025-financial",
 "takeda": "https://www.sec.gov/Archives/edgar/data/0001395064/000139506426000185/a2026_air.htm",
 "bi": "https://flcube.com/wp-content/uploads/2026/03/Boehringer-Ingelheim-Annual-Report-Highlights-2025.pdf",
 "ucb": "https://www.ucb.com/sites/default/files/2026-02/UCB-PR-2025-FY-Results-ENG.pdf",
 "csl": "https://cdn-api.markitdigital.com/apiman-gateway/ASX/asx-research/1.0/file/2924-02979923-3A673725&v=4a466cc3f899e00730cfbfcd5ab8940c41f474b6",
 "biogen": "https://investors.biogen.com/static-files/cfad0ddd-0fdc-40d1-8da6-8c3dcaedd05b",
 "jazz": "https://www.1stoncology.com/blog/?p=108879",
 "otsuka": "https://finance-frontend-pc-dist.west.edge.storage-yahoo.jp/disclosure/20260213/20260213559778.pdf",
}


def load(paths: list[str]) -> list[dict]:
    rows, seen = [], set()
    for p in paths:
        for r in csv.DictReader(open(p)):
            if not r.get("s2025") or r["brand"] in seen:
                continue
            seen.add(r["brand"])
            r["src"] = SRC.get(r["src"], r["src"])
            r["s2025"] = float(r["s2025"])
            r["s2024"] = float(r["s2024"]) if r.get("s2024") else None
            rows.append(r)
    rows.sort(key=lambda r: -r["s2025"])
    return rows


def project(r: dict, scen: str) -> list[float]:
    a = A.get(r["brand"], {})
    sc = SCEN[scen]
    if "g" in a:
        g0 = a["g"]
    elif r.get("s2024"):
        g0 = max(-.3, min(.4, (r["s2025"] / r["s2024"] - 1) * .6))
    else:
        g0 = .03
    g0 = g0 * sc["gmul"] + sc["g"] if g0 > 0 else g0 + sc["g"]
    us = a.get("us", US_SHARE.get(r["ta"], .6))
    mol = a.get("mol", "sm")
    out, underlying = [], r["s2025"]
    for i, y in enumerate(YEARS):
        underlying *= 1 + g0 * (a.get("decay", DECAY) ** i)
        parts = []
        for share, loe, curve in ((us, a.get("loe_us"), mol), (1 - us, a.get("loe_x"), "smx" if mol == "sm" else mol)):
            f = 1.0
            if loe and y >= loe:
                k = min(y - loe, len(RET[curve]) - 1)
                f = RET[curve][k]
                # products already off-patent before 2026: momentum in g already reflects erosion to 2025
                if loe <= 2025:
                    k0 = min(2025 - loe, len(RET[curve]) - 1)
                    f = RET[curve][k] / RET[curve][k0]
                f = min(1.0, f * sc["ret"] * a.get("ret_boost", 1.0))
            parts.append(share * f)
        val = underlying * sum(parts)
        ira = a.get("ira")
        if ira and y >= ira[0]:
            us_part = underlying * parts[0]
            val -= us_part * ira[1] * ira[2] * (0.9 if scen == "high" else 1.1 if scen == "low" else 1.0)
        out.append(round(max(val, 0), 3))
    return out


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] != "run":
    rows = load([os.path.join(HERE, f) for f in sys.argv[1:]])
    print(len(rows))

A.update({
 "Xtandi": dict(g=.02, loe_us=2027, loe_x=2027, mol="sm", ira=(2027, .48, .65), note="IRA price 2027; US LOE 2027"),
 "Enhertu": dict(g=.25, note="First-line HER2+ and HER2-low/ultralow breast cancer expansion"),
 "Vyvgart": dict(g=.35, note="gMG, CIDP and new FcRn indications; prefilled syringe"),
 "Privigen": dict(g=.06, note="Immunoglobulin demand growth (CSL fiscal year to June 2025)"),
 "Brukinsa": dict(g=.28, note="BTK share gains in CLL"),
 "Jakafi": dict(g=.04, loe_us=2028, mol="sm", us=1.0, note="US exclusivity to 2028; Incyte US sales"),
 "Bimzelx": dict(g=.45, note="IL-17A/F share gains in psoriasis and HS"),
 "Ingrezza": dict(g=.04),
 "Amvuttra": dict(g=.45, decay=.70, note="ATTR cardiomyopathy label (2025)"),
 "Lenvima/Kisplyx": dict(g=-.03, ira=(2028, .40, .45), note="IRA price 2028"),
 "Austedo/Austedo XR": dict(g=.12, ira=(2027, .38, .35), note="IRA price 2027"),
 "Rexulti": dict(g=.10, ira=(2028, .40, .30), note="IRA price 2028"),
 "Cimzia": dict(g=-.05, ira=(2028, .40, .25), note="IRA price 2028"),
 "Hizentra": dict(g=.07),
})

# Named launches / growth assets outside the top 100: 2031 sales (USD bn) low/base/high and launch year.
# CompePharma assumptions, anchored where a public forecast exists (see sources on the page).
NEW = [
 ("Diabetes & obesity", "Foundayo (orforglipron)", 2026, (7, 14, 22), "Approved Apr 2026; Evaluate puts it above $25bn in 2032"),
 ("Diabetes & obesity", "Retatrutide", 2027, (3, 8, 14), "28.3% weight loss in TRIUMPH-1; filing 2026"),
 ("Diabetes & obesity", "CagriSema", 2027, (1.5, 4, 8), "Filed Dec 2025; FDA decision pending"),
 ("Oncology", "PD-(L)1xVEGF bispecifics (ivonescimab and peers)", 2027, (2, 6, 12), "Ivonescimab PDUFA 14 Nov 2026; Evaluate's most valuable pipeline asset"),
 ("Oncology", "Datroway (datopotamab deruxtecan)", 2025, (1.5, 3, 5), "TROP2 ADC; $78m in Q3 2026"),
 ("Immunology & inflammation", "Icotrokinra (oral IL-23R)", 2026, (1, 3, 5.5), "First oral IL-23 pathway drug"),
 ("Neurology", "Anti-amyloid Alzheimer's (Leqembi, Kisunla)", 2023, (2.5, 5, 9), "Eisai guides Leqembi to ¥250-280bn in FY2027"),
 ("Neurology", "Cobenfy (xanomeline-trospium)", 2024, (1.5, 3, 5), "First new schizophrenia mechanism in decades"),
 ("Cardiovascular & renal", "Cardiac myosin inhibitors (Camzyos, aficamten)", 2022, (2, 4, 6), "Camzyos $1.07bn in 2025"),
 ("Infectious disease & HIV", "Yeztugo (twice-yearly lenacapavir PrEP)", 2025, (1.5, 3, 5), "Launched Jun 2025"),
 ("Vaccines", "Capvaxive (21-valent pneumococcal)", 2024, (1, 2.5, 4), "Adult pneumococcal share"),
 ("Respiratory", "Ohtuvayre (ensifentrine)", 2024, (1, 2, 3.5), "COPD maintenance"),
]


def new_series(launch: int, v2031: float) -> list[float]:
    """S-shaped ramp to the 2031 value from the launch year (sales at 2025 taken as negligible)."""
    import math
    out = []
    for y in YEARS:
        t = (y - max(launch, 2025)) / max(1, 2031 - max(launch, 2025))
        out.append(round(v2031 / (1 + math.exp(-7 * (t - .55))) if y >= launch else 0.0, 3))
    if out[-1]:
        k = v2031 / out[-1]
        out = [round(x * k, 3) for x in out]
    return out


def run(paths: list[str]) -> dict:
    rows = load(paths)[:100]
    tas: dict[str, dict] = {}
    drugs = []
    for i, r in enumerate(rows, 1):
        proj = {s: project(r, s) for s in SCEN}
        a = A.get(r["brand"], {})
        d = {"rank": i, "brand": r["brand"], "inn": r["inn"], "company": r["company"], "ta": r["ta"], "s2025": r["s2025"],
             "s2024": r["s2024"], "src": r["src"], "proj": proj, "note": a.get("note", ""),
             "loe_us": a.get("loe_us"), "loe_x": a.get("loe_x"), "ira": a.get("ira")}
        drugs.append(d)
        t = tas.setdefault(r["ta"], {"ta": r["ta"], "n": 0, "s2025": 0.0, "s2024": 0.0, "s2024n": 0,
                                       "top": {s: [0.0] * len(YEARS) for s in SCEN}, "new": {s: [0.0] * len(YEARS) for s in SCEN},
                                       "launches": []})
        t["n"] += 1
        t["s2025"] += r["s2025"]
        if r["s2024"]:
            t["s2024"] += r["s2024"]; t["s2024n"] += r["s2025"]
        for s in SCEN:
            t["top"][s] = [a_ + b_ for a_, b_ in zip(t["top"][s], proj[s])]
    for ta, name, launch, vals, note in NEW:
        t = tas.get(ta)
        if not t:
            continue
        ser = {s: new_series(launch, v) for s, v in zip(("low", "base", "high"), vals)}
        t["launches"].append({"name": name, "launch": launch, "v2031": dict(zip(("low", "base", "high"), vals)), "note": note})
        for s in SCEN:
            t["new"][s] = [a_ + b_ for a_, b_ in zip(t["new"][s], ser[s])]
    for t in tas.values():
        t["total"] = {s: [round(a_ + b_, 2) for a_, b_ in zip(t["top"][s], t["new"][s])] for s in SCEN}
        for s in SCEN:
            t["top"][s] = [round(x, 2) for x in t["top"][s]]
            t["new"][s] = [round(x, 2) for x in t["new"][s]]
        t["s2025"] = round(t["s2025"], 2)
        t["cagr"] = {s: round(((t["total"][s][-1] / t["s2025"]) ** (1 / 6) - 1) * 100, 1) for s in SCEN}
        t["cagr_top"] = {s: round(((t["top"][s][-1] / t["s2025"]) ** (1 / 6) - 1) * 100, 1) for s in SCEN}
        t["yoy2025"] = round((t["s2024n"] / t["s2024"] - 1) * 100, 1) if t["s2024"] else None
    return {"years": YEARS, "drugs": drugs, "tas": sorted(tas.values(), key=lambda t: -t["s2025"])}


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "run":
    res = run([os.path.join(HERE, f) for f in ("top100_sales_a.csv", "top100_sales_b.csv", "top100_sales_c.csv")])
    json.dump(res, open(os.path.join(HERE, "top100_2025.json"), "w"), indent=1)
    tot = {s: sum(t["total"][s][-1] for t in res["tas"]) for s in SCEN}
    top = {s: sum(t["top"][s][-1] for t in res["tas"]) for s in SCEN}
    s25 = sum(t["s2025"] for t in res["tas"])
    print(f"2025 {s25:.1f} | 2031 top100 {top} | incl launches {tot}")
    for t in res["tas"]:
        print(f'{t["ta"]:28} n={t["n"]:3} 2025={t["s2025"]:6.1f}  2031 low/base/high={t["total"]["low"][-1]:6.1f}/{t["total"]["base"][-1]:6.1f}/{t["total"]["high"][-1]:6.1f}  CAGR base {t["cagr"]["base"]}%  top-only {t["cagr_top"]["base"]}%')
