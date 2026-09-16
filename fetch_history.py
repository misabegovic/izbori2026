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


def build_timelines(rows, wanted):
    """{pid: [candidacy row]} for everyone on a 2026 ballot, newest election last."""
    ranks = rank_within_contest(rows)
    pubids, out = {}, defaultdict(list)
    for r in rows:
        pid = (r.get("person") or {}).get("id")
        if pid not in wanted:
            continue
        m = re.search(r"/(o-\d+)/", r.get("pageUrl") or "")
        if m:
            pubids[pid] = m.group(1)
        rank, size = ranks.get(r["id"], (None, None))
        out[pid].append({
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
        })
    for pid in out:
        out[pid].sort(key=lambda t: (t.get("y") or 0, t.get("lvl") or ""))
    return dict(out), pubids


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


def pull_appointed(pubids):
    """Seats people were appointed to rather than elected, keyed back to our pids.

    Mashinerija keeps these deliberately separate from elected persons: the record
    is a name on an institution's own page, with no identity resolution behind it.
    We only keep rows the API itself already linked to a person.
    """
    by_public = {v: k for k, v in pubids.items()}
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

    print("1/6 sve kandidature")
    rows = pull_all_candidacies()

    print("2/6 historije kandidata 2026")
    wanted = ballot_pids()
    timelines, pubids = build_timelines(rows, wanted)
    prior = sum(1 for t in timelines.values() if any(r["y"] != 2026 for r in t))
    print(f"   {len(wanted)} ljudi na listama, {prior} s ranijim kandidaturama, "
          f"{len(wanted) - prior} prvi put")
    json.dump(timelines, open(D + "timelines.json", "w"), ensure_ascii=False)
    json.dump(pubids, open(D + "pubids.json", "w"), ensure_ascii=False)

    print("3/6 koliko je ličnih glasova trebalo za mandat 2022")
    bars = seat_bar(rows)
    json.dump(bars, open(D + "seat_bar.json", "w"), ensure_ascii=False, indent=1)
    print(f"   {len(bars)} izbornih jedinica")

    print("4/6 da li je glas za listu bio bačen 2022")
    strength = list_strength(rows)
    json.dump(strength, open(D + "list_strength.json", "w"), ensure_ascii=False, indent=1)
    worst = max(strength.values(), key=lambda v: v["wasted_share"], default=None)
    print(f"   {len(strength)} jedinica; najviše bačenih glasova {worst['wasted_share']}%" if worst else "   0")

    print("5/6 imenovanja")
    json.dump(pull_appointed(pubids), open(D + "appointed.json", "w"), ensure_ascii=False, indent=1)

    print("6/6 potrošnja jedinica u kojima su sjedili")
    units = {r["unit"] for t in timelines.values() for r in t if r.get("unit") and r.get("elected")}
    json.dump(pull_unit_spend(units), open(D + "unit_spend.json", "w"), ensure_ascii=False, indent=1)

    json.dump({"generated": datetime.now(timezone.utc).isoformat(),
               "candidacies_seen": len(rows),
               "people_on_ballots": len(wanted),
               "people_with_history": prior},
              open(D + "history_meta.json", "w"), ensure_ascii=False, indent=1)
    print(f"gotovo za {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
