#!/usr/bin/env python3
"""Mashinerija → data/timelines.json, appointed.json, unit_spend.json.

Why this exists: fetch.py used to pull candidacy timelines one person at a time,
and only for people who had already won or hold office. Five of every six people
on the 2026 ballots therefore had no history, no page, and no vote count.

The bulk /candidacies collection is the whole public record: 174k rows, 200 per
page. Pulling all of it costs about 900 requests and a minute, and it buys two
things the per-person route cannot. Everyone gets a history, and every candidacy
can be placed against the people it actually ran against, so we can say where
someone stood on their own list and not just how many votes they got.

Source: https://gianniravioli.com/mashinerija/ (CC BY 4.0 — attribution required).
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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

BASE = "https://api.gianniravioli.com/mashinerija/v1"
UA = {"User-Agent": "izbori2026-voter-guide/1.0 (github.com/misabegovic/izbori2026)"}
PAGE = 200          # the API refuses anything larger
THREADS = 12
D = "data/"


def get(url, tries=4):
    """GET with backoff. The API is someone's volunteer server; do not hammer it."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return json.load(urllib.request.urlopen(req, timeout=120))
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def pull_all_candidacies():
    """Every candidacy CIK ever published, 2006-2026."""
    total = get(f"{BASE}/candidacies?limit=1")["meta"]["total"]
    offsets = list(range(0, total, PAGE))
    print(f"   {total} kandidatura u {len(offsets)} stranica")
    rows = []
    with ThreadPoolExecutor(THREADS) as ex:
        for page in ex.map(lambda o: get(f"{BASE}/candidacies?limit={PAGE}&offset={o}")["data"], offsets):
            rows += page
    if len(rows) != total:
        print(f"   upozorenje: dobili {len(rows)} od {total}")
    return rows


def ballot_pids():
    """Everyone on a 2026 ballot, from the unit files fetch.py wrote."""
    pids = set()
    for name in os.listdir(D + "units"):
        u = json.load(open(D + "units/" + name))
        for l in u.get("lists", []):
            for c in l.get("candidates", []):
                if c.get("pid"):
                    pids.add(c["pid"])
    return pids


def rank_within_contest(rows):
    """{candidacy id: (rank, field_size)} by personal votes.

    For a list seat the field is the party's own list in that area, because that is
    the race a preferential vote actually decides. For a single seat (mayor, RS
    president) the field is everyone on that ballot.
    """
    contests = defaultdict(list)
    for r in rows:
        if r.get("votes") is None:
            continue
        if r.get("seat") == "single":
            key = ("single", r.get("raceId"), r.get("areaCode"))
        else:
            party = (r.get("party") or {}).get("id") or (r.get("party") or {}).get("label")
            key = ("list", r.get("raceId"), r.get("areaCode"), party)
        contests[key].append(r)
    out = {}
    for key, group in contests.items():
        group.sort(key=lambda r: -(r.get("votes") or 0))
        size = len(group)
        for i, r in enumerate(group, 1):
            out[r["id"]] = (i, size)
    return out


def pull_bridges():
    """Mashinerija's own proposed identity links — published, ranked, never applied.

    The compiler splits a person whenever it cannot prove two candidacies are one
    human, and says so: "pogrešan most izmišlja osobu, pa red smije ostati dug".
    It then publishes 28k candidate links with the signals behind each one, and
    leaves the judgement to whoever needs it. This is that judgement, made here and
    written down, because a voter guide that tells you Bakir Izetbegović has never
    won anything is worse than one that says "probably the same man, here is why".
    """
    rows, off = [], 0
    while True:
        d = get(f"{BASE}/bridges?limit={PAGE}&offset={off}")
        rows += d["data"]
        if off + PAGE >= d["meta"]["total"]:
            return rows
        off += PAGE


# CIK prints RS candidates in Cyrillic and everyone else in Latin, and the same person
# can appear in either script across years. Without this, "БРАНКО БЛАНУША" and "BRANKO
# BLANUŠA" are two different names, which quietly breaks the rarity test below: a name
# held by five people looks like two in each script, and tier 0 fires when it must not.
CYRILLIC = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Ђ": "DJ", "Е": "E", "Ж": "Z",
    "З": "Z", "И": "I", "Ј": "J", "К": "K", "Л": "L", "Љ": "LJ", "М": "M", "Н": "N",
    "Њ": "NJ", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "Ћ": "C", "У": "U",
    "Ф": "F", "Х": "H", "Ц": "C", "Ч": "C", "Џ": "DZ", "Ш": "S",
}


