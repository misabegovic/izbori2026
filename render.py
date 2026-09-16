#!/usr/bin/env python3
"""Render data/ into dist/ — the simple voter guide (v3).

Every page is written for someone who does not follow politics: short
sentences, plain words, one idea per card, sources on every claim.
"""
import json
import os
import glob
import hashlib
import re
import shutil
import unicodedata
from collections import defaultdict, Counter
from jinja2 import Environment, FileSystemLoader
import analytics

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


def home_key(s):
    """Municipality name -> key that matches both CIK area names ('GRAD MOSTAR', '* STOLAC',
    'PROZOR - RAMA', 'FOČA (FBIH)') and our municipality list ('Mostar', 'Stolac', 'Prozor-Rama', 'Foča')."""
    k = party_key(re.sub(r"\(.*?\)", " ", s or ""))
    k = re.sub(r"^(grad|opcina|opstina) ", "", k)
    return k


def pid_slug(pid):
    return re.sub(r"[^A-Za-z0-9]+", "-", pid)


def nice_name(s):
    """CIK prints names in caps; show them as people write them."""
    s = (s or "").strip()
    s = re.sub(r"\s*-\s*NEOVISNI KANDIDAT.*$", "", s, flags=re.I)
    s = re.sub(r"\s*-\s*NEZAVISNI KANDIDAT.*$", "", s, flags=re.I)
    s = cyr2lat(s)
    return " ".join("-".join(p.capitalize() for p in w.split("-")) for w in s.lower().split())


SHORT = {}  # filled after programs load
KEEP = {"SDA", "SDP", "SBB", "HDZ", "SNSD", "NES", "PDA", "DF", "GS", "BIH", "RS", "NIP", "DNS", "NPS", "PSS", "PDP", "NPSP", "SPS", "RSS",
        "HRS", "HDS", "HSS", "HNP", "SDS", "BH", "NDP", "BPS", "HSP", "HKDU", "HDU", "HB", "AS", "SR", "SDBIH", "SPUBIH", "BNS", "SNP",
        "FBIH", "DNZ", "SNS", "BOSS", "HUM", "NL", "SRS", "SP", "DEMOS", "ZDK", "TK", "USK", "SBK", "HNK", "ZHK", "KS", "BPK", "PK", "SBIH", "A-SDA", "ASDA", "HSPAS", "HSPHB", "HRAST", "HDZ1990"}


def party_title(s, raw=False):
    """Readable party name: short name when we know it, otherwise gentle title case. raw=True keeps the printed name."""
    s = (s or "").strip()
    if not s:
        return s
    k = party_key(s)
    if not raw and k in SHORT:
        return SHORT[k]
    for name, rxs in alias_rx:
        if not raw and any(r.search(k) for r in rxs) and name in SHORT_NAMES:
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
programs = [dict(p, entity="FBiH") for p in json.load(open(D + "programs_fbih.json"))] + [dict(p, entity="RS") for p in json.load(open(D + "programs_rs.json"))]
aliases = {k: v for k, v in json.load(open(D + "party_aliases.json")).items() if not k.startswith("_")}
context = json.load(open(D + "context.json"))
promises22 = {}
for _f in ("promises2022_fbih.json", "promises2022_rs.json"):
    if os.path.exists(D + _f):
        for _p in json.load(open(D + _f)):
            _p["note"] = re.sub(r"\b[Nn]isam (našao|mogao|potvrdio)", "Nije nađen", _p.get("note") or "")
            for _x in _p["promises_2022"]:
                _x["what_happened"] = re.sub(r"\b[Nn]isam našao", "Nije nađen", _x.get("what_happened") or "")
            promises22[_p["program"]] = _p
OUTCOME_CLS = {"ispunjeno": "c-za", "djelimično": "c-uz", "nije": "c-protiv", "ne može se ocijeniti": "c-od"}


promises_hist = []
for _f in ("promises_history_fbih.json", "promises_history_rs.json"):
    if os.path.exists(D + _f):
        promises_hist += json.load(open(D + _f))


def history_for(prog):
    """Per-mandate promise record: earlier mandates from promises_history_*.json + 2022-26 from promises2022_*.json."""
    if not prog:
        return None
    rows = []
    for h in promises_hist:
        if h.get("program") != prog["name"]:
            continue
        h = dict(h)
        note = h.get("note") or ""
        h["gov_wide"] = bool(re.search(r"cijel[ua] vlad|ne po stranci|nisu razvrstan|agregat", note, re.I))
        h["note"] = re.sub(r"\b[Nn]isam (našao|mogao|potvrdio)", "Nije nađen", note)
        rows.append(h)
    p = promises22.get(prog["name"])
    if p:
        cnt = Counter(x["outcome"] for x in p["promises_2022"])
        rated = cnt.get("ispunjeno", 0) + cnt.get("djelimično", 0) + cnt.get("nije", 0)
        rows.append({"mandate": "2022-2026", "in_power": p.get("in_power_2022_2026"), "tracked": rated or None,
                     "fulfilled": cnt.get("ispunjeno", 0), "partial": cnt.get("djelimično", 0), "broken": cnt.get("nije", 0),
                     "examples": [], "sources": [], "confidence": p.get("confidence"), "note": "uzorak provjerenih obećanja, ne cijeli Istinomjerov skup"})
    rows.sort(key=lambda r: r["mandate"])
    if not rows:
        return None
    rated = [r for r in rows if r.get("tracked") and r.get("fulfilled") is not None and not r.get("gov_wide")]
    gov_only = False
    if not rated:
        rated = [r for r in rows if r.get("tracked") and r.get("fulfilled") is not None]
        gov_only = True
    def _pat(rs, gov_only):
        tot = sum(r["tracked"] for r in rs); ful = sum(r["fulfilled"] or 0 for r in rs); part = sum(r.get("partial") or 0 for r in rs)
        return {"mandates": len(rs), "tracked": tot, "pct_full": round(100 * ful / tot), "pct_part": round(100 * part / tot), "gov_only": gov_only}
    pattern = _pat(rated, gov_only) if rated else None
    gov_rows = [r for r in rows if r.get("tracked") and r.get("fulfilled") is not None and r.get("gov_wide")]
    pattern_gov = _pat(gov_rows, True) if gov_rows and not gov_only else None
    chart = [{"m": r["mandate"], "f": r.get("fulfilled") or 0, "p": r.get("partial") or 0, "b": r.get("broken") or 0,
              "t": r.get("tracked") or 0, "power": (("[brojke za cijelu vladu] " if r.get("gov_wide") else "") + (r.get("in_power") or ""))} for r in rows]
    return {"rows": rows, "pattern": pattern, "pattern_gov": pattern_gov, "chart": json.dumps(chart, ensure_ascii=False)}


