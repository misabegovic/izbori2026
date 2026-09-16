#!/usr/bin/env python3
"""Render data/ into dist/ — the simple voter guide (v3).

Every page is written for someone who does not follow politics: short
sentences, plain words, one idea per card, sources on every claim.
"""
import json
import os
import glob
import re
import shutil
import unicodedata
from collections import defaultdict, Counter
from jinja2 import Environment, FileSystemLoader

CYR = dict(zip("абвгдђежзијклљмнњопрстћуфхцчџшАБВГДЂЕЖЗИЈКЛЉМНЊОПРСТЋУФХЦЧЏШ",
               ["a","b","v","g","d","đ","e","ž","z","i","j","k","l","lj","m","n","nj","o","p","r","s","t","ć","u","f","h","c","č","dž","š",
                "A","B","V","G","D","Đ","E","Ž","Z","I","J","K","L","Lj","M","N","Nj","O","P","R","S","T","Ć","U","F","H","C","Č","Dž","Š"]))


def cyr2lat(s):
    return "".join(CYR.get(ch, ch) for ch in (s or ""))


def fold(s):
    s = cyr2lat(s or "").lower().replace("đ", "dj")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def party_key(s):
    return re.sub(r"[^a-z0-9]+", " ", fold(s)).strip()


def pid_slug(pid):
    return re.sub(r"[^A-Za-z0-9]+", "-", pid)


def nice_name(s):
    """CIK prints names in caps; show them as people write them."""
    s = (s or "").strip()
    s = re.sub(r"\s*-\s*NEOVISNI KANDIDAT.*$", "", s, flags=re.I)
    s = re.sub(r"\s*-\s*NEZAVISNI KANDIDAT.*$", "", s, flags=re.I)
    return " ".join("-".join(p.capitalize() for p in w.split("-")) for w in s.lower().split())


SHORT = {}  # filled after programs load
KEEP = {"SDA", "SDP", "SBB", "HDZ", "SNSD", "NES", "PDA", "DF", "GS", "BIH", "RS", "NIP", "DNS", "NPS", "PSS", "PDP", "NPSP", "SPS", "RSS",
        "HRS", "HDS", "HSS", "HNP", "SDS", "BH", "NDP", "BPS", "HSP", "HKDU", "HDU", "HB", "AS", "SR", "SDBIH", "SPUBIH", "BNS", "SNP",
        "FBIH", "DNZ", "SNS", "BOSS", "HUM", "NL", "SRS", "SP", "DEMOS", "ZDK", "TK", "USK", "SBK", "HNK", "ZHK", "KS", "BPK", "PK", "SBIH", "A-SDA", "ASDA", "HSPAS", "HSPHB", "HRAST", "HDZ1990"}


def party_title(s):
    """Readable party name: short name when we know it, otherwise gentle title case."""
    s = (s or "").strip()
    if not s:
        return s
    k = party_key(s)
    if k in SHORT:
        return SHORT[k]
    for name, rxs in alias_rx:
        if any(r.search(k) for r in rxs) and name in SHORT_NAMES:
            SHORT[k] = SHORT_NAMES[name]
            return SHORT[k]
    def fix(tok):
        core = re.sub(r"[^A-Za-z0-9ČĆŽŠĐА-Яа-я]", "", cyr2lat(tok))
        up = core.upper()
        if up in KEEP or (len(core) <= 4 and core.isupper() and not re.search(r"[AEIOU]", up)):
            return tok.upper() if not re.search("[А-Яа-я]", tok) else tok
        return tok.capitalize()
    parts = re.split(r"(\s+|-|/|,|\(|\))", s)
    out = "".join(fix(p) if p and not re.fullmatch(r"(\s+|-|/|,|\(|\))", p) else p for p in parts)
    return out.replace("Bih", "BiH").replace("BIH", "BiH").replace("Rs ", "RS ").replace(" I ", " i ").replace(" Za ", " za ").replace(" Od ", " od ")


def km(fening):
    if fening is None:
        return None
    v = fening / 100
    return f"{v:,.0f}".replace(",", ".") + " KM"


def num(n):
    return f"{n:,}".replace(",", ".") if isinstance(n, (int, float)) else n


# ---------------------------------------------------------------- load
D = "data/"
national = json.load(open(D + "national.json"))
municipalities = json.load(open(D + "municipalities.json"))
timelines = json.load(open(D + "timelines.json"))
people = json.load(open(D + "people_cache.json"))
profiles = json.load(open(D + "profiles.json"))
records = json.load(open(D + "records.json"))
votes = json.load(open(D + "votes.json"))
divisions = json.load(open(D + "divisions.json"))
key_decisions = json.load(open(D + "key_decisions.json"))
parties_api = json.load(open(D + "parties.json"))
programs = json.load(open(D + "programs_fbih.json")) + json.load(open(D + "programs_rs.json"))
aliases = {k: v for k, v in json.load(open(D + "party_aliases.json")).items() if not k.startswith("_")}
context = json.load(open(D + "context.json"))
speeches = json.load(open(D + "speeches.json")) if os.path.exists(D + "speeches.json") else {}
ecitizen = json.load(open(D + "ecitizen.json")) if os.path.exists(D + "ecitizen.json") else {"cities": {}}