def fold_name(row):
    """(SURNAME, GIVEN), one script, diacritics stripped. CIK printed 'IZETBEGOVIĆ BAKIR'
    in 2006 and 'BAKIR IZETBEGOVIĆ' from 2016, which is one reason the two never met."""
    sn, gn = (row.get("surname") or "").strip(), (row.get("given") or "").strip()
    if not sn or not gn:
        parts = (row.get("name") or "").split()
        if len(parts) < 2:
            return None
        sn, gn = parts[0], parts[1]
    def f(s):
        s = "".join(CYRILLIC.get(c, c) for c in s.upper())
        s = s.replace("Đ", "DJ")
        s = unicodedata.normalize("NFD", s)
        return "".join(c for c in s if unicodedata.category(c) != "Mn")
    return (" ".join(f(sn).split()), " ".join(f(gn).split()))


# 2026 areas that are a second, entity-wide list of the same race. Standing on the
# regular list and on this one is the only way one person legitimately appears twice
# in a single election, so it is the only exception the conflict guard allows.
COMPENSATORY = {"501", "502", "400", "300"}

TIERS = {
    -1: "ručno provjereno",
    0: "ime se u cijeloj bazi javlja samo u ta dva zapisa",
    1: "ista stranka na obje kandidature, ime rijetko",
    2: "jedno područje sadrži drugo, a zapisi dijele stranku",
}

MANUAL = D + "manual_merges.json"


def read_manual():
    """Hand-checked identities, from data/manual_merges.json.

    Some people the automatic rules can never reach, and they are exactly the people a
    voter looks up. Semir Efendić was mayor of Novi Grad Sarajevo three times and sat in
    the Sarajevo canton assembly, then stood for the Presidency in 2026 for a different
    party — no shared party, no shared area, no rare name, so every signal the register
    publishes says nothing. The file is the place to say "we checked this one", with the
    reason and a source per row, and `not_same` for the reverse: suggestions we looked at
    and rejected, so a namesake's record stops being offered as a maybe.
    """
    if not os.path.exists(MANUAL):
        return [], []
    d = json.load(open(MANUAL))
    return d.get("merges") or [], d.get("not_same") or []


