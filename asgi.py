"""Vercel ASGI entrypoint; searches finish before the response is returned."""
from fsae_search.web import create_app

app = create_app(synchronous=True)
