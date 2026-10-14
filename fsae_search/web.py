"""Local browser UI and JSON API; the Jev key stays in the backend."""
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .jev import configuration, plan, search
from .service import SearchService
from .store import ROOT, Store


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    vehicle_type: Literal['all', 'EV', 'IC'] = 'all'
    top_k: int = Field(default=50, ge=1, le=2000)
    threshold: float = Field(default=0.5, ge=0, le=1)
    strategy: Literal['sections','routed','rules']='sections'
    use_cache: bool=True


def create_app(store=None, *, synchronous=False):
    store = store or Store()
    service = None if synchronous else SearchService(store)

    @asynccontextmanager
    async def lifespan(app):
        yield
        if service is not None:
            service.close()

    app = FastAPI(title='FSAE Rule Search', lifespan=lifespan)
    app.state.service = service

    @app.get('/')
    def home():
        return FileResponse(ROOT / 'fsae_search/index.html', media_type='text/html')

    @app.get('/api/status')
    def status():
        key, settings = configuration()
        return dict(document=store.document, rules=len(store.rules), search_units=len(store.units),
                    visual_rules=sum(r['visuals']['has_visual_content'] for r in store.rules.values()),
                    jev_configured=bool(key), model=settings.model,
                    concurrency=settings.concurrency, batch_bytes=settings.batch_bytes,default_strategy='sections',
                    active_search_id=service.active_id if service is not None else None)

    @app.post('/api/local-search')
    def local_search(request: SearchRequest):
        if not request.query.strip():
            raise HTTPException(422, 'Enter a search query.')
        return store.local_search(request.query, request.top_k)

    @app.post('/api/plan')
    def search_plan(request: SearchRequest):
        _, settings = configuration()
        if request.strategy!='rules':
            from .retrieval import plan_sections
            return plan_sections(store,request.query,settings,request.vehicle_type,request.strategy)
        return plan(request.query, store.units, settings, request.vehicle_type)

    @app.post('/api/searches', status_code=202)
    def start(request: SearchRequest):
        if not request.query.strip():
            raise HTTPException(422, 'Enter a search query.')
        key, _ = configuration()
        if not key:
            raise HTTPException(503, 'Set JEV_KEY in the project .env to enable semantic search.')
        if synchronous:
            # Finish within this invocation; polling another instance cannot recover local jobs.
            try:
                output = search(store, request.query.strip(), vehicle_type=request.vehicle_type,
                                top_k=request.top_k, threshold=request.threshold,
                                strategy=request.strategy, use_cache=request.use_cache)
            except Exception:
                raise HTTPException(502, 'Search failed. Check Jev configuration and connectivity, then retry.')
            return dict(status='done', output=output)
        identifier = service.start(request.query.strip(), request.vehicle_type, request.top_k, request.threshold,
                                   request.strategy,request.use_cache)
        if identifier is None:
            raise HTTPException(409, 'A semantic search is already running. Wait for it to finish.')
        return dict(id=identifier)

    @app.get('/api/searches/{identifier}')
    def get_search(identifier: str):
        if synchronous:
            raise HTTPException(404, 'Search results are returned by POST /api/searches.')
        try:
            return service.get(identifier)
        except KeyError:
            raise HTTPException(404, 'Search expired. Run it again.')

    @app.get('/api/rules/{rule_id}')
    def get_rule(rule_id: str):
        try:
            return dict(store.entry(rule_id.upper()), related=store.related([rule_id.upper()]))
        except KeyError:
            raise HTTPException(404, 'Unknown rule or table.')

    @app.api_route('/pdf/{sha256}', methods=['GET', 'HEAD'])
    def pdf(sha256: str):
        if sha256 != store.document['sha256']:
            raise HTTPException(404, 'Unknown document version.')
        return FileResponse(store.pdf, media_type='application/pdf')

    return app
