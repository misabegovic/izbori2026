#!/usr/bin/env python3
"""Persona review of the rendered site with the Claude API.

Each of the 10 voter personas (phone-brain/personas/users/izbori-*.md) walks
through a fixed path of pages (index → općina → listić → kandidat → stranka →
kako-glasati) and scores it on the 5-point rubric from izbori-README.md.

Usage:
  pip install anthropic
  export ANTHROPIC_API_KEY=...          # or `ant auth login`
  python review.py [--personas DIR] [--out DIR] [--only 01,03] [--model claude-opus-5]

Output: <out>/review-<round>-<persona>.md (same shape as the manual reviews in
phone-brain/wiki/izbori2026/feedback/) and <out>/summary.json.
"""
import argparse
import datetime
import glob
import html as htmllib
import json
import os
import re

import anthropic

MODEL = "claude-opus-5"
MAX_CHARS = 14000  # per page, after stripping HTML

SCHEMA = {
    "type": "object",
    "properties": {
        "saw": {"type": "string", "description": "2-4 rečenice u prvom licu persone: šta sam vidio/la"},
        "stuck": {"type": "array", "items": {"type": "string"}, "description": "konkretna mjesta gdje sam zapeo/la, s doslovnim riječima sa stranice"},
        "learned": {"type": "string", "description": "jedna nova činjenica koju bih rekao/la komšiji, ili 'ništa'"},
        "scores": {
            "type": "object",
            "properties": {k: {"type": "integer", "minimum": 0, "maximum": 3} for k in ("ulaz", "jezik", "cinjenica", "otpornost", "povjerenje")},
            "required": ["ulaz", "jezik", "cinjenica", "otpornost", "povjerenje"],
            "additionalProperties": False,
        },
        "suggestions": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 5,
                        "description": "konkretni prijedlozi: šta promijeniti, na kojoj stranici/sekciji"},
        "manipulation_check": {"type": "string", "description": "da li bi nakon ovih stranica prepoznao/la bar jednu manipulaciju kojoj je inače podložan/na; koju"},
    },
    "required": ["saw", "stuck", "learned", "scores", "suggestions", "manipulation_check"],
    "additionalProperties": False,
}

# persona slug -> pages (općina page decides the rest)
PATHS = {
    "izbori-01-senad-tuzla": ("opcina-ba.fbih.tk.tuzla.html", "oi2026-4"),
    "izbori-02-jasmina-zenica": ("opcina-ba.fbih.zdk.zenica.html", "oi2026-7"),
    "izbori-03-milorad-prijedor": ("opcina-ba.rs.prijedor.html", "oi2026-6"),
    "izbori-04-anto-livno": ("opcina-ba.fbih.k10.livno.html", "oi2026-7"),
    "izbori-05-emina-bihac": ("opcina-ba.fbih.usk.bihac.html", "oi2026-2"),
    "izbori-06-dragan-bijeljina": ("opcina-ba.rs.bijeljina.html", "oi2026-6"),
    "izbori-07-fatima-mostar": ("opcina-ba.fbih.hnk.mostar.html", "oi2026-4"),
    "izbori-08-nermin-sarajevo": ("opcina-ba.fbih.ks.ilidza.html", "oi2026-2"),
    "izbori-09-ljubica-trebinje": ("opcina-ba.rs.trebinje.html", "oi2026-6"),
    "izbori-10-haris-gradacac": ("opcina-ba.fbih.tk.gracanica.html", "oi2026-7"),
}


def page_text(path):
    s = open(path, encoding="utf-8").read()
    s = re.sub(r"<style.*?</style>|<script.*?</script>", "", s, flags=re.S)
    s = re.sub(r"<(details|summary|h[1-3]|p|div|li|tr)[^>]*>", "\n", s)
    s = re.sub(r"<a [^>]*href=\"([^\"]+)\"[^>]*>", r" [link:\1] ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmllib.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s).strip()
    return s[:MAX_CHARS] + ("\n[… stranica skraćena …]" if len(s) > MAX_CHARS else "")


def first_link(text, prefix):
    m = re.search(r"\[link:(" + re.escape(prefix) + r"[^\]]+)\]", text)
    return m.group(1) if m else None


def build_path(dist, opcina, race):
    pages = ["index.html", opcina]
    op = page_text(os.path.join(dist, opcina))
    listic = first_link(op, f"listic-{race}-") or first_link(op, "listic-")
    if listic:
        pages.append(listic)
        lt = page_text(os.path.join(dist, listic))
        # a candidate with a voting record, else any candidate; and the first party with a page
        kand = None
        for m in re.finditer(r"\[link:(kandidat-[^\]]+)\]", lt):
            k = m.group(1)
            if "ima zapis glasanja" in lt[m.end():m.end() + 200]:
                kand = k
                break
            kand = kand or k
        if kand:
            pages.append(kand)
        st = first_link(lt, "stranka-")
        if st:
            pages.append(st)
    pages.append("kako-glasati.html")
    return [p for p in pages if os.path.exists(os.path.join(dist, p))]


def review_one(client, model, persona_md, rubric_md, pages, dist):
    bundle = "\n\n".join(f"===== STRANICA: {p} =====\n{page_text(os.path.join(dist, p))}" for p in pages)
    system = (
        "Ti si strogi UX evaluator koji doslovno glumi jednu personu birača u BiH. "
        "Čitaš stranice onako kako bi ih ta osoba vidjela na telefonu (širina 390px, font 19px). "
        "Ne izmišljaj sadržaj kojeg nema na stranicama. Navodi doslovne riječi sa stranice koje persona ne razumije. "
        "Odgovaraj na bosanskom/srpskom, u prvom licu persone gdje se traži."
    )
    user = (
        f"RUBRIKA I PRAVILA:\n{rubric_md}\n\nPERSONA:\n{persona_md}\n\n"
        f"Prođi kroz stranice ovim redom i ocijeni po rubrici (0-3 svako):\n{bundle}"
    )
    with client.messages.stream(
        model=model,
        max_tokens=16000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    ) as stream:
        resp = stream.get_final_message()
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"refusal: {resp.stop_details}")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text), resp.usage


