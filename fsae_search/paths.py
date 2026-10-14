"""Writable cache location for local runs and Vercel functions."""
import os
from pathlib import Path
import tempfile

from .store import ROOT

CACHE = Path(tempfile.gettempdir()) / 'fsae-search-cache' if os.environ.get('VERCEL') else ROOT / '.cache'
