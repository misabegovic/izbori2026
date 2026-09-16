#!/usr/bin/env python3
"""Everything that happened between the last general election and this one -> data/swing.json.

The seat-chance table in backtest.py measures one thing: what share of candidates in a
given situation won in 2022. It cannot know that a party has since collapsed or doubled,
because 2022 is the only election it looks at. A projection needs the other half — how the
vote has moved since — and in BiH there are exactly three post-2022 CIK results to move it
with:

  lokalni izbori 2024 (6.10.2024)      — council votes in all 143 municipalities
  prijevremeni izbori za predsjednika RS 2025 (23.11.2025) — entity-wide, RS only
  prijevremeni izbori Vareš 2026       — one municipality, mayor only (not used)

Local councils are not the same contest as a general election: people split tickets, local
names carry weight, turnout differs. So the file also carries lokalni 2020 and 2016, which
is what makes the 2024 numbers usable — the projection does not read "SNSD got 34% locally
in 2024" but "SNSD is 4 points above where it was locally in 2020", and 2020 sits next to
the 2022 general the same way. That ratio is the swing; project.py applies it.

Shares are computed over *list voters*, never over summed personal votes. A ballot circles
up to three names and lists differ wildly in how much their voters use that, so personal
votes exaggerate the disciplined lists. The API's `percentage` on each candidacy is that
candidate's votes as a share of their list's ballots, and its implied denominator is the
same for everyone on a list, which recovers the ballot count exactly. Same method as
list_strength() in fetch_history.py, so the two files can be read side by side.

Writes data/swing.json and data/ballots.json. The second file is the past ballots themselves,
candidate by candidate — where each person stood, at what position, with how many personal
votes and whether they got in. project.py needs it for two things it cannot do from totals:
follow a party's people to whatever list they are on now, and replay the whole projection on
2022 as if 2022 had not happened yet. Local-election rows are kept only for people who also
appear on a general-election ballot, which is what keeps the file from becoming a mirror of
the whole archive.

Run before project.py. Source: gianniravioli.com Mashinerija (CC BY 4.0).
"""
import json
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

BASE = "https://api.gianniravioli.com/mashinerija/v1"
UA = {"User-Agent": "izbori2026-voter-guide/1.0 (github.com/misabegovic/izbori2026)"}
PAGE = 200
D = "data/"

# General elections. 2010 and 2014 do not exist in any readable source (see README), so the
# proportional baseline is 2018 and 2022 only.
GENERAL = {
    2018: {"election": 16, "races": {"pd-psbih": "25-2", "pd-fbih": "25-4", "nsrs": "25-6",
                                     "skupstine-kantona": "25-7", "predsjednistvo": "25-1",
                                     "predsjednik-rs": "25-5"}},
    2022: {"election": 23, "races": {"pd-psbih": "32-2", "pd-fbih": "32-4", "nsrs": "32-6",
                                     "skupstine-kantona": "32-7", "predsjednistvo": "32-1",
                                     "predsjednik-rs": "32-5"}},
}
MAJORITY = {"predsjednistvo", "predsjednik-rs"}

# Council races of each local election. Mostar 2020 and Brčko ride along as separate races
# in the same election, so both ids are pulled and merged by municipality.
LOCAL = {
    2016: {"election": 10, "races": ["13-9", "14-9"]},
    2020: {"election": 18, "races": ["27-9", "29-9"]},
    2024: {"election": 27, "races": ["36-9"]},
}
LOCAL_EXTRA = {2020: [("19", ["28-9"])]}  # Mostar voted separately in December 2020

BY_ELECTION = {  # single-seat races held between general elections
    "rs-predsjednik-2025": {"race": "39-5", "date": "2025-11-23",
                            "title": "Prijevremeni izbori za predsjednika Republike Srpske"},
}


def get(url, tries=4):
    for attempt in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180))
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def pull(path):
    sep = "&" if "?" in path else "?"
    total = get(f"{BASE}{path}{sep}limit=1")["meta"]["total"]
    offs = list(range(0, total, PAGE))
    out = []
    with ThreadPoolExecutor(12) as ex:
        for page in ex.map(lambda o: get(f"{BASE}{path}{sep}limit={PAGE}&offset={o}")["data"], offs):
            out += page
    return out