def build_merges(rows, bridges):
    """Apply the bridges we are willing to stand behind; keep the rest as a suggestion.

    Applied across the whole register, not only the 2026 ballots, because backtest.py
    measures the seat-chance rule on the 2022 field and render.py applies it to merged
    profiles: if the two counted identity differently the same person would get one
    answer on the page and another in the calibration behind it.

    A wrong merge invents a person, so every rule here needs a reason a reader can
    check, and one hard guard catches the case that burned the first draft: two
    people named Denis Bećirović, one the sitting member of the Presidency and one a
    Tuzla councillor, share a party and a region and would otherwise have been fused.
    Nobody stands for two different offices at the same election, so a union that
    would produce that is refused whatever the other signals say.
    """
    by_pid = defaultdict(list)
    for r in rows:
        pid = (r.get("person") or {}).get("id")
        if pid:
            by_pid[pid].append(r)
    by_name = defaultdict(set)
    for r in rows:
        k = fold_name(r)
        pid = (r.get("person") or {}).get("id")
        if k and pid:
            by_name[k].add(pid)
    rows_by_id = {r["id"]: r for r in rows}

    def parties(pid):
        return {(r.get("party") or {}).get("id") for r in by_pid.get(pid, ())
                if (r.get("party") or {}).get("id")}

    def conflicted(pids):
        per = defaultdict(list)
        for p in pids:
            for r in by_pid.get(p, ()):
                per[r.get("electionId")].append(r)
        for group in per.values():
            if len(group) < 2:
                continue
            if len({(r.get("level") or {}).get("id") for r in group}) > 1:
                return True
            if len(group) > 2:
                return True
            if not {str(r.get("areaCode")) for r in group} & COMPENSATORY:
                return True
        return False

    def tier(b, pa, pb):
        a = rows_by_id.get(b["a"]["candidacyId"])
        sig = b.get("signals") or {}
        n = len(by_name.get(fold_name(a), ())) if a else 99
        if n == 2:
            return 0
        if sig.get("sameParty") and n <= 3:
            return 1
        if sig.get("areaContains") and n <= 3 and (parties(pa) & parties(pb)):
            return 2
        return None

    parent, group = {}, defaultdict(set)

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def seed(p):
        r = find(p)
        if not group[r]:
            group[r].add(p)

    manual, _ = read_manual()
    applied, maybe, refused = [], [], defaultdict(int)
    manual_conflicts = []
    for entry in manual:
        pids = [p for p in entry.get("pids", []) if p in by_pid]
        missing = [p for p in entry.get("pids", []) if p not in by_pid]
        if missing:
            print(f"   upozorenje: {entry.get('name')} — nepoznat zapis {missing}")
        if len(pids) < 2:
            continue
        for p in pids:
            seed(p)
        roots = {find(p) for p in pids}
        union = set().union(*(group[r] for r in roots))
        if conflicted(union):
            # The guard outranks a hand-written line: a person on two ballots of one
            # election is a mistake in the file, not a fact about the person.
            manual_conflicts.append(entry.get("name"))
            continue
        keep = find(pids[0])
        for r in roots:
            if r != keep:
                parent[r] = keep
                group.pop(r, None)
        group[keep] = union
        applied.append({"tier": -1, "pids": sorted(union), "name": entry.get("name"),
                        "why": entry.get("why"), "sources": entry.get("sources") or []})
    if manual_conflicts:
        print(f"   ODBIJENO iz manual_merges.json (dva listića istih izbora): {manual_conflicts}")

    ranked = []
    for b in bridges:
        pa = (rows_by_id.get(b["a"]["candidacyId"]) or {}).get("person", {}).get("id")
        pb = (rows_by_id.get(b["b"]["candidacyId"]) or {}).get("person", {}).get("id")
        if not pa or not pb or pa == pb:
            continue
        ranked.append((tier(b, pa, pb), b["id"], pa, pb, b))

    for t, bid, pa, pb, b in sorted(ranked, key=lambda x: (99 if x[0] is None else x[0], x[1])):
        if t is None:
            maybe.append((b, "signali nisu dovoljni"))
            continue
        seed(pa); seed(pb)
        ra, rb = find(pa), find(pb)
        if ra == rb:
            continue
        union = group[ra] | group[rb]
        if len(union) > 6:
            refused["grupa prevelika"] += 1
            maybe.append((b, "grupa bi postala prevelika"))
            continue
        if conflicted(union):
            refused["dvije kandidature na istim izborima"] += 1
            maybe.append((b, "spoj bi istu osobu stavio na dva listića istih izbora"))
            continue
        parent[rb] = ra
        group[ra] = union
        group.pop(rb, None)
        # `why` is TIERS[tier] and `pids` is the group this bridge landed in; neither is
        # worth repeating nine thousand times in a committed file.
        applied.append({"bridge": bid, "tier": t, "a": b["a"]["candidacyId"],
                        "b": b["b"]["candidacyId"]})

    groups = {r: sorted(v) for r, v in group.items() if len(v) > 1}
    # assign is derivable from groups (anything not in one is its own identity), so only
    # groups is written out; identity_map() in backtest.py and render.py rebuild it.
    assign = {p: root for root, members in groups.items() for p in members}
    n_manual = sum(1 for a in applied if a["tier"] == -1)
    print(f"   {len(bridges)} mostova: {len(applied) - n_manual} primijenjeno + {n_manual} ručnih, "
          f"{len(maybe)} ostaje kao prijedlog (većina van listića 2026); "
          f"odbijeno: {dict(refused)}")
    return assign, groups, applied, maybe


