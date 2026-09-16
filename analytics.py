"""Derived analytics over roll-call votes and party programs. Pure functions; render.py wires them in.

- similarity(): who votes like whom among 2026 candidates who were MPs (per chamber)
- party_line(): how often an MP votes with the majority of their own party's MPs
- party_matrix(): party x party agreement per chamber (for the heatmap)
- activity(): votes cast per year per MP (attendance over time)
- promise_themes(): 2026 promises grouped by everyday topic, across parties
"""
import re
from collections import defaultdict, Counter

CAST = {"za", "protiv", "suzdrzan"}
MIN_SHARED = 80


def _cast_map(votes, pid, div_chamber, chamber):
    return {d: v for d, v, ann in votes.get(pid, []) if not ann and v in CAST and div_chamber.get(d) == chamber}


def similarity(votes, div_chamber, chambers, people):
    """people: {pid: {"name","party","href"}} for 2026 candidates with a record.
    Returns {pid: {chamber: {"same": [...], "opposite": [...], "n": pool size}}}."""
    out = defaultdict(dict)
    for ch in chambers:
        maps = {pid: _cast_map(votes, pid, div_chamber, ch) for pid in people}
        maps = {p: m for p, m in maps.items() if len(m) >= MIN_SHARED}
        pids = list(maps)
        agree = {}
        for i, a in enumerate(pids):
            for b in pids[i + 1:]:
                ma, mb = maps[a], maps[b]
                if len(ma) > len(mb):
                    ma, mb = mb, ma
                shared = same = 0
                for d, v in ma.items():
                    w = mb.get(d)
                    if w:
                        shared += 1
                        if w == v:
                            same += 1
                if shared >= MIN_SHARED:
                    agree[(a, b)] = agree[(b, a)] = (round(100 * same / shared), shared)
        for a in pids:
            rows = [(b, pct, n) for (x, b), (pct, n) in agree.items() if x == a]
            if not rows:
                continue
            rows.sort(key=lambda r: -r[1])
            fmt = lambda r: {"pid": r[0], "name": people[r[0]]["name"], "party": people[r[0]]["party"], "href": people[r[0]]["href"], "pct": r[1], "n": r[2]}
            out[a][ch] = {"same": [fmt(r) for r in rows[:3]], "opposite": [fmt(r) for r in sorted(rows, key=lambda r: r[1])[:3] if r[1] < 60], "pool": len(pids)}
    return out


def party_line(votes, div_chamber, chambers, people):
    """{pid: {chamber: {"pct": agreement with own-party majority, "n": divisions compared, "others": MPs}}}."""
    out = defaultdict(dict)
    for ch in chambers:
        maps = {pid: _cast_map(votes, pid, div_chamber, ch) for pid in people}
        by_party = defaultdict(list)
        for pid, m in maps.items():
            if m:
                by_party[people[pid]["party"]].append(pid)
        for party, pids in by_party.items():
            if len(pids) < 3:
                continue
            for a in pids:
                same = n = 0
                for d, v in maps[a].items():
                    cnt = Counter(maps[b][d] for b in pids if b != a and d in maps[b])
                    if sum(cnt.values()) < 2:
                        continue
                    top, k = cnt.most_common(1)[0]
                    if k * 2 <= sum(cnt.values()):
                        continue
                    n += 1
                    if top == v:
                        same += 1
                if n >= MIN_SHARED:
                    out[a][ch] = {"pct": round(100 * same / n), "n": n, "others": len(pids) - 1}
    return out


def party_matrix(votes, div_chamber, chambers, people, party_label):
    """Per chamber: parties (with >= 2 MPs in the pool) and % of divisions where their majorities agreed."""
    out = {}
    for ch in chambers:
        maps = {pid: _cast_map(votes, pid, div_chamber, ch) for pid in people}
        by_party = defaultdict(list)
        for pid, m in maps.items():
            if len(m) >= MIN_SHARED:
                by_party[people[pid]["party"]].append(pid)
        parties = [p for p, pids in by_party.items() if len(pids) >= 2]
        if len(parties) < 2:
            continue
        pos = {}
        for p in parties:
            pos[p] = {}
            divs = set().union(*(maps[x].keys() for x in by_party[p]))
            for d in divs:
                cnt = Counter(maps[x][d] for x in by_party[p] if d in maps[x])
                top, k = cnt.most_common(1)[0]
                if k * 2 > sum(cnt.values()):
                    pos[p][d] = top
        parties.sort(key=lambda p: -len(by_party[p]))
        m, n = [], []
        for a in parties:
            row, rown = [], []
            for b in parties:
                shared = [d for d in pos[a] if d in pos[b]]
                same = sum(1 for d in shared if pos[a][d] == pos[b][d])
                row.append(round(100 * same / len(shared)) if len(shared) >= MIN_SHARED else None)
                rown.append(len(shared))
            m.append(row); n.append(rown)
        out[ch] = {"parties": [party_label(p) for p in parties], "mps": [len(by_party[p]) for p in parties], "m": m, "n": n}
    return out


