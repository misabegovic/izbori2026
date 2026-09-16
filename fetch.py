#!/usr/bin/env python3
"""Fetch election data from the Mashinerija open API -> data/ (national coverage).

Source: https://gianniravioli.com/mashinerija/ (CC BY 4.0 — attribution required).
Outputs:
  data/national.json       — race summaries + national party comparison 2018/2022/2026
  data/units/<race>-<area>.json — per-unit candidates, stats, party history, churn
  data/municipalities.json — općina -> ballots mapping (scraped from site index)
Run manually to refresh committed data; render.py consumes it.
"""
import json
import re
import html as htmllib
import urllib.request
import urllib.parse
import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

BASE = "https://api.gianniravioli.com/mashinerija/v1"
UA = {"User-Agent": "izbori2026-voter-guide/1.0 (github.com/misabegovic/izbori2026)"}

RACES = [  # (race2026, race2022, race2018, level_id, title, entity_scope)
    ("oi2026-1", "32-1", "25-1", "predsjednistvo", "Predsjedništvo BiH", "država"),
    ("oi2026-2", "32-2", "25-2", "pd-psbih", "Predstavnički dom PSBiH", "država"),
    ("oi2026-4", "32-4", "25-4", "pd-fbih", "Predstavnički dom Parlamenta FBiH", "fbih"),
    ("oi2026-5", "32-5", "25-5", "predsjednik-rs", "Predsjednik i potpredsjednici RS", "rs"),
    ("oi2026-6", "32-6", "25-6", "nsrs", "Narodna skupština RS", "rs"),
    ("oi2026-7", "32-7", "25-7", "skupstine-kantona", "Skupštine kantona", "fbih"),
]

# label fragments seen on the site index -> (race2026, areaCode)
def unit_label_to_ref(label):
    m = re.search(r"Predstavnički dom PSBiH (\d)A", label)
    if m: return ("oi2026-2", f"51{m.group(1)}")
    m = re.search(r"Predstavnički dom PSBiH (\d)B", label)
    if m: return ("oi2026-2", f"52{m.group(1)}")
    m = re.search(r"Predstavnički dom FBiH (\d+)", label)
    if m: return ("oi2026-4", f"4{int(m.group(1)):02d}")
    m = re.search(r"Narodna skupština RS (\d+)", label)
    if m: return ("oi2026-6", f"3{int(m.group(1)):02d}")
    return None

CANTON_AREA = {  # kanton name (lowercase) -> skupština area
    "unsko-sanski kanton": "201", "posavski kanton": "202", "tuzlanski kanton": "203",
    "zeničko-dobojski kanton": "204", "bosansko-podrinjski kanton": "205",
    "srednjobosanski kanton": "206", "hercegovačko-neretvanski kanton": "207",
    "zapadnohercegovački kanton": "208", "kanton sarajevo": "209", "kanton 10": "210",
}


def get(url, raw=False):
    req = urllib.request.Request(url, headers=UA)
    r = urllib.request.urlopen(req, timeout=90)
    return r.read().decode("utf-8", "replace") if raw else json.load(r)


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


def scrape_unit_membership(race, area):
    """Unit page -> {MEMBER NAME: subject name} for party-less coalition resolution."""
    slug = {"oi2026-2": "psbih", "oi2026-4": "parlament-fbih", "oi2026-6": "nsrs", "oi2026-7": "skupstine-kantona"}.get(race)
    if not slug:
        return {}
    try:
        raw = get(f"https://gianniravioli.com/mashinerija/izbori-2026/{slug}/{area}/", raw=True)
    except Exception:
        return {}
    raw = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S)
    t = htmllib.unescape(re.sub(r"<[^>]+>", "\n", raw))
    lines = [l.strip() for l in t.split("\n") if l.strip()]
    i = next((k for k, l in enumerate(lines) if "Skok na subjekt" in l), None)
    if i is None:
        return {}
    pairs, j = [], i + 1
    while j + 1 < len(lines) and re.fullmatch(r"\d+", lines[j + 1]):
        pairs.append((lines[j], int(lines[j + 1]))); j += 2
    membership = {}
    for nm, cnt in pairs:
        for k in range(j, len(lines) - 1):
            if lines[k] == nm and re.fullmatch(r"\d+ kandidat.*", lines[k + 1] or ""):
                found = []
                for m in range(k + 2, min(k + 2 + 4 * cnt + 60, len(lines) - 1)):
                    if re.fullmatch(r"\d+", lines[m]) and re.fullmatch(r"[A-ZČĆŽŠĐА-ЯЂЈЉЊЋЏ][A-ZČĆŽŠĐА-ЯЂЈЉЊЋЏ\s\-\.\']+", lines[m + 1] or ""):
                        found.append(lines[m + 1])
                        if len(found) >= cnt:
                            break
                for member in found:
                    membership[member] = nm
                break
    return membership


