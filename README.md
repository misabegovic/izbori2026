# Izbori 2026 — jednostavno

Vodič za birače koji ne prate politiku. Opći izbori u BiH, 4. oktobar 2026. Bez preporuka: javni zapis (ko se kandiduje, ko je već bio izabran, ko je mijenjao stranke, kako su glasali kao poslanici) pored obećanja stranaka za 2026, s izvorom uz svaku tvrdnju.

**Izvori:** [gianniravioli.com — Mashinerija](https://gianniravioli.com/mashinerija/) (CIK liste 2006–2026, mandati, poimenična glasanja PSBiH i NSRS, biografije, prijave imovine; CC BY 4.0), [Wikidata](https://www.wikidata.org/) (funkcije koje se ne biraju na listiću; CC0), eCitizen.ba (sjednice vijeća), mediji i stranačke stranice (obećanja; URL uz svako).

## Stranice

- `index.html` — gdje glasaš (pretraga općine), **pretraga kandidata po imenu**, ulaz za prvi put, tri činjenice
- `opcina-<slug>.html` — tvoji listići kao kartice (3–4), šta koji bira
- `listic-<race>-<area>.html` — po listi: 4 brojke (ljudi, već izabrani, mijenjali stranke, prvi put), rezultat 2022 ovdje, prvo obećanje, kako su njihovi poslanici glasali, ljudi na listi sa značkama
- `kandidat-<pid>.html` — **za svakog od 7.028 ljudi na listama**, ne samo za pobjednike: priča u jednoj rečenici, šansa za mjesto, koliko je glasova dobijao kroz izbore i koje je bio po glasovima na svojoj listi, šta je radio (imenovanja, tijela u kojima je sjedio i koliko ona troše, dnevni red tih sjednica, stranke kroz vrijeme), glasanje kao poslanik ako ga ima (prisustvo, % za, po godinama, ključne odluke), s kim glasa isto / suprotno, sve kandidature, biografija/imovina. Ko nema zapisa, na stranici to i piše.
- `stranka-<key>.html` — obećanja 2026 s izvorima i pouzdanošću, zapis glasanja po ključnim odlukama, budžetsko finansiranje 2024, poslanici koji se ponovo kandiduju
- `stranke.html` — sve stranke + matrica „ko glasa kao ko” (slaganje većina stranaka po domu)
- `obecanja.html` — obećanja 2026 svih stranaka po temi (plate, zdravstvo, putevi…), filter
- `metoda.html` — ko radi sajt, odakle su brojke, kako su birane ključne odluke, kako se računa šansa, šta ne znamo
- `predsjednistvo.html`, `desavanja.html`, `kako-glasati.html`, `opcine.html`
- ЋИР/LAT prekidač u zaglavlju (transliteracija u pregledniku)

## Kako radi

```
fetch.py          Mashinerija → data/units, people_cache, municipalities (kandidature, mandati, rezultati)
fetch_history.py  Mashinerija → data/timelines (svih 7.028), merges, maybe_same, person_stats,
                  pubids, appointed, unit_spend, seat_bar, list_strength
data/manual_merges.json   ručno provjereni identiteti (obrazloženje + izvor po redu) i
                  odbačeni prijedlozi; čita ga fetch_history.py
fetch_wikidata.py Wikidata → data/offices (funkcije koje CIK ne objavljuje: ministri, delegati,
                  entitetski premijeri, Predsjedništvo 2010–2018)
fetch_ecitizen.py eCitizen → data/ecitizen.json
fetch_votes.py    Mashinerija → data/divisions, outcomes, records, votes, profiles, parties, speeches
data/key_decisions.json   ručno odabrane ključne odluke saziva (25 PSBiH + 24 NSRS) s prostim opisom
data/programs_*.json      obećanja stranaka 2026 (web istraživanje, izvor + pouzdanost po stranci)
data/context.json         kandidati za Predsjedništvo/RS, teme, događaji 2022–26, kako se glasa
data/party_aliases.json   CIK ime liste → stranka iz programs_*.json
render.py         Jinja2 → dist/ (≈1.400 statičkih stranica)
serve.py          statički server za Railway
review.py         persona-review preko Claude API-ja (persone u phone-brain/personas/users)
backtest.py       kalibracija „šanse za mandat” na rezultatu 2022 → data/chance_calibration.json
analytics.py      izvedena analitika iz glasanja: sličnost poslanika, linija stranke, matrica stranaka, aktivnost po godinama; obećanja po temi
static/viz.js     D3 grafovi (trake, složene trake, karijera, gauge šanse, lični glasovi po izborima,
                  swarm svih kandidata s fokusom na jednog, stupci po godinama, matrica)
static/style.css  zajednički stil; ranije je bio uvučen u svaku stranicu
static/app.js     ЋИР/LAT, veličina slova, filteri; isto tako izdvojen
```

Redoslijed kad se osvježava sve: `fetch.py` → `fetch_history.py` (pravi `merges.json`, o koji se oslanja ostalo) → `fetch_wikidata.py` → `fetch_votes.py` → `backtest.py` → `render.py`.

Podaci su commitani, deploy ne zavisi od API-ja.

Swarm graf svih kandidata na jednom listiću stoji u `kandidati-<race>-<area>.json` i učitava se tek kad čitalac otvori graf. Isti blok uvučen u svih 7.000 profila je pravio `dist/` od 661 MB.

## Deploy

**muhamed.at/politika/analiza-izbora** — glavni javni URL. Sajt [muhamed.github.io](https://github.com/misabegovic/muhamed.github.io) u svom Pages buildu klonira ovaj repo s `main`, pokrene `render.py` i montira `dist/` pod `/politika/analiza-izbora/` (skripta `.github/scripts/build-analiza-izbora.sh` tamo). Svi linkovi koje `render.py` pravi su relativni, pa `dist/` radi pod bilo kojim putem bez prepisivanja.

Push na `main` ovdje pokrene `.github/workflows/notify-site.yml`, koji preko `repository_dispatch` javi sajtu da se rebuilda. Za to treba secret `SITE_DISPATCH_TOKEN` (PAT s `contents: write` na `misabegovic/muhamed.github.io`); bez njega sajt pokupi izmjenu na svom dnevnom buildu.

**Railway** — Nixpacks; build `pip install -r requirements.txt && python render.py`; start `python serve.py` (u `railway.json`).

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

## Šansa za mjesto

Dva ulaza, oba poznata unaprijed: **gdje je čovjek na listi** u odnosu na mandate koje je stranka dobila 2022 na istom papiru, i **šta je taj čovjek već napravio na izborima** (je li ikad bio prvi po ličnim glasovima na svojoj listi, je li već biran, ili je prvi put na listiću). `backtest.py` izmjeri stvarni udio izabranih za svaku kombinaciju na rezultatu 2022.

Uz procenat na svakom profilu stoji i **šta je mandat ovdje stvarno koštao** prošli put (`data/seat_bar.json`): koliko je ličnih glasova imao najslabije prošao izabrani, koliko prosječan, i koliko je ljudi imalo više glasova od najslabijeg izabranog a ipak ostalo vani. U Tuzlanskom kantonu 2022 takvih je bilo 142 od 588 kandidata. Mandat prvo osvaja lista; lični glasovi odlučuju tek ko ga unutar liste dobije.

Drugi ulaz je dodan jer bez njega brojka ne razlikuje ljude koje birači stvarno zaokružuju. U 2022 je od onih koji su ranije bili prvi po glasovima prošlo 10% čak i duboko na listi bez ijednog mandata, naspram 1% onih koji nikad nisu bili na listiću. Razmak postoji u svakoj grupi po mjestu na listi i u sve četiri trke posebno. Rijetke kombinacije se povlače prema prosjeku te grupe (`SHRINK = 25`), da ćelija od dvadesetak ljudi ne proizvede samouvjerenu brojku.

## Ide li glas nekud (druga metrika)

Šansa za mjesto kaže može li ovaj čovjek ući. Ne kaže da li glas uopšte išta nosi, a to je pitanje koje birač zapravo postavlja. Mandat prvo osvaja lista: ispod 3% na području lista ne dobija ništa, pa ni najpopularniji čovjek na njoj ne ide nikuda.

Zato uz svaki listić i profil stoji koliko je glasova 2022 na tom istom području otišlo listama bez ijednog mandata (`data/list_strength.json`). U Tuzlanskom kantonu 14,8%, u najgoroj jedinici 45,9%.

Udio se računa po **glasačima liste**, ne po zbiru ličnih glasova: jedan listić zaokružuje do tri imena, a liste se razlikuju koliko to koriste (2022: od 0,45 do 6,24 imena po listiću). Broj glasača liste vadi se iz `percentage` koji API daje uz svakog kandidata; nazivnik je isti za sve na listi u svih 496 provjerenih lista, pa je broj listića tačan, a ne procijenjen.

## Ko je isti čovjek

Nijedan izvor u BiH ne objavljuje identifikator osobe, a ime se kroz godine piše različito: 2006. je na listiću pisalo `IZETBEGOVIĆ BAKIR`, od 2016. `BAKIR IZETBEGOVIĆ`. Zato Mashinerija spaja kandidature samo kad je čovjek ostao u istoj izbornoj jedinici, a sve ostalo objavljuje kao **28.034 otvorena mosta** s razlozima uz svaki i nikad ih ne primjenjuje.

Bez njih Bakir Izetbegović na ovom sajtu ima dvije kandidature i nula mandata. `fetch_history.py` primjenjuje **9.640** mosta, po pravilima koja stoje na `metoda.html`:

| tier | pravilo | primijenjeno |
|---|---|---|
| 0 | ime se u cijeloj bazi od 173.752 kandidature javlja samo u ta dva zapisa | 9.172 |
| 1 | ista stranka na obje kandidature, ime rijetko (≤3 zapisa) | 400 |
| 2 | jedno područje sadrži drugo, zapisi dijele stranku, ime rijetko | 57 |
| ručno | `data/manual_merges.json`, uz obrazloženje i izvor po redu | 11 |

Ime se prvo prevede u jedno pismo. CIK kandidate u RS štampa ćirilicom a ostale latinicom, i ista osoba kroz godine zna biti u oba — bez prevođenja „БРАНКО БЛАНУША” i „BLANUŠA BRANKO” nisu isto ime, pa ni test rijetkosti ne valja (105 imena je izgledalo jedinstveno a nije). Takvih spojeva preko dva pisma ima 473; bez njih bi svaki kandidat iz RS bio odsječen od vlastite historije, jer su listići za 2026. tamo ćirilični.

Iznad svega jedno tvrdo pravilo: **niko ne stoji na dva listića istih izbora** (osim redovne i kompenzacijske liste iste trke), i ono nadjačava i ručni unos. Ono je jedino što razdvaja Denisa Bećirovića člana Predsjedništva od kandidata istog imena u Tuzli — dijele ime, stranku iz 2006. i regiju, a 2026. su na različitim listićima.

**Ručni spojevi** su za ljude koje nijedan signal ne može dohvatiti, a to su baš oni koje birač traži. Semir Efendić je tri puta biran za načelnika Novog Grada Sarajevo i sjedio u Skupštini KS, pa 2026. izlazi za Predsjedništvo pod drugom strankom — druga stranka, drugi nivo, drugo područje, ime nije rijetko. Svaki red u `data/manual_merges.json` nosi obrazloženje i izvor, koji se otvaraju s profila; `not_same` radi obrnuto i skida prijedlog koji smo pogledali i odbacili, da tuđi zapis ne visi uz ime.

Rezultat: ljudi s ranijim kandidaturama idu s **2.882 na 4.346**, a **2.110** ih je historiju dobilo spajanjem. Mostovi koje nismo prihvatili nisu obrisani — stoje na profilu pod „Možda je ista osoba” (2.903 reda za 972 osobe) i **ne ulaze ni u jednu brojku**. `backtest.py` mjeri kalibraciju na istom spajanju, da procenat na stranici i tabela iza njega ne govore o različitim ljudima.

## Funkcije koje se ne biraju na listiću

Izborni zapis zna samo ono što je na listiću. Ministra, delegata u domu naroda, entitetskog premijera ni predsjedavajućeg Predsjedništva niko ne bira direktno. **Opći izbori 2010. i 2014. ne postoje ni u jednom čitljivom izvoru**: arhiva iz 2010. ne može se pročitati jer joj ASP.NET ViewState pada na provjeri potpisa protiv CIK-ovog vlastitog balansera, a 2014. ima tačno jedan skup rezultata koji se zove `FinalniTest` i čija baza nikad nije objavljena (provjereno i u `/v1/coverage` Mashinerije i direktno na `izbori.ba/api_2018`).

Praktično: Bakir Izetbegović je bio u Predsjedništvu 2010–2018 i izborni zapis o tome ne zna ništa. `fetch_wikidata.py` to donosi s Wikidate (CC0) za **41 osobu** s listića 2026, u zaseban blok s datumima i linkom na stavku. Nije CIK i **ne ulazi ni u jednu brojku**. Osoba se veže uz stavku preko Mashinerijinog zapisa, po imenu kad to ime na listićima 2026 pripada tačno jednom čovjeku, ili po funkciji koju drži sada.

Spajanje je otvorilo i biografije, portrete i prijave imovine koje vise o starijem zapisu iste osobe: profila s podacima ima **2.360** umjesto 1.151.

## Ograničenja

- Karijere osoba su spojene po pravilima iznad. Nijedno nije dokaz: kod ⚠ i kod reda označenog „spojeno” moguća je greška.
- Opći izbori 2010. i 2014. nedostaju kod svih, ne samo kod Bakira Izetbegovića. To se ne zatvara skrejperom nego zahtjevom za pristup informacijama CIK-u.
- Poimenična glasanja postoje samo za PSBiH i NSRS. Parlament FBiH i kantoni ih ne objavljuju.
- eCitizen objavljuje dnevni red i zbir „za/protiv/uzdržan” po tački, ali nijedno ime: 38 gradova, 142 sjednice, nula imenovanih vijećnika. Zato se rad u vijeću prikazuje kao rad tijela, nikad kao lični glas.
- Listu iz 2026 spajamo s listom iz 2022 po imenu, a imena koalicija se mijenjaju. Za 2.634 od 7.779 kandidata ne nađemo nijedan glas njihove liste iz 2022, pa ih računica tretira kao novu listu.
- Obećanja su tvrdnje stranaka iz medija; `confidence` po stranci kaže koliko je izvor pouzdan.