def p22_for(prog):
    if not prog:
        return None
    p = promises22.get(prog["name"])
    if not p:
        return None
    cnt = Counter(x["outcome"] for x in p["promises_2022"])
    in_power = bool((p.get("in_power_2022_2026") or "").strip()) and "nisu bili" not in (p.get("in_power_2022_2026") or "").lower()
    grey = "još u toku ili se ne može provjeriti" if in_power else "nisu bili u vlasti, ne može se ocijeniti"
    return {**p, "counts": cnt, "in_power": in_power,
            "stack": [(grey if k == "ne može se ocijeniti" else k, cnt.get(k, 0), OUTCOME_CLS[k]) for k in ("ispunjeno", "djelimično", "nije", "ne može se ocijeniti")]}
speeches = json.load(open(D + "speeches.json")) if os.path.exists(D + "speeches.json") else {}
ecitizen = json.load(open(D + "ecitizen.json")) if os.path.exists(D + "ecitizen.json") else {"cities": {}}
appointed = json.load(open(D + "appointed.json")) if os.path.exists(D + "appointed.json") else {}
# What the election record could not say on its own. person_stats counts the merged
# record; merges says which links were made and why; maybe_same holds the links we
# would not make; offices holds terms CIK never published at all.
pstats = json.load(open(D + "person_stats.json")) if os.path.exists(D + "person_stats.json") else {}
merges = json.load(open(D + "merges.json")) if os.path.exists(D + "merges.json") else {}
merge_tiers = Counter(a["tier"] for a in merges.get("applied", []))
maybe_same = json.load(open(D + "maybe_same.json")) if os.path.exists(D + "maybe_same.json") else {}
offices = json.load(open(D + "offices.json")) if os.path.exists(D + "offices.json") else {}
offices_meta = json.load(open(D + "offices_meta.json")) if os.path.exists(D + "offices_meta.json") else {}
history_meta = json.load(open(D + "history_meta.json")) if os.path.exists(D + "history_meta.json") else {}
unit_spend = json.load(open(D + "unit_spend.json")) if os.path.exists(D + "unit_spend.json") else {}
seat_bar = json.load(open(D + "seat_bar.json")) if os.path.exists(D + "seat_bar.json") else {}
list_strength = json.load(open(D + "list_strength.json")) if os.path.exists(D + "list_strength.json") else {}

units = {}
for f in glob.glob(D + "units/*.json"):
    u = json.load(open(f))
    units[f"{u['race']}-{u['area']}"] = u

gen = national["generated"][:10]
env = Environment(loader=FileSystemLoader("templates"), autoescape=True, trim_blocks=True, lstrip_blocks=True)
# The site writes thousands with a dot (5.250), so a decimal point reads as thousands:
# "3.5%" looks like 35. Decimals take a comma.
env.filters["dec"] = lambda v: ("" if v is None else
                                ("manje od 0,1" if 0 < v < 0.05 else ("%.1f" % v).replace(".", ",")))
env.filters["num"] = num
env.filters["nice"] = nice_name
env.filters["ptitle"] = party_title
env.filters["ptitle_raw"] = lambda s: party_title(s, raw=True)
env.filters["km"] = km
SRC_NAME = {"cin": "CIN, imovinapoliticara.cin.ba", "pd.fbih.karton": "Parlament FBiH", "psbih.detail": "parlament.ba", "cik": "CIK", "nsrs": "NSRS"}
env.filters["srcname"] = lambda s: SRC_NAME.get(s or "", s or "")
env.filters["area"] = lambda a: nice_area(a)
env.filters["godina"] = lambda s: (s or "")[:4]
env.filters["datum"] = lambda s: (lambda m: f"{int(m.group(3))}. {int(m.group(2))}. {m.group(1)}." if m else s)(re.match(r"^(\d{4})-(\d{2})-(\d{2})", s or ""))


CANTON = {"1": "Unsko-sanski kanton", "2": "Posavski kanton", "3": "Tuzlanski kanton", "4": "Zeničko-dobojski kanton",
           "5": "Bosansko-podrinjski kanton", "6": "Srednjobosanski kanton", "7": "Hercegovačko-neretvanski kanton",
           "8": "Zapadnohercegovački kanton", "9": "Kanton Sarajevo", "10": "Kanton 10 (Livno, Tomislavgrad, Glamoč…)"}


def nice_area(a):
    """CIK area strings into words a voter recognises."""
    a = re.sub(r"^\*\s*", "", (a or "").strip())
    a = re.sub(r"^(GRAD|OPĆINA|OPŠTINA)\s+(?!SARAJEVO$)", "", a, flags=re.I)
    a = re.sub(r"\s*-\s*", "-", a)
    m = re.match(r"^KANTON (\d+)$", cyr2lat(a).upper())
    if m:
        return CANTON.get(m.group(1), a.title())
    m = re.match(r"^IZBORNA JEDINICA (\S+)$", cyr2lat(a).upper())
    if m:
        return f"izborna jedinica {m.group(1).lower()}"
    if len(a) > 40:
        return "cijeli entitet"
    return nice_name(a)


def mjesta(n):
    return f"{n} mjesto" if n == 1 else f"{n} mjesta"


env.globals["mjesta"] = mjesta


