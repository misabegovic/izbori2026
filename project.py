#!/usr/bin/env python3
"""Most likely outcome of the 2026 general election, and every candidate's odds inside it.

Two numbers live on this site now and they answer different questions.

  „Šansa za mjesto" (backtest.py) is a rate: of everyone who stood where this person stands
  — same place on the list relative to their party's last result, same personal record — what
  share got in, in 2022. It is a fact about the past and it does not move with the campaign.

  „Projekcija" (this file) is a forecast: given where the vote seems to be going in 2026, how
  often does this person end up with a seat when the election is simulated ten thousand times.
  It is the number that adds up — every candidate's odds inside one list sum to that list's
  projected seats, and the lists sum to the size of the chamber.

Both are kept and the profile shows them side by side, because where they disagree the
disagreement is the point: it means the party is heading somewhere its 2022 result alone would
not have predicted, or that the list order has put someone out of reach of their own votes.

How a vote becomes a seat is in seatlaw.py, which replays 2018 and 2022 and has to place every
single mandate correctly before anything here runs. How the vote is projected is in model.py.

The honest part is the backtest: the identical pipeline is pointed at 2022 and given only what
was knowable before it — the 2018 result and the 2016 and 2020 local elections — then scored
against what happened. Those errors are not a footnote, they *are* the uncertainty bands, and
the model's settings (how hard to lean on local swing, how much of a dead party's vote comes
back, how wide a list's error is) are fitted there rather than picked.

  python project.py                 # fit on 2022, then project 2026
  python project.py --backtest      # the 2022 replay only, printed in full
  python project.py --sims 2000     # faster, rougher
  python project.py --no-polls      # ignore data/polls.json

Writes data/projection.json and data/projection_backtest.json; render.py consumes both.
Source of every input: gianniravioli.com Mashinerija (CC BY 4.0), a mirror of the CIK.
"""
import argparse
import glob
import itertools
import json
import math
import os
import random
import time
from collections import defaultdict
from datetime import datetime, timezone

import model
import seatlaw

D = "data/"
SIMS = 10000
SEED = 20261004

RACES = {
    "oi2026-2": {"lvl": "pd-psbih", "title": "Predstavnički dom PSBiH", "short": "PSBiH",
                 "prior": {2022: "32-2", 2018: "25-2"},
                 "groups": [("FBiH", ["511", "512", "513", "514", "515"]),
                            ("RS", ["521", "522", "523"])],
                 "comp_area": {"FBiH": "501", "RS": "502"}, "chamber": 42, "one_house": True},
    "oi2026-4": {"lvl": "pd-fbih", "title": "Predstavnički dom Parlamenta FBiH", "short": "Parlament FBiH",
                 "prior": {2022: "32-4", 2018: "25-4"},
                 "groups": [("FBiH", None)], "comp_area": {"FBiH": "400"}, "chamber": 98, "one_house": True},
    "oi2026-6": {"lvl": "nsrs", "title": "Narodna skupština Republike Srpske", "short": "NSRS",
                 "prior": {2022: "32-6", 2018: "25-6"},
                 "groups": [("RS", None)], "comp_area": {"RS": "300"}, "chamber": 83, "one_house": True},
    "oi2026-7": {"lvl": "skupstine-kantona", "title": "Skupštine kantona", "short": "kantoni",
                 "prior": {2022: "32-7", 2018: "25-7"},
                 "groups": [], "comp_area": {}, "chamber": 289, "one_house": False},
}
COMP_AREAS = {"501", "502", "400", "300"}
CANTON = {"201": "Unsko-sanski kanton", "202": "Posavski kanton", "203": "Tuzlanski kanton",
          "204": "Zeničko-dobojski kanton", "205": "Bosansko-podrinjski kanton",
          "206": "Srednjobosanski kanton", "207": "Hercegovačko-neretvanski kanton",
          "208": "Zapadnohercegovački kanton", "209": "Kanton Sarajevo", "210": "Kanton 10"}
UNIT_TITLE = {"511": "Izborna jedinica 1A", "512": "Izborna jedinica 2A", "513": "Izborna jedinica 3A",
              "514": "Izborna jedinica 4A", "515": "Izborna jedinica 5A", "521": "Izborna jedinica 1B",
              "522": "Izborna jedinica 2B", "523": "Izborna jedinica 3B"}
# NSRS 301–309 and the FBiH parliament 401–412 are simply "Izborna jedinica 1" … "12"
UNIT_TITLE.update({f"{p}{i:02d}": f"Izborna jedinica {i}" for p in ("3", "4") for i in range(1, 13)})

DEFAULTS = {"name_weight": 0.5, "retention": 0.6, "lam": 0.5, "trend_shrink": 3000.0,
            "poll_weight": 0.10}


# ---------------------------------------------------------------- loading

def load():
    d = {
        "swing": json.load(open(D + "swing.json")),
        "ballots": json.load(open(D + "ballots.json")),
        "seats": json.load(open(D + "seats2026.json")),
        "munis": json.load(open(D + "municipalities.json")),
        "polls": json.load(open(D + "polls.json")),
        "timelines": json.load(open(D + "timelines.json")),
        "units": {},
    }
    for f in sorted(glob.glob(D + "units/*.json")):
        d["units"][os.path.basename(f)[:-5]] = json.load(open(f))
    return d


def person_prior(ballots, year, level):
    """{pid: [(party, weight)]} — where each person stood at the last general election.

    Weight is their share of their own list's ballots, so a party leader counts for more than
    the twentieth name when we ask where a party's support has gone. A candidacy at the level
    being projected counts full; another level of the same election counts less, because a
    cantonal MP moving to the state list says less about the state list than a state MP does."""
    out = defaultdict(list)
    for r in ballots["general"]:
        if r["y"] != year or not r.get("pid") or not r.get("party"):
            continue
        w = max((r.get("pct") or 1.0) / 100.0, 0.005)
        out[r["pid"]].append((r["party"], w * (1.0 if r["lvl"] == level else 0.6)))
    return out


def local_person(ballots, year):
    out = defaultdict(list)
    for r in ballots["local"]:
        if r["y"] == year and r.get("pid") and r.get("party"):
            out[r["pid"]].append((r["party"], max((r.get("pct") or 1.0) / 100.0, 0.005)))
    return out


def record_from_rows(rows, before):
    """The four classes backtest.py measures, from what was known before `before`."""
    past = [t for t in (rows or ()) if (t.get("y") or 0) < before]
    if not past:
        return "none"
    best, won = None, False
    for t in past:
        if t.get("elected"):
            won = True
        rk = t.get("rank")
        if t.get("seat") != "single" and rk and (best is None or rk < best):
            best = rk
    if best == 1:
        return "top1"
    if won or (best is not None and best <= 3):
        return "strong"
    return "ran"


def pctl(xs, q):
    if not xs:
        return None
    ys = sorted(xs)
    return ys[min(len(ys) - 1, max(0, int(round(q * (len(ys) - 1)))))]


def _median(xs):
    ys = sorted(xs)
    n = len(ys)
    return ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2


def _race_of(prior_race):
    for k, c in RACES.items():
        if prior_race in c["prior"].values():
            return k
    return None


def region_of(area):
    return "RS" if area[0] == "3" or area in ("521", "522", "523") else "FBiH"


# ---------------------------------------------------------------- ballots

def ballot_2026(data):
    """The certified 2026 ballot, as {race: {unit: {list: [cand]}}}, plus lookup tables."""
    ballot = defaultdict(lambda: defaultdict(dict))
    meta, info = {}, {}
    comp = defaultdict(dict)
    tl = data["timelines"]
    for uk, u in data["units"].items():
        race, area = u["race"], u["area"]
        if race not in RACES:
            continue
        for l in u["lists"]:
            rows = []
            for c in sorted(l["candidates"], key=lambda c: c.get("pos") or 999):
                key = c.get("pid") or f'{uk}|{l["name"]}|{c["name"]}'
                rows.append({"key": key, "pid": c.get("pid"), "pos": c.get("pos"), "name": c["name"]})
                if key not in meta:
                    meta[key] = {"pos": c.get("pos"),
                                 "record": record_from_rows(tl.get(c.get("pid")) or [], 2026)}
                    info[key] = {"name": c["name"], "pid": c.get("pid")}
            if area in COMP_AREAS:
                # The compensatory list's own order decides these seats and a voter cannot
                # change it (Izborni zakon, član 9.7), so it is kept exactly as printed.
                comp[(race, area)][l["name"]] = [r["key"] for r in rows]
                continue
            ballot[race][uk][l["name"]] = rows
            for r in rows:
                info[r["key"]].update({"unit": uk, "area": area, "list": l["name"], "pos": r["pos"]})
    return ballot, meta, info, dict(comp)


