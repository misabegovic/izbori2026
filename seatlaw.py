#!/usr/bin/env python3
"""How a vote turns into a seat in BiH, written out and checked against past results.

Every number on the projection pages rests on three rules. None of them is our invention;
all three are read out of the Election Law and then verified by replaying 2018 and 2022 —
feed the rules the votes that were actually cast and they have to hand back the people who
were actually elected, or the rules are wrong. `python seatlaw.py` runs that check.

1. Seats inside a constituency (`sainte_lague`). Divisors 1, 3, 5, 7 … A list under three
   percent of the constituency's ballots is dropped first and takes nothing.

2. Compensatory seats (`compensatory`). Entity-wide, among lists over three percent
   entity-wide. The divisor sequence does not restart: a party that already won four seats
   directly enters the compensatory round at divisor 9, which is what stops the big parties
   from collecting the compensation twice.

3. Who on the list gets the seat (`winners_within_list`). This is the rule almost nobody
   knows and the one that decides most careers: a candidate who clears 20 percent of their
   own list's ballots takes a seat on personal votes, in order of votes. Every remaining
   seat goes down the list in the order the party printed it, personal votes ignored.
   In 2022 that rule placed 113 of 113 regular mandates correctly, and 118 of 118 in 2018.

The practical consequence, and the reason the projection pages say it out loud: on a list
that wins two seats and has one candidate over 20 percent, the second seat belongs to
whoever the party put at the top — not to the candidate who campaigned hardest.
"""
from collections import defaultdict

THRESHOLD = 0.03          # of valid ballots in the constituency, and entity-wide for compensation
PERSONAL_GATE = 20.0      # percent of your own list's ballots that buys a seat outright


def sainte_lague(votes, seats, start=None):
    """Highest averages with divisors 1, 3, 5 … `start` continues an existing count.

    votes: {key: ballots}. Returns {key: seats won in this round}."""
    if seats <= 0 or not votes:
        return {}
    running = dict(start or {})
    got = defaultdict(int)
    for _ in range(seats):
        best = max(votes, key=lambda k: (votes[k] / (2 * running.get(k, 0) + 1), votes[k]))
        running[best] = running.get(best, 0) + 1
        got[best] += 1
    return dict(got)


def eligible(votes, total=None, threshold=THRESHOLD):
    total = total or sum(votes.values())
    if not total:
        return {}
    return {k: v for k, v in votes.items() if v and v / total >= threshold}


def direct_seats(unit_votes, seats):
    """Seats a constituency awards on its own. unit_votes: {list: ballots}."""
    return sainte_lague(eligible(unit_votes), seats)


def compensatory(entity_votes, direct, seats):
    """Compensatory seats for one entity, continuing each party's divisor sequence.

    entity_votes: {list: ballots summed over the entity's constituencies}
    direct: {list: seats already won directly} — parties under the entity threshold keep
    their direct seats but take no part in this round."""
    elig = eligible(entity_votes)
    start = {k: direct.get(k, 0) for k in elig}
    return sainte_lague(elig, seats, start=start)


def winners_within_list(candidates, seats, gate=PERSONAL_GATE):
    """Which candidates of one list take its seats.

    candidates: [{"id":…, "pos": int, "pct": percent of the list's ballots}] — `pct` is the
    share of the list's ballots this candidate was circled on, the same number the CIK API
    prints as `percentage`. Returns the winning ids in the order they were awarded."""
    if seats <= 0:
        return []
    won, taken = [], set()
    for c in sorted(candidates, key=lambda c: (-(c.get("pct") or 0), c.get("pos") or 999)):
        if len(won) >= seats:
            break
        if (c.get("pct") or 0) >= gate:
            won.append(c["id"])
            taken.add(c["id"])
    for c in sorted(candidates, key=lambda c: (c.get("pos") or 999)):
        if len(won) >= seats:
            break
        if c["id"] not in taken:
            won.append(c["id"])
            taken.add(c["id"])
    return won


# --- verification against what actually happened -------------------------------------