def scrape_municipalities():
    """Index page -> [{name, slug, group, entity, refs:[(race,area)], extra_labels}]"""
    raw = get("https://gianniravioli.com/mashinerija/izbori-2026/", raw=True)
    raw = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S)
    out = []
    for block in re.findall(r"<details.*?</details>", raw, flags=re.S):
        m = re.search(r'class="label"[^>]*>([^<]+)', block)
        if not m:
            continue
        group = htmllib.unescape(m.group(1)).strip()
        note = re.search(r'class="note quiet"[^>]*>(.*?)</div>', block, flags=re.S)
        shared = []
        if note:
            txt = htmllib.unescape(re.sub(r"<[^>]+>", " ", note.group(1)))
            for part in txt.replace("Svima zajedničko:", "").split("·"):
                part = part.strip().rstrip(".")
                if not part:
                    continue
                ref = unit_label_to_ref(part)
                if ref:
                    shared.append(ref)
                elif part.lower() in CANTON_AREA:
                    shared.append(("oi2026-7", CANTON_AREA[part.lower()]))
        entity = "rs" if group.lower().startswith(("republika srpska", "istočno sarajevo")) else ("brcko" if "brčko" in group.lower() else "fbih")
        for em in re.finditer(r'<li class="entry[^"]*".*?</li>', block, flags=re.S):
            entry = em.group(0)
            am = re.search(r'href="/mashinerija/jedinice/([^/"]+)/[^>]*>([^<]+)</a>', entry)
            if not am:
                continue
            slug, name = am.group(1), htmllib.unescape(am.group(2)).strip()
            mm = re.search(r'class="meta"[^>]*>(.*?)</p>', entry, flags=re.S)
            spans = re.findall(r"<span[^>]*>([^<]+)</span>", mm.group(1)) if mm else []
            refs = list(shared)
            for lbl in spans:
                lbl = htmllib.unescape(lbl).strip()
                ref = unit_label_to_ref(lbl)
                if ref and ref not in refs:
                    refs.append(ref)
                elif lbl.lower() in CANTON_AREA and ("oi2026-7", CANTON_AREA[lbl.lower()]) not in refs:
                    refs.append(("oi2026-7", CANTON_AREA[lbl.lower()]))
            out.append({"name": name, "slug": slug, "group": group, "entity": entity, "refs": refs})
    return out


def scrape_party_names(units):
    """Unit pages jump-lists -> {code: printed name} (API leaves coalition names null)."""
    names = json.load(open("data/party_names.json")) if os.path.exists("data/party_names.json") else {}
    race_page = {"oi2026-2": "psbih", "oi2026-4": "parlament-fbih", "oi2026-6": "nsrs", "oi2026-7": "skupstine-kantona"}
    for (race, area) in units:
        slug = race_page.get(race)
        if not slug:
            continue
        try:
            raw = get(f"https://gianniravioli.com/mashinerija/izbori-2026/{slug}/{area}/", raw=True)
        except Exception:
            continue
        raw = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S)
        t = htmllib.unescape(re.sub(r"<[^>]+>", "\n", raw))
        lines = [l.strip() for l in t.split("\n") if l.strip()]
        idx = next((i for i, l in enumerate(lines) if "Skok na subjekt" in l), None)
        if idx is None:
            continue
        pairs, j = [], idx + 1
        while j + 1 < len(lines) and re.fullmatch(r"\d+", lines[j + 1]):
            pairs.append((lines[j], int(lines[j + 1]))); j += 2
        for nm, _cnt in pairs:
            names.setdefault("_labels_seen", []).append(nm)
        # codes in ballot order for this unit come from candidacies; resolved later in merge step
        names.setdefault("_pages", {})[f"{race}-{area}"] = [nm for nm, _ in pairs]
    return names