def ballot_prior(data, year):
    """The ballot of a past general election, in the same shape, for the replay."""
    ballot = defaultdict(lambda: defaultdict(dict))
    meta, info = {}, {}
    hist = defaultdict(list)
    for r in data["ballots"]["general"] + data["ballots"]["local"]:
        hist[r["pid"]].append(r)
    for r in data["ballots"]["general"]:
        if r["y"] != year or r.get("seat") == "single" or not r.get("party"):
            continue
        race = _race_of(r["race"])
        if not race:
            continue
        uk = f"{race}-{r['area']}"
        key = f"{r['pid']}|{r['race']}|{r['area']}"
        ballot[race][uk].setdefault(r["party"], []).append(
            {"key": key, "pid": r["pid"], "pos": r.get("pos"), "name": r.get("party")})
        meta[key] = {"pos": r.get("pos"), "record": record_from_rows(hist.get(r["pid"]) or [], year)}
        info[key] = {"pid": r["pid"], "unit": uk, "area": r["area"], "list": r["party"],
                     "pos": r.get("pos"), "elected": r.get("elected"), "via": r.get("via")}
    for race in ballot:
        for uk in ballot[race]:
            for lname in ballot[race][uk]:
                ballot[race][uk][lname].sort(key=lambda c: c.get("pos") or 999)
    return ballot, meta, info


# ---------------------------------------------------------------- one scenario

class Scenario:
    """Everything needed to project one election, this one or a past one.

    `ballot` is the certified list of lists; `prior_year` is the general election before it;
    `local_a`/`local_b` are the two local elections whose ratio gives the swing. For 2026 that
    is 2022 with 2020 → 2024. For the replay it is 2018 with 2016 → 2020 and the ballot is
    2022's, so the model never sees the year it is being asked to predict."""

    def __init__(self, data, ballot, prior_year, local_a, local_b, seats, params):
        self.data, self.ballot, self.p = data, ballot, dict(params)
        self.prior_year, self.local_a, self.local_b = prior_year, local_a, local_b
        self.seats = seats
        self.seats_comp = dict(data["seats"]["compensatory"])
        self.polls_used = []
        self.diag = {"orphan": {}, "splits": [], "no_prior": []}
        self.build()

    def build(self):
        data, p = self.data, self.p
        prior = data["swing"]["general"][str(self.prior_year)]
        muni_of = defaultdict(list)
        for m in data["munis"]:
            for race, area in m["refs"]:
                muni_of[f"{race}-{area}"].append(m["slug"])
        loc_a_people = local_person(data["ballots"], self.local_a)
        loc_b_people = local_person(data["ballots"], self.local_b)

        self.units = {}
        for race, cfg in RACES.items():
            people = person_prior(data["ballots"], self.prior_year, cfg["lvl"])
            pri = (prior.get(cfg["lvl"]) or {}).get("areas") or {}
            for uk, lists in (self.ballot.get(race) or {}).items():
                area = uk.rsplit("-", 1)[1]
                if area in COMP_AREAS:
                    continue
                prior_votes = {pp: v["voters"]
                               for pp, v in (pri.get(area) or {}).get("by_party", {}).items()
                               if v.get("voters")}
                if not prior_votes:
                    self.diag["no_prior"].append(uk)
                    continue
                munis = muni_of.get(uk) or []
                inh, dg = model.inheritance(lists, prior_votes, people, p["name_weight"])
                geo_prior = self.geo(munis, self.local_b)
                geo_list = {}
                for lname in lists:
                    acc = defaultdict(float)
                    for pp, spread in inh.items():
                        f = spread.get(lname)
                        if f:
                            for m, v in (geo_prior.get(pp) or {}).items():
                                acc[m] += f * v
                    geo_list[lname] = dict(acc)
                base = model.baseline(lists, prior_votes, inh, dg["orphans"], geo_prior, geo_list,
                                      p["retention"])
                self.diag["orphan"][uk] = round(
                    100 * sum(dg["orphans"].values()) / max(sum(prior_votes.values()), 1), 1)
                for s in dg["splits"]:
                    self.diag["splits"].append(dict(s, unit=uk))

                # How plainly is this list one earlier party carrying on? A list whose baseline
                # is one party that put most of itself here (SDA -> SDA) is a different animal
                # from one assembled out of fragments, and the replay shows the second kind is
                # far harder to project. How wide its band is depends on this.
                cont = {}
                for lname in lists:
                    best = 0.0
                    for pp, spread in inh.items():
                        f = spread.get(lname) or 0.0
                        if f >= 0.5 and base.get(lname):
                            best = max(best, f * prior_votes[pp] / base[lname])
                    cont[lname] = round(min(best, 1.0), 3)

                sa = self.local_shares(lists, munis, self.local_a, loc_a_people)
                sb = self.local_shares(lists, munis, self.local_b, loc_b_people)
                trend = model.trend_factors(lists, sa, sb, p["trend_shrink"])
                adj = model.apply_swing(base, trend, p["lam"])
                tot = sum(adj.values()) or 1.0
                btot = sum(base.values()) or 1.0
                self.units[uk] = {
                    "race": race, "area": area, "seats": self.seats.get(uk, 0), "lists": lists,
                    "share": {l: v / tot for l, v in adj.items()},
                    "base_share": {l: v / btot for l, v in base.items()},
                    "trend": trend, "weight": sum(prior_votes.values()),
                    "prior_votes": prior_votes, "inherit": inh, "cont": cont,
                }
        if self.p.get("calib"):
            self.recalibrate(self.p["calib"])

    def recalibrate(self, calib):
        """Undo a measured tilt in this same model. Applied only when the replay says it helps."""
        for u in self.units.values():
            adj = {}
            for l, s in u["share"].items():
                x = -math.log10(max(s, 0.001))
                adj[l] = s * math.exp(min(max(calib["a"] + calib["b"] * x, -0.8), 0.8))
            tot = sum(adj.values()) or 1.0
            u["share"] = {l: v / tot for l, v in adj.items()}

    def geo(self, munis, year):
        loc = self.data["swing"]["local"].get(str(year)) or {}
        prof = defaultdict(dict)
        for m in munis:
            row = loc.get(m)
            if not row:
                continue
            for party, v in row["by_party"].items():
                if v.get("voters"):
                    prof[party][m] = v["voters"]
        return prof

    def local_shares(self, lists, munis, year, people):
        loc = self.data["swing"]["local"].get(str(year)) or {}
        votes = defaultdict(float)
        for m in munis:
            row = loc.get(m)
            if not row:
                continue
            for party, v in row["by_party"].items():
                if v.get("voters"):
                    votes[party] += v["voters"]
        if not votes:
            return {}
        inh, _ = model.inheritance(lists, dict(votes), people, self.p["name_weight"])
        out = defaultdict(float)
        for party, v in votes.items():
            for lname, f in (inh.get(party) or {}).items():
                out[lname] += v * f
        return dict(out)

    def apply_polls(self, polls, weight):
        """Nudge each region's shares toward a poll. Small on purpose; see data/polls.json."""
        used = []
        for poll in polls.get("polls", []):
            race = poll.get("race")
            if race not in RACES or not poll.get("parties"):
                continue
            scope = poll.get("scope")
            targets = [uk for uk, u in self.units.items()
                       if u["race"] == race and (scope == "država" or scope == region_of(u["area"]))]
            if not targets:
                continue
            rel = {"high": 1.0, "medium": 0.6, "low": 0.3}.get(poll.get("reliability"), 0.3)
            w = weight * rel
            matched = set()
            for uk in targets:
                u = self.units[uk]
                mapped = {}
                for pname, pv in poll["parties"].items():
                    for lname in u["share"]:
                        if model.name_match(pname, lname) or program_match(pname, lname):
                            mapped[lname] = pv / 100.0
                            matched.add(pname)
                if not mapped:
                    continue
                s = sum(mapped.values()) or 1.0
                u["share"] = model.blend_polls(u["share"], {l: v / s for l, v in mapped.items()}, w)
            used.append({"id": poll["id"], "agencija": poll.get("agency"),
                         "objavljena": poll.get("published"), "pouzdanost": poll.get("reliability"),
                         "tezina": round(w, 3), "jedinica": len(targets), "vezano": sorted(matched),
                         "bez_veze": sorted(set(poll["parties"]) - matched)})
        return used


_ALIAS = None


def program_match(program_name, list_name):
    """Poll party names are the names used in data/programs_*.json, and data/party_aliases.json
    already maps those onto the printed CIK list names, so reuse it rather than guess twice."""
    global _ALIAS
    if _ALIAS is None:
        import re
        raw = json.load(open(D + "party_aliases.json"))
        _ALIAS = {k: [re.compile(r) for r in v] for k, v in raw.items() if not k.startswith("_")}
    for rx in _ALIAS.get(program_name, ()):
        if rx.search(model.fold(list_name)):
            return True
    return False


