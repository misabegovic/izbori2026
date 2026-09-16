#!/usr/bin/env python3
"""The projection machinery: from the last results to a distribution over this one.

Used twice, with the same code, which is the whole point. `project.py` runs it forward on
2026 and runs it backward on 2022 — trained only on what was knowable before October 2022,
then scored against what happened. Anything the model can only do with hindsight would show
up there as a number that is too good, so it cannot be hidden.

The chain, in order:

  ancestry      Which 2026 list inherits which 2022 list's voters. Names lie: SDS is not on
                the 2026 ballot for the National Assembly, and 28 of the 29 Otadžbinska
                stranka candidates who sat in that assembly in 2022 sat there for SDS. So
                the match is made from the people first and the printed name second, and
                a party can split across several lists in the proportion its people did.
  baseline      Last general election's ballots, moved through that ancestry.
  swing         Where the vote has gone since, measured as the ratio between the last two
                local elections for the same people, shrunk toward no change by a factor
                the backtest fits rather than one we pick.
  polls         Barely. See data/polls.json for why the weight is what it is.
  simulate      Draw an error for every list, run the real seat law over the result, and do
                it thousands of times. The spread of those runs is the uncertainty, and it
                comes from how wrong this same model was in 2022, not from an assumption.

Nothing here decides who *should* win. It reads the last results and the law.
"""
import math
import random
import re
import unicodedata
from collections import defaultdict

import seatlaw

# ---------------------------------------------------------------- names

