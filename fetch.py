#!/usr/bin/env python3
"""Fetch election data from the Mashinerija open API into data/build.json.

Source: https://gianniravioli.com/mashinerija/ (CC BY 4.0 — attribution required).
Run manually when you want to refresh committed data; render.py consumes data/build.json.
"""
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

BASE = "https://api.gianniravioli.com/mashinerija/v1"
UA = {"User-Agent": "izbori2026-voter-guide/0.1 (github.com/misabegovic/izbori2026)"}

BALLOTS = [
    {"id": "predsjednistvo", "race": "oi2026-1", "area": None,
     "title": "Predsjedništvo BiH", "mandates": 2,
     "note": "Bošnjački i hrvatski član (glas se u FBiH). Jedan kandidat, većinski."},
    {"id": "psbih-5a", "race": "oi2026-2", "area": "515",
     "title": "Predstavnički dom PSBiH — izborna jedinica 5A", "mandates": 5,
     "note": "Državni parlament. Obavezno jedan subjekt + do 3 kandidata s njegove liste."},
    {"id": "pfbih-j3", "race": "oi2026-4", "area": "403",
     "title": "Predstavnički dom Parlamenta FBiH — izborna jedinica 3", "mandates": 7,
     "note": "Entitetski parlament. Obavezno jedan subjekt + do 3 kandidata."},
    {"id": "tk", "race": "oi2026-7", "area": "203",
     "title": "Skupština Tuzlanskog kantona (CIK: Kanton 3)", "mandates": 35,
     "note": "Kantonalna skupština. Obavezno jedan subjekt + do 3 kandidata."},
]

# units for churn analysis: (label, area, level_id, race2026)
CHURN_UNITS = [
    ("psbih-5a", "515", "pd-psbih"),
    ("pfbih-j3", "403", "pd-fbih"),
    ("tk", "203", "skupstine-kantona"),
]


def get(url):
    req = urllib.request.Request(url, headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=60))


def paged(path):
    out, off = [], 0
    while True:
        d = get(f"{BASE}{path}{'&' if '?' in path else '?'}limit=200&offset={off}")
        out += d["data"]
        if off + 200 >= d["meta"]["total"]:
            return out
        off += 200


def norm(name):
    return " ".join(sorted((name or "").upper().split()))


def enrich_person(pid):
    try:
        return get(f"{BASE}/persons/{urllib.parse.quote(pid, safe='')}")["data"]
    except Exception:
        return None


def main():
    party_names = json.load(open("data/party_names.json"))
    build = {"generated": datetime.now(timezone.utc).isoformat(), "ballots": [], "churn": {}}

    for b in BALLOTS:
        path = f"/races/{b['race']}/candidacies"
        if b["area"]:
            path += f"?areaCode={b['area']}"
        cands = paged(path)
        if b["id"] == "predsjednistvo":
            # user's ballot: Bosniak + Croat member only (FBiH voter)
            cands = [c for c in cands if "SRPSKI" not in ((c.get("area") or {}).get("label") or "").upper()]

        # synthetic ids for party-less coalition blocks (TK quirk)
        none_seq = 0
        prev_none = False
        for c in cands:
            if (c.get("party") or {}).get("id") is None:
                if not prev_none:
                    none_seq += 1
                c["_code"] = f"TK203-NONE-{none_seq if b['id'] == 'tk' else none_seq}"
                prev_none = True
            else:
                prev_none = False
                c["_code"] = c["party"]["id"]

        pids = sorted({(c.get("person") or {}).get("id") for c in cands if (c.get("person") or {}).get("id")})
        with ThreadPoolExecutor(16) as ex:
            people = {pid: p for pid, p in zip(pids, ex.map(enrich_person, pids)) if p}

        if b["id"] == "predsjednistvo":
            # group by member race (B/H član), not party — one candidate per subject
            lists = []
            by_area = {}
            for c in cands:
                lab = (c.get("area") or {}).get("label") or "?"
                key = "Bošnjački član" if "BOŠNJAČKI" in lab.upper() else "Hrvatski član"
                by_area.setdefault(key, []).append(c)
            for key, rows in by_area.items():
                group = {"code": key, "name": key, "candidates": []}
                for c in rows:
                    rec = people.get((c.get("person") or {}).get("id")) or {}
                    group["candidates"].append({
                        "pos": c.get("position"), "name": c["name"],
                        "party": (c.get("party") or {}).get("label") or party_names.get(c["_code"], ""),
                        "stood": rec.get("stood"), "won": rec.get("won"),
                        "office": rec.get("isOfficeHolder"), "bio": rec.get("hasBiography"),
                        "confidence": rec.get("confidence"),
                        "first": rec.get("firstYear"), "last": rec.get("lastYear"),
                    })
                lists.append(group)
        else:
            lists = []
            for c in cands:
                code = c["_code"]
                rec = people.get((c.get("person") or {}).get("id")) or {}
                entry = {
                    "pos": c.get("position"), "name": c["name"],
                    "stood": rec.get("stood"), "won": rec.get("won"),
                    "office": rec.get("isOfficeHolder"), "bio": rec.get("hasBiography"),
                    "confidence": rec.get("confidence"),
                    "first": rec.get("firstYear"), "last": rec.get("lastYear"),
                }
                existing = next((g for g in lists if g["code"] == code), None)
                if existing is None:
                    existing = {"code": code,
                                "name": party_names.get(code) or (c.get("party") or {}).get("label") or code,
                                "candidates": []}
                    lists.append(existing)
                existing["candidates"].append(entry)
            for g in lists:
                g["candidates"].sort(key=lambda x: x["pos"] or 99)

        allp = list(people.values())
        stats = {
            "candidates": len(cands),
            "persons": len(allp),
            "ever_won": sum(1 for p in allp if p["won"] > 0),
            "debut": sum(1 for p in allp if p["stood"] == 1),
            "fillers3": sum(1 for p in allp if p["stood"] >= 3 and p["won"] == 0),
        }
        build["ballots"].append({**b, "stats": stats, "lists": lists})
        print(f"{b['id']}: {stats['candidates']} kandidata, {len(lists)} subjekata")

    # churn: 2018->2022 retention + 2022 winners on 2026 ballots
    ballot_names = {b["id"]: {norm(c["name"]) for l in b["lists"] for c in l["candidates"]} for b in build["ballots"]}
    all_names_26 = set().union(*ballot_names.values())
    for bid, area, lvl in CHURN_UNITS:
        def mandates(year):
            return {norm(m["name"]) for m in paged(f"/mandates?year={year}")
                    if (m.get("area") or {}).get("id") == area and (m.get("level") or {}).get("id") == lvl}
        w18, w22 = mandates(2018), mandates(2022)
        build["churn"][bid] = {
            "m22": len(w22),
            "kept_18_22": len(w18 & w22),
            "running_same_race": len(w22 & ballot_names.get(bid, set())),
            "moved_up": sorted(w22 & (all_names_26 - ballot_names.get(bid, set()))),
            "gone": sorted(w22 - all_names_26),
        }
        print(f"churn {bid}: kept {build['churn'][bid]['kept_18_22']}/{len(w22)}")

    json.dump(build, open("data/build.json", "w"), ensure_ascii=False, indent=1)
    print("data/build.json written")


if __name__ == "__main__":
    main()