def maybe_records(maybe, rows, wanted, assign):
    """'Might be the same person' — shown on the profile, counted nowhere.

    Attached to the merged identity, not the raw record, or a suggestion about Bakir
    Izetbegović's 2006 record would never reach the page his 2026 candidacy renders.
    A suggestion pointing back inside the same merged identity is dropped: it is not a
    suggestion any more, it is already on the timeline above."""
    by_id = {r["id"]: r for r in rows}
    ballot_of = defaultdict(set)
    for pid in wanted:
        ballot_of[assign.get(pid, pid)].add(pid)
    # suggestions we looked at by hand and rejected: a namesake, not this person
    rejected = defaultdict(set)
    for entry in read_manual()[1]:
        rejected[entry.get("pid")] |= set(entry.get("others") or [])
    out = defaultdict(list)
    seen = set()
    for b, why in maybe:
        a, c = by_id.get(b["a"]["candidacyId"]), by_id.get(b["b"]["candidacyId"])
        if not a or not c:
            continue
        for mine, other in ((a, c), (c, a)):
            mine_pid = (mine.get("person") or {}).get("id")
            other_pid = (other.get("person") or {}).get("id")
            root = assign.get(mine_pid, mine_pid)
            if assign.get(other_pid, other_pid) == root:
                continue
            for pid in ballot_of.get(root, ()):
                if other_pid in rejected.get(pid, ()):
                    continue
                key = (pid, other["id"])
                if key in seen:
                    continue
                seen.add(key)
                out[pid].append({
                    "y": other.get("year"),
                    "lvl": (other.get("level") or {}).get("label"),
                    "area": (other.get("area") or {}).get("label"),
                    "party": (other.get("party") or {}).get("label"),
                    "votes": other.get("votes"),
                    "elected": other.get("elected"),
                    "pid": other_pid,
                    "url": other.get("pageUrl"),
                    "signals": b.get("signals"),
                    "why": why,
                })
    for pid in out:
        out[pid].sort(key=lambda r: (r.get("y") or 0))
    return dict(out)


def build_timelines(rows, wanted, assign=None):
    """{pid: [candidacy row]} for everyone on a 2026 ballot, newest election last.

    `assign` maps a person id onto the merged identity it belongs to, so a candidacy
    filed under a record the API kept separate lands on the ballot profile it belongs
    to. Rows that arrived that way carry `via_merge`, because the page has to say so.
    """
    assign = assign or {}
    ranks = rank_within_contest(rows)
    # every ballot identity, and the person records that resolve onto it
    members = defaultdict(set)
    for pid in wanted:
        members[assign.get(pid, pid)].add(pid)
    reaches = defaultdict(set)
    for pid in set(assign) | set(wanted):
        root = assign.get(pid, pid)
        for ballot_pid in members.get(root, ()):
            reaches[pid].add(ballot_pid)

    pubids, pubids_all, out = {}, {}, defaultdict(list)
    for r in rows:
        pid = (r.get("person") or {}).get("id")
        targets = reaches.get(pid)
        if not targets:
            continue
        m = re.search(r"/(o-\d+)/", r.get("pageUrl") or "")
        rank, size = ranks.get(r["id"], (None, None))
        row = {
            "y": r.get("year"),
            "lvl": (r.get("level") or {}).get("label"),
            "area": (r.get("area") or {}).get("label"),
            "unit": (r.get("unit") or {}).get("id"),
            "party": (r.get("party") or {}).get("label"),
            "race": r.get("raceId"),
            "seat": r.get("seat"),
            "pos": r.get("position"),
            "votes": r.get("votes"),
            "pct": (r.get("percentage") or {}).get("value"),
            "rank": rank,
            "of": size,
            "elected": r.get("elected"),
            "via": r.get("electedVia"),
        }
        for ballot_pid in targets:
            if m:
                pubids_all[m.group(1)] = ballot_pid
                if ballot_pid == pid:
                    pubids[ballot_pid] = m.group(1)
            entry = dict(row)
            if pid != ballot_pid:
                entry["via_merge"] = pid
            out[ballot_pid].append(entry)
    for pid in out:
        out[pid].sort(key=lambda t: (t.get("y") or 0, t.get("lvl") or ""))
    return dict(out), pubids, pubids_all


def person_stats(timelines):
    """stood/won recomputed on the merged record, so the badge on a list agrees with
    the profile behind it. data/people_cache.json still holds the API's own count."""
    out = {}
    for pid, tl in timelines.items():
        years = [t["y"] for t in tl if t.get("y")]
        out[pid] = {
            "stood": len(tl),
            "won": sum(1 for t in tl if t.get("elected")),
            "firstYear": min(years) if years else None,
            "lastYear": max(years) if years else None,
            "merged": sum(1 for t in tl if t.get("via_merge")),
        }
    return out


# 2026 race -> the same race in 2022. Area codes are identical across the two years;
# the only 2026-only codes are the compensatory lists (501, 502, 400, 300), which have
# no 2022 counterpart and are handled separately in render.py.
RACE_2022 = {"oi2026-2": "32-2", "oi2026-4": "32-4", "oi2026-6": "32-6", "oi2026-7": "32-7"}