RACE = {
    "oi2026-1": {"short": "Predsjedništvo BiH", "kind": "one", "who": "tri člana koji predstavljaju državu prema svijetu i komanduju vojskom",
                 "plain": "Biraš JEDNOG čovjeka. Pobjeđuje ko ima najviše glasova.", "level": "BiH"},
    "oi2026-2": {"short": "Državni parlament", "kind": "list", "who": "parlament cijele BiH (zvanično: Predstavnički dom PSBiH)",
                 "plain": "Odlučuje o zakonima za cijelu BiH: granica, PDV, sudovi, put u EU.", "level": "BiH", "chamber": "predstavnicki-dom-psbih"},
    "oi2026-4": {"short": "Parlament Federacije", "kind": "list", "who": "parlament Federacije BiH (zvanično: Predstavnički dom Parlamenta FBiH)",
                 "plain": "Odlučuje o penzijama, zdravstvu, platama i porezima u Federaciji.", "level": "FBiH"},
    "oi2026-5": {"short": "Predsjednik RS", "kind": "one", "who": "predsjednik i dva potpredsjednika Republike Srpske",
                 "plain": "Biraš JEDNOG čovjeka. Ko ima najviše glasova je predsjednik; potpredsjednici su kandidati s najviše glasova među Bošnjacima i Hrvatima (ako pobijedi Srbin), jer RS mora imati po jednog iz sva tri naroda.", "level": "RS"},
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


PARTY_STOP = {"koalicija", "za", "i", "bih", "lista", "zajedno", "u", "na", "pokret", "stranka", "nezavisna", "narodna", "bosnu", "hercegovinu", "bosne", "hercegovine", "rs", "dr", "hb", "as", "srpske", "srpska"}


def party_tokens(name):
    return {w for w in party_key(name).split() if w not in PARTY_STOP and not w.isdigit()}


def same_party(a, b):
    """Printed names that are the same party: known identity, or a party that later ran inside a
    coalition whose printed name still carries it (SDA -> 'Koalicija za Mostar 2020 - SDA, BPS, DF')."""
    if party_identity(a) == party_identity(b):
        return True
    ta, tb = party_tokens(a), party_tokens(b)
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if bool(small) and len(small) <= 2 and small <= big:
        return True
    acr = {t for t in small if len(t) <= 4 and not t.isdigit()}   # 'pdp' inside 'za pravdu i red ... pdp rs'
    return bool(acr) and acr <= big and len(small) <= 5


def unique_parties(tl):
    out = []
    for t in sorted(dedupe_tl(tl), key=lambda t: (t.get("y") or 0)):
        p = t.get("party")
        if p and not any(same_party(p, q) for _, q in out):
            out.append((t["y"], p))
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


def short_or_coal(p):
    """Short party name; long coalition strings become 'HDZ BiH (koalicija)'."""
    raw, short = party_title(p, raw=True), party_title(p)
    if len(raw) > 28 and short != raw:
        return f"{short} (koalicija)"
    return raw


CAL = json.load(open(D + "chance_calibration.json")) if os.path.exists(D + "chance_calibration.json") else {}


def cal_pct(bucket, personal, default):
    """Observed 2022 win rate for people in this position bucket with this past record.

    Falls back to the position-only rate, then to the hand-set default, so a missing
    or half-built calibration file degrades instead of inventing a number."""
    cell = (CAL.get("crossed") or {}).get(f"{bucket}|{personal}")
    if cell and cell.get("pct"):
        return cell["pct"]
    return ((CAL.get("position") or {}).get(bucket) or {}).get("pct") or default


# How the record read before this election. backtest.py measures the 2022 win rate for
# each of these against each list position, because on an open list a preferential vote
# moves people: in 2022 someone who had already topped their own list won about one time
# in four, against one in thirty for someone who had never been on a ballot.
PERSONAL_CLAUSE = {
    "top1": "Već je bio prvi po glasovima na svojoj listi.",
    "strong": "Već je biran ili bio pri vrhu svoje liste po glasovima.",
    "ran": "Dosad se nije približio vrhu svoje liste po glasovima.",
    "none": "Nikad prije nije bio na listiću.",
}
PERSONAL_SHORT = {
    "top1": "bio prvi po glasovima",
    "strong": "bio pri vrhu po glasovima",
    "ran": "bez jačeg rezultata",
    "none": "prvi put na listiću",
}


def personal_bucket(pid):
    """Four classes, same ones backtest.py measured on 2022, using only what was known
    before 2026. Ranks come from data/timelines.json, where every candidacy is placed
    against the people on the same list."""
    past = [t for t in timelines.get(pid, []) if (t.get("y") or 0) < 2026]
    if not past:
        return "none"
    best, won = None, False
    for t in past:
        if t.get("elected"):
            won = True
        if t.get("seat") != "single" and t.get("rank") and (best is None or t["rank"] < best):
            best = t["rank"]
    if best == 1:
        return "top1"
    if won or (best is not None and best <= 3):
        return "strong"
    return "ran"


def popularity(pid):
    """Personal votes already won, and where that placed the person on their own list.

    This is a record, not a forecast: every number here already happened."""
    past = [t for t in timelines.get(pid, []) if (t.get("y") or 0) < 2026 and t.get("votes")]
    if not past:
        return None
    ranked = [t for t in past if t.get("rank") and t.get("seat") != "single"]
    return {
        "rows": sorted(past, key=lambda t: (t.get("y") or 0)),
        "n": len(past),
        "top": max(past, key=lambda t: t.get("votes") or 0),
        "last": max(past, key=lambda t: t.get("y") or 0),
        "best": min(ranked, key=lambda t: (t["rank"], -(t.get("pct") or 0))) if ranked else None,
        "bucket": personal_bucket(pid),
        "bucket_text": PERSONAL_SHORT[personal_bucket(pid)],
    }


def office_terms(rows):
    """Group repeats of the same office into one line with its terms.

    The chair of the Presidency rotates every eight months, so a two-term member
    collects four identical entries; printed raw they read like four different jobs."""
    out, order = {}, []
    for o in rows or ():
        key = (o["title"], o.get("of"), o.get("district"))
        if key not in out:
            out[key] = {"title": o["title"], "of": o.get("of"), "district": o.get("district"),
                        "party": o.get("party"), "terms": []}
            order.append(key)
        a, b = (o.get("start") or "")[:4], (o.get("end") or "")[:4]
        if not a:
            span = None
        elif not b:
            span = f"od {a}."
        elif a == b:
            span = a
        else:
            span = f"{a}–{b}"
        if span and span not in out[key]["terms"]:
            out[key]["terms"].append(span)
    return [out[k] for k in order]


def office_line(rows):
    """The single office worth putting in a one-sentence summary: the one held
    longest. Bakir Izetbegović stood twice by the election record and won nothing;
    he also sat in the Presidency for eight years, and that is the sentence."""
    if not rows:
        return None
    def span(o):
        a, b = (o.get("start") or "")[:4], (o.get("end") or "")[:4]
        if not a:
            return 0
        return (int(b) if b else 2026) - int(a)
    best = max(rows, key=span)
    if span(best) < 1:
        return None
    a, b = (best.get("start") or "")[:4], (best.get("end") or "")[:4]
    when = f"{a}–{b}" if b else f"od {a}."
    title = best["title"]
    if title[:1].isupper() and title[1:2].islower():
        title = title[0].lower() + title[1:]
    return f"Bio/la je {title}, {when}"


def person_view(c):
    """Everything a page needs to say about one candidate, in plain words."""
    pid = c.get("pid") or ""
    rec = people.get(pid, {})
    tl = timelines.get(pid, [])
    prof = profiles.get(pid, {})
    # The API counts only the candidacies it was willing to put under one person id.
    # data/person_stats.json counts the merged record the profile below actually shows,
    # so the badge on a ballot card and the history on this page cannot disagree.
    st = pstats.get(pid)
    if st:
        stood, won = st.get("stood") or 0, st.get("won") or 0
    else:
        stood, won = rec.get("stood") or c.get("stood") or 0, rec.get("won") or c.get("won") or 0
    parties = unique_parties(tl)
    won_rows = [t for t in tl if t.get("elected")]
    home = None
    for t in sorted(tl, key=lambda t: -(t.get("y") or 0)):
        if t.get("area") and (("vijeće" in (t.get("lvl") or "")) or ("ačelnik" in (t.get("lvl") or ""))):
            home = nice_name(t["area"]); break
    v = {"pid": pid, "slug": pid_slug(pid) if pid else None, "name": nice_name(c.get("name")), "raw_name": c.get("name"), "home": nice_area(home) if home else None, "home_key": home_key(home) if home else "",
         "pos": c.get("pos"), "stood": stood, "won": won, "office": rec.get("isOfficeHolder") or c.get("office"),
         "parties": parties, "n_parties": len(parties), "confidence": rec.get("confidence") or c.get("confidence"),
         "has_record": pid in records, "has_page": bool(pid),
         "merged": st.get("merged") or 0, "office_rows": offices.get(pid),
         "office_terms": office_terms((offices.get(pid) or {}).get("offices")),
         "maybe": maybe_same.get(pid) or [],
         "won_rows": won_rows,
         "img": f"lica/{prof['publicId']}.webp" if prof.get("portrait") and prof.get("publicId") and os.path.exists(f"static/lica/{prof['publicId']}.webp") else None,
         "img_credit": (prof.get("portrait") or {}).get("credit"),
         "pop": popularity(pid) if pid else None}
    badges = []
    last_win = max((t.get("y") or 0) for t in won_rows) if won_rows else 0
    if v["office"] and (not last_win or last_win >= 2018):
        badges.append(("office", "sada na funkciji", "Po javnom registru trenutno drži izbornu funkciju."))
    else:
        v["office"] = False
    if won and won > 0:
        lv = {t.get("lvl") for t in won_rows}
        local = lv and all(("vijeće" in (l or "")) or ("ačelnik" in (l or "")) for l in lv)
        where = "lokalno" if local else ""
        badges.append(("won", (f"izabran {won}× {where}" if won > 1 else f"već biran {where}").strip(),
                       "Ranije izabran: " + ", ".join(f"{t['y']} {t['lvl']}" for t in won_rows[:6])))
    if v["n_parties"] > 1:
        badges.append(("switch", f"mijenjao stranke ({v['n_parties']})", "Kandidovao se za različite stranke: " + " → ".join(f"{short_or_coal(p)} ({y})" for y, p in parties) + ". Ako je stranka samo promijenila ime ili ušla u koaliciju, ovo može biti greška."))
    if stood == 1:
        badges.append(("new", "prvi put", "Prvi put na listiću."))
    if stood >= 2 and not won:
        badges.append(("filler", f"{stood}. put na listi, još neizabran", "Kandidovao se više puta, do sada nije osvojio mandat."))
    if v["has_record"]:
        badges.append(("record", "ima zapis glasanja", "Bio poslanik 2022–2026, vidi kako je glasao."))
    if v["office_rows"]:
        _o = v["office_rows"]["offices"]
        badges.append(("funkcija", "držao/la javnu funkciju",
                       "Funkcije koje CIK ne objavljuje, po Wikidati: "
                       + "; ".join(f"{x['title']} ({(x.get('start') or '')[:4]}"
                                   + (f"–{x['end'][:4]}" if x.get("end") else "–")
                                   + ")" for x in _o[:6]) + "."))
    # personal votes, the thing an open list actually decides. Same badge on the ballot
    # card and on the profile, so the two pages never tell a different story.
    best = (v["pop"] or {}).get("best")
    if best and best.get("rank") == 1:
        badges.append(("pop", "prvi po glasovima",
                       f"{best['y']}: {num(best['votes'])} glasova, najviše od {best['of']} ljudi na svojoj listi"
                       + (f" ({round(best['pct'])} posto svih glasova liste)" if best.get("pct") else "") + "."))
    elif best and best.get("rank") and best["rank"] <= 3:
        badges.append(("pop", f"{best['rank']}. po glasovima",
                       f"{best['y']}: {num(best['votes'])} glasova, {best['rank']}. od {best['of']} ljudi na svojoj listi."))
    v["badges"] = badges
    # one-sentence story
    s = []
    if stood == 1:
        s.append("Prvi put se kandiduje.")
    else:
        s.append(f"Kandiduje se {stood}. put" + (f", izabran/a {won} puta." if won else ", do sada nije izabran/a."))
    if v["n_parties"] > 1:
        s.append("Stranke: " + " → ".join(f"{short_or_coal(p)} ({y})" for y, p in parties) + ".")
    elif parties and stood > 1:
        printed = []
        for t in sorted(dedupe_tl(tl), key=lambda t: (t.get("y") or 0)):
            nm = party_title(t.get("party"), raw=True) if t.get("party") else None
            if nm and nm not in printed:
                printed.append(nm)
        if len(printed) > 1:
            s.append(f"Uvijek za istu stranku, koja je na listiću pisala kao: {' → '.join(printed)} (promjena imena ili koalicija, ne stranke).")
        else:
            s.append(f"Uvijek za: {party_title(parties[0][1])}.")
    _line = office_line((v["office_rows"] or {}).get("offices"))
    if _line:
        s.insert(1, _line + ".")
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
            "program": program_for(list_display.get(pk, "")), "p22": p22_for(program_for(list_display.get(pk, ""))), "hist": history_for(program_for(list_display.get(pk, ""))), "key_votes": party_key_votes(pk),
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
ASSET_V = hashlib.sha256(b"".join(open(f, "rb").read() for f in ("static/style.css", "static/app.js"))).hexdigest()[:8]
base_ctx = {"generated": gen, "RACE": RACE, "PRES_CTX": PRES_CTX, "COMP": COMP, "CHAMBER_NAME": CHAMBER_NAME, "ASSET_V": ASSET_V}

RACE_LVL = {"oi2026-2": "Predstavnički dom PSBiH", "oi2026-4": "Predstavnički dom Parlamenta FBiH", "oi2026-6": "Narodna skupština Republike Srpske", "oi2026-7": "Skupštine kantona"}

# --- chance of winning a seat: rough estimate from 2022 seats here, list position, prior wins
def chance_word(pct):
    return "velika" if pct >= 50 else "srednja" if pct >= 18 else "mala" if pct >= 5 else "vrlo mala"


def od_deset(pct):
    """Odds in words. „N od 10" reads naturally down to about a tenth, but below that it
    flattens everything: 1 percent and 9 percent both became „1 od 10". Now that the rule
    tells those apart, small numbers switch to „1 od N"."""
    if pct >= 10:
        return f"{round(pct / 10)} od 10"
    return f"1 od {max(2, round(100 / max(pct, 1)))}"


def list_chances(u, l):
    """{pid: (pct, word, why)} for one list on one ballot. pct = share of candidates in the same
    situation who actually won in 2022 (data/chance_calibration.json, backtest.py). Estimate, not a forecast."""
    pi = party_identity(l["name"])
    seats = 0
    for nm, cnt in u.get("seats22", {}).items():
        if party_identity(nm) == pi:
            seats += cnt
    cands = l["candidates"]
    total22 = sum((h.get("votes") or 0) for h in u.get("party_history", []) if h["year"] == 2022) or 1
    v22 = sum((h.get("votes") or 0) for h in u.get("party_history", []) if h["year"] == 2022 and party_identity(h["party"]) == pi)
    ranked = sorted(cands, key=lambda c: c.get("pos") or 99)
    out = {}
    for rank, c in enumerate(ranked, 1):
        pid = c.get("pid") or ""
        pb = personal_bucket(pid) if pid else "none"
        # A list that did not clear 3 percent here in 2022 is the weak end of the
        # "party holds no seat" group the calibration measured, so the measured number is
        # closer to a ceiling than a floor for it. We say that rather than invent a number:
        # matching a 2026 list back to its 2022 self by name is itself unreliable, and for
        # 2634 of 7779 candidates we find no 2022 votes for their list at all.
        dead_list = seats <= 0 and v22 / total22 < 0.03
        if seats <= 0:
            bucket = "no_seats_pos1" if rank == 1 else "no_seats_rest"
            where = ("stranka 2022 ovdje nije dobila nijedno mjesto, a ovaj je prvi na listi" if rank == 1
                     else "stranka 2022 ovdje nije dobila nijedno mjesto, a ovaj nije ni prvi na listi")
        elif rank <= seats:
            bucket = "within"; where = f"stranka je 2022 ovdje dobila {mjesta(seats)}, a ovaj je {rank}. na listi"
        elif rank == seats + 1:
            bucket = "plus1"; where = f"prvi iza {mjesta(seats)} koliko je stranka dobila 2022"
        elif rank == seats + 2:
            bucket = "plus2"; where = "drugi iza mjesta koliko je stranka dobila 2022"
        else:
            bucket = "beyond"; where = "daleko iza mjesta koliko je stranka dobila 2022"

        default = {"within": 63, "plus1": 19, "plus2": 6, "beyond": 2,
                   "no_seats_pos1": 15, "no_seats_rest": 2}[bucket]
        pct = cal_pct(bucket, pb, default)
        why = (where[0].upper() + where[1:] + ". " + PERSONAL_CLAUSE[pb]
               + f" Od ovakvih je 2022 prošlo {od_deset(pct)}.")
        if dead_list:
            why += (" Ova lista 2022 ovdje nije izlazila ili nije prešla 3 posto glasova, "
                    "pa je za nju ovaj procenat prije gornja nego donja granica.")
        if u["area"] in COMP:
            pct = min(pct, 19); why = "Ovo je dodatna lista: ta mjesta stranka dijeli po svom redu, pa se ne može računati."
        out[c.get("pid") or c["name"]] = (pct, chance_word(pct), why, od_deset(pct), pb)
    return out


def vote_weight(u, list_name):
    """The other question, the one a chance percentage does not answer: is the ballot
    thrown away? A seat is taken by the list, so a vote on a list under the 3 percent
    census does nothing at all, however popular the person on it. In 2022 that was 14.8
    percent of votes in Tuzla canton and 45.9 percent in the worst constituency."""
    st = list_strength.get(f"{u['race']}-{u['area']}")
    if not st:
        return None
    pi = party_identity(list_name)
    mine = None
    for label, row in st["by_party"].items():
        if party_identity(label) == pi:
            mine = {**row, "label": label} if mine is None else {
                **mine, "voters": mine["voters"] + row["voters"],
                "seats": mine["seats"] + row["seats"],
                "share": round(mine["share"] + row["share"], 1)}
    return {"unit": st, "list": mine}


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
            past = [x for x in tl if (x.get("y") or 0) < 2026 and x.get("votes")]
            best_v = max(past, key=lambda x: x["votes"]) if past else None
            ranked = [x for x in past if x.get("rank") and x.get("seat") != "single"]
            best_r = min(ranked, key=lambda x: x["rank"]) if ranked else None
            rec = record_summary(pid)
            r0 = (rec or [None])[-1] if rec else None
            out.append({"id": pid, "n": v["name"], "l": li, "pos": c.get("pos"), "s": v["stood"] or 0, "w": v["won"] or 0, "p": max(v["n_parties"], 1),
                        "v22": v22, "za": r0["za_pct"] if r0 else None, "pris": r0["prisustvo_pct"] if r0 else None, "rec": bool(rec),
                        "vb": best_v["votes"] if best_v else None, "vby": best_v["y"] if best_v else None,
                        "rk": best_r["rank"] if best_r else None, "rko": best_r["of"] if best_r else None,
                        "story": v["story"], "href": f"kandidat-{v['slug']}.html" if v["has_page"] else None, "img": v["img"],
                        "ch": chance[0] if chance else None, "chw": chance[1] if chance else None})
    return json.dumps({"lists": lists, "cands": out}, ensure_ascii=False, separators=(",", ":"))

unit_json = {uk: unit_cands_json(u) for uk, u in units.items() if RACE[u["race"]]["kind"] == "list"}
# One file per ballot, fetched by viz.js when the reader opens the chart. Inlining this in
# every profile made dist/ 661 MB; as files it is a couple of megabytes served once.
unit_json_url = {}
for _uk, _j in unit_json.items():
    _name = f"kandidati-{_uk}.json"
    write(_name, _j)
    unit_json_url[_uk] = _name
for _asset in ("viz.js", "style.css", "app.js"):
    shutil.copy(f"static/{_asset}", f"dist/{_asset}")
shutil.copytree("static/lica", "dist/lica")

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
# --- derived analytics over roll-call votes (analytics.py)
DIV_CH = {d: x["chamber"] for d, x in divisions.items()}
people_rec = {}
for pid, entries in cand_index.items():
    if pid in records:
        uk0, lname0, c0 = entries[0]
        people_rec[pid] = {"name": nice_name(c0.get("name")), "party": party_identity(lname0), "party_name": party_title(lname0),
                           "href": f"kandidat-{pid_slug(pid)}.html"}
SIM = analytics.similarity(votes, DIV_CH, list(CHAMBER_NAME), people_rec)
PLINE = analytics.party_line(votes, DIV_CH, list(CHAMBER_NAME), people_rec)
PMATRIX = analytics.party_matrix(votes, DIV_CH, list(CHAMBER_NAME), people_rec, lambda pk: party_title(list_display.get(pk, pk)))
ACT = analytics.activity(votes, divisions, DIV_CH, list(CHAMBER_NAME), people_rec, records)
for _pid in SIM:
    for _ch in SIM[_pid]:
        for _row in SIM[_pid][_ch]["same"] + SIM[_pid][_ch]["opposite"]:
            _row["party"] = people_rec[_row["pid"]]["party_name"]
THEMES = analytics.promise_themes(programs)

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


# Council work, as close to a personal record as the sources allow.
# eCitizen publishes agendas and the for/against/abstain totals of a session, but it
# never names who voted which way: 38 cities, 142 sessions, zero named councillors.
# So this is what the body decided while the person sat in it, labelled as such, and
# it must never be printed as if it were their own vote.
ec_by_home = {}
for _m in municipalities:
    if _m["slug"] in ec_by_slug:
        ec_by_home[home_key(_m["name"])] = {**ec_by_slug[_m["slug"]], "muni": _m["name"], "slug": _m["slug"]}

SPEND_WORD = {"procurement.awarded.total": "ugovorenih javnih nabavki",
              "budget.appropriation.adopted": "usvojenog budžeta"}


def local_record(tl):
    """For someone with no roll-call record: the bodies they actually sat in, what those
    bodies spend, and what they had on the agenda. Institution-level facts, every one."""
    seats = [t_ for t_ in tl if t_.get("elected") and t_.get("unit")]
    if not seats:
        return None
    first = {}
    for t_ in seats:
        u = t_["unit"]
        if u not in first or (t_.get("y") or 0) < first[u]["y"]:
            first[u] = {"y": t_.get("y"), "lvl": t_.get("lvl"), "area": t_.get("area")}
    bodies = []
    for uid, info in sorted(first.items(), key=lambda kv: -(kv[1]["y"] or 0)):
        spend = unit_spend.get(uid) or {}
        years = sorted(((int(y), v) for y, v in (spend.get("years") or {}).items()
                        if int(y) >= (info["y"] or 0)), reverse=True)[:4]
        council = ec_by_home.get(home_key(info["area"] or ""))
        agenda = []
        # Only sessions that fall inside the term this seat started. A council sits four
        # years; showing this year's agenda to someone who left in 2020 would be a lie.
        last_win = max((t_.get("y") or 0) for t_ in seats if t_.get("unit") == uid)
        if council:
            for sess in council["sessions"]:
                year = int((sess.get("date") or "0")[:4] or 0)
                if not (last_win <= year <= last_win + 4):
                    continue
                for a in sess["agendas"][:3]:
                    agenda.append({"date": sess.get("date"), "name": a.get("name"),
                                   "for": a.get("for"), "against": a.get("against"),
                                   "abstained": a.get("abstained")})
        bodies.append({"unit": uid, "lvl": info["lvl"], "area": info["area"], "since": info["y"],
                       "spend": [{"y": y, "value": v["value"], "what": SPEND_WORD.get(v["measure"], v["measure"])}
                                 for y, v in years],
                       "muni": council["muni"] if council else None,
                       "agenda": agenda[:6]})
    return bodies or None


def loyalty(tl):
    """Which party, for how long, and every switch — computed from candidacies, so it is
    what CIK published and not what anyone says about themselves."""
    rows = [t_ for t_ in tl if t_.get("party") and t_.get("y")]
    if not rows:
        return None
    spans, cur = [], None
    for t_ in sorted(rows, key=lambda r: r["y"]):
        k = party_identity(t_["party"])
        if cur and cur["key"] == k:
            cur["to"] = t_["y"]
            cur["n"] += 1
        else:
            cur = {"key": k, "name": t_["party"], "from": t_["y"], "to": t_["y"], "n": 1}
            spans.append(cur)
    return {"spans": spans, "switches": len(spans) - 1,
            "years": (spans[-1]["to"] - spans[-1]["from"]) if spans else 0}


n_kand = 0
search_rows = []
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
    sp_good = [x for x in sp if len(re.sub(r"[^\wČĆŽŠĐčćžšđ ]", "", x["text"]).strip()) >= 40]
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
    def _where(uu):
        if uu["race"] in ("oi2026-1", "oi2026-5"):
            return ""
        if uu["area"] in COMP:
            return ", " + COMP[uu["area"]]
        ms = unit_munis.get(f"{uu['race']}-{uu['area']}", [])
        return ", " + (", ".join(ms[:3]) + (f" i još {len(ms) - 3}" if len(ms) > 3 else "")) if ms else f", područje {uu['area']}"
    runs = [{"unit": units[e[0]], "list": e[1], "chance": _chance(e), "href": unit_href(units[e[0]]["race"], units[e[0]]["area"]), "pos": e[2].get("pos"),
             "party_href": party_href(e[1]), "where": _where(units[e[0]])} for e in entries]
    main_uk = next((e[0] for e in entries if units[e[0]]["area"] not in COMP), uk)
    _mu = units[main_uk]
    bar = seat_bar.get(f"{_mu['race']}-{_mu['area']}")
    tl_json = json.dumps([{"y": t.get("y"), "won": bool(t.get("elected")), "lvl": t.get("lvl")} for t in tl], ensure_ascii=False)
    pop = v["pop"]
    pop_json = json.dumps({"rows": [{"y": t.get("y"), "votes": t.get("votes"), "rank": t.get("rank"),
                                     "of": t.get("of"), "pct": t.get("pct"), "elected": bool(t.get("elected")),
                                     "label": f"{t.get('lvl') or ''}{', ' + nice_area(t['area']) if t.get('area') else ''}"}
                                    for t in (pop or {}).get("rows", [])]}, ensure_ascii=False) if pop else None
    appt = appointed.get(pid) or []
    _mlist = next((e[1] for e in entries if e[0] == main_uk), None)
    weight = vote_weight(_mu, _mlist) if _mlist and RACE[_mu["race"]]["kind"] == "list" else None
    # the legal preferential bar: 20 percent of a list's voters must circle you to jump the
    # party's order. pop["best"]["pct"] is measured against the same denominator.
    pref = None
    if weight:
        _b = (pop or {}).get("best")
        pref = {"need": 20, "had": round(_b["pct"]) if _b and _b.get("pct") else None,
                "y": _b["y"] if _b else None, "where": nice_area(_b["area"]) if _b and _b.get("area") else None}
    bodies = local_record(tl) if not rec else None
    loy = loyalty(tl)
    act_json = {ch: json.dumps({"rows": rows, "avg": (CH_AVG.get(ch) or {}).get("pris")}, ensure_ascii=False) for ch, rows in ACT.get(pid, {}).items()}
    html = kand_tpl.render(p=v, tl=tl, tl_json=tl_json, pop=pop, pop_json=pop_json, appt=appt, bodies=bodies, loy=loy, bar=bar, weight=weight, pref=pref,
                           prof=prof, rec=rec, kd=kd, replacement=replacement, cands_url=unit_json_url.get(main_uk), CH_AVG=CH_AVG, speeches_n=len(sp), speeches=sp_good[:5], assets=assets, runs=runs,
                           sim=SIM.get(pid, {}), pline=PLINE.get(pid, {}), act=act_json, my_party=people_rec.get(pid, {}).get("party_name"), **base_ctx)
    write(f"kandidat-{v['slug']}.html", html)
    n_kand += 1
    # One compact row per person for the name search. Folding happens in the browser with
    # the same foldq() the municipality box uses, so Cyrillic and Latin both match and the
    # file does not have to carry a second copy of every name.
    marks = ""
    if v["office"]:
        marks += "o"
    elif v["won"]:
        marks += "w"
    if (v["pop"] or {}).get("best") and v["pop"]["best"]["rank"] == 1:
        marks += "p"
    if v["stood"] == 1:
        marks += "n"
    _u0 = units[entries[0][0]]
    _ms = unit_munis.get(f"{_u0['race']}-{_u0['area']}", [])
    where = v["home"] or (", ".join(_ms[:2]) + ("…" if len(_ms) > 2 else "") if _ms else RACE[_u0["race"]]["short"])
    search_rows.append([v["name"], v["slug"], party_title(entries[0][1]), where, marks])

search_rows.sort(key=lambda r: fold(r[0]))
write("kandidati.json", json.dumps({"n": len(search_rows), "c": search_rows},
                                   ensure_ascii=False, separators=(",", ":")))

# --- ballot (unit) pages
listic_tpl = env.get_template("listic.html")
for uk, u in units.items():
    race = u["race"]
    hist22, hist18 = {}, {}
    for h in u.get("party_history", []):
        tgt = hist22 if h["year"] == 2022 else hist18
        k_ = party_identity(h["party"])
        tgt[k_] = {"votes": (tgt.get(k_, {}).get("votes") or 0) + (h.get("votes") or 0)}
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
                      "w22": (vote_weight(u, l["name"]) or {}).get("list"),
                      "seats22": seats22.get(pi, 0), "program": prog, "p22": p22_for(prog), "hist": history_for(prog), "party_href": party_href(l["name"]),
                      "key_votes": recent_kv})
    total22 = sum((h.get("votes") or 0) for h in u.get("party_history", []) if h["year"] == 2022)
    top22 = sorted([h for h in u.get("party_history", []) if h["year"] == 2022], key=lambda h: -(h.get("votes") or 0))[:5]
    munis = unit_munis.get(uk, [])
    now_ids = {party_identity(l["name"]) for l in u["lists"]}
    absent22 = []
    for h in sorted([h for h in u.get("party_history", []) if h["year"] == 2022], key=lambda h: -(h.get("votes") or 0)):
        pi_ = party_identity(h["party"])
        if pi_ not in now_ids and total22 and (h.get("votes") or 0) >= 0.03 * total22 and pi_ not in {a[2] for a in absent22} and not any(same_party(h["party"], l["name"]) for l in u["lists"]):
            absent22.append((party_title(h["party"]), h.get("votes") or 0, pi_, party_href(h["party"])))
    html = listic_tpl.render(u=u, r=RACE[race], lists=lists, total22=total22, top22=top22, munis=munis, cands_url=unit_json_url.get(uk), absent22=absent22,
                               weight=(vote_weight(u, u["lists"][0]["name"]) if u.get("lists") and RACE[race]["kind"] == "list" else None),
                               bar=seat_bar.get(f"{race}-{u['area']}"), **base_ctx)
    write(unit_href(race, u["area"]), html)