def fold(s):
    s = unicodedata.normalize("NFKD", (s or "")).lower()
    # Cyrillic to Latin first, so 'БРАНКО' and 'BRANKO' are one string (CIK prints RS lists
    # in Cyrillic and the rest in Latin, and the same party appears in both).
    cyr = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "dj", "е": "e", "ж": "z",
           "з": "z", "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n",
           "њ": "nj", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "ћ": "c", "у": "u",
           "ф": "f", "х": "h", "ц": "c", "ч": "c", "џ": "dz", "ш": "s"}
    s = "".join(cyr.get(ch, ch) for ch in s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


PARTY_STOP = {"koalicija", "za", "i", "bih", "lista", "zajedno", "u", "na", "stranka",
              "nezavisna", "narodna", "bosnu", "hercegovinu", "bosne", "hercegovine", "rs",
              "dr", "hb", "as", "srpske", "srpska", "neovisni", "nezavisni", "kandidat"}


def party_tokens(name):
    return {w for w in fold(name).split() if w not in PARTY_STOP and not w.isdigit()}


def name_match(a, b):
    """Two printed list names that plainly carry the same party.

    Deliberately strict in one direction only: a short name fully contained in a longer one
    counts ('PDP' inside 'DRAŠKO STANIVUKOVIĆ - POKRET SIGURNA SRPSKA (PSS,PDP,NPSP..)'),
    because that is how BiH coalition lists are printed. Two long names have to share most
    of their words. Everything this misses is caught by the people-flow, which is why the
    two are combined rather than ranked."""
    ta, tb = party_tokens(a), party_tokens(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if small <= big:
        return 1.0
    shared = len(ta & tb)
    if shared >= 2 and shared / len(small) >= 0.6:
        return 0.8
    acr = {t for t in small if 2 <= len(t) <= 4}
    if acr and acr <= big:
        return 0.7
    return 0.0


# ---------------------------------------------------------------- ancestry

def inheritance(unit_lists, prior_votes, prior_by_person, name_weight=0.5):
    """Who inherits whom, in one constituency.

    unit_lists:       {list name: [ {pid, pos, name} ]} — the ballot we are projecting
    prior_votes:      {party label: ballots} — the same constituency, last time
    prior_by_person:  {pid: [(party label, weight)]} — where this person stood last time and
                      how much of that list they carried (their share of its ballots)

    Returns ({party: {list: fraction}}, diagnostics). Fractions for one party sum to 1 when
    it has any successor at all, and to 0 when nobody carries it — those ballots come back
    as `orphans` and are handled separately, because pretending a vanished party's voters
    simply evaporate is as wrong as pretending they all moved to one place."""
    people = defaultdict(lambda: defaultdict(float))
    for lname, cands in unit_lists.items():
        for c in cands:
            for party, w in prior_by_person.get(c.get("pid") or "", ()):
                if party in prior_votes:
                    people[party][lname] += w

    names = defaultdict(lambda: defaultdict(float))
    for party in prior_votes:
        for lname in unit_lists:
            m = name_match(party, lname)
            if m:
                names[party][lname] = m

    out, orphans, notes = {}, {}, []
    for party, votes in prior_votes.items():
        p, n = people.get(party) or {}, names.get(party) or {}
        ps, ns = sum(p.values()), sum(n.values())
        if not ps and not ns:
            orphans[party] = votes
            continue
        mix = defaultdict(float)
        if ps and ns:
            for k, v in n.items():
                mix[k] += name_weight * v / ns
            for k, v in p.items():
                mix[k] += (1 - name_weight) * v / ps
        elif ns:
            for k, v in n.items():
                mix[k] += v / ns
        else:
            for k, v in p.items():
                mix[k] += v / ps
        total = sum(mix.values())
        out[party] = {k: v / total for k, v in mix.items() if v > 0}
        if len(out[party]) > 1 and votes:
            notes.append({"party": party, "votes": votes,
                          "split": {k: round(v, 3) for k, v in sorted(out[party].items(), key=lambda x: -x[1])},
                          "from": "ljudi" if not ns else ("ime" if not ps else "ime i ljudi")})
    return out, {"orphans": orphans, "splits": notes}


def cosine(a, b):
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    num = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    da = math.sqrt(sum(v * v for v in a.values()))
    db = math.sqrt(sum(v * v for v in b.values()))
    return num / (da * db) if da and db else 0.0


def baseline(unit_lists, prior_votes, inherit, orphans, geo_prior=None, geo_list=None,
             retention=0.6):
    """Ballots each 2026 list starts from, before any swing.

    Orphaned ballots — a party that ran last time and has no successor on this ballot — are
    not dropped and not spread evenly. They go to the lists whose voters live in the same
    places, measured by how the municipalities of this constituency voted at the last local
    election, and only `retention` of them come back at all. The rest is people who stayed
    home, which is what usually happens to a party's vote when the party is gone."""
    base = {l: 0.0 for l in unit_lists}
    for party, votes in prior_votes.items():
        for lname, frac in (inherit.get(party) or {}).items():
            base[lname] += votes * frac
    if orphans:
        pool = sum(base.values()) or 1.0
        for party, votes in orphans.items():
            weights = {}
            for lname in unit_lists:
                sim = cosine((geo_prior or {}).get(party) or {}, (geo_list or {}).get(lname) or {})
                weights[lname] = (base[lname] / pool) * (0.25 + sim)
            tot = sum(weights.values())
            if tot <= 0:
                continue
            for lname, w in weights.items():
                base[lname] += votes * retention * w / tot
    return base


# ---------------------------------------------------------------- swing

def trend_factors(list_names, prev_share, next_share, shrink_votes=3000.0):
    """How much each list moved between the two local elections, per list.

    Both sides are already expressed in this ballot's lists (the caller runs the same
    ancestry over the local results), so this is a like-for-like ratio. It is shrunk toward
    1 by the amount of vote behind it: a list whose predecessors polled two hundred votes
    locally does not get to claim it tripled."""
    out = {}
    for l in list_names:
        a, b = prev_share.get(l, 0.0), next_share.get(l, 0.0)
        if a <= 0 or b <= 0:
            out[l] = 1.0
            continue
        mass = min(a, b)
        w = mass / (mass + shrink_votes)
        out[l] = math.exp(w * math.log(b / a))
    return out


def apply_swing(base, trend, lam):
    """base × trend^lam, renormalised to the same total. lam comes from the backtest."""
    adj = {l: v * (trend.get(l, 1.0) ** lam) for l, v in base.items()}
    tot_before, tot_after = sum(base.values()), sum(adj.values())
    if tot_after <= 0:
        return dict(base)
    return {l: v * tot_before / tot_after for l, v in adj.items()}


def blend_polls(shares, poll_shares, weight):
    """Pull a region's list shares toward a poll, in log space, by `weight`.

    Only lists the poll actually names move; everything else is rescaled so the region still
    sums to one. Weight is small on purpose — see data/polls.json."""
    if weight <= 0 or not poll_shares:
        return dict(shares)
    out = {}
    for l, v in shares.items():
        p = poll_shares.get(l)
        if p and v > 0:
            out[l] = math.exp((1 - weight) * math.log(v) + weight * math.log(p))
        else:
            out[l] = v
    tot = sum(out.values()) or 1.0
    return {l: v / tot for l, v in out.items()}


# ---------------------------------------------------------------- personal votes

RECORD_BUCKETS = ["top1", "strong", "ran", "none"]


def fit_personal(rows):
    """How a list's ballots spread over the people on it, learned from past lists.

    rows: [{race, pos, n, pct, record}] — one per past candidacy, `pct` being that
    candidate's share of their own list's ballots, the same number the seat law reads.

    Returns the average log strength by (position band, record) and the spread around it.
    How much a list's percentages add up to is a separate draw — a ballot circles up to
    three names and lists differ enormously in how much their voters use that, so the total
    is taken from the observed distribution rather than assumed."""
    by_cell = defaultdict(list)
    for r in rows:
        if not r.get("pct") or r["pct"] <= 0:
            continue
        by_cell[(pos_band(r["pos"], r["n"]), r["record"])].append(math.log(r["pct"]))
    cells = {}
    for k, vals in by_cell.items():
        m = sum(vals) / len(vals)
        var = sum((v - m) ** 2 for v in vals) / max(len(vals) - 1, 1)
        cells["|".join(map(str, k))] = {"mu": m, "sd": math.sqrt(var), "n": len(vals)}
    return cells


def pos_band(pos, n):
    """Where on the list, in bands that mean the same thing on a list of 3 and one of 30."""
    pos = pos or 99
    if pos == 1:
        return "p1"
    if pos == 2:
        return "p2"
    if pos == 3:
        return "p3"
    if n and pos <= max(4, n * 0.25):
        return "top25"
    if n and pos <= max(6, n * 0.5):
        return "mid"
    return "tail"


def cell_stats(cells, band, record, fallback_sd=0.9):
    c = cells.get(f"{band}|{record}")
    if c and c["n"] >= 12:
        return c["mu"], max(c["sd"], 0.25)
    c = cells.get(f"{band}|ran") or cells.get(f"{band}|none")
    if c:
        return c["mu"], max(c["sd"], fallback_sd)
    return math.log(1.0), fallback_sd


# ---------------------------------------------------------------- simulation

def draw_pcts(cands, rng, cells, total, spread=1.0):
    """Each candidate's share of their own list's ballots, for one run.

    `spread` widens the draw. It exists because the 2022 replay found the missing uncertainty
    here and not in the vote shares: the seat ranges per party were already wide enough, but
    the model was too sure about *which* person on the list takes them. Who crosses twenty
    percent of their own list's ballots — the one thing that can beat the party's order — turns
    out to be less predictable than the position-and-record pattern suggests."""
    n = len(cands)
    ws = []
    for c in cands:
        mu, sd = cell_stats(cells, pos_band(c.get("pos"), n), c.get("record") or "none")
        ws.append(math.exp(mu + rng.gauss(0.0, sd * spread)))
    s = sum(ws) or 1.0
    return [total * w / s for w in ws]
