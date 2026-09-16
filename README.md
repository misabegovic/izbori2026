# Izbori 2026 — informisani glas

Neutralan, podacima vođen vodič kroz listiće za Opće izbore u BiH (4. oktobar 2026). Bez preporuka — samo javni zapis: ko se kandiduje, ko je ikad osvojio mandat, ko drži funkciju, ko je serijski punilac liste, i koliko je promjena realna po jedinicama.

**Izvor:** [gianniravioli.com — Mashinerija](https://gianniravioli.com/mashinerija/) (CIK-verifikovane liste + registar 2006–2026), CC BY 4.0.

## Kako radi

- `fetch.py` — povlači podatke s Mashinerija API-ja u `data/build.json` (pokrenuti ručno kad se osvježava)
- `render.py` — Jinja2 → statički HTML u `dist/`
- `serve.py` — statički server (`$PORT`), za Railway
- `data/party_names.json` — mapiranje šifri koalicija na štampana imena (API ih ne vraća)

## Deploy (Railway)

Nixpacks; build: `pip install -r requirements.txt && python render.py`; start: `python serve.py` (već u `railway.json`). Data je commitana, pa deploy ne zavisi od dostupnosti API-ja.

## Lokalno

```bash
pip install -r requirements.txt
python render.py && python serve.py   # http://localhost:8000
```

## Disclaimer

Zapisi o osobama nastaju spajanjem kandidatura istog imena kroz cikluse — zaključak, ne dokaz. Vidi oznaku „⚠ zapis”.
