#!/usr/bin/env python3
"""Wikidata → data/offices.json: funkcije koje CIK nikad nije objavio.

Why this exists: CIK publishes candidacies, and only those. It has no record of the
2010 and 2014 general elections at all — the 2010 archive cannot be read by anyone
because its ViewState fails MAC validation behind CIK's own balancer, and the single
2014 result set was never actually published, so its database is gone. Bakir
Izetbegović sat in the Presidency for those eight years and the election record is
simply silent about it.

It is also silent about every office nobody is directly elected to: ministers,
delegates in the two Houses of Peoples, entity prime ministers, party leaders.
A voter asking "what has this person actually done" is asking about those.

Wikidata publishes them with start and end dates and an item to check, under CC0.
It is not CIK and render.py has to say so on the page: this is a separate block,
labelled with its source, and it never feeds a number the election record produces.

Matching is the risk. Two links are used and the stronger one wins:
  mashinerija  — the compiler already resolved this QID onto a person; we inherit it
  ime          — exact folded-name match, and only when that name belongs to exactly
                 one identity on the 2026 ballots after merging

Run manually to refresh committed data; render.py consumes it.
"""
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

WD = "https://www.wikidata.org/w/api.php"
MASH = "https://api.gianniravioli.com/mashinerija/v1"
UA = {"User-Agent": "izbori2026-voter-guide/1.0 (https://github.com/misabegovic/izbori2026)"}
D = "data/"
CACHE = ".cache/wikidata.json"   # discovery is 50 searches; keep it out of the way of reruns
LANGS = "bs|hr|sr|sh|en"

# 2026 race id → the level id both CIK and Wikidata can be read against
RACE_LEVEL = {
    "oi2026-1": "predsjednistvo", "oi2026-2": "pd-psbih", "oi2026-4": "pd-fbih",
    "oi2026-5": "predsjednik-rs", "oi2026-6": "nsrs", "oi2026-7": "skupstine-kantona",
}

# Wikimedia rate-limits shared egress hard; this is somebody's free service.
PAUSE = 0.7


def wd(params, tries=10):
    """Wikimedia throttles hard and shares its limit across whoever else is on this
    egress, so a 429 is normal rather than exceptional: back off long, not briefly."""
    url = WD + "?" + urllib.parse.urlencode(dict(params, format="json"))
    for attempt in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503):
                raise
        except Exception:
            pass
        time.sleep(min(60, 5 * 2 ** attempt))
    raise RuntimeError(f"Wikidata odbija: {url}")


def mash(path, tries=4):
    for attempt in range(tries):
        try:
            return json.load(urllib.request.urlopen(
                urllib.request.Request(MASH + path, headers=UA), timeout=120))
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def search(query):
    """Every item matching a CirrusSearch statement query."""
    out, off = set(), 0
    while True:
        d = wd({"action": "query", "list": "search", "srsearch": query,
                "srlimit": 50, "sroffset": off, "srnamespace": 0})
        hits = d["query"]["search"]
        out |= {h["title"] for h in hits}
        off += 50
        if not hits or off >= d["query"]["searchinfo"]["totalhits"]:
            return out
        time.sleep(PAUSE)


def entities(qids, props="labels|aliases|claims|sitelinks"):
    out = {}
    qids = sorted(qids)
    for i in range(0, len(qids), 50):
        d = wd({"action": "wbgetentities", "ids": "|".join(qids[i:i + 50]),
                "props": props, "languages": LANGS})
        out.update(d.get("entities", {}))
        time.sleep(PAUSE)
    return out