# --- municipality pages
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
        agg = {}
        for h in u.get("party_history", []):
            if h["year"] != 2022:
                continue
            k_ = party_identity(h["party"])
            if k_ not in agg:
                agg[k_] = {"party": h["party"], "votes": 0}
            agg[k_]["votes"] += h.get("votes") or 0
        top = sorted(agg.values(), key=lambda h: -(h.get("votes") or 0))[:3]
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
def heat_sentences(m):
    out = []
    for i, p in enumerate(m["parties"]):
        pairs = [(m["parties"][j], m["m"][i][j]) for j in range(len(m["parties"])) if j != i and m["m"][i][j] is not None]
        if not pairs:
            continue
        pairs.sort(key=lambda x: -x[1])
        same = ", ".join(f"{q} {v}%" for q, v in pairs[:2])
        opp = pairs[-1]
        out.append(f"{p}: najčešće isto kao {same}; najrjeđe isto kao {opp[0]} ({opp[1]}%).")
    return out
PINFO = {}
for _pk, _pp in party_pages.items():
    if _pp.get("program"):
        _c = (_pp.get("p22") or {}).get("counts") or {}
        _rated = _c.get("ispunjeno", 0) + _c.get("djelimično", 0) + _c.get("nije", 0)
        PINFO[_pp["program"]["name"]] = {"href": _pp["href"], "p22": f"prošli put provjereno {_rated}: {_c.get('ispunjeno', 0)} uradili, {_c.get('djelimično', 0)} pola, {_c.get('nije', 0)} nisu" if _rated else ("nisu bili u vlasti 2022–2026, nema šta provjeriti" if _c else "")}