units = {}
for f in glob.glob(D + "units/*.json"):
    u = json.load(open(f))
    units[f"{u['race']}-{u['area']}"] = u

gen = national["generated"][:10]
env = Environment(loader=FileSystemLoader("templates"), autoescape=True, trim_blocks=True, lstrip_blocks=True)
env.filters["num"] = num
env.filters["nice"] = nice_name
env.filters["ptitle"] = party_title
env.filters["km"] = km

RACE = {
    "oi2026-1": {"short": "Predsjedništvo BiH", "kind": "one", "who": "tri člana koji predstavljaju državu prema svijetu i komanduju vojskom",
                 "plain": "Biraš JEDNOG čovjeka. Pobjeđuje ko ima najviše glasova.", "level": "BiH"},
    "oi2026-2": {"short": "Državni parlament", "kind": "list", "who": "parlament cijele BiH (zvanično: Predstavnički dom PSBiH)",
                 "plain": "Odlučuje o zakonima za cijelu BiH: granica, PDV, sudovi, put u EU.", "level": "BiH", "chamber": "predstavnicki-dom-psbih"},
    "oi2026-4": {"short": "Parlament Federacije", "kind": "list", "who": "parlament Federacije BiH (zvanično: Predstavnički dom Parlamenta FBiH)",
                 "plain": "Odlučuje o penzijama, zdravstvu, platama i porezima u Federaciji.", "level": "FBiH"},
    "oi2026-5": {"short": "Predsjednik RS", "kind": "one", "who": "predsjednik i dva potpredsjednika Republike Srpske",
                 "plain": "Biraš JEDNOG čovjeka. Prvi je predsjednik, najbolji iz druga dva naroda su potpredsjednici.", "level": "RS"},
    "oi2026-6": {"short": "Narodna skupština RS", "kind": "list", "who": "parlament Republike Srpske",
                 "plain": "Odlučuje o penzijama, zdravstvu, platama, porezima i budžetu RS.", "level": "RS", "chamber": "narodna-skupstina-rs"},
    "oi2026-7": {"short": "Skupština kantona", "kind": "list", "who": "parlament tvog kantona",
                 "plain": "Odlučuje o školama, bolnicama, policiji i inspekcijama u tvom kantonu.", "level": "kanton"},
}
CHAMBER_NAME = {"predstavnicki-dom-psbih": "Državni parlament (PSBiH)", "narodna-skupstina-rs": "Narodna skupština RS"}
VOTE_WORD = {"za": "ZA", "protiv": "PROTIV", "suzdrzan": "uzdržan", "nije-prisutan": "nije bio", "nije-glasao": "nije glasao", None: "nije glasao"}
MAJ_WORD = {"za": "ZA", "protiv": "PROTIV", "suzdrzan": "uzdržani", "nije-prisutan": "većina nije glasala"}
VOTE_CLS = {"za": "v-za", "protiv": "v-protiv", "suzdrzan": "v-uz", "nije-prisutan": "v-odsutan", "nije-glasao": "v-odsutan", None: "v-odsutan"}

# ---------------------------------------------------------------- party <-> program
prog_by_name = {p["name"]: p for p in programs}
alias_rx = [(name, [re.compile(r) for r in rxs]) for name, rxs in aliases.items()]
SHORT_NAMES = {"SDP BiH": "SDP BiH", "SDA": "SDA", "Stranka za BiH": "Stranka za BiH", "DF (Željko Komšić - Za građansku državu DF/GS)": "DF (Komšić)",
               "SBB Fahrudin Radončić": "SBB (Radončić)", "Naša stranka": "Naša stranka", "NES (Nezavisni europski savez, NES BiH / PDA / Naprijed!)": "NES, PDA, Naprijed!",
               "Snaga naroda": "Snaga naroda (Isak)", "HDZ BiH": "HDZ BiH", "Narod i pravda (NiP)": "Narod i pravda (NiP)",
               "Bosanskohercegovačka inicijativa Kasumović Fuad": "BH inicijativa (Kasumović)", "HDZ 1990": "HDZ 1990 (koalicija)", "Naprijed BiH": "Naprijed BiH!",
               "Koalicija za državu": "Koalicija za državu", "SNSD": "SNSD", "Pokret Sigurna Srpska (Draško Stanivuković; PSS, PDP, NPSP)": "Pokret Sigurna Srpska (Stanivuković)",
               "Ujedinjena Srpska": "Ujedinjena Srpska", "DNS-NPS (Banjac-Nešić)": "DNS-NPS (Banjac, Nešić)", "Narodni front Jelena Trivić": "Narodni front (Trivić)",
               "Socijalistička partija Petar Đokić / DEMOS / NDP": "SP (Đokić), DEMOS, NDP", "SPS Goran Selak Pokret Jedinstvena Srpska": "SPS (Selak)",
               "Republička stranka Srpske RSS": "Republička stranka Srpske", "Za pravdu i red - Lista Nebojše Vukanovića / PDP RS Igor Crnadak": "Za pravdu i red (Vukanović), PDP (Crnadak)",
               "Volja naroda Srpske dr Vlado Đajić": "Volja naroda Srpske (Đajić)", "Nezavisna lista Doboj Sevlid Hurtić": "Nezavisna lista Doboj (Hurtić)"}


