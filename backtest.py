#!/usr/bin/env python3
"""Backtest the seat-chance rule on 2022: same rule (seats the party had last time here,
rank on list by position), measured against who actually won in 2022.
Writes data/chance_calibration.json = observed win rate per bucket; render.py uses it."""
import json, urllib.request, urllib.parse
from collections import defaultdict
BASE = "https://api.gianniravioli.com/mashinerija/v1"; UA = {"User-Agent": "izbori2026-voter-guide/1.0"}
def get(u): return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120))
def paged(p):
    out, off = [], 0
    while True:
        d = get(f"{BASE}{p}{'&' if '?' in p else '?'}limit=200&offset={off}"); out += d["data"]
        if off + 200 >= d["meta"]["total"]: return out
        off += 200
RACES22 = ["32-2", "32-4", "32-6", "32-7"]
# seats 2018 by (level, area, party label)
seats18 = defaultdict(int)
for m in paged("/mandates?year=2018"):
    seats18[((m.get("level") or {}).get("id"), str((m.get("area") or {}).get("id")), ((m.get("party") or {}).get("label") or "").upper())] += 1
m18 = defaultdict(int)
for (lvl, area, _), n in seats18.items(): m18[(lvl, area)] += n
import unicodedata, re
def key(s):
    s = unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split()[:2])
seats18k = defaultdict(int)
for (lvl, area, p), n in seats18.items(): seats18k[(lvl, area, key(p))] += n
buckets = defaultdict(lambda: [0, 0])  # bucket -> [n, won]
for r in RACES22:
    rows = paged(f"/races/{r}/candidacies")
    lists = defaultdict(list)
    for c in rows:
        lvl = (c.get("level") or {}).get("id"); area = str((c.get("area") or {}).get("id"))
        party = ((c.get("party") or {}).get("label") or (c.get("party") or {}).get("id") or "")
        lists[(lvl, area, party)].append(c)
    # vote share 2018 unknown here; use seats only
    for (lvl, area, party), cs in lists.items():
        s = seats18k.get((lvl, area, key(party)), 0)
        cs.sort(key=lambda c: c.get("position") or 99)
        for rank, c in enumerate(cs, 1):
            if s <= 0: b = "no_seats_pos1" if rank == 1 else "no_seats_rest"
            elif rank <= s: b = "within"
            elif rank == s + 1: b = "plus1"
            elif rank == s + 2: b = "plus2"
            else: b = "beyond"
            buckets[b][0] += 1; buckets[b][1] += 1 if c.get("elected") else 0
    print(r, {k: (v[0], v[1]) for k, v in buckets.items()})
cal = {k: {"n": v[0], "won": v[1], "pct": round(100 * v[1] / v[0]) if v[0] else None} for k, v in buckets.items()}
json.dump(cal, open("data/chance_calibration.json", "w"), indent=1)
print(json.dumps(cal, indent=1))
