#!/usr/bin/env python3
"""Render data/ into dist/ static HTML (national coverage)."""
import json
import os
import glob
import shutil
from collections import defaultdict
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
national = json.load(open("data/national.json"))
municipalities = json.load(open("data/municipalities.json"))
timelines = json.load(open("data/timelines.json"))
mps = json.load(open("data/mps.json"))

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


def enrich_candidate(c):
    c = dict(c)
    c["timeline"] = timelines.get(c.get("pid") or "", [])
    return c


# --- unit pages ---
unit_tpl = env.get_template("unit.html")
for key, u in units.items():
    lists = [{**l, "candidates": [enrich_candidate(c) for c in l["candidates"]]} for l in u["lists"]]
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
    html = opcina_tpl.render(m=m, ballots=ballots, generated=gen)
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
    v = r["votes"]
    tot = v["za"] + v["protiv"] + v["suzdrzan"] or 1
    tl = timelines.get(r["pid"], [])
    v2022 = next((t.get("votes") for t in tl if t.get("y") == 2022 and t.get("lvl") == "Predstavnički dom PSBiH"), None)
    mp_rows.append({"name": nm, **v, "za_pct": round(100 * v["za"] / tot),
                    "speeches": r["speeches"], "personal22": v2022})
mp_rows.sort(key=lambda r: -r["za_pct"])
html = env.get_template("poslanici.html").render(mps=mp_rows, generated=gen)
open("dist/poslanici.html", "w").write(html)

# --- index ---
html = env.get_template("index.html").render(
    national=national, municipalities=municipalities, generated=gen)
open("dist/index.html", "w").write(html)

print(f"rendered: {len(units)} jedinica, {len(municipalities)} općina, stranke, poslanici, index")