# ---------------------------------------------------------------- personal votes

def personal_cells(ballots, years):
    """How a list's ballots spread over the people on it, learned from past ballots."""
    hist = defaultdict(list)
    for r in ballots["general"] + ballots["local"]:
        hist[r["pid"]].append(r)
    sizes, sums = defaultdict(int), defaultdict(float)
    for r in ballots["general"]:
        if r["y"] in years and r.get("seat") != "single":
            key = (r["race"], r["area"], r["party"])
            sizes[key] += 1
            sums[key] += r.get("pct") or 0.0
    rows = []
    for r in ballots["general"]:
        if r["y"] not in years or r.get("seat") == "single" or not r.get("pct"):
            continue
        key = (r["race"], r["area"], r["party"])
        rows.append({"pos": r.get("pos"), "n": sizes[key], "pct": r["pct"],
                     "record": record_from_rows(hist.get(r["pid"]) or [], r["y"])})
    totals = defaultdict(list)
    for (race, _a, _p), t in sums.items():
        rk = _race_of(race)
        if rk and t > 0:
            totals[rk].append(t)
    totals = {k: sorted(v) for k, v in totals.items()}
    totals["_all"] = sorted(x for v in totals.values() for x in v)
    return model.fit_personal(rows), totals


def pick_total(rng, totals, race):
    pool = totals.get(race) or totals.get("_all") or [100.0]
    return pool[rng.randrange(len(pool))]


# ---------------------------------------------------------------- simulation

def simulate(scn, cells, totals, meta, comp_lists, sims, seed, sg,
             seat_jitter=0.0, comp_fallback=False):
    """Run the election `sims` times and count everything that comes out of it.

    One draw per list moves that list in every constituency at once — a party does not have a
    bad day in one place only — and a smaller draw per constituency on top. Both come from a
    core-plus-tail shape fitted on the 2022 replay: most of the time a list lands close to
    where the model puts it, and about one time in twelve it misses by a mile. Fitting one
    bell curve to both would make the big parties' ranges absurd and still hide how far a list
    can fall."""
    rng = random.Random(seed)
    race_units = defaultdict(list)
    for uk, u in scn.units.items():
        race_units[u["race"]].append(uk)

    # Two widths, and they are not the same one. The list-wide draw has to come from how big
    # the list is across the whole race; the constituency draw from how big it is *here*. Using
    # one number for both is how SDA at 24 percent in Sarajevo ends up wearing the error bar of
    # SDA at 2 percent in Republika Srpska, which is a different party's problem entirely.
    race_share = defaultdict(float)
    race_weight = defaultdict(float)
    race_cont = {}
    for uk, u in scn.units.items():
        for l, sh in u["share"].items():
            race_share[(u["race"], l)] += sh * u["weight"]
            race_weight[(u["race"], l)] += u["weight"]
            c = (u.get("cont") or {}).get(l, 0.0)
            race_cont[(u["race"], l)] = max(race_cont.get((u["race"], l), 0.0), c)
    wide = {k: sigma_for(v / max(race_weight[k], 1.0), race_cont[k], sg) for k, v in race_share.items()}
    narrow = {(uk, l): sigma_for(sh, (u.get("cont") or {}).get(l, 0.0), sg)
              for uk, u in scn.units.items() for l, sh in u["share"].items()}

    root2 = math.sqrt(2.0)

    # A multiplicative error has to be centred, or width turns into advantage. Drawing
    # share * exp(N(0, s^2)) gives an average of share * exp(s^2/2), which is above the share
    # it started from — and the wider the list's error, the further above. Renormalising then
    # takes that surplus off everyone else, so the small and freshly-assembled lists, which
    # have the widest errors, quietly inflate at the expense of the big ones. Subtracting half
    # the variance puts the average back on the projected share, whatever the width.
    def half_var(t):
        core, q, tail = t
        return ((1 - q) * core * core + q * tail * tail) / 2.0 / 2.0

    centre = {k: half_var(v) for k, v in wide.items()}
    centre_n = {k: half_var(v) for k, v in narrow.items()}

    def wobble(table, key, offset):
        core, q, tail = table[key]
        return rng.gauss(0.0, tail if rng.random() < q else core) / root2 - offset

    seats_runs = defaultdict(lambda: defaultdict(list))
    unit_runs = defaultdict(lambda: defaultdict(list))
    chamber_runs = defaultdict(list)
    cand = defaultdict(lambda: [0, 0, 0])
    over_thr = defaultdict(int)
    pct_sum, pct_n = defaultdict(float), defaultdict(int)

    for _ in range(sims):
        shock = {}
        for race, uks in race_units.items():
            for l in {l for uk in uks for l in scn.units[uk]["share"]}:
                shock[(race, l)] = wobble(wide, (race, l), centre[(race, l)])

        for race, uks in race_units.items():
            cfg = RACES[race]
            ent_votes = defaultdict(lambda: defaultdict(float))
            ent_direct = defaultdict(lambda: defaultdict(int))
            got_all, race_seats = {}, defaultdict(int)

            for uk in uks:
                u = scn.units[uk]
                drawn = {l: sh * math.exp(shock[(race, l)] + wobble(narrow, (uk, l), centre_n[(uk, l)]))
                         for l, sh in u["share"].items()}
                tot = sum(drawn.values()) or 1.0
                drawn = {l: v / tot for l, v in drawn.items()}
                seats = u["seats"]
                if seat_jitter and seats > 1 and rng.random() < seat_jitter:
                    seats += rng.choice((-1, 1))
                got = seatlaw.direct_seats(drawn, seats)
                got_all[uk] = got
                for l, v in drawn.items():
                    if v >= seatlaw.THRESHOLD:
                        over_thr[(uk, l)] += 1
                for l, k in got.items():
                    race_seats[l] += k
                    unit_runs[uk][l].append(k)
                for tag, areas in cfg["groups"]:
                    if areas is None or u["area"] in areas:
                        for l, v in drawn.items():
                            ent_votes[tag][l] += v * u["weight"]
                        for l, k in got.items():
                            ent_direct[tag][l] += k

            comp_got = {}
            for tag, _areas in cfg["groups"]:
                ncomp = scn.seats_comp.get(f"{race}|{tag}", 0)
                if ncomp:
                    g = seatlaw.compensatory(ent_votes[tag], ent_direct[tag], ncomp)
                    comp_got[tag] = g
                    for l, k in g.items():
                        race_seats[l] += k

            elected = set()
            for uk in uks:
                u = scn.units[uk]
                for l, k in got_all[uk].items():
                    if k <= 0:
                        continue
                    cands = u["lists"][l]
                    pcts = model.draw_pcts([meta[c["key"]] for c in cands], rng, cells,
                                           pick_total(rng, totals, race),
                                           sg.get("pers_boost", 1.0))
                    for i, c in enumerate(cands):
                        pct_sum[c["key"]] += pcts[i]
                        pct_n[c["key"]] += 1
                    for w in seatlaw.winners_within_list(
                            [{"id": c["key"], "pos": c["pos"], "pct": pcts[i]}
                             for i, c in enumerate(cands)], k):
                        cand[w][0] += 1
                        cand[w][1] += 1
                        elected.add(w)

            for tag, g in comp_got.items():
                area = cfg["comp_area"].get(tag)
                for l, k in g.items():
                    order = (comp_lists.get((race, area)) or {}).get(l)
                    if order is None and comp_fallback:
                        order = fallback_comp_order(scn, race, cfg, tag, l)
                    taken = 0
                    for key in order or ():
                        if taken >= k:
                            break
                        if key in elected:
                            continue
                        cand[key][0] += 1
                        cand[key][2] += 1
                        elected.add(key)
                        taken += 1

            for l, k in race_seats.items():
                seats_runs[race][l].append(k)
            chamber_runs[race].append(dict(race_seats))

    # a list that won nothing in a run never appended a zero; pad so percentiles are honest
    for per in seats_runs.values():
        for xs in per.values():
            xs += [0] * (sims - len(xs))
    for per in unit_runs.values():
        for xs in per.values():
            xs += [0] * (sims - len(xs))
    return {"seats": seats_runs, "unit": unit_runs, "chamber": chamber_runs, "cand": cand,
            "over_thr": over_thr, "sims": sims,
            "pct": {k: pct_sum[k] / pct_n[k] for k in pct_n if pct_n[k]}}


_FALLBACK = {}


