"""One interactive query at a time; four Jev network workers by default."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import threading
from uuid import uuid4

from .jev import search
from .store import ROOT, encode


class SearchService:
    def __init__(self, store):
        self.store = store
        self.jobs = OrderedDict()
        self.lock = threading.Lock()
        self.active_id = None
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='rule-search')

    def start(self, query, vehicle_type='all', top_k=30, threshold=0.5, strategy='sections',use_cache=True):
        with self.lock:
            if self.active_id is not None:
                return None
            identifier = uuid4().hex
            job = dict(id=identifier, query=query, status='running', completed=0,
                       total=len(self.store.units), vehicle_type=vehicle_type)
            self.jobs[identifier] = job
            self.active_id = identifier
            while len(self.jobs) > 16:
                self.jobs.popitem(last=False)
            self.worker.submit(self._run, identifier, query, vehicle_type, top_k, threshold,strategy,use_cache)
            return identifier

    def _run(self, identifier, query, vehicle_type, top_k, threshold,strategy,use_cache):
        def progress(done, total):
            with self.lock:
                self.jobs[identifier].update(completed=done, total=total)
        try:
            outcome = search(self.store, query, vehicle_type=vehicle_type, top_k=top_k,
                             threshold=threshold, progress=progress,strategy=strategy,use_cache=use_cache)
            directory = ROOT / '.cache' / 'searches'
            directory.mkdir(parents=True, exist_ok=True)
            (directory / (identifier + '.json')).write_text(encode(outcome) + '\n')
            with self.lock:
                self.jobs[identifier].update(status='done', output=outcome)
        except Exception:
            # Provider exceptions may contain request headers: never echo them.
            with self.lock:
                self.jobs[identifier].update(status='error', error='Search failed. Check Jev configuration and connectivity, then retry.')
        finally:
            with self.lock:
                self.active_id = None

    def get(self, identifier):
        with self.lock:
            return dict(self.jobs[identifier])

    def close(self):
        self.worker.shutdown(wait=False, cancel_futures=True)
