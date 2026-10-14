# FSAE rule search

Search the 2027 V1 Formula SAE rulebook with local keyword search or Jev semantic search.

## Start reading

- `main.py` → `fsae_search/__main__.py`: entry point and CLI commands.
- `fsae_search/web.py` and `index.html`: API and browser UI; `service.py` runs background searches.
- `fsae_search/extract.py` → `store.py`: PDF extraction, indexes, and local search.
- `fsae_search/retrieval.py`: search strategies and caching; `sections.py`, `jev.py`, and `bundles.py` handle semantic scoring.
- `frontend/main.py` → `asgi.py`: Vercel public proxy and internal search backend.
- `analysis/` and `fsae_search/experiments.py`: extraction notes and retrieval experiments.

## Run locally

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m fsae_search build
.venv/bin/python main.py
```

Open http://127.0.0.1:8000. For semantic search, set `JEV_KEY` in `.env`
using `.env.example` as a guide. Local keyword search works without a key.

## Vercel

After local setup above, use uv 0.9.25+ and run `bunx vercel@latest dev --local` to check both services together.
`app` serves public traffic and calls internal `search` through the injected
`SEARCH_URL` binding; do not set it yourself. Set `JEV_KEY` in Vercel for semantic
search. Indexes are built during deployment; runtime caches are temporary.