def program_for(list_name):
    k = party_key(list_name)
    for name, rxs in alias_rx:
        if any(r.search(k) for r in rxs):
            return prog_by_name.get(name)
    return None


# ---------------------------------------------------------------- people
def dedupe_tl(tl):
    seen, out = set(), []
    for t in tl:
        k = (t.get("y"), fold(t.get("lvl") or "")[:8], fold(t.get("area") or "")[:10], party_key(t.get("party") or "")[:12])
        if k in seen:
            continue
        seen.add(k); out.append(t)
    return out


def party_identity(name):
    """Same party under different printed names (coalition lists, renames we know) -> same id."""
    prog = program_for(name)
    if prog:
        return "prog:" + prog["name"]
    k = party_key(name)
    return " ".join(k.split()[:2])


def unique_parties(tl):
    seen, out = set(), []
    for t in sorted(dedupe_tl(tl), key=lambda t: (t.get("y") or 0)):
        p = t.get("party")
        if p and party_identity(p) not in seen:
            seen.add(party_identity(p)); out.append((t["y"], p))
    return out


def vote_map(pid):
    return {d: v for d, v, ann in votes.get(pid, []) if not ann}


def record_summary(pid):
    r = records.get(pid)
    if not r:
        return None
    out = []
    for ch in r["chambers"]:
        c = ch.get("counted") or {}
        voted = c.get("for", 0) + c.get("against", 0) + c.get("abstained", 0)
        nsrs = ch["chamber"] == "narodna-skupstina-rs"
        missed = c.get("absent", 0) + c.get("didNotVote", 0) + (c.get("noVotePrinted", 0) if nsrs else 0)
        seen = voted + missed
        if seen == 0:
            continue
        out.append({"chamber": ch["chamber"], "chamber_name": CHAMBER_NAME.get(ch["chamber"], ch["chamber"]), "nsrs": nsrs,
                    "saziv": ch.get("saziv"), "za": c.get("for", 0), "protiv": c.get("against", 0), "uz": c.get("abstained", 0),
                    "odsutan": missed,
                    "za_pct": round(100 * c.get("for", 0) / voted) if voted else None,
                    "prisustvo_pct": round(100 * voted / seen),
                    "n": seen})
    return out or None


def person_view(c):
    """Everything a page needs to say about one candidate, in plain words."""
    pid = c.get("pid") or ""
    rec = people.get(pid, {})
    tl = timelines.get(pid, [])
    prof = profiles.get(pid, {})
    stood, won = rec.get("stood") or c.get("stood") or 0, rec.get("won") or c.get("won") or 0
    parties = unique_parties(tl)
    won_rows = [t for t in tl if t.get("elected")]
    v = {"pid": pid, "slug": pid_slug(pid) if pid else None, "name": nice_name(c.get("name")), "raw_name": c.get("name"),
         "pos": c.get("pos"), "stood": stood, "won": won, "office": rec.get("isOfficeHolder") or c.get("office"),
         "parties": parties, "n_parties": len(parties), "confidence": rec.get("confidence") or c.get("confidence"),
         "has_record": pid in records, "has_page": bool(tl) or pid in records or bool(prof.get("bio")),
         "won_rows": won_rows}
    badges = []
    if v["office"]:
        badges.append(("office", "sada na funkciji", "Trenutno drži izbornu funkciju."))
    if won and won > 0:
        lv = {t.get("lvl") for t in won_rows}
        local = lv and all(("vijeće" in (l or "")) or ("ačelnik" in (l or "")) for l in lv)
        where = "lokalno" if local else ""
        badges.append(("won", (f"izabran {won}× {where}" if won > 1 else f"već biran {where}").strip(),
                       "Ranije izabran: " + ", ".join(f"{t['y']} {t['lvl']}" for t in won_rows[:6])))
    if v["n_parties"] > 1:
        badges.append(("switch", f"mijenjao stranke ({v['n_parties']})", "Kandidovao se za različite stranke: " + " → ".join(f"{party_title(p)} ({y})" for y, p in parties) + ". Ako je stranka samo promijenila ime, ovo može biti greška."))
    if stood == 1:
        badges.append(("new", "prvi put", "Prvi put na listiću."))
    if stood >= 3 and not won:
        badges.append(("filler", f"{stood}. put na listi, još neizabran", "Kandidovao se više puta, do sada nije osvojio mandat."))
    if v["has_record"]:
        badges.append(("record", "ima zapis glasanja", "Bio poslanik 2022–2026, vidi kako je glasao."))
    v["badges"] = badges
    # one-sentence story
    s = []
    if stood == 1:
        s.append("Prvi put se kandiduje.")
    else:
        s.append(f"Kandiduje se {stood}. put" + (f", izabran/a {won} puta." if won else ", do sada nije izabran/a."))
    if v["n_parties"] > 1:
        s.append("Stranke: " + " → ".join(f"{party_title(p)} ({y})" for y, p in parties) + ".")
    elif parties and stood > 1:
        s.append(f"Uvijek za: {party_title(parties[0][1])}.")
    v["story"] = " ".join(s)
    return v