def claim_ids(entity, prop):
    out = []
    for st in (entity.get("claims") or {}).get(prop, []):
        v = (((st.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {})
        if v.get("id"):
            out.append(v["id"])
    return out


def label(entity):
    for lang in ("bs", "hr", "sr", "sh", "en"):
        v = (entity.get("labels") or {}).get(lang)
        if v:
            return v["value"]
    return entity.get("id")


# Cyrillic labels are common on Wikidata for RS politicians, and CIK prints Latin.
# Without this the fold of "Елмедин Конаковић" is the empty string, which then matches
# every candidate whose name also folds to nothing — the first draft of this file
# attached the foreign minister to eleven thousand people that way.
CYR = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Ђ": "DJ", "Е": "E", "Ж": "Z",
    "З": "Z", "И": "I", "Ј": "J", "К": "K", "Л": "L", "Љ": "LJ", "М": "M", "Н": "N",
    "Њ": "NJ", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "Ћ": "C", "У": "U",
    "Ф": "F", "Х": "H", "Ц": "C", "Ч": "C", "Џ": "DZ", "Ш": "S",
}


def fold(text):
    """Comparable form of a personal name: Cyrillic to Latin, diacritics dropped,
    tokens sorted, so 'IZETBEGOVIĆ BAKIR' and 'Bakir Izetbegović' meet.

    Returns None when what is left is not a name, which is the only safe answer:
    an empty key would match everything."""
    text = (text or "").upper()
    text = "".join(CYR.get(c, c) for c in text)
    text = text.replace("Đ", "DJ")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    parts = sorted(re.sub(r"[^A-Z ]", " ", text).split())
    if len(parts) < 2 or sum(len(p) for p in parts) < 5:
        return None
    return " ".join(parts)


def cached(name, build):
    """Discovery costs fifty searches against somebody's free service. Do it once."""
    store = {}
    if os.path.exists(CACHE):
        store = json.load(open(CACHE))
    if name not in store or os.environ.get("WD_REFRESH"):
        store[name] = build()
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        json.dump(store, open(CACHE, "w"), ensure_ascii=False)
    return store[name]


def discover():
    """QIDs of people who have held office in BiH.

    Two passes, because neither alone is enough: the first finds people tagged as
    BiH politicians, the second walks back from every office those people held and
    picks up whoever holds the same office without the citizenship or occupation
    statement. That second pass is what catches ministers and mayors.
    """
    found = set()
    for q in ("haswbstatement:P27=Q225 haswbstatement:P106=Q82955",
              "haswbstatement:P27=Q225 haswbstatement:P39"):
        s = search(q)
        print(f"   {q} → {len(s)}")
        found |= s
        time.sleep(PAUSE)

    ents = entities(found)
    positions = {q for e in ents.values() for q in claim_ids(e, "P39")}
    plabels = entities(sorted(positions), props="labels|claims")

    bih = []
    for q, e in plabels.items():
        scope = {x for p in ("P1001", "P17") for x in claim_ids(e, p)}
        name = label(e)
        if scope & {"Q225", "Q11198", "Q164423", "Q194318"} or \
           any(w in name for w in ("Bosn", "Srpske", "Federacije", "Herzegovina", "Hercegovine")):
            bih.append(q)
    print(f"   {len(positions)} funkcija, od toga {len(bih)} bosanskohercegovačkih")

    for q in bih:
        found |= search(f"haswbstatement:P39={q}")
        time.sleep(PAUSE / 2)
    print(f"   ukupno {len(found)} osoba")
    return sorted(found), sorted(positions)


def time_value(snaks):
    for s in snaks or ():
        v = (s.get("datavalue") or {}).get("value") or {}
        t = v.get("time")
        if t:
            return t[1:11].replace("-00", "-01")
    return None


def id_value(snaks):
    for s in snaks or ():
        v = (s.get("datavalue") or {}).get("value") or {}
        if v.get("id"):
            return v["id"]
    return None


# Wikidata labels for BiH offices are uneven: some items have no Bosnian label, a few
# name the ministry instead of the minister, and one names a list of mayors instead of
# the office. A page in Bosnian should not print any of that raw.
TITLE_BS = {
    "Minister of Foreign Affairs": "ministar vanjskih poslova BiH",
    "Minister of Security of Bosnia and Herzegovina": "ministar sigurnosti BiH",
    "Minister of Civil Affairs": "ministar civilnih poslova BiH",
    "Minister of Justice of Bosnia and Herzegovina": "ministar pravde BiH",
    "Minister of Finance and Treasury": "ministar finansija i trezora BiH",
    "Minister of Human Rights and Refugees of Bosnia and Herzegovina": "ministar za ljudska prava i izbjeglice BiH",
    "Minister of Foreign Trade and Economic Relations (Bosnia and Herzegovina)": "ministar vanjske trgovine i ekonomskih odnosa BiH",
    "Prime Minister of Republika Srpska": "predsjednik Vlade Republike Srpske",
    "Prime Minister of the Federation of Bosnia and Herzegovina": "premijer Federacije BiH",
    "Member of the House of Peoples of the Federation of Bosnia and Herzegovina": "delegat u Domu naroda Parlamenta FBiH",
    "Representative of the Parliamentary Assembly of the Council of Europe": "član Parlamentarne skupštine Vijeća Evrope",
    "substitute member of the Parliamentary Assembly of the Council of Europe": "zamjenski član Parlamentarne skupštine Vijeća Evrope",
    "Special Guest of the Parliamentary Assembly of the Council of Europe": "specijalni gost Parlamentarne skupštine Vijeća Evrope",
    "Governor of the Central Bank of Bosnia and Herzegovina": "guverner Centralne banke BiH",
    "Permanent Representative of Bosnia and Herzegovina to the United Nations": "stalni predstavnik BiH pri UN-u",
    "Bosnian Herzegovinian Ambassador to the United States": "ambasador BiH u SAD-u",
    "Spisak gradonačelnika Brčko Distrikta": "gradonačelnik Brčko distrikta",
    "Spisak gradonačelnika Sarajeva": "gradonačelnik Sarajeva",
    "Spisak predsjednika Republike Srpske": "predsjednik Republike Srpske",
    "Ministarstvo unutrašnjih poslova Federacije Bosne i Hercegovine": "ministar unutrašnjih poslova FBiH",
    "Ministarstvo saobraćaja i veza Republike Srpske": "ministar saobraćaja i veza Republike Srpske",
    "Dom naroda Parlamentarne skupštine Bosne i Hercegovine": "delegat u Domu naroda PSBiH",
    "Član Senata Republike Srpske": "član Senata Republike Srpske",
}

# A title that says nothing without a qualifier naming the body. Wikidata often has
# these bare, and "Premijer" on its own is not a fact anybody can check.
BARE = {"direktor", "premijer", "ministar", "gradonačelnik", "načelnik", "predsjedavajući",
        "predsjednik", "zastupnik", "poslanik", "delegat", "član", "politician",
        "member of parliament", "minister"}


def clean_title(title, qid, of):
    """Bosnian where we have it, nothing where the item says nothing."""
    title = TITLE_BS.get(title, title)
    if not title or title == qid or re.fullmatch(r"Q\d+", title):
        return None
    if title.strip().lower() in BARE and not of:
        return None
    return title


def read_offices(entity, names):
    """P39 'position held' with its dates, newest first, plain labels."""
    out = []
    for st in (entity.get("claims") or {}).get("P39", []):
        pos = (((st.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}).get("id")
        if not pos:
            continue
        q = st.get("qualifiers") or {}
        of = names.get(id_value(q.get("P642")) or "")
        title = clean_title(names.get(pos) or pos, pos, of)
        if not title:
            continue
        out.append({
            "qid": pos,
            "title": title,
            "start": time_value(q.get("P580")),
            "end": time_value(q.get("P582")),
            "of": of,
            "district": names.get(id_value(q.get("P768")) or ""),
            "party": names.get(id_value(q.get("P4100")) or ""),
        })
    out.sort(key=lambda o: (o.get("start") or "0000", o.get("end") or "9999"))
    return out


# Wikidata position → the CIK race level it corresponds to. Only used to break a tie
# between two candidates with the same name, never to assert anything on a page.
LEVEL_OF_POSITION = {
    "Q19973243": "predsjednistvo", "Q109646833": "predsjednistvo",
    "Q109646836": "predsjednistvo", "Q109646831": "predsjednistvo",
    "Q848335": "predsjednistvo",
    "Q21290855": "pd-psbih",
    "Q109374396": "pd-fbih",
    "Q6594693": "predsjednik-rs",
    "Q12757792": "nsrs",
    "Q12638170": "nacelnik",
}


def current_level(offices):
    """The level of the office this person holds now, or held last."""
    open_now = [o for o in offices if not o.get("end")]
    pool = open_now or offices
    for o in sorted(pool, key=lambda o: o.get("start") or "", reverse=True):
        lvl = LEVEL_OF_POSITION.get(o["qid"])
        if lvl:
            return lvl
    return None


def break_tie(hits, offices, levels_2026):
    """Two people share a name and one of them is in office. The ballot says which.

    Denis Bećirović is the case this exists for: the member of the Presidency and a
    Stranka za BiH candidate in Tuzla carry the same name, and the compiler's own
    records are already tangled between them. The sitting member is standing for the
    Presidency again, the other is standing for the House of Representatives, and
    Wikidata says which office is held now. Anything less clear stays unmatched."""
    lvl = current_level(offices)
    if not lvl:
        return None
    keep = [p for p in hits if lvl in levels_2026.get(p, set())]
    return keep[0] if len(keep) == 1 else None


def wikipedia_url(entity):
    """A page a reader can actually open, in a language they read, if one exists."""
    links = entity.get("sitelinks") or {}
    for key in ("bswiki", "hrwiki", "srwiki", "shwiki", "enwiki"):
        link = links.get(key)
        if link and link.get("title"):
            lang = key[:-4]
            return f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(link["title"].replace(" ", "_"))
    return None


def mashinerija_qids():
    """{publicId: QID} the compiler itself already resolved. Stronger than any match
    we could make here, because it was made against the person record, not the name."""
    out, off = {}, 0
    while True:
        d = mash(f"/biographies?limit=200&offset={off}")
        for row in d["data"]:
            pub = (row.get("person") or {}).get("id")
            for f in row.get("fields", []):
                if f.get("field") == "qid" and pub:
                    out[pub] = f["value"]
        if off + 200 >= d["meta"]["total"]:
            return out
        off += 200


def main():
    os.makedirs(D, exist_ok=True)
    started = time.time()

    timelines = json.load(open(D + "timelines.json"))
    pubids_all = json.load(open(D + "pubids_all.json")) if os.path.exists(D + "pubids_all.json") else {}

    print("1/4 ko je sve držao funkciju u BiH")
    def find_all():
        people_qids, position_qids = discover()
        return {"people": people_qids, "positions": position_qids}
    found = cached("discovery", find_all)
    qids, position_qids = found["people"], found["positions"]

    print("2/4 zapisi o tim ljudima")
    position_labels = cached("positions", lambda: entities(position_qids, props="labels|claims"))
    people = cached("people", lambda: entities(qids))
    people = {q: e for q, e in people.items() if "Q5" in claim_ids(e, "P31")}
    print(f"   {len(people)} ljudi")

    # label every item any qualifier points at, so the page never prints a Q-number
    extra = set()
    for e in people.values():
        for st in (e.get("claims") or {}).get("P39", []):
            q = st.get("qualifiers") or {}
            for p in ("P642", "P768", "P4100"):
                v = id_value(q.get(p))
                if v:
                    extra.add(v)
        extra |= set(claim_ids(e, "P102"))
    names = {q: label(e) for q, e in position_labels.items()}
    names.update({q: label(e) for q, e in entities(sorted(extra - set(names)), props="labels").items()})

    print("3/4 spajanje s listićima 2026")
    by_public = mashinerija_qids()
    strong = {}                       # QID -> pid, resolved upstream
    for pub, qid in by_public.items():
        pid = pubids_all.get(pub)
        if pid:
            strong[qid] = pid
    print(f"   {len(by_public)} biografija s QID-om, {len(strong)} ih pogađa listić 2026")

    # name index over the merged ballot identities
    ballot_name = defaultdict(set)
    levels_2026 = defaultdict(set)
    for pid, tl in timelines.items():
        for row in tl:
            if row.get("y") == 2026 and row.get("race"):
                levels_2026[pid].add(RACE_LEVEL.get(row["race"], row["race"]))
    for fn in os.listdir(D + "units"):
        for lst in json.load(open(D + "units/" + fn)).get("lists", []):
            for c in lst.get("candidates", []):
                key = fold(c.get("name"))
                if c.get("pid") and key:
                    ballot_name[key].add(c["pid"])

    offices, ambiguous = {}, []
    for qid, e in people.items():
        rows = read_offices(e, names)
        if not rows:
            continue
        labels = {v["value"] for v in (e.get("labels") or {}).values()}
        labels |= {a["value"] for vs in (e.get("aliases") or {}).values() for a in vs}
        pid, how = strong.get(qid), "mashinerija"
        if not pid:
            hit = set()
            for lb in labels:
                key = fold(lb)
                if key:
                    hit |= ballot_name.get(key, set())
            if len(hit) != 1:
                pid = break_tie(sorted(hit), rows, levels_2026) if hit else None
                if not pid:
                    if hit:
                        ambiguous.append({"qid": qid, "name": label(e), "pids": sorted(hit)})
                    continue
                how = "funkcija"
            else:
                pid, how = hit.pop(), "ime"
        prev = offices.get(pid)
        if prev and prev["link"] == "mashinerija" and how == "ime":
            continue
        offices[pid] = {
            "qid": qid,
            "name": label(e),
            "link": how,
            "url": f"https://www.wikidata.org/wiki/{qid}",
            "wiki": wikipedia_url(e),
            "parties": [names.get(p) or p for p in claim_ids(e, "P102")],
            "offices": rows,
        }

    print(f"   {len(offices)} profila dobija blok 'Funkcije' "
          f"({sum(1 for v in offices.values() if v['link'] == 'mashinerija')} preko Mashinerije, "
          f"{sum(1 for v in offices.values() if v['link'] == 'ime')} preko imena, "
          f"{sum(1 for v in offices.values() if v['link'] == 'funkcija')} preko funkcije); "
          f"{len(ambiguous)} odbačeno kao dvosmisleno")

    print("4/4 zapis")
    json.dump(offices, open(D + "offices.json", "w"), ensure_ascii=False, indent=1)
    json.dump({"generated": datetime.now(timezone.utc).isoformat(),
               "source": "Wikidata (CC0)",
               "people_seen": len(people),
               "people_matched": len(offices),
               "ambiguous": ambiguous},
              open(D + "offices_meta.json", "w"), ensure_ascii=False, indent=1)
    print(f"gotovo za {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