def main():
    os.makedirs("data/units", exist_ok=True)
    started = datetime.now(timezone.utc)
    print("1/7 općine…")
    municipalities = scrape_municipalities()
    json.dump(municipalities, open("data/municipalities.json", "w"), ensure_ascii=False, indent=1)
    print(f"   {len(municipalities)} općina")

    print("2/7 sve kandidature 2026…")
    all_cands = {}
    for race, _, _, _, title, _ in RACES:
        all_cands[race] = paged(f"/races/{race}/candidacies")
        print(f"   {race}: {len(all_cands[race])}")

    print("3/7 osobe…")
    pids = sorted({(c.get("person") or {}).get("id") for c in sum(all_cands.values(), []) if (c.get("person") or {}).get("id")})
    people = {}
    if os.path.exists("data/people_cache.json"):
        people = json.load(open("data/people_cache.json"))
    todo = [p for p in pids if p not in people]
    print(f"   cache: {len(people)}, za povući: {len(todo)}")
    def enrich(pid):
        try:
            d = get(f"{BASE}/persons/{urllib.parse.quote(pid, safe='')}")["data"]
            return pid, {k: d.get(k) for k in ("stood", "won", "firstYear", "lastYear", "isOfficeHolder", "hasBiography", "confidence")}
        except Exception:
            return pid, None
    if todo:
        with ThreadPoolExecutor(24) as ex:
            for pid, p in ex.map(enrich, todo):
                if p:
                    people[pid] = p
        json.dump(people, open("data/people_cache.json", "w"), ensure_ascii=False)
    print(f"   {len(people)} osoba")

    print("4/7 historija stranaka 2018/2022…")
    party_hist = {}  # (level, area) -> [{party, votes, year}]
    for _, r22, r18, lvl, _, _ in RACES:
        for year, rid in ((2022, r22), (2018, r18)):
            for row in paged(f"/races/{rid}/results"):
                area = (row.get("area") or {}).get("id")
                party = (row.get("party") or {}).get("label") or (row.get("party") or {}).get("id")
                if area and party:
                    party_hist.setdefault((lvl, str(area)), []).append(
                        {"year": year, "party": party, "votes": row.get("votes")})
    print(f"   {len(party_hist)} jedinica")

    print("5/7 mandati 2018/2022…")
    winners = {}  # (level, area, year) -> set(norm names)
    for year in (2018, 2022):
        for m in paged(f"/mandates?year={year}"):
            lvl, area = (m.get("level") or {}).get("id"), str((m.get("area") or {}).get("id"))
            winners.setdefault((lvl, area, year), set()).add(norm(m.get("name")))
    print(f"   {len(winners)} grupa")

    print("6/7 jedinice…")
    race_meta = {r[0]: r for r in RACES}
    race_page = {"oi2026-2": "psbih", "oi2026-4": "parlament-fbih", "oi2026-6": "nsrs", "oi2026-7": "skupstine-kantona"}
    unit_keys = set()
    for race, cands in all_cands.items():
        for c in cands:
            a = (c.get("area") or {}).get("id")
            if a:
                unit_keys.add((race, str(a)))
    party_names = json.load(open("data/party_names.json"))
    party_names = {k: v for k, v in party_names.items() if not k.startswith("_")}

    def page_pairs(race, area):
        slug = race_page.get(race)
        if not slug:
            return []
        try:
            raw = get(f"https://gianniravioli.com/mashinerija/izbori-2026/{slug}/{area}/", raw=True)
        except Exception:
            return []
        raw = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S)
        t = htmllib.unescape(re.sub(r"<[^>]+>", "\n", raw))
        lines = [l.strip() for l in t.split("\n") if l.strip()]
        idx = next((i for i, l in enumerate(lines) if "Skok na subjekt" in l), None)
        if idx is None:
            return []
        pairs, j = [], idx + 1
        while j + 1 < len(lines) and re.fullmatch(r"\d+", lines[j + 1]):
            pairs.append((lines[j], int(lines[j + 1]))); j += 2
        return pairs

    for race, area in sorted(unit_keys):
        cands = [c for c in all_cands[race] if str((c.get("area") or {}).get("id")) == area]
        lvl = race_meta[race][3]
        # resolve party-less coalition candidacies by member names scraped from the unit page
        if any((c.get("party") or {}).get("id") is None for c in cands):
            membership = scrape_unit_membership(race, area)
        else:
            membership = {}
        import hashlib
        for c in cands:
            pid = (c.get("party") or {}).get("id")
            if pid is None:
                subj = membership.get(c["name"])
                c["_subj"] = subj
                c["_code"] = (f"{race}{area}-X" + hashlib.md5(subj.encode()).hexdigest()[:8]) if subj else f"{race}{area}-NONE"
            else:
                c["_subj"] = None
                c["_code"] = pid
        # name resolution for label-less numeric codes: ordered zip, then count-match
        raw_groups = []
        for c in cands:
            if not raw_groups or raw_groups[-1][0] != c["_code"]:
                raw_groups.append([c["_code"], 0])
            raw_groups[-1][1] += 1
        needs = {code for code, _ in raw_groups
                 if "-X" not in code and "-NONE" not in code and code not in party_names
                 and not any((c.get("party") or {}).get("label") for c in cands if c["_code"] == code)}
        if needs:
            pairs = page_pairs(race, area)
            used = set()
            gi = 0
            for pi, (nm, pcnt) in enumerate(pairs):
                # accumulate adjacent same-code blocks
                tot = 0; codes_here = []
                while gi < len(raw_groups) and tot < pcnt:
                    tot += raw_groups[gi][1]; codes_here.append(raw_groups[gi][0]); gi += 1
                if tot == pcnt:
                    for code in codes_here:
                        if code in needs:
                            party_names[code] = nm; used.add(pi)
            # fallback: count-match remaining
            for code in list(needs - set(party_names)):
                cnt = sum(c for cd, c in raw_groups if cd == code)
                cand = [(pi, nm) for pi, (nm, pc) in enumerate(pairs) if pc == cnt and pi not in used]
                if len(cand) == 1:
                    party_names[code] = cand[0][1]
        groups = {}
        order = []
        for c in cands:
            code = c["_code"]
            if code not in groups:
                groups[code] = {"code": code,
                                "name": c.get("_subj") or party_names.get(code) or (c.get("party") or {}).get("label") or code,
                                "candidates": []}
                order.append(code)
            rec = people.get((c.get("person") or {}).get("id")) or {}
            groups[code]["candidates"].append({
                "pos": c.get("position"), "name": c["name"],
                "pid": (c.get("person") or {}).get("id"),
                "stood": rec.get("stood"), "won": rec.get("won"),
                "office": rec.get("isOfficeHolder"), "bio": rec.get("hasBiography"),
                "confidence": rec.get("confidence"),
            })
        lists = [groups[k] for k in order]
        for g in lists:
            g["candidates"].sort(key=lambda x: x["pos"] or 99)
        unit_people = [people[(c.get("person") or {}).get("id")] for c in cands if (c.get("person") or {}).get("id") in people]
        stats = {"candidates": len(cands), "persons": len(unit_people),
                 "ever_won": sum(1 for p in unit_people if p["won"] > 0),
                 "debut": sum(1 for p in unit_people if p["stood"] == 1),
                 "fillers3": sum(1 for p in unit_people if (p["stood"] or 0) >= 3 and p["won"] == 0)}
        w18 = winners.get((lvl, area, 2018), set())
        w22 = winners.get((lvl, area, 2022), set())
        names26 = {norm(c["name"]) for c in cands}
        churn = {"m18": len(w18), "m22": len(w22), "kept_18_22": len(w18 & w22),
                 "running_again": len(w22 & names26),
                 "gone": sorted(w22 - names26)}
        hist = sorted(party_hist.get((lvl, area), []), key=lambda r: -(r["votes"] or 0))
        json.dump({"race": race, "area": area, "title": race_meta[race][4],
                   "stats": stats, "lists": lists, "churn": churn, "party_history": hist},
                  open(f"data/units/{race}-{area}.json", "w"), ensure_ascii=False, indent=1)
    print(f"   {len(unit_keys)} jedinica")
    json.dump(party_names, open("data/party_names.json", "w"), ensure_ascii=False, indent=1)

    print("6.5/7 glasanja poslanika + historije kandidata…")
    # PSBiH incumbents (2022 winners) running again in 2026 -> voting aggregates + speeches
    # PSBiH incumbents (2022 winners) running again in 2026 -> voting aggregates + speeches
    mp_winners22 = set()
    for (lvl, area, year), ns in winners.items():
        if lvl == "pd-psbih" and year == 2022:
            mp_winners22 |= ns
    name26_to_pid = {}
    for race, cands in all_cands.items():
        for c in cands:
            pid = (c.get("person") or {}).get("id")
            if pid:
                name26_to_pid.setdefault(norm(c["name"]), pid)
    mps = {}
    def mp_stats(item):
        nm, pid = item
        try:
            v = {k: get(f"{BASE}/persons/{urllib.parse.quote(pid, safe='')}/votes?vote={k}&limit=1")["meta"]["total"]
                 for k in ("za", "protiv", "suzdrzan")}
            sp = get(f"{BASE}/persons/{urllib.parse.quote(pid, safe='')}/speeches?limit=1")["meta"]["total"]
            return nm, {"pid": pid, "votes": v, "speeches": sp}
        except Exception:
            return nm, None
    todo = [(nm, name26_to_pid[nm]) for nm in mp_winners22 if nm in name26_to_pid]
    with ThreadPoolExecutor(12) as ex:
        for nm, r in ex.map(mp_stats, todo):
            if r:
                mps[nm] = r
    json.dump(mps, open("data/mps.json", "w"), ensure_ascii=False, indent=1)
    print(f"   {len(mps)} poslanika sa zapisom glasanja")

    # full candidacy timelines for anyone who ever won or holds office
    notable = [pid for pid, p in people.items() if p.get("won", 0) > 0 or p.get("isOfficeHolder")]
    def timeline(pid):
        try:
            rows = get(f"{BASE}/persons/{urllib.parse.quote(pid, safe='')}/candidacies")["data"]
            return pid, [{"y": r.get("year"), "lvl": (r.get("level") or {}).get("label"),
                          "area": (r.get("area") or {}).get("label"),
                          "party": (r.get("party") or {}).get("label"),
                          "pos": r.get("position"), "votes": r.get("votes"),
                          "elected": r.get("elected")} for r in rows]
        except Exception:
            return pid, None
    timelines = {}
    with ThreadPoolExecutor(24) as ex:
        for pid, t in ex.map(timeline, notable):
            if t:
                timelines[pid] = t
    json.dump(timelines, open("data/timelines.json", "w"), ensure_ascii=False)
    print(f"   {len(timelines)} historija kandidata")

    print("7/7 nacionalna slika…")
    allp = list(people.values())
    national = {
        "generated": started.isoformat(),
        "candidacies": sum(len(v) for v in all_cands.values()),
        "persons": len(allp),
        "ever_won": sum(1 for p in allp if p["won"] > 0),
        "debut": sum(1 for p in allp if p["stood"] == 1),
        "fillers3": sum(1 for p in allp if (p["stood"] or 0) >= 3 and p["won"] == 0),
        "fillers5": sum(1 for p in allp if (p["stood"] or 0) >= 5 and p["won"] == 0),
        "races": [{"race": r, "title": t, "scope": s,
                   "candidates": len(all_cands[r]),
                   "units": len({str((c.get("area") or {}).get("id")) for c in all_cands[r]})}
                  for r, _, _, _, t, s in RACES],
    }
    json.dump(national, open("data/national.json", "w"), ensure_ascii=False, indent=1)
    print("gotovo.")


if __name__ == "__main__":
    main()