# ---------------------------------------------------------------- lists / parties
list_members = defaultdict(list)     # party identity -> [(unit_key, candidate dict)]
list_display = {}                    # party identity -> printed name (most common variant)
list_codes = defaultdict(set)
_name_count = defaultdict(Counter)
for uk, u in units.items():
    for l in u["lists"]:
        k = party_identity(l["name"])
        _name_count[k][l["name"]] += len(l["candidates"])
        list_codes[k].add(l["code"])
        for c in l["candidates"]:
            list_members[k].append((uk, c))
for k, cnt in _name_count.items():
    list_display[k] = cnt.most_common(1)[0][0]

for _pk, _nm in list_display.items():
    for name, rxs in alias_rx:
        if any(r.search(party_key(_nm)) for r in rxs) and name in SHORT_NAMES:
            SHORT[party_key(_nm)] = SHORT_NAMES[name]
            break
# ballot names that are exactly one presidency list
SHORT[party_key("UJEDINJENI ZA DRŽAVU BOSNU I HERCEGOVINU")] = "Ujedinjeni za državu BiH (SDP i partneri)"
SHORT[party_key("ZA PRAVDU I RED LISTA NEBOJŠE VUKANOVIĆA")] = "Za pravdu i red (Vukanović)"
SHORT[party_key("SDS-SRPSKA DEMOKRATSKA STRANKA")] = "SDS"
SHORT[party_key("NAROD I PRAVDA")] = "Narod i pravda (NiP)"
SHORT[party_key("DEMOKRATSKA FRONTA")] = "DF"

kd_by_id = {d["id"]: d for d in key_decisions}
kd_by_chamber = defaultdict(list)
for d in key_decisions:
    kd_by_chamber[d["chamber"]].append(d)


def party_key_votes(pk):
    """For each key decision: how this list's 2026 candidates (who were MPs) voted."""
    pids = {c["pid"] for _, c in list_members.get(pk, []) if c.get("pid") in records}
    if not pids:
        return None
    out = []
    for d in key_decisions:
        cnt = Counter(); who = []
        for pid in pids:
            vm = vote_map(pid)
            if d["id"] in vm:
                v = vm[d["id"]]
                cnt[v] += 1
                who.append((pid, v))
        if not who:
            continue
        maj = max(("za", "protiv", "suzdrzan"), key=lambda k: cnt.get(k, 0))
        voted = cnt.get("za", 0) + cnt.get("protiv", 0) + cnt.get("suzdrzan", 0)
        if voted == 0 or voted * 2 < len(who):
            maj = "nije-prisutan"
        out.append({"d": d, "cnt": dict(cnt), "n": len(who), "maj": maj, "maj_word": MAJ_WORD[maj], "maj_cls": VOTE_CLS[maj],
                    "za": cnt.get("za", 0), "protiv": cnt.get("protiv", 0), "uz": cnt.get("suzdrzan", 0),
                    "odsutan": cnt.get("nije-prisutan", 0) + cnt.get("nije-glasao", 0) + cnt.get(None, 0)})
    return out or None


