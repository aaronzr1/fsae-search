"""Public UI and runtime proxy to the internally bound search service."""
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

app = FastAPI(title='FSAE Rule Search', docs_url=None, redoc_url=None, openapi_url=None)
FORWARDED_HEADERS = {'accept', 'content-type', 'range', 'if-range', 'if-none-match', 'if-modified-since'}
HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
               'te', 'trailer', 'transfer-encoding', 'upgrade'}


@app.get('/')
def home():
    index = Path(__file__).with_name('index.html')
    if not index.exists():
        # vercel dev uses the source tree; production uses the build's packaged copy.
        index = Path(__file__).resolve().parents[1] / 'fsae_search/index.html'
    return FileResponse(index, media_type='text/html')


async def proxy(request: Request):
    # Read the caller-side binding only at request time; there is no fallback hostname.
    base = os.environ.get('SEARCH_URL')
    if not base:
        raise HTTPException(503, 'Search service binding is unavailable.')
    path = request.scope['raw_path'].decode('ascii').lstrip('/')
    url = httpx.URL(base.rstrip('/') + '/' + path).copy_with(query=request.scope['query_string'])
    headers = {name: value for name, value in request.headers.items() if name in FORWARDED_HEADERS}
    client = httpx.AsyncClient(timeout=300, follow_redirects=False)
    try:
        upstream = await client.send(client.build_request(request.method, url, headers=headers,
                                                          content=await request.body()), stream=True)
    except httpx.HTTPError:
        await client.aclose()
        raise HTTPException(502, 'Search service is unavailable. Please retry.')

    async def close():
        await upstream.aclose()
        await client.aclose()

    response_headers = {name: value for name, value in upstream.headers.items() if name not in HOP_HEADERS}
    return StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code,
                             headers=response_headers, background=BackgroundTask(close))


app.add_api_route('/api/{path:path}', proxy, methods=['GET', 'POST'], include_in_schema=False)
app.add_api_route('/pdf/{path:path}', proxy, methods=['GET', 'HEAD'], include_in_schema=False)