def activity(votes, divisions, div_chamber, chambers, people, records):
    """{pid: {chamber: [{"y": year, "voted": n, "total": divisions that year while in the chamber, "pct": %}]}}."""
    div_year = {d: (x.get("heldOn") or x.get("votedAt") or "")[:4] for d, x in divisions.items()}
    per_year = defaultdict(Counter)
    for d, ch in div_chamber.items():
        if div_year.get(d):
            per_year[ch][div_year[d]] += 1
    out = defaultdict(dict)
    for pid in people:
        rec = records.get(pid) or {}
        for ch in chambers:
            chrec = next((c for c in rec.get("chambers", []) if c["chamber"] == ch), None)
            if not chrec:
                continue
            first, last = (chrec.get("firstSeen") or "")[:4], (chrec.get("lastSeen") or "9999")[:4]
            cast = Counter(div_year[d] for d, v, ann in votes.get(pid, []) if not ann and v in CAST and div_chamber.get(d) == ch and div_year.get(d))
            rows = []
            for y in sorted(per_year[ch]):
                if first <= y <= last:
                    tot = per_year[ch][y]
                    rows.append({"y": y, "voted": cast.get(y, 0), "total": tot, "pct": round(100 * cast.get(y, 0) / tot) if tot else 0})
            if rows:
                out[pid][ch] = rows
    return out


THEMES = [
    ("plate", "Plate i penzije", r"plat[aeu]|penzij|minimaln|neto|mirovin"),
    ("posao", "Posao i mladi", r"posl|zapošlj|radn[aio]|mlad|odlaz|iseljav|ostanak|nezaposlen"),
    ("zdravstvo", "Zdravstvo", r"zdrav|bolnic|lijek|ljekar|liječ|specijalist|pregled|pacijent"),
    ("putevi", "Putevi i saobraćaj", r"put|autoput|cest|saobraća|željezn|aerodrom|koridor"),
    ("struja", "Struja, gas, grijanje", r"struj|elektr|energ|gas|plin|grijan|toplan|solar|hidro"),
    ("porezi", "Porezi, takse i cijene", r"porez|pdv|doprinos|cijen|inflacij|akciz|taks|namet|naknad|parafisk"),
    ("korupcija", "Korupcija, sudovi, poštena uprava", r"korupc|sud|tužila|pravosuđ|kriminal|imunitet|nepotiz|porijekl|pravn[aeu] držav|vladavin|čistih ruku|manipulac|depolitiz|odgovornost|privilegij"),
    ("obrazovanje", "Škole i djeca", r"škol|obrazov|vrtić|djec|dječ|student|univerz"),
    ("eu", "EU i NATO", r"\bEU\b|evrops|europs|nato|pregovor|kandidat"),
    ("ustav", "Ustav, narodi, uređenje", r"ustav|izborn|entitet|nadležnost|referendum|jednakopravn|legitimn|preglasav|dejton|hrvat|bošnja|srb|narod|federaliz|građansk|manjin|povratni|institucij|jedinstven"),
    ("poljoprivreda", "Poljoprivreda i sela", r"poljoprivred|selo|sela|ruraln|zemljorad|stočar|podstic"),
    ("socijala", "Socijalna pomoć i stanovi", r"socijal|stan[oa]|stambe|pomoć|invalid|borac|borač|porodilj|dodat|dostojanstv"),
    ("privreda", "Privreda i investicije", r"investicij|ekonom|privred|industrij|rudni|razvoj|fond|preduze|dijaspor"),
    ("sigurnost", "Sigurnost i policija", r"sigurnos|policij|odbran|vojsk|mup"),
    ("okolis", "Voda, otpad, priroda", r"vod[aeu]|otpad|priro|okoliš|zagađ|zrak|šum"),
]


def promise_themes(programs):
    """[{key, label, rows:[{party, promise, href}]}] for every party program with promises."""
    out = {k: [] for k, _, _ in THEMES}
    other = []
    for p in programs:
        for pr in p.get("promises") or []:
            hit = False
            for k, _, rx in THEMES:
                if re.search(rx, pr, re.I):
                    out[k].append({"party": p["name"], "promise": pr, "power": p.get("power")}); hit = True
            if not hit:
                other.append({"party": p["name"], "promise": pr, "power": p.get("power")})
    themes = [{"key": k, "label": lab, "rows": out[k], "parties": len({r["party"] for r in out[k]})} for k, lab, _ in THEMES if out[k]]
    themes.sort(key=lambda t: -t["parties"])
    if other:
        themes.append({"key": "ostalo", "label": "Ostalo", "rows": other, "parties": len({r["party"] for r in other})})
    return themes
