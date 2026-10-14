"""Package the shared browser UI inside the independently built app service."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent
shutil.copyfile(root.parent / 'fsae_search/index.html', root / 'index.html')