def fallback_comp_order(scn, race, cfg, tag, lname):
    """Replay only: the compensatory lists of 2018 and 2022 are not published anywhere machine
    readable, so the replay has to guess the order a party chose. It guesses "highest up their
    constituency list first". The backtest reports that limit instead of folding it into the
    headline score."""
    key = (race, tag, lname)
    if key in _FALLBACK:
        return _FALLBACK[key]
    areas = dict(cfg["groups"]).get(tag)
    rows = []
    for _uk, u in scn.units.items():
        if u["race"] != race:
            continue
        if areas is not None and u["area"] not in areas:
            continue
        rows += list(u["lists"].get(lname, ()))
    rows.sort(key=lambda c: (c.get("pos") or 999))
    _FALLBACK[key] = [c["key"] for c in rows]
    return _FALLBACK[key]


# ---------------------------------------------------------------- fitting on 2022

def actual_shares(data, year):
    out = {}
    for race, cfg in RACES.items():
        areas = ((data["swing"]["general"][str(year)].get(cfg["lvl"])) or {}).get("areas") or {}
        for area, d in areas.items():
            tot = d["voters"] or 1
            out[f"{race}-{area}"] = {p: (v["voters"] or 0) / tot for p, v in d["by_party"].items()}
    return out


def score(scn, actual):
    """Weighted mean absolute error on list shares, in percentage points."""
    num = den = 0.0
    for uk, u in scn.units.items():
        act = actual.get(uk) or {}
        w = u["weight"]
        for l, pred in u["share"].items():
            num += w * abs(pred - act.get(l, 0.0))
            den += w
    return 100 * num / den if den else None


def residuals(scn, actual, floor=0.002):
    """How wrong the projection was in 2022, measured the three ways that matter.

    By size: a list under one percent moves in a way a list over fifteen does not, and one
    number for both would put absurd bands on SDA and dishonestly tight ones on a list of
    thirty unknowns.

    By whether the list is plainly a continuation: the worst misses in the replay were not big
    parties drifting, they were lists the model *assembled* from a predecessor that had split
    or folded — SDBiH, Koalicija Država, PDA — where it put seventeen percent on something
    that got two. The 2026 ballot is full of that kind, so they get their own width.

    And by shape. The errors are not a bell curve. For a large continuing list the typical
    miss is small, a spread of about 0.2 in log terms, but roughly one list in twelve misses
    by a mile. One standard deviation across both is wrong twice over: it makes SDA's range
    absurd and it still hides how far a list can fall. So the width is kept as a core plus a
    tail, and the simulation reaches for the tail as often as 2022 did."""
    rows = []
    for uk, u in scn.units.items():
        act = actual.get(uk) or {}
        for l, pred in u["share"].items():
            a = act.get(l, 0.0)
            if pred >= floor and a >= floor:
                rows.append((pred, math.log(a / pred), (u.get("cont") or {}).get(l, 0.0)))
    fallback = {"core": {"nastavak": (0.45, 0.10), "nova": (0.65, 0.10)},
                "tail": {"nastavak": (1.4, 0.30), "nova": (1.8, 0.30)}, "q": 0.08,
                "n": len(rows), "buckets": [], "bias": {"a": 0.0, "b": 0.0}}
    if len(rows) < 20:
        return fallback

    def line(points, default):
        sw = sum(w for _x, _y, w in points)
        if not sw or len(points) < 2:
            return default
        mx = sum(x * w for x, _y, w in points) / sw
        my = sum(y * w for _x, y, w in points) / sw
        den = sum(w * (x - mx) ** 2 for x, _y, w in points)
        b = (sum(w * (x - mx) * (y - my) for x, y, w in points) / den) if den else 0.0
        return round(my - b * mx, 4), round(b, 4)

    buckets, core_pts = [], {"nastavak": [], "nova": []}
    tail_pts = {"nastavak": [], "nova": []}
    qs, bias_pts = [], []
    for lo, hi in ((0.002, 0.01), (0.01, 0.03), (0.03, 0.07), (0.07, 0.15), (0.15, 1.01)):
        mid = -math.log10(math.sqrt(lo * hi))
        allsel = [e for p, e, _c in rows if lo <= p < hi]
        if len(allsel) >= 5:
            bias_pts.append((mid, sum(allsel) / len(allsel), len(allsel)))
        for tag, test in (("nastavak", lambda c: c >= 0.6), ("nova", lambda c: c < 0.6)):
            sel = [e for p, e, c in rows if lo <= p < hi and test(c)]
            if len(sel) < 5:
                continue
            m = _median(sel)
            core = max(1.4826 * _median([abs(x - m) for x in sel]), 0.05)
            tails = [x for x in sel if abs(x - m) > 2.5 * core]
            q = len(tails) / len(sel)
            tail = max((sum((x - m) ** 2 for x in tails) / len(tails)) ** 0.5 if tails else 0.0,
                       2.5 * core)
            core_pts[tag].append((mid, core, len(sel)))
            tail_pts[tag].append((mid, tail, len(sel)))
            qs.append((q, len(sel)))
            buckets.append({"od": round(100 * lo, 1), "do": round(100 * hi, 1), "vrsta": tag,
                            "n": len(sel), "jezgro": round(core, 3), "rep_udio": round(100 * q),
                            "rep_sirina": round(tail, 3),
                            "prosjecna_greska": round(sum(sel) / len(sel), 3)})
    core_lines = {t: line(core_pts[t], fallback["core"][t]) for t in ("nastavak", "nova")}
    tail_lines = {t: line(tail_pts[t], fallback["tail"][t]) for t in ("nastavak", "nova")}
    wq = sum(w for _q, w in qs) or 1
    ba, bb = line(bias_pts, (0.0, 0.0))
    return {"core": core_lines, "tail": tail_lines,
            "q": round(min(max(sum(v * w for v, w in qs) / wq, 0.02), 0.20), 4),
            "n": len(rows), "buckets": buckets, "bias": {"a": ba, "b": bb}}


def sigma_for(share, cont, sg):
    """(usual width, how often it blows out, how wide when it does) for one list.

    The tail is fitted on its own rather than as a fixed multiple of the core, because the two
    do not move together. A large continuing list is normally within a fifth of where the model
    puts it — but when it goes, it goes a very long way, further in absolute terms than a small
    list ever does. Tying the tail to the core by one ratio quietly makes the big parties look
    certain, and the 2022 replay catches that immediately: it starts saying 86 percent about
    people who won two times in three."""
    x = -math.log10(max(share, 0.001))
    tag = "nastavak" if cont >= 0.6 else "nova"
    k = sg.get("boost", 1.0)
    a, b = sg["core"][tag]
    core = min(max(a + b * x, 0.10), 1.30) * k
    ta, tb = (sg.get("tail") or {}).get(tag, (core * 3.0, 0.0))
    tail = min(max((ta + tb * x) * k, 2.5 * core), 2.60 * k)
    return core, sg["q"], tail


def fit(data, verbose=True):
    """Try the settings on 2022 and keep the ones that were least wrong.

    Only three things are free: how much to trust the printed name against where the people
    went, how much of a vanished party's vote comes back at all, and how hard to lean on the
    local-election swing. Everything else is the law or a measurement."""
    prior_ballot, prior_meta, prior_info = ballot_prior(data, 2022)
    seats22 = defaultdict(int)
    for r in data["ballots"]["general"]:
        if r["y"] == 2022 and r.get("elected") and r.get("via") != "compensation":
            race = _race_of(r["race"])
            if race:
                seats22[f"{race}-{r['area']}"] += 1
    seats22 = dict(seats22)
    actual = actual_shares(data, 2022)

    best = best_s = best_scn = None
    tried = []
    for nw in (0.25, 0.5, 0.75):
        for ret in (0.4, 0.6, 0.8):
            for lam in (0.0, 0.15, 0.25, 0.35, 0.5, 0.75, 1.0):
                params = {**DEFAULTS, "name_weight": nw, "retention": ret, "lam": lam}
                scn = Scenario(data, prior_ballot, 2018, 2016, 2020, seats22, params)
                s = score(scn, actual)
                tried.append({"name_weight": nw, "retention": ret, "lam": lam, "mae": round(s, 3)})
                if best_s is None or s < best_s:
                    best, best_s, best_scn = params, s, scn
    if verbose:
        print(f"   najbolje: ime/ljudi {best['name_weight']}, povrat {best['retention']}, "
              f"pomak^{best['lam']} → prosječna greška {best_s:.2f} p.p. po listi")
        print(f"      bez pomaka (lam=0): {min(t['mae'] for t in tried if t['lam'] == 0):.2f} p.p.; "
              f"puni pomak (lam=1): {min(t['mae'] for t in tried if t['lam'] == 1.0):.2f} p.p.")

    # The replay shows the projection leaning: too much on the lists it already thinks are
    # big. A tilt correction is the obvious fix, so it is tried — and kept only if it helps.
    raw = residuals(best_scn, actual)
    tilted = Scenario(data, prior_ballot, 2018, 2016, 2020, seats22, {**best, "calib": raw["bias"]})
    mae_tilt = score(tilted, actual)
    used, plain_s = mae_tilt < best_s - 1e-9, best_s
    if used:
        best, best_scn, best_s = {**best, "calib": raw["bias"]}, tilted, mae_tilt
    sg = residuals(best_scn, actual)
    sg["ispravka_nagiba"] = {
        "koeficijenti": raw["bias"], "greska_s_njom": round(mae_tilt, 3),
        "greska_bez_nje": round(plain_s, 3), "primijenjena": used,
        "zasto": ("Model sistematski precjenjuje velike liste i podcjenjuje male. Ispravka tog "
                  "nagiba je izmjerena na 2022. i isprobana. Uključuje se samo ako na istom "
                  "testu smanji prosječnu grešku; ovdje stoji i kad nije, da se vidi šta je "
                  "probano i zašto nije ušlo."),
    }
    if verbose:
        print(f"   ispravka nagiba: {plain_s:.2f} p.p. bez nje, {mae_tilt:.2f} s njom → "
              f"{'uključena' if used else 'nije uključena'}")
        print(f"   rasipanje (n={sg['n']}; rep u {round(100 * sg['q'])}% slučajeva):")
        for b in sg["buckets"]:
            print(f"      {b['vrsta']:8s} lista {b['od']:>5}–{b['do']:<5}%: uobičajeno "
                  f"{b['jezgro']:.2f}, rep {b['rep_sirina']:.2f}, n={b['n']}")
    return best, best_scn, {"mae": best_s, "sigma": sg, "grid": tried, "prior_info": prior_info,
                            "prior_meta": prior_meta, "prior_ballot": prior_ballot,
                            "seats22": seats22, "actual": actual}


