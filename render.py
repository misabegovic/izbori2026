#!/usr/bin/env python3
"""Render data/ into dist/ static HTML (national coverage)."""
import json
import os
import glob
import re
import shutil
import unicodedata
from collections import defaultdict
from jinja2 import Environment, FileSystemLoader

def fold(s):
    s = (s or "").lower().replace("\u0111", "dj")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()

env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
national = json.load(open("data/national.json"))
municipalities = json.load(open("data/municipalities.json"))
timelines = json.load(open("data/timelines.json"))
mps = json.load(open("data/mps.json"))
ecitizen = json.load(open("data/ecitizen.json")) if os.path.exists("data/ecitizen.json") else {"cities": {}}

units = {}
for f in glob.glob("data/units/*.json"):
    u = json.load(open(f))
    units[f"{u['race']}-{u['area']}"] = u

if os.path.exists("dist"):
    shutil.rmtree("dist")
os.makedirs("dist")

gen = national["generated"][:10]
RACE_LABEL = {"oi2026-1": "Predsjedništvo BiH", "oi2026-2": "Predstavnički dom PSBiH",
              "oi2026-4": "Parlament FBiH", "oi2026-5": "Predsjednik i potpredsjednici RS",
              "oi2026-6": "Narodna skupština RS", "oi2026-7": "Skupštine kantona"}
AREA_LABEL = {}
for u in units.values():
    AREA_LABEL[(u["race"], u["area"])] = None  # filled below from unit pages' titles where useful


def unit_href(race, area):
    return f"jedinica-{race}-{area}.html"


def unit_name(race, area):
    u = units.get(f"{race}-{area}")
    if not u:
        return f"{RACE_LABEL.get(race, race)} {area}"
    lbl = u["lists"][0]["name"] if u["race"] == "oi2026-1" else None
    return f"{u['title']} — jedinica {area}"


# eCitizen city slug -> municipality slug (fold diacritics, unify separators)
slug_by_folded = {}
for m in municipalities:
    tail = m["slug"].split(".")[-1]
    slug_by_folded[fold(tail).replace("-", " ")] = m["slug"]
ec_by_slug = {}
for city, data in ecitizen["cities"].items():
    key = fold(city.replace("_", " "))
    slug = slug_by_folded.get(key)
    if slug and data.get("sessions"):
        ec_by_slug[slug] = {"city": city, **data}
print(f"eCitizen mapirano: {len(ec_by_slug)} općina")

# party-level MP aggregates (za/protiv/suzdrzan/odsutan + govori)
party_mp = defaultdict(lambda: {"for": 0, "against": 0, "abstained": 0, "absent": 0, "speeches": 0, "n": 0})
for nm, r in mps.items():
    if not r.get("party") or not r.get("record"):
        continue
    c = r["record"].get("counted", {})
    p = party_mp[r["party"]]
    p["for"] += c.get("for", 0); p["against"] += c.get("against", 0)
    p["abstained"] += c.get("abstained", 0); p["absent"] += c.get("absent", 0)
    p["speeches"] += r.get("speeches", 0); p["n"] += 1

def party_key(s):
    return fold(s).replace(" ", "")

party_mp_folded = {party_key(k): v for k, v in party_mp.items()}


def enrich_candidate(c):
    c = dict(c)
    c["timeline"] = timelines.get(c.get("pid") or "", [])
    return c


# --- unit pages ---
unit_tpl = env.get_template("unit.html")
for key, u in units.items():
    lists = [{**l, "candidates": [enrich_candidate(c) for c in l["candidates"]]} for l in u["lists"]]
    # 'šta dobijaš' cards: per-list 2022 votes+seats in this unit + list quality + MP behavior
    hist22_by_party = {party_key(h["party"]): h for h in u.get("party_history", []) if h["year"] == 2022}
    hist18_by_party = {party_key(h["party"]): h for h in u.get("party_history", []) if h["year"] == 2018}
    seats22_by_party = {party_key(k): v for k, v in u.get("seats22", {}).items()}
    for l in lists:
        k = party_key(l["name"])
        l["card"] = {
            "votes22": (hist22_by_party.get(k) or {}).get("votes"),
            "votes18": (hist18_by_party.get(k) or {}).get("votes"),
            "seats22": seats22_by_party.get(k, 0),
            "n": len(l["candidates"]),
            "office": sum(1 for c in l["candidates"] if c.get("office")),
            "won": sum(1 for c in l["candidates"] if c.get("won")),
            "debut": sum(1 for c in l["candidates"] if c.get("stood") == 1),
            "fillers": sum(1 for c in l["candidates"] if (c.get("stood") or 0) >= 3 and not c.get("won")),
            "mp": party_mp_folded.get(k),
        }
    html = unit_tpl.render(u=u, lists=lists, generated=gen,
                           hist18=[h for h in u["party_history"] if h["year"] == 2018],
                           hist22=[h for h in u["party_history"] if h["year"] == 2022])
    open(f"dist/{unit_href(u['race'], u['area'])}", "w").write(html)

