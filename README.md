# Izbori 2026 — jednostavno

Vodič za birače koji ne prate politiku. Opći izbori u BiH, 4. oktobar 2026. Bez preporuka: javni zapis (ko se kandiduje, ko je već bio izabran, ko je mijenjao stranke, kako su glasali kao poslanici) pored obećanja stranaka za 2026, s izvorom uz svaku tvrdnju.

**Izvori:** [gianniravioli.com — Mashinerija](https://gianniravioli.com/mashinerija/) (CIK liste 2006–2026, mandati, poimenična glasanja PSBiH i NSRS, biografije, prijave imovine; CC BY 4.0), eCitizen.ba (sjednice vijeća), mediji i stranačke stranice (obećanja; URL uz svako).

## Stranice

- `index.html` — gdje glasaš (pretraga općine), ulaz za prvi put, tri činjenice
- `opcina-<slug>.html` — tvoji listići kao kartice (3–4), šta koji bira
- `listic-<race>-<area>.html` — po listi: 4 brojke (ljudi, već izabrani, mijenjali stranke, prvi put), rezultat 2022 ovdje, prvo obećanje, kako su njihovi poslanici glasali, ljudi na listi sa značkama
- `kandidat-<pid>.html` — priča u jednoj rečenici, glasanje kao poslanik (prisustvo, % za, ključne odluke), sve kandidature, biografija/imovina iz javnih izvora
- `stranka-<key>.html` — obećanja 2026 s izvorima i pouzdanošću, zapis glasanja po ključnim odlukama, budžetsko finansiranje 2024, poslanici koji se ponovo kandiduju
- `predsjednistvo.html`, `desavanja.html`, `kako-glasati.html`, `stranke.html`, `opcine.html`
- ЋИР/LAT prekidač u zaglavlju (transliteracija u pregledniku)

## Kako radi

```
fetch.py          Mashinerija → data/units, people_cache, timelines, municipalities (kandidature, mandati, historija)
fetch_ecitizen.py eCitizen → data/ecitizen.json
fetch_votes.py    Mashinerija → data/divisions, outcomes, records, votes, profiles, parties, speeches
data/key_decisions.json   ručno odabrane ključne odluke saziva (25 PSBiH + 24 NSRS) s prostim opisom
data/programs_*.json      obećanja stranaka 2026 (web istraživanje, izvor + pouzdanost po stranci)
data/context.json         kandidati za Predsjedništvo/RS, teme, događaji 2022–26, kako se glasa
data/party_aliases.json   CIK ime liste → stranka iz programs_*.json
render.py         Jinja2 → dist/ (≈1.400 statičkih stranica)
serve.py          statički server za Railway
review.py         persona-review preko Claude API-ja (persone u phone-brain/personas/users)
```

Podaci su commitani, deploy ne zavisi od API-ja.

## Deploy (Railway)

Nixpacks; build `pip install -r requirements.txt && python render.py`; start `python serve.py` (u `railway.json`).

## Lokalno

```bash
pip install -r requirements.txt
python render.py && python serve.py   # http://localhost:8000
```

## Persona review

Deset persona neobrazovanih, manipulaciji podložnih birača živi u `phone-brain/personas/users/izbori-*.md`, rubrika u `izbori-README.md`. Nalazi idu u `phone-brain/wiki/izbori2026/feedback/`.

```bash
pip install anthropic && export ANTHROPIC_API_KEY=...
python review.py --round r2            # svih 10; --only 01,05 za pojedine
```

## Ograničenja

- Karijere osoba su spojene po imenu kroz izbore (Mashinerija pravila); kod ⚠ moguća je greška.
- Poimenična glasanja postoje samo za PSBiH i NSRS. Parlament FBiH i kantoni ih ne objavljuju.
- Obećanja su tvrdnje stranaka iz medija; `confidence` po stranci kaže koliko je izvor pouzdan.