def ece(pairs, edges=(0, 2, 5, 10, 20, 35, 50, 65, 80, 92, 100.1)):
    """Average distance between what was said and what happened, weighted by how many people
    were said it about. Zero means a stated probability means exactly what it says."""
    num = den = 0.0
    for lo, hi in zip(edges, edges[1:]):
        rows = [(p, w) for p, w in pairs if lo <= p < hi]
        if not rows:
            continue
        said = sum(p for p, _ in rows) / len(rows)
        happened = 100 * sum(w for _, w in rows) / len(rows)
        num += len(rows) * abs(said - happened)
        den += len(rows)
    return num / den if den else None


def band_coverage(sim, fitinfo):
    """Share of parties whose real 2022 seat count fell inside the projected 5–95 band.

    Should come out near 90. Much higher means the seat ranges are padded, which is its own
    kind of dishonesty — a range wide enough to be always right says nothing."""
    info, inside, total = fitinfo["prior_info"], 0, 0
    for race, per in sim["seats"].items():
        act = defaultdict(int)
        for _k, m in info.items():
            if m["unit"].startswith(race) and m.get("elected"):
                act[m["list"]] += 1
        for l, xs in per.items():
            a = act.get(l, 0)
            if a or sum(xs) / len(xs) >= 0.5:
                total += 1
                inside += pctl(xs, 0.05) <= a <= pctl(xs, 0.95)
    return round(100 * inside / max(total, 1), 1)


def fit_spread(data, params, fitinfo, sg, seed, sims=1500):
    """Where the missing uncertainty actually lives, decided by measurement rather than taste.

    Run straight, the model comes out wrong in two opposite directions at once: the seat range
    per party covers the real 2022 answer almost every time — wider than the nine times in ten
    it claims — while the odds it gives individual people are too sure, 97 percent said about
    140 candidates of whom 119 got in. Both cannot be fixed by one dial.

    They are not the same failure. The vote shares are fine; what the model does not know is
    *which* person on a list takes its seats, because crossing twenty percent of your own
    list's ballots — the one thing that beats the party's printed order — is less predictable
    than position and past record make it look. So two dials are tried together: one widening
    the vote shares, one widening the personal-vote draw, and the grid is printed in full.

    The guess turns out to be wrong, which is why the grid is printed rather than a conclusion:
    widening the personal-vote draw helps a little and then hurts, and what actually fixes the
    calibration is widening the vote shares. That also leaves the seat bands covering about 98
    percent of real answers instead of the 90 they advertise, and that is not fixed — it is
    stated on the page, because a range wide enough to always be right is its own dishonesty
    and hiding it would be worse."""
    cells, totals = personal_cells(data["ballots"], (2018,))
    info = fitinfo["prior_info"]
    rows, best = [], None
    for share_k in (1.0, 1.3, 1.6):
        for pers_k in (1.0, 1.5, 2.0, 2.5):
            trial = {**sg, "boost": share_k, "pers_boost": pers_k}
            scn = Scenario(data, fitinfo["prior_ballot"], 2018, 2016, 2020, fitinfo["seats22"], params)
            sim = simulate(scn, cells, totals, fitinfo["prior_meta"], {}, sims, seed, trial,
                           comp_fallback=True)
            pairs = [(100.0 * (sim["cand"].get(key) or [0])[0] / sim["sims"],
                      1 if m.get("elected") else 0) for key, m in info.items()]
            e, b, cov = ece(pairs), brier(pairs), band_coverage(sim, fitinfo)
            # what we are minimising: a stated probability meaning what it says, plus the seat
            # band not being padded past the 90 percent it advertises
            # calibration carries more weight than coverage because it is measured on
            # thousands of people and coverage on about a hundred party-rows
            loss = e + abs(cov - 90) / 15.0
            rows.append({"udjeli": share_k, "licni": pers_k, "ece": round(e, 3), "brier": b,
                         "pokrivenost": cov, "ukupno": round(loss, 3)})
            if best is None or loss < best[2]:
                best = (share_k, pers_k, loss)
    return best[0], best[1], rows


# ---------------------------------------------------------------- scoring the replay

def calibration(pairs, edges=(0, 2, 5, 10, 20, 35, 50, 65, 80, 92, 100.1)):
    """Said N percent, and then what happened. The one table that says whether a probability
    on this site means anything at all."""
    out = []
    for lo, hi in zip(edges, edges[1:]):
        rows = [(p, w) for p, w in pairs if lo <= p < hi]
        if not rows:
            continue
        out.append({"od": lo, "do": round(min(hi, 100), 1), "n": len(rows),
                    "rekli": round(sum(p for p, _ in rows) / len(rows), 1),
                    "stvarno": round(100 * sum(w for _, w in rows) / len(rows), 1),
                    "izabranih": sum(w for _, w in rows)})
    return out


def brier(pairs):
    return round(sum((p / 100 - w) ** 2 for p, w in pairs) / len(pairs), 4) if pairs else None