def party_summary(pk):
    mem = list_members.get(pk, [])
    n = len(mem)
    pids = [c.get("pid") for _, c in mem]
    won = sum(1 for _, c in mem if (people.get(c.get("pid"), {}).get("won") or 0) > 0)
    switch = sum(1 for _, c in mem if len(unique_parties(timelines.get(c.get("pid") or "", []))) > 1)
    new = sum(1 for _, c in mem if (people.get(c.get("pid"), {}).get("stood") or 0) == 1)
    office = sum(1 for _, c in mem if people.get(c.get("pid"), {}).get("isOfficeHolder"))
    mps = [c for _, c in mem if c.get("pid") in records]
    seen = set(); mps_u = []
    for c in mps:
        if c["pid"] not in seen:
            seen.add(c["pid"]); mps_u.append(person_view(c))
    votes22 = 0; votes18 = 0; seats22 = 0; units_in = 0
    pi = party_identity(list_display.get(pk, ""))
    for uk, u in units.items():
        for h in u.get("party_history", []):
            if party_identity(h["party"]) == pi:
                if h["year"] == 2022:
                    votes22 += h.get("votes") or 0
                else:
                    votes18 += h.get("votes") or 0
        for nm, cnt in u.get("seats22", {}).items():
            if party_identity(nm) == pi:
                seats22 += cnt
        if any(party_identity(l["name"]) == pk for l in u["lists"]):
            units_in += 1
    funding = None
    for code in list_codes.get(pk, []):
        p = parties_api.get(code)
        if p and p.get("funding"):
            paid = sum(f.get("paid") or 0 for f in p["funding"] if f.get("year") == 2024)
            funding = {"year": 2024, "paid": paid, "rows": sorted(p["funding"], key=lambda f: -(f.get("paid") or 0))[:6]}
    return {"key": pk, "name": list_display.get(pk, pk), "n": n, "won": won, "switch": switch, "new": new, "office": office,
            "mps": mps_u, "votes22": votes22, "votes18": votes18, "seats22": seats22, "units_in": units_in, "funding": funding,
            "program": program_for(list_display.get(pk, "")), "key_votes": party_key_votes(pk),
            "href": f"stranka-{re.sub(r'[^a-z0-9]+', '-', fold(pk.replace('prog:', ''))).strip('-')}.html"}


party_pages = {}
for pk, mem in list_members.items():
    if len(mem) >= 15 or program_for(list_display[pk]):
        party_pages[pk] = party_summary(pk)


def party_href(list_name):
    pk = party_identity(list_name)
    return party_pages[pk]["href"] if pk in party_pages else None


# ---------------------------------------------------------------- output
if os.path.exists("dist"):
    shutil.rmtree("dist")
os.makedirs("dist")


def write(name, html):
    open(f"dist/{name}", "w").write(html)


def unit_href(race, area):
    return f"listic-{race}-{area}.html"


unit_munis = defaultdict(list)
for m in municipalities:
    for race, area in m["refs"]:
        unit_munis[f"{race}-{area}"].append(m["name"])
PRES_CTX = {}
for grp in list(context["presidency"].values()) + [context["rs_president"]]:
    for r_ in grp:
        PRES_CTX[fold(r_["name"])] = r_
env.filters["lat"] = lambda x: fold(re.sub(r"\s*-\s*NE[OZ]?[A-Z]*VISNI KANDIDAT.*$", "", cyr2lat(x or ""), flags=re.I))
COMP = {"501": "dodatna lista za cijelu Federaciju", "502": "dodatna lista za cijelu RS", "400": "dodatna lista za cijelu Federaciju", "300": "dodatna lista za cijelu RS"}
base_ctx = {"generated": gen, "RACE": RACE, "PRES_CTX": PRES_CTX, "COMP": COMP}

RACE_LVL = {"oi2026-2": "Predstavnički dom PSBiH", "oi2026-4": "Predstavnički dom Parlamenta FBiH", "oi2026-6": "Narodna skupština Republike Srpske", "oi2026-7": "Skupštine kantona"}

# --- chance of winning a seat: rough estimate from 2022 seats here, list position, prior wins
CAL = json.load(open(D + "chance_calibration.json")) if os.path.exists(D + "chance_calibration.json") else {}
def cal_pct(bucket, default):
    return (CAL.get(bucket) or {}).get("pct", default)
def chance_word(pct):
    return "velika" if pct >= 50 else "srednja" if pct >= 15 else "mala" if pct >= 5 else "vrlo mala"


