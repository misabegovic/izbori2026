#!/usr/bin/env python3
"""Fetch parliamentary behaviour + person profiles from Mashinerija -> data/.

Covers what the API carries with roll-call votes: Predstavnički dom PSBiH and
Narodna skupština RS, saziv 2022–2026. Also biographies, portraits, declared
assets, party funding and speeches — for 2026 candidates only.

Outputs:
  data/divisions.json   — every roll-call division (chamber, sitting, agenda text, counts)
  data/outcomes.json    — adopted / rejected per division (from transcripts)
  data/votes.json       — {personId: [[divisionId, vote], ...]} for 2026 candidates with a record
  data/records.json     — {personId: {chamber, saziv, counted{...}, publicId}} for those candidates
  data/profiles.json    — {personId: {publicId, bio{...}, portrait{...}, assets[...], speeches n}}
  data/parties.json     — {code: {name, stood, won, funding[...]}}
  data/speeches.json    — {personId: [{sitting, date, agendaItem, words, text(trunc)}]} candidates only
Run manually; render.py consumes the committed files.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://api.gianniravioli.com/mashinerija/v1"
UA = {"User-Agent": "izbori2026-voter-guide/1.0 (github.com/misabegovic/izbori2026)"}
SAZIV = "2022-2026"


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:  # noqa
            if i == tries - 1:
                raise
            time.sleep(2 ** i)


def paged(path, limit=200, log=None):
    out, off = [], 0
    while True:
        d = get(f"{BASE}{path}{'&' if '?' in path else '?'}limit={limit}&offset={off}")
        out += d["data"]
        tot = d["meta"]["total"]
        if log:
            print(f"   {log}: {min(off + limit, tot)}/{tot}", end="\r", flush=True)
        if off + limit >= tot:
            if log:
                print()
            return out
        off += limit


def q(s):
    return urllib.parse.quote(s, safe="")


def main():
    people = json.load(open("data/people_cache.json"))  # personId -> summary (2026 candidates)
    cand_pids = set(people)

    # 1. divisions + outcomes (both chambers)
    print("1/6 glasanja (divisions)…")
    divisions = {}
    for row in paged("/divisions", log="divisions"):
        divisions[row["divisionId"]] = {
            "chamber": row["sitting"]["href"].split("/")[-1] if False else None,
            "sitting": row["sitting"]["id"], "sittingLabel": row["sitting"]["label"],
            "votedAt": row.get("votedAt"), "agendaItem": row.get("agendaItem"),
            "subject": row.get("subject"), "agenda": row.get("agenda"),
            "round": row.get("round"), "repeated": row.get("repeated"), "annulled": row.get("annulled"),
            "published": row.get("published"),
        }
    sittings = {}
    for s in paged("/sittings", log="sittings"):
        sittings[s["sittingId"]] = {"chamber": s["chamber"]["id"], "title": s.get("title"),
                                    "heldOn": s.get("heldOn"), "saziv": s.get("saziv")}
    for d in divisions.values():
        st = sittings.get(d["sitting"], {})
        d["chamber"] = st.get("chamber")
        d["heldOn"] = st.get("heldOn")
        d["saziv"] = st.get("saziv")
    json.dump(divisions, open("data/divisions.json", "w"), ensure_ascii=False)
    outcomes = {}
    for o in paged("/outcomes", log="outcomes"):
        if o.get("division"):
            outcomes[o["division"]["id"]] = {"adopted": o.get("adopted"), "entityMajority": o.get("entityMajority"),
                                             "generalMajority": o.get("generalMajority"), "narrated": o.get("narrated"),
                                             "verbatim": o.get("verbatim")}
    json.dump(outcomes, open("data/outcomes.json", "w"), ensure_ascii=False)
    print(f"   {len(divisions)} glasanja, {len(sittings)} sjednica, {len(outcomes)} ishoda")

    # 2. voting records -> which record-holders are 2026 candidates
    print("2/6 glasački učinak…")
    vrs = paged("/voting-records", log="records")
    pub_ids = sorted({r["person"]["id"] for r in vrs if r.get("person")})

    def resolve(pub):
        try:
            d = get(f"{BASE}/persons/{q(pub)}")["data"]
            return pub, d.get("personId"), d
        except Exception:
            return pub, None, None
    pub_to_pid, person_detail = {}, {}
    with ThreadPoolExecutor(16) as ex:
        for pub, pid, d in ex.map(resolve, pub_ids):
            if pid:
                pub_to_pid[pub] = pid
                person_detail[pid] = d
    records = {}
    for r in vrs:
        pub = (r.get("person") or {}).get("id")
        pid = pub_to_pid.get(pub)
        if not pid or pid not in cand_pids:
            continue
        rec = records.setdefault(pid, {"publicId": pub, "chambers": []})
        rec["chambers"].append({"chamber": r["chamber"]["id"], "saziv": r.get("saziv"),
                                "divisions": r.get("divisions"), "counted": r.get("counted"),
                                "seatBasis": r.get("seatBasis"), "firstSeen": r.get("firstSeen"),
                                "lastSeen": r.get("lastSeen")})
    json.dump(records, open("data/records.json", "w"), ensure_ascii=False, indent=1)
    print(f"   {len(vrs)} zapisa, {len(records)} pripada kandidatima 2026")

    # 3. every vote of every candidate with a record
    print("3/6 pojedinačni glasovi…")
    votes = {}
    if os.path.exists("data/votes.json"):
        votes = json.load(open("data/votes.json"))

    def person_votes(pid):
        pub = records[pid]["publicId"]
        try:
            rows = paged(f"/persons/{q(pub)}/votes")
            return pid, [[v["division"]["id"], v["vote"], bool(v.get("annulled"))] for v in rows if v.get("division")]
        except Exception as e:
            print("   !", pid, e)
            return pid, None
    todo = [pid for pid in records if pid not in votes]
    done = 0
    with ThreadPoolExecutor(8) as ex:
        for pid, v in ex.map(person_votes, todo):
            done += 1
            print(f"   {done}/{len(todo)}", end="\r", flush=True)
            if v is not None:
                votes[pid] = v
                if done % 10 == 0:
                    json.dump(votes, open("data/votes.json", "w"), ensure_ascii=False)
    print()
    json.dump(votes, open("data/votes.json", "w"), ensure_ascii=False)
    print(f"   {len(votes)} osoba, {sum(len(v) for v in votes.values())} glasova")

    # 4. profiles: publicId for all notable candidates, bios, portraits, assets
    print("4/6 profili…")
    profiles = {}
    if os.path.exists("data/profiles.json"):
        profiles = json.load(open("data/profiles.json"))
    notable = [pid for pid, p in people.items() if (p.get("won") or 0) > 0 or p.get("isOfficeHolder") or p.get("hasBiography")]
    todo = [pid for pid in notable if pid not in profiles]

    def detail(pid):
        if pid in person_detail:
            return pid, person_detail[pid]
        try:
            return pid, get(f"{BASE}/persons/{q(pid)}")["data"]
        except Exception:
            return pid, None
    done = 0
    with ThreadPoolExecutor(16) as ex:
        for pid, d in ex.map(detail, todo):
            done += 1
            print(f"   {done}/{len(todo)}", end="\r", flush=True)
            if d:
                profiles[pid] = {"publicId": d.get("publicId"), "partyCount": d.get("partyCount"),
                                 "hasPortrait": d.get("hasPortrait"), "hasBiography": d.get("hasBiography"),
                                 "confidence": d.get("confidence"), "confidenceNote": d.get("confidenceNote"),
                                 "pageUrl": d.get("pageUrl")}
    print()
    json.dump(profiles, open("data/profiles.json", "w"), ensure_ascii=False)
    pub_to_pid_all = {v["publicId"]: k for k, v in profiles.items() if v.get("publicId")}

    bios = paged("/biographies", log="biographies")
    nb = 0
    for b in bios:
        pid = pub_to_pid_all.get((b.get("person") or {}).get("id"))
        if pid:
            profiles[pid]["bio"] = {f["field"]: {"value": f["value"], "src": f.get("sourceId"), "url": f.get("documentUrl")}
                                    for f in b.get("fields", [])}
            nb += 1
    ports = paged("/portraits", log="portraits")
    npo = 0
    for p in ports:
        pid = pub_to_pid_all.get((p.get("person") or {}).get("id"))
        if pid:
            profiles[pid]["portrait"] = {"grade": p.get("grade"), "licence": p.get("licence"), "credit": p.get("credit"),
                                         "sourceUrl": p.get("sourceUrl"), "ref": p.get("ref")}
            npo += 1
    assets = paged("/assets/summary", log="assets")
    na = 0
    for a in assets:
        pid = pub_to_pid_all.get((a.get("person") or {}).get("id"))
        if pid:
            profiles[pid].setdefault("assets", []).append(
                {"src": a.get("sourceId"), "kind": a.get("kind"), "currency": a.get("currency"),
                 "holdings": a.get("holdings"), "valued": a.get("valued"), "totalFening": a.get("totalFening")})
            na += 1
    json.dump(profiles, open("data/profiles.json", "w"), ensure_ascii=False)
    print(f"   {len(profiles)} profila: {nb} biografija, {npo} portreta, {na} redova imovine")

    # 5. parties + funding
    print("5/6 stranke i finansiranje…")
    parties = {}
    for p in paged("/parties?year=2026", log="parties"):
        parties[p["code"]] = {"name": p.get("name"), "slug": p.get("slug"), "stood": p.get("stood"), "won": p.get("won"),
                              "firstYear": p.get("firstYear"), "inFunding": p.get("inFunding"), "names": p.get("names"),
                              "pageUrl": p.get("pageUrl"), "funding": []}
    for f in paged("/funding", log="funding"):
        code = (f.get("party") or {}).get("id") or f.get("subjectCode")
        if code in parties:
            parties[code]["funding"].append({"year": f.get("year"), "payer": (f.get("payer") or {}).get("label"),
                                             "paid": (f.get("paid") or {}).get("value"),
                                             "planned": (f.get("planned") or {}).get("value")})
    json.dump(parties, open("data/parties.json", "w"), ensure_ascii=False, indent=1)
    print(f"   {len(parties)} subjekata 2026")

    # 6. speeches of candidates with records (truncated text)
    print("6/6 govori…")
    speeches = {}
    allsp = paged("/speeches", log="speeches")
    pub_rec = {v["publicId"]: k for k, v in records.items()}
    for s in allsp:
        pid = pub_rec.get((s.get("person") or {}).get("id"))
        if not pid or s.get("collective"):
            continue
        speeches.setdefault(pid, []).append({"sitting": s["sitting"]["id"], "agendaItem": s.get("agendaItem"),
                                             "words": s.get("words"), "role": s.get("role"),
                                             "text": (s.get("text") or "")[:600]})
    json.dump(speeches, open("data/speeches.json", "w"), ensure_ascii=False)
    print(f"   {sum(len(v) for v in speeches.values())} govora za {len(speeches)} kandidata")


if __name__ == "__main__":
    main()