def backtest_report(data, params, fitinfo, sims, seed, sg):
    """Replay 2022 with the fitted settings and score it against what actually happened."""
    scn = Scenario(data, fitinfo["prior_ballot"], 2018, 2016, 2020, fitinfo["seats22"], params)
    cells, totals = personal_cells(data["ballots"], (2018,))
    sim = simulate(scn, cells, totals, fitinfo["prior_meta"], {}, sims, seed, sg, comp_fallback=True)

    info = fitinfo["prior_info"]
    pairs, pairs_direct, pairs_comp = [], [], []
    for key, m in info.items():
        p = 100.0 * (sim["cand"].get(key) or [0])[0] / sim["sims"]
        won = 1 if m.get("elected") else 0
        pairs.append((p, won))
        (pairs_comp if m.get("via") == "compensation" else pairs_direct).append((p, won))

    per_race, seat_err = {}, []
    for race, per in sim["seats"].items():
        act = defaultdict(int)
        for key, m in info.items():
            if m["unit"].startswith(race) and m.get("elected"):
                act[m["list"]] += 1
        rows = []
        for l, xs in per.items():
            exp, a = sum(xs) / len(xs), act.get(l, 0)
            rows.append({"lista": l, "projekcija": round(exp, 1), "stvarno": a,
                         "p05": pctl(xs, 0.05), "p95": pctl(xs, 0.95),
                         "u_rasponu": bool(pctl(xs, 0.05) <= a <= pctl(xs, 0.95))})
            if a or exp >= 0.5:
                seat_err.append(abs(exp - a))
        rows.sort(key=lambda r: (-r["stvarno"], -r["projekcija"]))
        per_race[race] = {"title": RACES[race]["title"], "rows": rows,
                          "mae_mandata": round(sum(abs(r["projekcija"] - r["stvarno"]) for r in rows)
                                               / max(len(rows), 1), 2),
                          "u_rasponu": round(100 * sum(1 for r in rows if r["u_rasponu"])
                                             / max(len(rows), 1))}

    named = {}
    for race in sim["seats"]:
        ranked = sorted(((100.0 * (sim["cand"].get(k) or [0])[0] / sim["sims"], k)
                         for k, m in info.items() if m["unit"].startswith(race)), reverse=True)
        real = {k for k, m in info.items() if m["unit"].startswith(race) and m.get("elected")}
        top = {k for _p, k in ranked[:len(real)]}
        named[race] = {"title": RACES[race]["title"], "mjesta": len(real),
                       "pogodjeno": len(top & real),
                       "pct": round(100 * len(top & real) / max(len(real), 1))}

    return {
        "what": ("Isti model i isti kod, pušten na 2022. i hranjen samo onim što se moglo znati "
                 "prije 2. oktobra 2022: rezultatom općih izbora 2018. i lokalnim izborima 2016. "
                 "i 2020. Nijedan glas iz 2022. nije ušao u račun; 2022. služi samo da se "
                 "prebroji koliko je model pogriješio."),
        "params": {k: v for k, v in params.items() if k != "calib"},
        "share_mae_pp": round(fitinfo["mae"], 3),
        "rasipanje": fitinfo["sigma"],
        "grid": fitinfo["grid"],
        "kalibracija": calibration(pairs),
        "kalibracija_direktni": calibration(pairs_direct),
        "brier": brier(pairs), "brier_direktni": brier(pairs_direct),
        "n_kandidata": len(pairs), "n_kompenzacijskih": sum(1 for _p, w in pairs_comp if w),
        "po_trkama": per_race, "imena": named,
        "mandati_mae": round(sum(seat_err) / max(len(seat_err), 1), 3),
        "ogranicenje_komp": ("Kompenzacijske liste iz 2018. i 2022. nigdje nisu objavljene u "
                             "čitljivom obliku, pa replay mora pogađati redoslijed koji je "
                             "stranka izabrala. Za 2026. te liste postoje i model ih čita "
                             "direktno, pa je ovaj dio testa stroži nego što stvarna projekcija "
                             "treba biti. Zato uz ukupnu kalibraciju stoji i ona bez "
                             "kompenzacijskih mandata."),
    }


# ---------------------------------------------------------------- majority races

# Which past results say something about each single-seat race, and how much. The RS presidency
# was voted again on 23 November 2025 after Milorad Dodik was removed from office, and that
# by-election is the most recent read of that electorate there is — leaving it out is how a
# model ends up giving Branko Blanuša, who took 48.1 percent in it and is running again, one
# percent of the odds.
MAJORITY_SOURCES = {
    "oi2026-1-701": [("general", "2022", "predsjednistvo", "701", 1.00),
                     ("general", "2018", "predsjednistvo", "701", 0.35)],
    "oi2026-1-702": [("general", "2022", "predsjednistvo", "702", 1.00),
                     ("general", "2018", "predsjednistvo", "702", 0.35)],
    "oi2026-1-703": [("general", "2022", "predsjednistvo", "703", 1.00),
                     ("by", "rs-predsjednik-2025", None, "5", 0.60),
                     ("general", "2018", "predsjednistvo", "703", 0.35)],
    "oi2026-5-5": [("by", "rs-predsjednik-2025", None, "5", 1.00),
                   ("general", "2022", "predsjednik-rs", "5", 0.45),
                   ("general", "2018", "predsjednik-rs", "5", 0.20)],
}
MAJORITY_TITLE = {
    "oi2026-1-701": "Predsjedništvo BiH — bošnjački član",
    "oi2026-1-702": "Predsjedništvo BiH — hrvatski član",
    "oi2026-1-703": "Predsjedništvo BiH — srpski član",
    "oi2026-5-5": "Predsjednik Republike Srpske",
}
MAJORITY_REGION = {"oi2026-1-701": "FBiH", "oi2026-1-702": "FBiH",
                   "oi2026-1-703": "RS", "oi2026-5-5": "RS"}


def majority_sources(data, key):
    """[{label, weight, rows}] for one single-seat race, newest first."""
    sw = data["swing"]
    out = []
    for kind, a, lvl, area, w in MAJORITY_SOURCES.get(key, ()):
        if kind == "general":
            rows = ((sw["general"][a].get(lvl) or {}).get("areas") or {}).get(area) or []
            label = {"predsjednistvo": f"Predsjedništvo {a}.",
                     "predsjednik-rs": f"predsjednik RS {a}."}.get(lvl, str(a))
        else:
            be = sw["by_election"].get(a) or {}
            rows = (be.get("areas") or {}).get(area) or []
            label = f"{be.get('title', a)}, {be.get('date', '')}"
        if rows:
            out.append({"label": label, "weight": w, "rows": rows})
    return out


def majority_races(data, proj_shares, params, sims, seed):
    """Presidency and the RS president: one seat, most votes wins, no list to hide behind.

    Three things say something about a candidate here and the model uses all three: what this
    same seat did the last time it was voted, how strong the party behind them looks in this
    projection, and the one poll close enough to the election to be worth anything. What it
    cannot see is a name, a rally, or a face people already know — so when a party puts up
    someone who has never run for this seat, the model says so out loud and widens the band
    instead of handing that person their predecessor's result."""
    rng = random.Random(seed + 7)
    poll_pres = next((p for p in data["polls"]["polls"] if p.get("presidency")), None)
    out = {}

    for key, title in MAJORITY_TITLE.items():
        u = data["units"].get(key)
        srcs = majority_sources(data, key)
        if not u or not srcs:
            continue

        def same_person(a, b):
            """CIK printed „RADONČIĆ FAHRUDIN" in 2018 and „FAHRUDIN RADONČIĆ" in 2026, so the
            names have to be compared as a set of words, not as a string. Without that, a man
            who took 13 percent of this exact race eight years ago reads to the model as
            somebody who has never run."""
            return set(model.fold(a).split()) == set(model.fold(b).split())

        def by_name(c, s):
            for r in s["rows"]:
                if same_person(r["name"], c["name"]):
                    return r["share"]
            return None

        def by_party(c, s):
            tot = 0.0
            for r in s["rows"]:
                if model.fold(r["party"]) == model.fold(c["list"]) or model.name_match(r["party"], c["list"]):
                    tot += r["share"]
            return tot or None

        def blend(getter, c):
            """Weighted geometric mean across the sources that have this candidate at all."""
            num = den = 0.0
            for s in srcs:
                v = getter(c, s)
                if v and v > 0:
                    num += s["weight"] * math.log(v)
                    den += s["weight"]
            return math.exp(num / den) if den else None

        # what a candidate with nothing measurable behind them has historically got here
        minor = [r["share"] for s in srcs for r in s["rows"][2:] if r["share"] > 0]
        floor = _median(minor) if minor else 1.0
        region = MAJORITY_REGION[key]
        area = key.rsplit("-", 1)[1]

        cands = []
        for l in u["lists"]:
            for c in l["candidates"]:
                cands.append({"name": c["name"], "pid": c.get("pid"), "list": l["name"]})
        for c in cands:
            c["prev_self"] = blend(by_name, c)
            c["prev_party"] = blend(by_party, c)
            c["party_proj"] = ((proj_shares.get((region, c["list"])) or 0) * 100) or None
            c["poll"] = None
            if poll_pres:
                for nm, v in (poll_pres["presidency"].get(area) or {}).items():
                    if not nm.startswith("_") and same_person(nm, c["name"]):
                        c["poll"] = v
            c["novo_lice"] = c["prev_self"] is None

        raw = []
        for c in cands:
            W = ({"prev_self": 0.50, "prev_party": 0.15, "party_proj": 0.15, "poll": 0.20}
                 if not c["novo_lice"] else
                 {"prev_party": 0.40, "party_proj": 0.40, "poll": 0.20})
            num = den = 0.0
            for k, w in W.items():
                v = c.get(k)
                if v and v > 0:
                    num += w * math.log(v)
                    den += w
            c["oslonjeno_na"] = [k for k in W if c.get(k)]
            raw.append(math.exp(num / den) if den else floor)
        tot = sum(raw) or 1.0
        for c, r in zip(cands, raw):
            c["share"] = 100 * r / tot

        base_sd = params.get("sd_majority", 0.30)
        # centred the same way: a candidate nobody can measure gets a wider error, and that
        # must not by itself make them likelier to win
        for c in cands:
            c["_sd"] = base_sd * (1.5 if c["novo_lice"] else 1.0)
        wins = defaultdict(int)
        for _ in range(sims):
            draw = {c["name"]: c["share"] * math.exp(rng.gauss(0.0, c["_sd"]) - c["_sd"] ** 2 / 2)
                    for c in cands}
            wins[max(draw, key=draw.get)] += 1
        for c in cands:
            c["p_win"] = round(100 * wins[c["name"]] / sims, 1)
            c["share"] = round(c["share"], 1)
            c.pop("_sd", None)
            for k in ("prev_self", "prev_party", "party_proj", "poll"):
                if c.get(k) is not None:
                    c[k] = round(c[k], 1)
        cands.sort(key=lambda c: -c["p_win"])
        out[key] = {
            "title": title, "race": key.rsplit("-", 2)[0] if key.count("-") > 2 else key.rsplit("-", 1)[0],
            "area": area, "candidates": cands, "sd": base_sd,
            "izvori": [{"label": s["label"], "tezina": s["weight"],
                        "redovi": [{"name": r["name"], "party": r["party"], "share": r["share"],
                                    "won": r["elected"]} for r in s["rows"][:6]]} for s in srcs],
            "napomena": ("Ovdje nema liste iza koje se stoji: pobjeđuje onaj s najviše glasova. "
                         "Model zna samo šta je ista trka dala zadnji put, koliko je jaka stranka "
                         "iza kandidata i šta kaže jedna anketa. Ne zna koliko je neko ime "
                         "poznato, pa je raspon širok — a kod kandidata koji ovu trku nisu vozili "
                         "ranije još širi."),
        }
    return out