def list_chances(u, l):
    """{pid: (pct, word, why)} for one list on one ballot. pct = share of candidates in the same
    situation who actually won in 2022 (data/chance_calibration.json, backtest.py). Estimate, not a forecast."""
    pi = party_identity(l["name"])
    seats = 0
    for nm, cnt in u.get("seats22", {}).items():
        if party_identity(nm) == pi:
            seats += cnt
    cands = l["candidates"]
    lvl = RACE_LVL.get(u["race"], "")
    def strength(c):
        pid = c.get("pid") or ""
        tl = timelines.get(pid, [])
        pv = next((t.get("votes") for t in tl if t.get("y") == 2022 and t.get("votes") and (t.get("lvl") or "") == lvl), 0) or 0
        won = (people.get(pid, {}).get("won") or 0)
        return 1.0 / (c.get("pos") or 99) + (0.6 if won else 0) + min(pv / 5000.0, 1.0)
    ranked = sorted(cands, key=strength, reverse=True)
    out = {}
    for rank, c in enumerate(ranked, 1):
        if seats <= 0:
            if rank == 1:
                pct = cal_pct("no_seats_pos1", 15); why = f"stranka 2022 ovdje nije imala mandat, ovaj je prvi na listi; 2022 je od takvih prošlo {pct}%"
            else:
                pct = cal_pct("no_seats_rest", 2); why = f"stranka 2022 ovdje nije imala mandat i nije prvi na listi; 2022 je od takvih prošlo {pct}%"
        elif rank <= seats:
            pct = cal_pct("within", 63); why = f"stranka je 2022 ovdje imala {seats} mandat(a), ovaj je među prvih {seats} na listi; 2022 je od takvih prošlo {pct}%"
        elif rank == seats + 1:
            pct = cal_pct("plus1", 19); why = f"prvi iza {seats} mjesta koja je stranka imala 2022; 2022 je od takvih prošlo {pct}%"
        elif rank == seats + 2:
            pct = cal_pct("plus2", 6); why = f"drugi iza mjesta koja je stranka imala 2022; 2022 je od takvih prošlo {pct}%"
        else:
            pct = cal_pct("beyond", 2); why = f"daleko iza mjesta koja je stranka imala 2022; 2022 je od takvih prošlo {pct}%"
        if u["area"] in COMP:
            pct = min(pct, 19); why = "dodatna lista: mjesta dijeli stranka po svom redu, pa je procjena nesigurna"
        out[c.get("pid") or c["name"]] = (pct, chance_word(pct), why)
    return out


# --- per-ballot comparison data (for D3 chart)
def unit_cands_json(u):
    lists = [party_title(l["name"]) for l in u["lists"]]
    out = []
    for li, l in enumerate(u["lists"]):
        ch = list_chances(u, l) if RACE[u["race"]]["kind"] == "list" else {}
        for c in l["candidates"]:
            v = person_view(c)
            pid = c.get("pid") or ""
            chance = ch.get(pid or c["name"])
            tl = timelines.get(pid, [])
            v22 = next((t.get("votes") for t in tl if t.get("y") == 2022 and t.get("votes") and (t.get("lvl") or "") == RACE_LVL.get(u["race"], "")), None)
            rec = record_summary(pid)
            r0 = (rec or [None])[-1] if rec else None
            out.append({"id": pid, "n": v["name"], "l": li, "pos": c.get("pos"), "s": v["stood"] or 0, "w": v["won"] or 0, "p": max(v["n_parties"], 1),
                        "v22": v22, "za": r0["za_pct"] if r0 else None, "pris": r0["prisustvo_pct"] if r0 else None, "rec": bool(rec),
                        "story": v["story"], "href": f"kandidat-{v['slug']}.html" if v["has_page"] else None,
                        "ch": chance[0] if chance else None, "chw": chance[1] if chance else None})
    return json.dumps({"lists": lists, "cands": out}, ensure_ascii=False, separators=(",", ":"))

unit_json = {uk: unit_cands_json(u) for uk, u in units.items() if RACE[u["race"]]["kind"] == "list"}
shutil.copy("static/viz.js", "dist/viz.js")

# chamber averages for comparison on candidate pages
CH_AVG = {}
for _ch in CHAMBER_NAME:
    _rows = [r for pid in records for r in (record_summary(pid) or []) if r["chamber"] == _ch and r["za_pct"] is not None]
    if _rows:
        CH_AVG[_ch] = {"za": round(sum(r["za_pct"] for r in _rows) / len(_rows)), "pris": round(sum(r["prisustvo_pct"] for r in _rows) / len(_rows))}

# --- candidate pages
kand_tpl = env.get_template("kandidat.html")
cand_index = {}   # pid -> (unit_key, list name, candidate)
for uk, u in units.items():
    for l in u["lists"]:
        for c in l["candidates"]:
            if c.get("pid"):
                cand_index.setdefault(c["pid"], []).append((uk, l["name"], c))