def party_label(r):
    p = r.get("party") or {}
    return p.get("label") or p.get("id")


def list_voters(cands):
    """Ballots cast for this list, recovered from the percentage the API prints per candidate.

    Every candidate on a list shares one denominator — their list's ballot count — so each
    candidate with a usable percentage reproduces it. Candidates under 0.5 percent are
    dropped because the rounding there is coarser than the number we want."""
    denoms = [c["votes"] / (c["percentage"]["value"] / 100)
              for c in cands
              if c.get("votes") and (c.get("percentage") or {}).get("value", 0) > 0.5]
    if not denoms:
        return None
    return round(sum(denoms) / len(denoms))


def fold_lists(rows, key):
    """rows -> {area: {party: {voters, votes, seats, cands}}} for proportional contests."""
    groups = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r.get("seat") == "single":
            continue
        p = party_label(r)
        if p:
            groups[key(r)][p].append(r)
    out = {}
    for area, parties in groups.items():
        by = {}
        for p, cands in parties.items():
            voters = list_voters(cands)
            by[p] = {
                "voters": voters,
                "votes": sum(c.get("votes") or 0 for c in cands),
                "seats": sum(1 for c in cands if c.get("elected")),
                "cands": len(cands),
            }
        total = sum(v["voters"] for v in by.values() if v["voters"])
        if not total:
            continue
        for v in by.values():
            v["share"] = round(100 * v["voters"] / total, 3) if v["voters"] else None
        out[str(area)] = {"voters": total, "seats": sum(v["seats"] for v in by.values()), "by_party": by}
    return out


def fold_single(rows, key):
    """rows -> {area: [{name, party, votes, share, elected}]} for majority contests."""
    groups = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    out = {}
    for area, cands in groups.items():
        total = sum(c.get("votes") or 0 for c in cands) or 1
        out[str(area)] = sorted(
            [{"name": c.get("name"), "party": party_label(c), "votes": c.get("votes") or 0,
              "share": round(100 * (c.get("votes") or 0) / total, 2), "elected": bool(c.get("elected"))}
             for c in cands], key=lambda x: -x["votes"])
    return out