def majority_backtest(data):
    """How far this same recipe was from the 2022 single-seat races using only 2018.

    Twelve pairs is a thin test and it is reported as such — but it is the only measurement we
    have of how wrong a one-seat projection in BiH can be, and it sets how wide the band is."""
    sw = data["swing"]
    errs, rows = [], []
    for lvl, areas in (("predsjednistvo", ("701", "702", "703")), ("predsjednik-rs", ("5",))):
        a18 = (sw["general"]["2018"].get(lvl) or {}).get("areas") or {}
        a22 = (sw["general"]["2022"].get(lvl) or {}).get("areas") or {}
        for area in areas:
            prev = {model.fold(x["party"]): x["share"] for x in (a18.get(area) or [])}
            for x in (a22.get(area) or []):
                p = prev.get(model.fold(x["party"]))
                if p and x["share"]:
                    errs.append(math.log(x["share"] / p))
                    rows.append({"trka": lvl, "area": area, "stranka": x["party"][:34],
                                 "2018": round(p, 1), "2022": round(x["share"], 1)})
    if len(errs) < 2:
        return 0.30, rows
    m = sum(errs) / len(errs)
    sd = math.sqrt(sum((e - m) ** 2 for e in errs) / (len(errs) - 1))
    return round(min(max(sd, 0.15), 0.6), 3), rows


# ---------------------------------------------------------------- coalition arithmetic

def coalition_math(runs, chamber_size, top_n=6, max_size=4):
    """Which combinations of lists reach half the chamber, and how often.

    Arithmetic, not a prediction about who would sit with whom — the site has no source for
    that and does not guess. It answers only: after this election, which groupings add up."""
    if not runs:
        return None
    need = chamber_size // 2 + 1
    totals = defaultdict(int)
    for r in runs:
        for l, k in r.items():
            totals[l] += k
    top = [l for l, _ in sorted(totals.items(), key=lambda x: -x[1])[:top_n]]
    combos = []
    for size in range(1, max_size + 1):
        for combo in itertools.combinations(top, size):
            hits = sum(1 for r in runs if sum(r.get(l, 0) for l in combo) >= need)
            if hits:
                combos.append({"liste": list(combo), "n": size,
                               "p": round(100 * hits / len(runs), 1),
                               "mandati": round(sum(sum(r.get(l, 0) for l in combo) for r in runs)
                                                / len(runs), 1)})
    combos.sort(key=lambda c: (c["n"], -c["p"]))
    sizes = defaultdict(int)
    for r in runs:
        cum = k = 0
        for _l, v in sorted(r.items(), key=lambda x: -x[1]):
            cum += v
            k += 1
            if cum >= need:
                break
        sizes[k] += 1
    veto = {}
    for l in top:
        c = sum(1 for r in runs if sum(v for k2, v in r.items() if k2 != l) < need)
        veto[l] = round(100 * c / len(runs), 1)
    return {"vecina": need,
            "kombinacije": [c for c in combos if c["p"] >= 1.0][:40],
            "najmanje_lista": {str(k): round(100 * v / len(runs), 1) for k, v in sorted(sizes.items())},
            "bez_njih_nema_vecine": veto}


# ---------------------------------------------------------------- output