def seat_bar(rows):
    """What a seat actually cost in personal votes here last time.

    This exists to answer the obvious objection to a low chance: "but people vote for
    him". Both things are true at once. A seat is won by the list first, and only then
    does your own count decide who inside the list takes it. In Tuzla canton in 2022,
    142 people collected more personal votes than the lowest-polling winner and still
    did not get in. Printing that next to the percentage is more use than the percentage.
    """
    out = {}
    for race26, race22 in RACE_2022.items():
        areas = {}
        for r in rows:
            if r["raceId"] != race22 or r.get("votes") is None:
                continue
            areas.setdefault(str(r.get("areaCode")), []).append(r)
        for area, cands in areas.items():
            won = sorted((r for r in cands if r.get("elected")), key=lambda r: r["votes"])
            if not won:
                continue
            floor = won[0]["votes"]
            votes = [r["votes"] for r in won]
            mid = votes[len(votes) // 2] if len(votes) % 2 else (votes[len(votes) // 2 - 1] + votes[len(votes) // 2]) // 2
            out[f"{race26}-{area}"] = {
                "year": 2022,
                "candidates": len(cands),
                "seats": len(won),
                "min": floor,
                "median": mid,
                "max": votes[-1],
                "outpolled": sum(1 for r in cands if not r.get("elected") and r["votes"] > floor),
                "lowest": {"name": won[0].get("name"), "votes": floor,
                           "party": (won[0].get("party") or {}).get("label"),
                           "pos": won[0].get("position")},
            }
    return out


def list_strength(rows):
    """Was a vote for this list thrown away last time?

    A seat chance answers "can this person get in". It does not answer the question a
    voter actually asks, which is whether the ballot does anything at all. A list under
    the 3 percent census takes no seat, so every vote on it works out to nothing.

    The share has to be computed over voters, not over personal votes: a ballot may circle
    up to three names, and lists differ in how much their voters use that (0.45 to 6.24
    names per ballot in 2022). The API's `percentage` is a candidate's personal votes as a
    share of their list's ballots, and its implied denominator is identical for every
    candidate on a list in all 496 lists checked, so it recovers the ballot count exactly.
    """
    out = {}
    for race26, race22 in RACE_2022.items():
        areas = defaultdict(lambda: defaultdict(list))
        for r in rows:
            if r["raceId"] != race22 or r.get("seat") == "single":
                continue
            party = (r.get("party") or {}).get("label") or (r.get("party") or {}).get("id")
            if party:
                areas[str(r.get("areaCode"))][party].append(r)
        for area, parties in areas.items():
            by_party, total = {}, 0
            for party, cands in parties.items():
                denoms = [c["votes"] / (c["percentage"]["value"] / 100)
                          for c in cands
                          if c.get("votes") and (c.get("percentage") or {}).get("value", 0) > 0.5]
                voters = round(sum(denoms) / len(denoms)) if denoms else None
                if not voters:
                    continue
                seats = sum(1 for c in cands if c.get("elected"))
                by_party[party] = {"voters": voters, "seats": seats}
                total += voters
            if not total:
                continue
            wasted = sum(v["voters"] for v in by_party.values() if not v["seats"])
            for v in by_party.values():
                v["share"] = round(100 * v["voters"] / total, 1)
            out[f"{race26}-{area}"] = {
                "year": 2022,
                "voters": total,
                "lists": len(by_party),
                "lists_with_seats": sum(1 for v in by_party.values() if v["seats"]),
                "wasted_voters": wasted,
                "wasted_share": round(100 * wasted / total, 1),
                "by_party": by_party,
            }
    return out


def pull_appointed(by_public):
    """Seats people were appointed to rather than elected, keyed back to our pids.

    Mashinerija keeps these deliberately separate from elected persons: the record
    is a name on an institution's own page, with no identity resolution behind it.
    We only keep rows the API itself already linked to a person.
    """
    rows, off = [], 0
    while True:
        d = get(f"{BASE}/appointed?limit={PAGE}&offset={off}")
        rows += d["data"]
        if off + PAGE >= d["meta"]["total"]:
            break
        off += PAGE
    out = defaultdict(list)
    for r in rows:
        public = (r.get("electedPerson") or {}).get("id") or r.get("slug")
        pid = by_public.get(public)
        if not pid:
            continue
        out[pid].append({
            "institution": (r.get("institution") or {}).get("label"),
            "position": r.get("positionLabel") or r.get("position"),
            "role": r.get("role"),
            "party": r.get("partyText"),
            "club": r.get("club"),
            "from": r.get("termFrom"),
            "to": r.get("termTo"),
            "src": r.get("sourceUrl"),
        })
    print(f"   {len(rows)} imenovanih, {len(out)} spojeno s kandidatima 2026")
    return dict(out)


def pull_unit_spend(unit_ids):
    """What the bodies our candidates sat in actually spent.

    This is a fact about the institution, never about the person. render.py has to
    label it that way: one councillor of thirty does not 'spend' a city budget.
    """
    def one(uid):
        try:
            d = get(f"{BASE}/units/{urllib.parse.quote(uid, safe='')}/rollup")["data"]
        except Exception:
            return uid, None
        years = {}
        for row in d:
            head = row.get("headline") or {}
            q = head.get("total") or {}
            if not q.get("value"):
                continue
            years[row.get("year")] = {
                "measure": head.get("conceptId"),
                "basis": head.get("basis"),
                "value": q.get("value"),
                "full_year": head.get("coversFullYear"),
            }
        return uid, ({"years": years} if years else None)

    out = {}
    with ThreadPoolExecutor(THREADS) as ex:
        for uid, v in ex.map(one, sorted(unit_ids)):
            if v:
                out[uid] = v
    print(f"   {len(out)} jedinica s iznosima od {len(unit_ids)} traženih")
    return out


def main():
    os.makedirs(D, exist_ok=True)
    started = time.time()

    print("1/8 sve kandidature")
    rows = pull_all_candidacies()

    print("2/8 mostovi identiteta")
    bridges = pull_bridges()
    wanted = ballot_pids()
    assign, groups, applied, maybe = build_merges(rows, bridges)

    print("3/8 historije kandidata 2026")
    timelines, pubids, pubids_all = build_timelines(rows, wanted, assign)
    prior = sum(1 for t in timelines.values() if any(r["y"] != 2026 for r in t))
    gained = sum(1 for t in timelines.values() if any(r.get("via_merge") for r in t))
    print(f"   {len(wanted)} ljudi na listama, {prior} s ranijim kandidaturama, "
          f"{len(wanted) - prior} prvi put; {gained} ih je historiju dobilo spajanjem")
    json.dump(timelines, open(D + "timelines.json", "w"), ensure_ascii=False)
    json.dump(pubids, open(D + "pubids.json", "w"), ensure_ascii=False)
    json.dump(pubids_all, open(D + "pubids_all.json", "w"), ensure_ascii=False)
    json.dump(person_stats(timelines), open(D + "person_stats.json", "w"), ensure_ascii=False)
    json.dump({"generated": datetime.now(timezone.utc).isoformat(),
               "bridges_seen": len(bridges), "applied": applied,
               "groups": groups, "tiers": TIERS},
              open(D + "merges.json", "w"), ensure_ascii=False)
    json.dump(maybe_records(maybe, rows, wanted, assign),
              open(D + "maybe_same.json", "w"), ensure_ascii=False)

    print("4/8 koliko je ličnih glasova trebalo za mandat 2022")
    bars = seat_bar(rows)
    json.dump(bars, open(D + "seat_bar.json", "w"), ensure_ascii=False, indent=1)
    print(f"   {len(bars)} izbornih jedinica")

    print("5/8 da li je glas za listu bio bačen 2022")
    strength = list_strength(rows)
    json.dump(strength, open(D + "list_strength.json", "w"), ensure_ascii=False, indent=1)
    worst = max(strength.values(), key=lambda v: v["wasted_share"], default=None)
    print(f"   {len(strength)} jedinica; najviše bačenih glasova {worst['wasted_share']}%" if worst else "   0")

    print("6/8 imenovanja")
    json.dump(pull_appointed(pubids_all), open(D + "appointed.json", "w"), ensure_ascii=False, indent=1)

    print("7/8 potrošnja jedinica u kojima su sjedili")
    units = {r["unit"] for t in timelines.values() for r in t if r.get("unit") and r.get("elected")}
    json.dump(pull_unit_spend(units), open(D + "unit_spend.json", "w"), ensure_ascii=False, indent=1)

    print("8/8 sažetak")
    json.dump({"generated": datetime.now(timezone.utc).isoformat(),
               "candidacies_seen": len(rows),
               "bridges_seen": len(bridges),
               "bridges_applied": len(applied),
               "people_on_ballots": len(wanted),
               "people_with_history": prior,
               "people_gained_by_merge": gained},
              open(D + "history_meta.json", "w"), ensure_ascii=False, indent=1)
    print(f"gotovo za {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