# --- municipality pages ---
opcina_tpl = env.get_template("opcina.html")
for m in municipalities:
    ballots = []
    if m["entity"] == "rs":
        ballots.append({"href": unit_href("oi2026-1", "703"), "name": "Predsjedništvo BiH — srpski član"})
        ballots.append({"href": unit_href("oi2026-5", "5"), "name": "Predsjednik i potpredsjednici RS"})
    elif m["entity"] == "fbih":
        ballots.append({"href": unit_href("oi2026-1", "701"), "name": "Predsjedništvo BiH — bošnjački član"})
        ballots.append({"href": unit_href("oi2026-1", "702"), "name": "Predsjedništvo BiH — hrvatski član"})
    else:
        ballots.append({"href": None, "name": "Predsjedništvo BiH — zavisi od opcije (Brčko)"})
    for race, area in m["refs"]:
        ballots.append({"href": unit_href(race, area), "name": unit_name(race, area)})
    html = opcina_tpl.render(m=m, ballots=ballots, ec=ec_by_slug.get(m["slug"]), generated=gen)
    open(f"dist/opcina-{m['slug']}.html", "w").write(html)

# --- općine index ---
groups = defaultdict(list)
for m in municipalities:
    groups[m["group"]].append(m)
html = env.get_template("opcine.html").render(
    groups=sorted(groups.items()), municipalities=municipalities, generated=gen)
open("dist/opcine.html", "w").write(html)

# --- stranke: national party comparison ---
party_nat = defaultdict(lambda: {"votes18": 0, "votes22": 0, "cands26": 0, "won_ever": 0, "debut": 0})
for u in units.values():
    for h in u["party_history"]:
        k = h["party"]
        if h["year"] == 2018:
            party_nat[k]["votes18"] += h["votes"] or 0
        else:
            party_nat[k]["votes22"] += h["votes"] or 0
    for l in u["lists"]:
        k = l["name"]
        for c in l["candidates"]:
            party_nat[k]["cands26"] += 1
            if c.get("won"):
                party_nat[k]["won_ever"] += 1
            if c.get("stood") == 1:
                party_nat[k]["debut"] += 1
top = sorted(party_nat.items(), key=lambda kv: -kv[1]["cands26"])[:30]
html = env.get_template("stranke.html").render(parties=top, generated=gen)
open("dist/stranke.html", "w").write(html)

# --- poslanici: PSBiH incumbents' voting records ---
mp_rows = []
for nm, r in mps.items():
    rec = r.get("record") or {}
    c = rec.get("counted", {})
    tot = c.get("for", 0) + c.get("against", 0) + c.get("abstained", 0) or 1
    seen = c.get("for", 0) + c.get("against", 0) + c.get("abstained", 0) + c.get("absent", 0) or 1
    tl = timelines.get(r["pid"], [])
    v2022 = next((t.get("votes") for t in tl if t.get("y") == 2022 and t.get("lvl") == "Predstavnički dom PSBiH"), None)
    mp_rows.append({"name": nm, "party": r.get("party"),
                    "za": c.get("for", 0), "protiv": c.get("against", 0),
                    "suzdrzan": c.get("abstained", 0), "odsutan": c.get("absent", 0),
                    "za_pct": round(100 * c.get("for", 0) / tot),
                    "prisustvo": round(100 * (seen - c.get("absent", 0)) / seen),
                    "speeches": r.get("speeches", 0), "personal22": v2022})
mp_rows.sort(key=lambda r: -r["za_pct"])
html = env.get_template("poslanici.html").render(mps=mp_rows, generated=gen)
open("dist/poslanici.html", "w").write(html)

# --- sjednice: national eCitizen overview ---
sj = []
m_by_slug = {m["slug"]: m for m in municipalities}
for slug, ec in ec_by_slug.items():
    m = m_by_slug.get(slug)
    if not m:
        continue
    sessions = ec.get("sessions", [])
    latest = None
    if sessions:
        s = sessions[0]
        latest = {"name": s.get("name"), "date": s.get("date"), "n_agendas": len(s.get("agendas", []))}
    sj.append({"slug": slug, "name": m["name"], "latest": latest})
sj.sort(key=lambda c: c["name"])
html = env.get_template("sjednice.html").render(cities=sj, generated=gen)
open("dist/sjednice.html", "w").write(html)

# --- index ---
html = env.get_template("index.html").render(
    national=national, municipalities=municipalities, generated=gen)
open("dist/index.html", "w").write(html)

print(f"rendered: {len(units)} jedinica, {len(municipalities)} općina, stranke, poslanici, index")