def main():
    started = time.time()
    out = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source": "gianniravioli.com Mashinerija (CC BY 4.0), ogledalo CIK-a",
        "method": ("udjeli po glasačima liste, ne po zbiru ličnih glasova: listić zaokružuje do tri "
                   "imena i liste se razlikuju koliko to koriste. Broj glasača liste vadi se iz "
                   "`percentage` koji API daje uz svakog kandidata."),
        "general": {}, "local": {}, "by_election": {}, "seats": {},
    }

    print("1/4 opći izbori 2018 i 2022")
    for year, cfg in GENERAL.items():
        out["general"][str(year)] = {}
        for level, race in cfg["races"].items():
            rows = pull(f"/candidacies?raceId={race}")
            if level in MAJORITY:
                out["general"][str(year)][level] = {"kind": "single",
                                                    "areas": fold_single(rows, lambda r: r.get("areaCode"))}
            else:
                folded = fold_lists(rows, lambda r: r.get("areaCode"))
                out["general"][str(year)][level] = {"kind": "list", "areas": folded}
                out["seats"].setdefault(str(year), {})[level] = {a: v["seats"] for a, v in folded.items()}
            print(f"   {year} {level}: {len(rows)} kandidatura")

    print("2/4 lokalni izbori 2016, 2020, 2024 (vijeća)")
    for year, cfg in LOCAL.items():
        rows = []
        for race in cfg["races"]:
            rows += pull(f"/candidacies?raceId={race}")
        for _eid, races in LOCAL_EXTRA.get(year, []):
            for race in races:
                try:
                    rows += pull(f"/candidacies?raceId={race}")
                except Exception as e:
                    print(f"   upozorenje: {race} nije povučen ({e})")
        # Municipality slug is the join key to municipalities.json; areaCode alone repeats
        # across entities in some years.
        def muni(r):
            return ((r.get("unit") or {}).get("id")) or f"area:{r.get('areaCode')}"
        out["local"][str(year)] = fold_lists(rows, muni)
        print(f"   {year}: {len(rows)} kandidatura, {len(out['local'][str(year)])} općina")

    print("3/4 prijevremeni izbori između općih")
    for key, cfg in BY_ELECTION.items():
        rows = pull(f"/candidacies?raceId={cfg['race']}")
        out["by_election"][key] = {
            "title": cfg["title"], "date": cfg["date"],
            "areas": fold_single(rows, lambda r: r.get("areaCode") or "all"),
        }
        print(f"   {cfg['title']}: {len(rows)} kandidata")

    print("4/5 listići iz prošlosti, kandidat po kandidat")
    merges = {}
    try:
        groups = json.load(open(D + "merges.json")).get("groups") or {}
        merges = {pid: root for root, members in groups.items() for pid in members}
    except FileNotFoundError:
        print("   upozorenje: nema data/merges.json, identiteti ostaju kako ih API vraća")

    def root(pid):
        return merges.get(pid, pid)

    def row(r):
        p = r.get("person") or {}
        return {
            "pid": root(p.get("id")), "y": r.get("year"), "race": r.get("raceId"),
            "lvl": (r.get("level") or {}).get("id"), "area": str(r.get("areaCode") or ""),
            "unit": (r.get("unit") or {}).get("id"), "party": party_label(r),
            "pos": r.get("position"), "votes": r.get("votes"),
            "pct": (r.get("percentage") or {}).get("value"),
            "elected": bool(r.get("elected")), "via": r.get("electedVia"),
            "seat": r.get("seat"),
        }

    general_rows = []
    for year, cfg in GENERAL.items():
        for race in cfg["races"].values():
            general_rows += [row(r) for r in pull(f"/candidacies?raceId={race}")]
    # who we care about: anyone on a general ballot then, and everyone on the 2026 ballot now
    keep = {r["pid"] for r in general_rows if r["pid"]}
    try:
        keep |= set(json.load(open(D + "timelines.json")))
    except FileNotFoundError:
        pass

    local_rows = []
    for year, cfg in LOCAL.items():
        races = list(cfg["races"]) + [rc for _e, rcs in LOCAL_EXTRA.get(year, []) for rc in rcs]
        for race in races:
            try:
                local_rows += [x for x in (row(r) for r in pull(f"/candidacies?raceId={race}"))
                               if x["pid"] in keep]
            except Exception as e:
                print(f"   upozorenje: {race} nije povučen ({e})")

    ballots = {"generated": out["generated"],
               "note": ("Kandidature s ranijih izbora. Opći izbori su tu u cijelosti; s lokalnih "
                        "su zadržani samo ljudi koji se pojavljuju i na nekom općem listiću, "
                        "jer samo njih projekcija prati."),
               "identities": "spojene po data/merges.json" if merges else "kako ih API vraća",
               "general": general_rows, "local": local_rows}
    json.dump(ballots, open(D + "ballots.json", "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"   {len(general_rows)} općih + {len(local_rows)} lokalnih kandidatura zapisano")

    print("5/5 provjera veze s izbornim jedinicama 2026")
    munis = json.load(open(D + "municipalities.json"))
    known = {m["slug"] for m in munis}
    for year, areas in out["local"].items():
        hit = sum(1 for a in areas if a in known)
        missed = sorted(a for a in areas if a not in known)
        out.setdefault("coverage", {})[year] = {"municipalities": len(areas), "matched": hit,
                                                "unmatched": missed[:40]}
        print(f"   {year}: {hit}/{len(areas)} općina veže se na jedinicu 2026" +
              (f"; bez veze: {', '.join(missed[:6])}" + ("…" if len(missed) > 6 else "") if missed else ""))

    json.dump(out, open(D + "swing.json", "w"), ensure_ascii=False, indent=1)
    print(f"\ndata/swing.json zapisan za {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
