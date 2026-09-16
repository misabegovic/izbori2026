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

    print("1/4 sve kandidature")
    rows = pull_all_candidacies()

    print("2/4 historije kandidata 2026")
    wanted = ballot_pids()
    timelines, pubids = build_timelines(rows, wanted)
    prior = sum(1 for t in timelines.values() if any(r["y"] != 2026 for r in t))
    print(f"   {len(wanted)} ljudi na listama, {prior} s ranijim kandidaturama, "
          f"{len(wanted) - prior} prvi put")
    json.dump(timelines, open(D + "timelines.json", "w"), ensure_ascii=False)
    json.dump(pubids, open(D + "pubids.json", "w"), ensure_ascii=False)

    print("3/4 imenovanja")
    json.dump(pull_appointed(pubids), open(D + "appointed.json", "w"), ensure_ascii=False, indent=1)

    print("4/4 potrošnja jedinica u kojima su sjedili")
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