def to_markdown(slug, r, pages, rnd):
    sc = r["scores"]
    total = sum(sc.values())
    lines = [
        "---", "kind: feedback", "status: active", "confidence: medium", f"persona: {slug}", f"round: {rnd}",
        "source: review.py (Claude API)", f"date: {datetime.date.today().isoformat()}", "---", "",
        f"# Review {rnd}: {slug}", "",
        "Stranice: " + ", ".join(f"`{p}`" for p in pages), "",
        "## Šta sam vidio/la", "", r["saw"], "",
        "## Gdje sam zapeo/la", "", *[f"- {s}" for s in r["stuck"]], "",
        "## Šta sam zaključio/la", "", r["learned"], "",
        "## Manipulacija", "", r["manipulation_check"], "",
        "## Ocjene", "",
        f"| Ulaz | Jezik | Jedna činjenica | Otpornost | Povjerenje | Ukupno |", "|---|---|---|---|---|---|",
        f"| {sc['ulaz']} | {sc['jezik']} | {sc['cinjenica']} | {sc['otpornost']} | {sc['povjerenje']} | **{total}/15** |", "",
        "## Prijedlozi", "", *[f"{i + 1}. {s}" for i, s in enumerate(r["suggestions"])], "",
    ]
    return "\n".join(lines), total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--personas", default="../phone-brain/personas/users")
    ap.add_argument("--dist", default="dist")
    ap.add_argument("--out", default="../phone-brain/wiki/izbori2026/feedback")
    ap.add_argument("--round", default="r2")
    ap.add_argument("--only", default="")
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args()
    client = anthropic.Anthropic()
    rubric = open(os.path.join(a.personas, "izbori-README.md"), encoding="utf-8").read()
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    os.makedirs(a.out, exist_ok=True)
    summary = {}
    for f in sorted(glob.glob(os.path.join(a.personas, "izbori-[0-9]*.md"))):
        slug = os.path.basename(f)[:-3]
        if only and not any(slug.startswith(f"izbori-{o.zfill(2)}") for o in only):
            continue
        opcina, race = PATHS[slug]
        pages = build_path(a.dist, opcina, race)
        print(f"{slug}: {len(pages)} stranica …", flush=True)
        try:
            r, usage = review_one(client, a.model, open(f, encoding="utf-8").read(), rubric, pages, a.dist)
        except anthropic.RateLimitError as e:
            print("  rate limit:", e.message); continue
        except anthropic.APIStatusError as e:
            print("  api error:", e.status_code, e.message); continue
        except anthropic.APIConnectionError as e:
            print("  network:", e); continue
        md, total = to_markdown(slug, r, pages, a.round)
        open(os.path.join(a.out, f"review-{a.round}-{slug}.md"), "w", encoding="utf-8").write(md)
        summary[slug] = {"total": total, "scores": r["scores"], "tokens": {"in": usage.input_tokens, "out": usage.output_tokens}}
        print(f"  {total}/15  (tokens in {usage.input_tokens}, out {usage.output_tokens})")
    json.dump(summary, open(os.path.join(a.out, f"summary-{a.round}.json"), "w"), ensure_ascii=False, indent=1)
    if summary:
        ok = sum(1 for v in summary.values() if v["total"] >= 11)
        worst = min(v["total"] for v in summary.values())
        print(f"\nprolaz: {ok}/{len(summary)} persona ≥11, najgora {worst}/15 → {'PROLAZ' if ok >= 8 and worst >= 8 else 'PAD'}")


if __name__ == "__main__":
    main()
