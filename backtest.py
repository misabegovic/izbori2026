#!/usr/bin/env python3
"""Calibrate the seat-chance rule against who actually won in 2022.

The rule used to have one input: where you sit on the list, against how many seats
your party won here last time. That ignores the thing an open-list ballot is for.
A voter can move a name up, and in 2022 that moved a lot of names: someone who had
previously topped their own list by personal votes won 26% of the time, against 3%
for someone who had never run. The gap holds inside every position bucket and in
each of the four races separately, so it is not one race carrying the average.

So the rule now has two inputs, and this script measures the observed win rate for
each combination against the 2022 result. Thin cells are pulled toward the
position-only rate so a cell of twenty people cannot produce a confident number.

Writes data/chance_calibration.json; render.py consumes it. Estimate, not forecast.
"""
import json
import os
import re
import time
import unicodedata
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

BASE = "https://api.gianniravioli.com/mashinerija/v1"
UA = {"User-Agent": "izbori2026-voter-guide/1.0 (github.com/misabegovic/izbori2026)"}
PAGE = 200
SHRINK = 25          # pseudo-observations pulling each cell toward its position-only rate
RACES22 = ["32-2", "32-4", "32-6", "32-7"]
POS_BUCKETS = ["within", "plus1", "plus2", "beyond", "no_seats_pos1", "no_seats_rest"]
PERSONAL = ["top1", "strong", "ran", "none"]


def get(url, tries=4):
    for attempt in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120))
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def pull(path):
    total = get(f"{BASE}{path}{'&' if '?' in path else '?'}limit=1")["meta"]["total"]
    offs = list(range(0, total, PAGE))
    out = []
    with ThreadPoolExecutor(12) as ex:
        for page in ex.map(lambda o: get(f"{BASE}{path}{'&' if '?' in path else '?'}limit={PAGE}&offset={o}")["data"], offs):
            out += page
    return out


def identity_map():
    """The merged identity of every person record, as fetch_history.py decided it.

    The chance rule is measured here and applied in render.py. If this script counted
    a person's past on the API's split records while the profile shows the merged one,
    the two would answer the same question differently — so it reads the same file."""
    path = "data/merges.json"
    if not os.path.exists(path):
        print("   upozorenje: nema data/merges.json, mjerim na nespojenim zapisima")
        return {}
    groups = json.load(open(path)).get("groups") or {}
    return {pid: root for root, members in groups.items() for pid in members}


def fold(s):
    s = unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split()[:2])


def vote_ranks(rows):
    """{candidacy id: rank by personal votes in its own contest}."""
    contests = defaultdict(list)
    for r in rows:
        if r.get("votes") is None:
            continue
        if r.get("seat") == "single":
            k = ("s", r["raceId"], r["areaCode"])
        else:
            k = ("l", r["raceId"], r["areaCode"], (r.get("party") or {}).get("id"))
        contests[k].append(r)
    out = {}
    for group in contests.values():
        group.sort(key=lambda r: -(r.get("votes") or 0))
        for i, r in enumerate(group, 1):
            out[r["id"]] = i
    return out


def personal_bucket_factory(rows, ranks, before_year, assign=None):
    """How the public record looked before `before_year`, per person.

    top1   — already came first by personal votes on one of their own lists
    strong — already won a seat, or already placed top three on a list
    ran    — has run before and did neither
    none   — never on a ballot before
    """
    assign = assign or {}
    prior = defaultdict(list)
    for r in rows:
        if (r.get("year") or 0) < before_year:
            pid = (r.get("person") or {}).get("id")
            prior[assign.get(pid, pid)].append(r)

    def bucket(pid):
        past = prior.get(assign.get(pid, pid)) or []
        if not past:
            return "none"
        best, won = None, False
        for r in past:
            if r.get("elected"):
                won = True
            rk = ranks.get(r["id"])
            if rk and r.get("seat") != "single" and (best is None or rk < best):
                best = rk
        if best == 1:
            return "top1"
        if won or (best is not None and best <= 3):
            return "strong"
        return "ran"

    return bucket