def build_output(data, scn, sim, info, comp_lists, params, bt, majority, sg):
    sims = sim["sims"]
    races = {}
    for race, cfg in RACES.items():
        uks = sorted(uk for uk, u in scn.units.items() if u["race"] == race)
        if not uks:
            continue
        if cfg["one_house"]:
            houses = [{"key": race, "title": cfg["title"], "units": uks,
                       "seats": sum(scn.units[uk]["seats"] for uk in uks)
                                + sum(v for k, v in scn.seats_comp.items() if k.startswith(race + "|")),
                       "runs": sim["chamber"][race]}]
        else:
            houses = []
            for uk in uks:
                area = uk.rsplit("-", 1)[1]
                runs = [{l: xs[i] for l, xs in sim["unit"][uk].items() if xs[i]} for i in range(sims)]
                houses.append({"key": uk, "title": f"Skupština {CANTON.get(area, area)}",
                               "units": [uk], "seats": scn.units[uk]["seats"], "runs": runs})

        for h in houses:
            runs = h.pop("runs")
            rows = []
            for l in {l for uk in h["units"] for l in scn.units[uk]["share"]}:
                xs = [r.get(l, 0) for r in runs]
                # share over the constituencies this list actually stands in, not over the
                # whole chamber: a list that runs only in Republika Srpska is not on "six
                # percent of the country", it is on eighteen percent of where it appears, and
                # the second number is the one that decides whether it clears three percent
                here = [uk for uk in h["units"] if l in scn.units[uk]["share"]]
                w_tot = sum(scn.units[uk]["weight"] for uk in here) or 1
                share = sum(scn.units[uk]["share"][l] * scn.units[uk]["weight"] for uk in here) / w_tot
                base = sum(scn.units[uk]["base_share"].get(l, 0) * scn.units[uk]["weight"]
                           for uk in here) / w_tot
                rows.append({"lista": l, "mandati": round(sum(xs) / len(xs), 1),
                             "p05": pctl(xs, 0.05), "p50": pctl(xs, 0.5), "p95": pctl(xs, 0.95),
                             "mode": max(set(xs), key=xs.count),
                             "udio": round(100 * share, 2),
                             "udio_bez_pomaka": round(100 * base, 2),
                             "jedinica": len(here),
                             "p_bar_jedan": round(100 * sum(1 for x in xs if x >= 1) / len(xs), 1)})
            rows.sort(key=lambda r: -r["mandati"])
            h["rows"] = rows
            h["koalicije"] = coalition_math(runs, h["seats"])

        units_out = {}
        for uk in uks:
            u = scn.units[uk]
            area = u["area"]
            rows = []
            for l in u["share"]:
                xs = sim["unit"][uk].get(l) or [0] * sims
                rows.append({
                    "lista": l,
                    "udio": round(100 * u["share"][l], 2),
                    "udio_bez_pomaka": round(100 * u["base_share"].get(l, 0), 2),
                    "pomak": round(u["trend"].get(l, 1.0), 3),
                    "nastavak": (u.get("cont") or {}).get(l, 0.0),
                    "mandati": round(sum(xs) / len(xs), 2),
                    "p50": pctl(xs, 0.5), "p95": pctl(xs, 0.95),
                    "p_prag": round(100 * sim["over_thr"].get((uk, l), 0) / sims, 1),
                    "kandidati": sorted(
                        [{"key": c["key"], "pid": c["pid"], "ime": c["name"], "pos": c["pos"],
                          "p": round(100 * (sim["cand"].get(c["key"]) or [0])[0] / sims, 1)}
                         for c in u["lists"][l]], key=lambda c: (-c["p"], c["pos"] or 999)),
                })
            rows.sort(key=lambda r: -r["udio"])
            units_out[uk] = {"area": area, "race": race, "region": region_of(area),
                             "title": CANTON.get(area) or UNIT_TITLE.get(area) or f"Izborna jedinica {area}",
                             "mandati": u["seats"], "glasaca_2022": u["weight"],
                             "siroce_2022_pct": scn.diag["orphan"].get(uk), "liste": rows}
        races[race] = {"title": cfg["title"], "short": cfg["short"], "chamber": cfg["chamber"],
                       "one_house": cfg["one_house"], "houses": houses, "units": units_out,
                       "kompenzacijski": {k.split("|")[1]: v for k, v in scn.seats_comp.items()
                                          if k.startswith(race + "|")}}

    cands = {}
    for key, nfo in info.items():
        if not nfo.get("unit"):
            continue
        got = sim["cand"].get(key) or [0, 0, 0]
        cands[key] = {"p": round(100 * got[0] / sims, 1),
                      "p_direktno": round(100 * got[1] / sims, 1),
                      "p_komp": round(100 * got[2] / sims, 1),
                      "unit": nfo["unit"], "lista": nfo["list"], "pos": nfo["pos"]}
        if key in sim["pct"]:
            cands[key]["ocekivani_pct"] = round(sim["pct"][key], 1)
    for (race, area), by_list in comp_lists.items():
        for lname, keys in by_list.items():
            for i, k in enumerate(keys, 1):
                if k in cands:
                    cands[k]["komp_lista"] = {"race": race, "area": area, "mjesto": i, "od": len(keys)}

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "election": "Opći izbori u BiH, 4. oktobar 2026.",
        "sims": sims,
        "what": ("Najvjerovatniji ishod izbora i, unutar njega, vjerovatnoća da svaki pojedini "
                 "kandidat dobije mandat. Nije anketa i nije preporuka: polazi od rezultata "
                 "2022, pomjeri ga onoliko koliko su se glasovi pomjerili između lokalnih "
                 "izbora 2020. i 2024, i pusti izborni zakon da podijeli mandate deset hiljada "
                 "puta."),
        "law": {
            "raspodjela": "Sainte-Laguë, djelitelji 1, 3, 5, 7 … (Izborni zakon BiH, član 9.5)",
            "prag": ("3 posto važećih listića u izbornoj jedinici; isto toliko na nivou entiteta "
                     "za kompenzacijske mandate (član 9.6)"),
            "unutar_liste": ("Kandidat koji pređe 20 posto glasača svoje liste uzima mandat po "
                             "ličnim glasovima; sve preostale mandate lista dijeli po svom "
                             "redoslijedu, bez obzira na lične glasove (član 9.8 stav 2)"),
            "kompenzacijski": ("Dodjeljuju se redom s kompenzacijske liste, od vrha, preskačući "
                               "one koji su već izabrani; birač taj redoslijed ne može "
                               "promijeniti (član 9.7)"),
            "provjera": ("seatlaw.py pušta ova pravila na stvarne rezultate 2018. i 2022: svih "
                         "231 lista koje su osvojile mandat i svih 518 mandata po godini izlaze "
                         "tačno, bez ijednog odstupanja."),
            "izvor": ("https://www.izbori.ba/Documents/documents/ZAKONI/Tehnicki_precisceni_tekst/"
                      "Tehnicki_precisceni_tekst_IZ_BiH_05_2024-hrv.pdf"),
        },
        "params": {**{k: v for k, v in params.items() if k != "calib"}, "rasipanje": sg},
        "inputs": {
            "baza": "opći izbori 2022, glasači liste po izbornoj jedinici",
            "pomak": "lokalni izbori 2020 → 2024, po općinama koje čine istu jedinicu",
            "rs_2025": "prijevremeni izbori za predsjednika RS, 23. novembra 2025",
            "ankete": "data/polls.json — mala težina, obrazloženje uz svaku",
            "mandati_po_jedinici": data["seats"]["_assumption"],
            "mandati_napomena": data["seats"]["_note"],
        },
        "races": races,
        "majority": majority,
        "candidates": cands,
        "diagnostics": {
            "siroce_po_jedinici": scn.diag["orphan"],
            "podjele": sorted(scn.diag["splits"], key=lambda s: -s["votes"])[:80],
            "bez_2022": scn.diag["no_prior"],
            "ankete": scn.polls_used,
        },
        "backtest": {k: v for k, v in bt.items() if k != "po_trkama"},
    }


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=SIMS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--backtest", action="store_true", help="samo replay 2022, bez projekcije")
    ap.add_argument("--no-polls", action="store_true")
    args = ap.parse_args()
    t0 = time.time()

    print("1/5 učitavanje")
    data = load()
    print(f"   {len(data['units'])} listića, {len(data['ballots']['general'])} ranijih kandidatura")

    print("2/5 podešavanje na rezultatu 2022 (model ne vidi 2022)")
    params, _scn, fitinfo = fit(data)
    sg = fitinfo["sigma"]
    sd_maj, maj_rows = majority_backtest(data)
    params["sd_majority"] = sd_maj
    print(f"   većinske trke: rasipanje {sd_maj} (log), mjereno na {len(maj_rows)} para 2018→2022")

    print("   gdje fali nesigurnost: u udjelima ili u tome ko unutar liste")
    boost, pers, boost_rows = fit_spread(data, params, fitinfo, sg, args.seed,
                                         sims=max(1200, min(args.sims // 5, 2000)))
    sg["boost"], sg["pers_boost"] = boost, pers
    sg["boost_grid"] = boost_rows
    for r in boost_rows:
        print(f"      udjeli ×{r['udjeli']}, lični glasovi ×{r['licni']}: kalibracija "
              f"{r['ece']} p.p., raspon pokriva {r['pokrivenost']}%, Brier {r['brier']}"
              + ("  ← izabrano" if (r["udjeli"], r["licni"]) == (boost, pers) else ""))

    print("3/5 ocjena tog replaya")
    bt = backtest_report(data, params, fitinfo, min(args.sims, 4000), args.seed, sg)
    bt["vecinske"] = {"sd": sd_maj, "parovi": maj_rows}
    json.dump(bt, open(D + "projection_backtest.json", "w"), ensure_ascii=False, indent=1)
    print(f"   Brier {bt['brier']} (bez kompenzacijskih {bt['brier_direktni']}); "
          f"greška po listi {bt['share_mae_pp']} p.p.; greška po mandatu {bt['mandati_mae']}")
    for race, n in bt["imena"].items():
        print(f"   {RACES[race]['short']}: od {n['mjesta']} izabranih model je imenovao "
              f"{n['pogodjeno']} ({n['pct']}%)")
    print("   kalibracija (rekli → stvarno):")
    for r in bt["kalibracija"]:
        print(f"      {r['od']:>3}–{r['do']:<5} n={r['n']:<5} rekli {r['rekli']:>5}%  "
              f"stvarno {r['stvarno']:>5}%")
    if args.backtest:
        print(f"\ndata/projection_backtest.json zapisan za {time.time() - t0:.0f}s")
        return

    print("4/5 projekcija 2026")
    ballot, meta, info, comp_lists = ballot_2026(data)
    scn = Scenario(data, ballot, 2022, 2020, 2024, data["seats"]["direct"], params)
    if not args.no_polls:
        scn.polls_used = scn.apply_polls(data["polls"], params["poll_weight"])
    for p in scn.polls_used:
        print(f"   anketa {p['id']}: težina {p['tezina']}, vezano {len(p['vezano'])} stranaka"
              + (f", bez veze na listić: {', '.join(p['bez_veze'])}" if p["bez_veze"] else ""))
    cells, totals = personal_cells(data["ballots"], (2018, 2022))
    sim = simulate(scn, cells, totals, meta, comp_lists, args.sims, args.seed, sg, seat_jitter=0.25)
    print(f"   {args.sims} simulacija; {sum(1 for v in sim['cand'].values() if v[0])} "
          f"kandidata dobije mandat bar jednom")

    proj = defaultdict(float)
    for uk, u in scn.units.items():
        if u["race"] != "oi2026-2":
            continue
        reg = region_of(u["area"])
        for l, s in u["share"].items():
            proj[(reg, l)] += s * u["weight"]
    for reg in ("FBiH", "RS"):
        tot = sum(v for (r, _l), v in proj.items() if r == reg) or 1.0
        for k in [k for k in proj if k[0] == reg]:
            proj[k] /= tot
    majority = majority_races(data, dict(proj), params, args.sims, args.seed)

    print("5/5 zapisivanje")
    out = build_output(data, scn, sim, info, comp_lists, params, bt, majority, sg)
    json.dump(out, open(D + "projection.json", "w"), ensure_ascii=False, separators=(",", ":"))
    for race, r in out["races"].items():
        if r["one_house"]:
            h = r["houses"][0]
            top = "; ".join(f"{x['lista'][:20]} {x['mandati']:g} ({x['p05']}–{x['p95']})"
                            for x in h["rows"][:5])
            print(f"   {r['short']} ({h['seats']}): {top}")
    for m in (majority or {}).values():
        a = m["candidates"][0]
        b = m["candidates"][1] if len(m["candidates"]) > 1 else None
        print(f"   {m['title']}: {a['name']} {a['p_win']}%"
              + (f" · {b['name']} {b['p_win']}%" if b else ""))
    print(f"\ndata/projection.json zapisan za {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
