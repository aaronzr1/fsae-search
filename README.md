# FSAE rule search

Search the 2027 V1 Formula SAE rulebook with local keyword search or Jev semantic search.

## Start reading

- `main.py` → `fsae_search/__main__.py`: entry point and CLI commands.
- `fsae_search/web.py` and `index.html`: API and browser UI; `service.py` runs background searches.
- `fsae_search/extract.py` → `store.py`: PDF extraction, indexes, and local search.
- `fsae_search/retrieval.py`: search strategies and caching; `sections.py`, `jev.py`, and `bundles.py` handle semantic scoring.
- `analysis/` and `fsae_search/experiments.py`: extraction notes and retrieval experiments.

## Run locally

```sh
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m fsae_search build
.venv/bin/python main.py
```

Open http://127.0.0.1:8000. For semantic search, set `JEV_KEY` in `.env`
using `.env.example` as a guide. Local keyword search works without a key.