def position_bucket(rank, seats):
    if seats <= 0:
        return "no_seats_pos1" if rank == 1 else "no_seats_rest"
    if rank <= seats:
        return "within"
    if rank == seats + 1:
        return "plus1"
    if rank == seats + 2:
        return "plus2"
    return "beyond"


def main():
    print("1/3 sve kandidature")
    rows = pull("/candidacies")
    print(f"   {len(rows)} kandidatura")

    print("2/3 mandati 2018 (koliko je stranka tad dobila gdje)")
    seats18 = defaultdict(int)
    for m in pull("/mandates?year=2018"):
        seats18[((m.get("level") or {}).get("id"), str((m.get("area") or {}).get("id")),
                 fold((m.get("party") or {}).get("label")))] += 1

    print("3/3 mjerenje na rezultatu 2022")
    assign = identity_map()
    ranks = vote_ranks(rows)
    personal = personal_bucket_factory(rows, ranks, 2022, assign)
    if assign:
        print(f"   {len(set(assign.values()))} spojenih identiteta ulazi u mjerenje")

    lists = defaultdict(list)
    for r in rows:
        if r["raceId"] in RACES22:
            lists[((r.get("level") or {}).get("id"), str((r.get("area") or {}).get("id")),
                   (r.get("party") or {}).get("label") or (r.get("party") or {}).get("id") or "")].append(r)

    pos = defaultdict(lambda: [0, 0])
    cross = defaultdict(lambda: [0, 0])
    per_race = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for (lvl, area, party), cands in lists.items():
        seats = seats18.get((lvl, area, fold(party)), 0)
        cands.sort(key=lambda c: c.get("position") or 99)
        for rank, c in enumerate(cands, 1):
            pbk = position_bucket(rank, seats)
            per = personal((c.get("person") or {}).get("id"))
            won = 1 if c.get("elected") else 0
            pos[pbk][0] += 1
            pos[pbk][1] += won
            cross[(pbk, per)][0] += 1
            cross[(pbk, per)][1] += won
            per_race[c["raceId"]][per][0] += 1
            per_race[c["raceId"]][per][1] += won

    out_pos = {}
    for b in POS_BUCKETS:
        n, w = pos[b]
        out_pos[b] = {"n": n, "won": w, "pct": round(100 * w / n) if n else None}

    out_cross = {}
    for b in POS_BUCKETS:
        base = (pos[b][1] / pos[b][0]) if pos[b][0] else 0
        for p in PERSONAL:
            n, w = cross[(b, p)]
            if not n:
                continue
            smoothed = (w + SHRINK * base) / (n + SHRINK)
            out_cross[f"{b}|{p}"] = {
                "n": n, "won": w,
                "raw_pct": round(100 * w / n),
                "pct": max(1, round(100 * smoothed)),
            }

    stability = {}
    for race, d in per_race.items():
        stability[race] = {p: (round(100 * d[p][1] / d[p][0], 1) if d[p][0] else None) for p in PERSONAL}

    cal = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "measured_on": "opći izbori 2022, trke 32-2, 32-4, 32-6, 32-7",
        "seats_from": "mandati 2018",
        "identities": "spojene po data/merges.json" if assign else "zapisi kakve API vraća",
        "shrink_k": SHRINK,
        "position": out_pos,
        "crossed": out_cross,
        "stability_by_race": stability,
    }
    json.dump(cal, open("data/chance_calibration.json", "w"), ensure_ascii=False, indent=1)

    print(f"\n{'mjesto na listi':16s} {'prošlost':8s} {'n':>6s} {'sirovo':>8s} {'glađeno':>8s}")
    for b in POS_BUCKETS:
        print(f"{b:16s} {'—':8s} {out_pos[b]['n']:6d} {str(out_pos[b]['pct'])+'%':>8s}")
        for p in PERSONAL:
            c = out_cross.get(f"{b}|{p}")
            if c:
                print(f"{'':16s} {p:8s} {c['n']:6d} {str(c['raw_pct'])+'%':>8s} {str(c['pct'])+'%':>8s}")
    print("\nstabilnost po trkama (% izabranih):")
    for race, d in sorted(stability.items()):
        print(f"  {race}: " + ", ".join(f"{p}={d[p]}" for p in PERSONAL if d[p] is not None))


if __name__ == "__main__":
    main()