n_kand = 0
for pid, entries in cand_index.items():
    uk, lname, c = entries[0]
    v = person_view(c)
    if not v["has_page"]:
        continue
    tl = sorted([t for t in dedupe_tl(timelines.get(pid, [])) if t.get("y") != 2026], key=lambda t: (t.get("y") or 0, t.get("lvl") or ""))
    prof = profiles.get(pid, {})
    vm = vote_map(pid)
    rec = record_summary(pid)
    replacement = bool(rec) and not any(t.get("elected") and t.get("y") == 2022 for t in tl)
    kd = []
    for d in key_decisions:
        if d["id"] in vm:
            kd.append({"d": d, "vote": vm[d["id"]], "word": VOTE_WORD[vm[d["id"]]], "cls": VOTE_CLS[vm[d["id"]]]})
    sp = [dict(x, text=re.sub(r"_{3,}\s*\(\?\)|_{3,}", "…", x["text"])) for x in speeches.get(pid, [])]
    assets = None
    if prof.get("assets"):
        by_src = defaultdict(list)
        for a in prof["assets"]:
            by_src[a["src"]].append(a)
        assets = {src: rows for src, rows in by_src.items()}
    entries = sorted(entries, key=lambda e: units[e[0]]["area"] in COMP)
    def _chance(e):
        uu = units[e[0]]
        if RACE[uu["race"]]["kind"] != "list":
            return None
        ll = next(l for l in uu["lists"] if l["name"] == e[1])
        return list_chances(uu, ll).get(pid)
    runs = [{"unit": units[e[0]], "list": e[1], "chance": _chance(e), "href": unit_href(units[e[0]]["race"], units[e[0]]["area"]), "pos": e[2].get("pos"),
             "party_href": party_href(e[1])} for e in entries]
    main_uk = next((e[0] for e in entries if units[e[0]]["area"] not in COMP), uk)
    tl_json = json.dumps([{"y": t.get("y"), "won": bool(t.get("elected")), "lvl": t.get("lvl")} for t in tl], ensure_ascii=False)
    html = kand_tpl.render(p=v, tl=tl, tl_json=tl_json, prof=prof, rec=rec, kd=kd, replacement=replacement, cands_json=unit_json.get(main_uk), CH_AVG=CH_AVG, speeches_n=len(sp), speeches=sp[:5], assets=assets, runs=runs, **base_ctx)
    write(f"kandidat-{v['slug']}.html", html)
    n_kand += 1

# --- ballot (unit) pages
listic_tpl = env.get_template("listic.html")
for uk, u in units.items():
    race = u["race"]
    hist22 = {party_identity(h["party"]): h for h in u.get("party_history", []) if h["year"] == 2022}
    hist18 = {party_identity(h["party"]): h for h in u.get("party_history", []) if h["year"] == 2018}
    seats22 = {}
    for k_, v_ in u.get("seats22", {}).items():
        seats22[party_identity(k_)] = seats22.get(party_identity(k_), 0) + v_
    lists = []
    for l in u["lists"]:
        pi = party_identity(l["name"])
        pk = pi
        cands = [person_view(c) for c in l["candidates"]]
        chs = list_chances(u, l) if RACE[race]["kind"] == "list" else {}
        for cv, c in zip(cands, l["candidates"]):
            cv["chance"] = chs.get(c.get("pid") or c["name"])
        prog = program_for(l["name"])
        kv = party_pages[pi]["key_votes"] if pi in party_pages else None
        recent_kv = None
        ch = RACE[race].get("chamber")
        if kv and ch:
            pool = [x for x in kv if x["d"]["chamber"] == ch]
            recent_kv = sorted(pool, key=lambda x: x["d"]["date"], reverse=True)[:4] or None
        lists.append({"name": l["name"], "key": pk, "cands": cands, "n": len(cands),
                      "won": sum(1 for c in cands if c["won"]), "switch": sum(1 for c in cands if c["n_parties"] > 1),
                      "new": sum(1 for c in cands if c["stood"] == 1), "office": sum(1 for c in cands if c["office"]),
                      "mps": sum(1 for c in cands if c["has_record"]),
                      "votes22": (hist22.get(pi) or {}).get("votes"), "votes18": (hist18.get(pi) or {}).get("votes"),
                      "seats22": seats22.get(pi, 0), "program": prog, "party_href": party_href(l["name"]),
                      "key_votes": recent_kv})
    total22 = sum((h.get("votes") or 0) for h in u.get("party_history", []) if h["year"] == 2022)
    top22 = sorted([h for h in u.get("party_history", []) if h["year"] == 2022], key=lambda h: -(h.get("votes") or 0))[:5]
    munis = unit_munis.get(uk, [])
    html = listic_tpl.render(u=u, r=RACE[race], lists=lists, total22=total22, top22=top22, munis=munis, cands_json=unit_json.get(uk), **base_ctx)
    write(unit_href(race, u["area"]), html)

# --- municipality pages
slug_by_folded = {}
for m in municipalities:
    slug_by_folded[fold(m["slug"].split(".")[-1]).replace("-", " ")] = m["slug"]
ec_by_slug = {}
for city, data in ecitizen["cities"].items():
    slug = slug_by_folded.get(fold(city.replace("_", " ")))
    if slug and data.get("sessions"):
        good = []
        for sess in data["sessions"]:
            ag = [a for a in (sess.get("agendas") or []) if a.get("for") is not None]
            if ag:
                good.append({**sess, "agendas": [dict(a, name=(a.get("name") or "")[:110]) for a in ag[:6]]})
        if good:
            ec_by_slug[slug] = {**data, "sessions": good}
