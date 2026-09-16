#!/usr/bin/env python3
"""Fetch municipal assembly session data from the eCitizen.ba platform.

38 municipalities run the same product with a public REST API:
  https://ecitizen.ba/{city}/webApi/api/...
Sessions have agendas with per-item vote breakdowns (for/against/abstained/notPresent).
Output: data/ecitizen.json
"""
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

UA = {"User-Agent": "izbori2026-voter-guide/1.1 (github.com/misabegovic/izbori2026)",
      "Content-Type": "application/json"}
SESSIONS_PER_CITY = 5

CITIES = ["bihac", "bosanska_krupa", "bosanski_petrovac", "busovaca", "buzim", "capljina",
          "cazin", "celinac", "citluk", "doboj_istok", "gacko", "gornji_vakuf_uskoplje",
          "gracanica", "gradacac", "ilijas", "istocno_novo_sarajevo", "kalesija", "kljuc",
          "kostajnica", "laktasi", "ljubuski", "mostar", "mrkonjic_grad", "odzak", "orasje",
          "prijedor", "samac", "sanski_most", "siroki_brijeg", "srbac", "tesanj", "teslic",
          "tomislavgrad", "trebinje", "trnovo", "tuzla", "vogosca", "zepce"]


def post(city, path, body):
    req = urllib.request.Request(f"https://ecitizen.ba/{city}/webApi/api/{path}",
                                 data=json.dumps(body).encode(), headers=UA, method="POST")
    return json.load(urllib.request.urlopen(req, timeout=40))


def get(city, path):
    req = urllib.request.Request(f"https://ecitizen.ba/{city}/webApi/api/{path}", headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=40))


def fetch_city(city):
    try:
        sessions = get(city, "SessionsPublic/GetFiveLatest/1")
    except Exception as e:
        return city, {"error": str(e)[:120]}
    out = {"sessions": [], "council": []}
    for s in (sessions or [])[:SESSIONS_PER_CITY]:
        sid = s.get("id")
        row = {"id": sid, "name": s.get("name"), "agendas": []}
        try:
            detail = get(city, f"SessionsPublic/GetByID/{sid}/1")
            row["date"] = (detail or {}).get("startDateTime", "")[:10]
        except Exception:
            pass
        try:
            ag = post(city, "SessionsPublic/GetAgendasBySessionID",
                      {"sessionId": sid, "languageId": 1, "pageNumber": 1, "pageSize": 100})
            for a in (ag or {}).get("results", []):
                row["agendas"].append({
                    "item": a.get("itemNumber"), "name": a.get("name"),
                    "status": a.get("statusName"),
                    "for": a.get("for"), "against": a.get("against"),
                    "abstained": a.get("abstained"), "notPresent": a.get("notPresent")})
        except Exception:
            pass
        out["sessions"].append(row)
    try:
        council = post(city, "CouncilMembersPublic/Search",
                       {"languageId": 1, "pageNumber": 1, "pageSize": 100})
        for m in (council or {}).get("results", []):
            out["council"].append({"name": m.get("name") or m.get("fullName"),
                                   "answered": m.get("numberOfAnsweredQuestions"),
                                   "unanswered": m.get("numberOfNotAnsweredQuestions")})
    except Exception:
        pass
    return city, out


def main():
    result = {"generated": datetime.now(timezone.utc).isoformat(), "cities": {}}
    with ThreadPoolExecutor(10) as ex:
        for city, data in ex.map(fetch_city, CITIES):
            result["cities"][city] = data
            n = len(data.get("sessions", []))
            print(f"{city}: {n} sjednica" + (" GREŠKA " + data["error"] if "error" in data else ""))
    json.dump(result, open("data/ecitizen.json", "w"), ensure_ascii=False, indent=1)
    ok = sum(1 for c in result["cities"].values() if c.get("sessions"))
    print(f"gotovo: {ok}/{len(CITIES)} gradova sa sjednicama")


if __name__ == "__main__":
    main()