write("stranke.html", env.get_template("stranke.html").render(parties=plist, pmatrix={ch: json.dumps(m, ensure_ascii=False) for ch, m in PMATRIX.items()}, heat_text={ch: heat_sentences(m) for ch, m in PMATRIX.items()}, **base_ctx))
write("obecanja.html", env.get_template("obecanja.html").render(themes=THEMES, n_parties=len([p for p in programs if p.get("promises")]), pinfo=PINFO, **base_ctx))
RACE22_NAME = {"32-2": "Predstavnički dom PSBiH", "32-4": "Predstavnički dom Parlamenta FBiH",
               "32-6": "Narodna skupština RS", "32-7": "Skupštine kantona"}
# How often a 2026 list cannot be matched back to any 2022 result by name. This is a real
# limit on the chance estimate, so metoda.html prints it rather than hiding it.
unmatched_lists, total_cands = 0, 0
for _uk, _u in units.items():
    if RACE[_u["race"]]["kind"] != "list":
        continue
    for _l in _u["lists"]:
        _pi = party_identity(_l["name"])
        _v = sum((h.get("votes") or 0) for h in _u.get("party_history", [])
                 if h["year"] == 2022 and party_identity(h["party"]) == _pi)
        total_cands += len(_l["candidates"])
        if not _v:
            unmatched_lists += len(_l["candidates"])
write("metoda.html", env.get_template("metoda.html").render(
    cal=CAL, RACE22_NAME=RACE22_NAME, unmatched_lists=unmatched_lists, total_cands=total_cands,
    kd=key_decisions, n_records=len(records), n_div=len(divisions), n_programs=len(programs),
    bridges_seen=history_meta.get("bridges_seen", 0), bridges_applied=history_meta.get("bridges_applied", 0),
    candidacies_seen=history_meta.get("candidacies_seen", 0),
    merged_people=history_meta.get("people_gained_by_merge", 0),
    merge_tiers=merge_tiers, maybe_people=len(maybe_same),
    maybe_rows=sum(len(v) for v in maybe_same.values()),
    offices_people=len(offices), offices_link=Counter(v["link"] for v in offices.values()),
    offices_dropped=len(offices_meta.get("ambiguous", [])), **base_ctx))

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