opcina_tpl = env.get_template("opcina.html")
for m in municipalities:
    ballots = []
    if m["entity"] == "rs":
        pres = [("oi2026-1", "703")]
    elif m["entity"] == "fbih":
        pres = [("oi2026-1", "701"), ("oi2026-1", "702")]
    else:
        pres = [("oi2026-1", "701"), ("oi2026-1", "702"), ("oi2026-1", "703")]
    order = pres + ([("oi2026-5", "5")] if m["entity"] == "rs" else []) + [tuple(r) for r in m["refs"]]
    seen = set()
    for race, area in order:
        if (race, area) in seen:
            continue
        seen.add((race, area))
        u = units.get(f"{race}-{area}")
        if not u:
            continue
        sub = {"701": "bošnjački član", "702": "hrvatski član", "703": "srpski član"}.get(area) if race == "oi2026-1" else None
        top = sorted([h for h in u.get("party_history", []) if h["year"] == 2022], key=lambda h: -(h.get("votes") or 0))[:3]
        ballots.append({"race": race, "r": RACE[race], "sub": sub, "href": unit_href(race, area), "n_lists": len(u["lists"]),
                        "n_cands": u["stats"]["candidates"], "area": area, "top22": top, "max22": (top[0].get("votes") or 1) if top else 1})
    # FBiH: bošnjački + hrvatski član su jedan papir s dvije kolone
    pres_b = [b for b in ballots if b["race"] == "oi2026-1" and b["area"] in ("701", "702")]
    if len(pres_b) == 2:
        merged = {"race": "oi2026-1", "r": RACE["oi2026-1"], "multi": True, "subs": pres_b}
        ballots = [merged] + [b for b in ballots if b not in pres_b]
    html = opcina_tpl.render(m=m, ballots=ballots, ec=ec_by_slug.get(m["slug"]), **base_ctx)
    write(f"opcina-{m['slug']}.html", html)

groups = defaultdict(list)
for m in municipalities:
    groups[m["group"]].append(m)
for m in municipalities:
    m["folded"] = fold(m["name"])
write("opcine.html", env.get_template("opcine.html").render(groups=sorted(groups.items()), **base_ctx))

# --- party pages + index of parties
stranka_tpl = env.get_template("stranka.html")
for pk, ps in party_pages.items():
    write(ps["href"], stranka_tpl.render(p=ps, **base_ctx))
plist = sorted(party_pages.values(), key=lambda p: -p["n"])
write("stranke.html", env.get_template("stranke.html").render(parties=plist, **base_ctx))

# --- presidency page
def pres_cands(area):
    u = units[f"oi2026-1-{area}"]
    out = []
    for l in u["lists"]:
        for c in l["candidates"]:
            v = person_view(c)
            v["list"] = l["name"]; v["party_href"] = party_href(l["name"])
            out.append(v)
    return out
ctx_pres = context["presidency"]
def merge_ctx(cands, ctx_rows):
    by = {fold(r["name"]): r for r in ctx_rows}
    for c in cands:
        c["ctx"] = by.get(fold(cyr2lat(c["raw_name"]).split(" - ")[0]))
    return cands
pres = {"bosnjacki": merge_ctx(pres_cands("701"), ctx_pres["bosnjacki"]),
        "hrvatski": merge_ctx(pres_cands("702"), ctx_pres["hrvatski"]),
        "srpski": merge_ctx(pres_cands("703"), ctx_pres["srpski"])}
rs_u = units["oi2026-5-5"]
rs_c = []
for l in rs_u["lists"]:
    for c in l["candidates"]:
        v = person_view(c); v["list"] = l["name"]; v["party_href"] = party_href(l["name"]); rs_c.append(v)
rs_c = merge_ctx(rs_c, context["rs_president"])
write("predsjednistvo.html", env.get_template("predsjednistvo.html").render(pres=pres, rs=rs_c, note=context["rs_president_note"], **base_ctx))

# --- what happened
kd_view = []
for d in sorted(key_decisions, key=lambda d: d["date"], reverse=True):
    p = d.get("published") or {}
    kd_view.append({**d, "chamber_name": CHAMBER_NAME.get(d["chamber"]), "za": p.get("for"), "protiv": p.get("against"), "uz": p.get("abstainPublished")})
write("desavanja.html", env.get_template("desavanja.html").render(events=context["events"], themes=context["themes"], kd=kd_view, **base_ctx))

# --- how to vote
write("kako-glasati.html", env.get_template("kako.html").render(ctx=context, **base_ctx))

# --- index
for m in municipalities:
    m["folded"] = fold(m["name"])
write("index.html", env.get_template("index.html").render(municipalities=municipalities, national=national, ctx=context, **base_ctx))

print(f"rendered: {len(units)} listića, {len(municipalities)} općina, {n_kand} kandidata, {len(party_pages)} stranaka")