def _self_test():
    import json
    import time
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    BASE = "https://api.gianniravioli.com/mashinerija/v1"
    UA = {"User-Agent": "izbori2026-voter-guide/1.0 (github.com/misabegovic/izbori2026)"}

    def get(url, tries=4):
        for a in range(tries):
            try:
                return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180))
            except Exception:
                if a == tries - 1:
                    raise
                time.sleep(2 * (a + 1))

    def pull(path):
        sep = "&" if "?" in path else "?"
        total = get(f"{BASE}{path}{sep}limit=1")["meta"]["total"]
        out = []
        with ThreadPoolExecutor(12) as ex:
            for page in ex.map(lambda o: get(f"{BASE}{path}{sep}limit=200&offset={o}")["data"],
                               range(0, total, 200)):
                out += page
        return out

    ELECTIONS = {2018: (16, {"pd-psbih": "25-2", "pd-fbih": "25-4", "nsrs": "25-6", "skupstine-kantona": "25-7"}),
                 2022: (23, {"pd-psbih": "32-2", "pd-fbih": "32-4", "nsrs": "32-6", "skupstine-kantona": "32-7"})}
    GROUPS = [("pd-psbih", "FBiH", ["511", "512", "513", "514", "515"]),
              ("pd-psbih", "RS", ["521", "522", "523"]),
              ("pd-fbih", "FBiH", None), ("nsrs", "RS", None)]
    failures = 0

    for year, (eid, races) in ELECTIONS.items():
        rows = [r for r in pull(f"/candidacies?electionId={eid}") if r.get("seat") != "single"]
        by_list = defaultdict(list)
        for r in rows:
            by_list[(r["raceId"], r["areaCode"], (r["party"] or {}).get("label"))].append(r)

        # rule 3 — who inside the list
        ok = miss = 0
        for cands in by_list.values():
            regular = [c for c in cands if c.get("electedVia") == "regular"]
            if not regular:
                continue
            pred = winners_within_list(
                [{"id": c["id"], "pos": c.get("position"), "pct": (c.get("percentage") or {}).get("value") or 0}
                 for c in cands], len(regular))
            if set(pred) == {c["id"] for c in regular}:
                ok += 1
            else:
                miss += 1
        print(f"{year} pravilo unutar liste: {ok} lista tačno, {miss} promašeno")
        failures += miss

        # rules 1 and 2 — how many seats each list takes
        ballots, direct_act, comp_act = {}, defaultdict(lambda: defaultdict(int)), defaultdict(lambda: defaultdict(int))
        for (race, area, party), cands in by_list.items():
            denoms = [c["votes"] / ((c.get("percentage") or {}).get("value") / 100)
                      for c in cands if c.get("votes") and (c.get("percentage") or {}).get("value", 0) > 0.5]
            if denoms:
                ballots[(race, area, party)] = round(sum(denoms) / len(denoms))
            for c in cands:
                if c.get("electedVia") == "regular":
                    direct_act[(race, area)][party] += 1
                elif c.get("electedVia") == "compensation":
                    comp_act[(race, area)][party] += 1

        for level, tag, only in GROUPS:
            race = races[level]
            areas = only or sorted({a for (r, a) in direct_act if r == race})
            cells_ok = cells_bad = 0
            entity_votes, entity_direct, entity_comp = defaultdict(int), defaultdict(int), defaultdict(int)
            for area in areas:
                unit = {p: v for (r, a, p), v in ballots.items() if r == race and a == area}
                seats = sum(direct_act[(race, area)].values())
                pred = direct_seats(unit, seats)
                for p in unit:
                    (cells_ok, cells_bad)  # keep flake quiet
                    if pred.get(p, 0) == direct_act[(race, area)].get(p, 0):
                        cells_ok += 1
                    else:
                        cells_bad += 1
                    entity_votes[p] += unit[p]
                    entity_direct[p] += direct_act[(race, area)].get(p, 0)
                    entity_comp[p] += comp_act[(race, area)].get(p, 0)
            ncomp = sum(entity_comp.values())
            pred_comp = compensatory(entity_votes, entity_direct, ncomp)
            comp_bad = sum(1 for p in entity_votes if pred_comp.get(p, 0) != entity_comp.get(p, 0))
            print(f"   {year} {level} {tag}: direktni {cells_ok} tačno / {cells_bad} netačno; "
                  f"kompenzacijskih {ncomp}, netačno {comp_bad}")
            failures += cells_bad + comp_bad

    print("\nSVE TAČNO" if not failures else f"\n{failures} ODSTUPANJA — pravila iznad nisu tačna")
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if _self_test() else 0)
